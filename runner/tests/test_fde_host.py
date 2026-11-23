"""Unit tests for the host-side FAT32 and NBD helpers."""

import struct
import uuid
from pathlib import Path
from typing import Any

import pytest

from ubuntu_gui_testing_runner import fde_host


class _FakeNbd:
    """An NBD client that serves scripted reads and records writes."""

    def __init__(self, blocks: dict[int, bytes]) -> None:
        self._blocks = blocks
        self.writes: list[tuple[int, bytes]] = []

    def read(self, offset: int, length: int) -> bytes:
        block = self._blocks.get(offset)
        if block is None:
            raise AssertionError(f"unexpected read at {offset}")
        return block[:length]

    def write(self, offset: int, payload: bytes) -> None:
        self.writes.append((offset, payload))

    def close(self) -> None:
        pass


def _bpb(*, fsinfo: int = 1, backup_boot: int = 6) -> bytes:
    """A minimal FAT32 boot sector with the given FSInfo and backup sectors."""
    sector = bytearray(512)
    struct.pack_into("<HBHBHHBH", sector, 11, 512, 1, 1, 1, 0, 0, 0xF8, 0)
    struct.pack_into("<IIHHIH", sector, 32, 1000, 1, 0, 0, 2, fsinfo)
    struct.pack_into("<H", sector, 50, backup_boot)
    sector[510:512] = b"\x55\xaa"
    return bytes(sector)


def test_dirent_packs_the_full_32_byte_layout() -> None:
    entry = fde_host._pack_dirent(b"SYSPREP EFI", 0x20, 0x12345, 0x1000)

    assert len(entry) == 32
    name, attr, _reserved = struct.unpack_from("<11sBB", entry, 0)
    assert name == b"SYSPREP EFI"
    assert attr == 0x20
    high, low, size = struct.unpack_from("<H4xHI", entry, 20)
    assert (high << 16) | low == 0x12345
    assert size == 0x1000


def test_volume_reads_fsinfo_sector_as_16_bit() -> None:
    nbd = _FakeNbd({0: _bpb(fsinfo=1, backup_boot=6), 512: bytes(512)})

    volume = fde_host._Fat32Volume(nbd, 0)  # type: ignore[arg-type]

    assert volume.fsinfo_sec == 1
    assert volume.cluster_size == 512
    assert volume.data_offset == 1024
    assert volume.max_cluster == 999


def test_volume_rejects_a_non_fat32_boot_sector() -> None:
    sector = bytearray(_bpb())
    struct.pack_into("<H", sector, 22, 4)
    nbd = _FakeNbd({0: bytes(sector)})

    with pytest.raises(fde_host.FdeHostError, match="not FAT32"):
        fde_host._Fat32Volume(nbd, 0)  # type: ignore[arg-type]


class _FakeProcess:
    stderr = None

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        pass

    def wait(self, timeout: float | None = None) -> int:
        return 0


def _install_daemon(monkeypatch: pytest.MonkeyPatch, captured: list[list[str]]) -> None:
    """Fake the daemon so it creates its socket and records its argv."""

    def popen(argv: list[str], **_kwargs: Any) -> _FakeProcess:
        captured.append(argv)
        address = next(arg for arg in argv if arg.startswith("addr.type=unix"))
        Path(address.split("addr.path=", 1)[1]).touch()
        return _FakeProcess()

    monkeypatch.setattr(
        "ubuntu_gui_testing_runner.fde_host.shutil.which",
        lambda _name: "/usr/bin/daemon",
    )
    monkeypatch.setattr("ubuntu_gui_testing_runner.fde_host.subprocess.Popen", popen)


def test_export_writability_follows_the_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: list[list[str]] = []
    _install_daemon(monkeypatch, captured)
    monkeypatch.setattr(fde_host, "NbdClient", lambda _path: _FakeNbd({}))

    for writable, export in ((True, "writable=on"), (False, "writable=off")):
        captured.clear()
        with fde_host.open_qcow2_nbd(tmp_path / "disk.qcow2", writable=writable):
            pass
        argv = captured[0]
        assert argv[argv.index("--export") + 1].endswith(export)
        node = argv[argv.index("--blockdev") + 1]
        assert f"read-only={'off' if writable else 'on'}" in node


def test_nbd_startup_retries_a_refused_connection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: list[list[str]] = []
    _install_daemon(monkeypatch, captured)
    attempts: list[Path] = []

    class _Client(_FakeNbd):
        def __init__(self, path: Path) -> None:
            super().__init__({})
            attempts.append(path)
            if len(attempts) == 1:
                raise ConnectionRefusedError()

        def close(self) -> None:
            pass

    monkeypatch.setattr(fde_host, "NbdClient", _Client)
    monkeypatch.setattr(
        "ubuntu_gui_testing_runner.fde_host.time.sleep", lambda _seconds: None
    )

    with fde_host.open_qcow2_nbd(tmp_path / "disk.qcow2", writable=True) as client:
        assert isinstance(client, _Client)

    assert len(attempts) == 2


class _BufferNbd:
    """An NBD client backed by a flat byte buffer."""

    def __init__(self, size: int) -> None:
        self.buffer = bytearray(size)

    def read(self, offset: int, length: int) -> bytes:
        window = self.buffer[offset : offset + length]
        return bytes(window).ljust(length, b"\0")

    def write(self, offset: int, payload: bytes) -> None:
        end = offset + len(payload)
        if end > len(self.buffer):
            self.buffer.extend(bytes(end - len(self.buffer)))
        self.buffer[offset:end] = payload

    def close(self) -> None:
        pass


def _fat32_image() -> _BufferNbd:
    """Build a one-FAT FAT32 volume whose root directory is cluster 2."""
    nbd = _BufferNbd(128 * 512)
    sector = bytearray(512)
    struct.pack_into("<HBHBHHBH", sector, 11, 512, 1, 1, 1, 0, 0, 0xF8, 0)
    struct.pack_into("<IIHHIH", sector, 32, 128, 8, 0, 0, 2, 1)
    struct.pack_into("<H", sector, 50, 6)
    sector[510:512] = b"\x55\xaa"
    nbd.write(0, bytes(sector))
    fat = bytearray(8 * 512)
    struct.pack_into("<III", fat, 0, 0x0FFFFFF8, 0x0FFFFFFF, 0x0FFFFFFF)
    nbd.write(512, bytes(fat))
    nbd.write(1024, b"RRaA" + bytes(484) + b"rrAa" + bytes(12))
    return nbd


def test_volume_reads_back_a_written_file() -> None:
    nbd = _fat32_image()
    fde_host._Fat32Volume(nbd, 0).write_file(  # type: ignore[arg-type]
        "/EFI/ubuntu/shimx64.efi", b"shim-bytes"
    )

    volume = fde_host._Fat32Volume(nbd, 0)  # type: ignore[arg-type]

    assert volume.read_file("\\EFI\\ubuntu\\shimx64.efi") == b"shim-bytes"


def test_volume_read_rejects_a_missing_file() -> None:
    volume = fde_host._Fat32Volume(_fat32_image(), 0)  # type: ignore[arg-type]

    with pytest.raises(fde_host.FdeHostError, match="not found"):
        volume.read_file("\\EFI\\ubuntu\\absent.efi")


def test_pe_digest_ignores_the_checksum_and_certificate_entry() -> None:
    image = bytearray(fde_host.minimal_efi_application())
    digest = fde_host.authenticode_sha256_pe(bytes(image))

    image[fde_host._CHECKSUM_OFFSET : fde_host._CHECKSUM_OFFSET + 4] = (
        b"\x01\x02\x03\x04"
    )
    image[fde_host._CERT_DIRECTORY_OFFSET : fde_host._CERT_DIRECTORY_OFFSET + 8] = (
        b"\x00\x01\x00\x00\x20\x00\x00\x00"
    )

    assert fde_host.authenticode_sha256_pe(bytes(image)) == digest


def test_pe_digest_covers_section_data() -> None:
    image = bytearray(fde_host.minimal_efi_application())
    digest = fde_host.authenticode_sha256_pe(bytes(image))

    image[len(image) - 1] ^= 0xFF

    assert fde_host.authenticode_sha256_pe(bytes(image)) != digest


def test_pe_digest_rejects_non_pe_bytes() -> None:
    with pytest.raises(fde_host.FdeHostError, match="MZ header"):
        fde_host.authenticode_sha256_pe(b"not a PE")


def test_certificate_list_uses_the_uefi_x509_type() -> None:
    # gEfiCertX509Guid: firmware skips a db entry whose type is not this exact GUID.
    assert fde_host.EFI_CERT_X509_GUID.bytes_le == bytes.fromhex(
        "a159c0a5e494a74a87b5ab155c2bf072"
    )
    sig_list = fde_host.signature_list_x509(b"\x30\x00")
    assert sig_list[:16] == bytes.fromhex("a159c0a5e494a74a87b5ab155c2bf072")


class _FakeStore:
    """An NvramStore that records what a preparation appends and sets."""

    def __init__(self) -> None:
        self.signature_lists: list[bytes] = []
        self.variables: dict[str, tuple[uuid.UUID, bytes, int]] = {}

    @classmethod
    def from_file(cls, _path: Path) -> "_FakeStore":
        return cls()

    def append_db_signature_list(self, signature_list: bytes) -> None:
        self.signature_lists.append(signature_list)

    def set_variable(
        self, name: str, guid: uuid.UUID, data: bytes, *, attributes: int
    ) -> None:
        self.variables[name] = (guid, data, attributes)

    def to_bytes(self) -> bytes:
        return b"nvram"


class _FakeQcow2:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *_args: object) -> None:
        pass


def test_weak_prep_dispatches_a_weak_signed_driver(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The shim must keep its vendor signature: grub's signer has to chain to the
    # CA the firmware measures while verifying shim, so the weak authority comes
    # from a pre-OS driver instead.
    partition = fde_host.GptPartition(
        number=2,
        start_lba=2048,
        size_lba=4096,
        unique_guid=uuid.UUID("29fd9c6e-6e9c-fd29-0000-000000000000"),
        name="ubuntu-seed",
    )
    store = _FakeStore()
    signed: list[tuple[bytes, int, str]] = []
    written: list[tuple[str, str, bytes]] = []
    driver = b"driver-image"
    cert_der = b"\x30\x00"

    def fake_sign(image: bytes, rsa_bits: int, common_name: str) -> tuple[bytes, bytes]:
        signed.append((image, rsa_bits, common_name))
        return b"weak-driver", cert_der

    def fake_write(
        _nbd: object, partition_name: str, fat_path: str, content: bytes
    ) -> fde_host.GptPartition:
        written.append((partition_name, fat_path, content))
        return partition

    monkeypatch.setattr(fde_host, "minimal_efi_driver", lambda: driver)
    monkeypatch.setattr(fde_host, "sign_efi_application", fake_sign)
    monkeypatch.setattr(fde_host, "open_qcow2_nbd", lambda *_a, **_k: _FakeQcow2())
    monkeypatch.setattr(fde_host, "write_fat32_file", fake_write)
    monkeypatch.setattr(fde_host, "NvramStore", _FakeStore)
    monkeypatch.setattr(_FakeStore, "from_file", classmethod(lambda _cls, _p: store))

    fde_host.prepare_clone_host_state(
        ("preos-weak-sb",), tmp_path / "disk.qcow2", tmp_path / "VARS.fd"
    )

    assert signed == [(driver, 1024, "UGT Weak RSA-1024 CA")]
    assert written == [("ubuntu-seed", "/EFI/ugt/weak.efi", b"weak-driver")]
    assert store.signature_lists == [fde_host.signature_list_x509(cert_der)]
    assert (tmp_path / "VARS.fd").read_bytes() == b"nvram"

    guid, order, attributes = store.variables["DriverOrder"]
    assert (guid, order) == (fde_host.EFI_GLOBAL_VARIABLE_GUID, struct.pack("<H", 1))
    assert attributes == fde_host._EFI_VARIABLE_NV_BS_RT

    guid, option, attributes = store.variables["Driver0001"]
    assert (guid, attributes) == (
        fde_host.EFI_GLOBAL_VARIABLE_GUID,
        fde_host._EFI_VARIABLE_NV_BS_RT,
    )
    assert "UGT Weak Signed Driver".encode("utf-16-le") in option
    assert "\\EFI\\ugt\\weak.efi".encode("utf-16-le") in option
    assert partition.unique_guid.bytes_le in option
    assert struct.pack("<QQ", partition.start_lba, partition.size_lba) in option


def test_pe_digest_covers_the_gap_before_the_certificate_table() -> None:
    image = bytearray(fde_host.minimal_efi_application())
    pe_offset = struct.unpack_from("<I", image, 0x3C)[0]
    security_entry = pe_offset + 4 + 20 + 112 + 32
    struct.pack_into("<II", image, security_entry, len(image), 8)
    image += b"\xaa" * 64 + b"\xbb" * 8

    digest = fde_host.authenticode_sha256_pe(bytes(image))
    image[len(image) - 8 - 64] ^= 0xFF
    assert fde_host.authenticode_sha256_pe(bytes(image)) != digest

    image[len(image) - 8 - 64] ^= 0xFF
    image[-1] ^= 0xFF
    assert fde_host.authenticode_sha256_pe(bytes(image)) == digest


def test_volume_read_rejects_a_directory() -> None:
    nbd = _fat32_image()
    volume = fde_host._Fat32Volume(nbd, 0)  # type: ignore[arg-type]
    volume.write_file("/EFI/ubuntu/shimx64.efi", b"shim-bytes")

    with pytest.raises(fde_host.FdeHostError, match="is a FAT32 directory"):
        volume.read_file("\\EFI\\ubuntu")
