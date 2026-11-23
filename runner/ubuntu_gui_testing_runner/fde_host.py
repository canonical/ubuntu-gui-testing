"""Rootless host-side disk, UEFI NVRAM, and domain firmware preparation.

Prepares disposable clone overlays, FAT32 EFI system files, and EDK2
authenticated variable stores without host root privileges, using
``qemu-storage-daemon`` over a private UNIX socket for sector-level writes.
"""

from __future__ import annotations

import contextlib
import hashlib
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import defusedxml.ElementTree as DefusedET

PLAIN_OVMF_CODE: Final = Path("/usr/share/OVMF/OVMF_CODE_4M.fd")
PLAIN_OVMF_VARS: Final = Path("/usr/share/OVMF/OVMF_VARS_4M.fd")

EFI_GLOBAL_VARIABLE_GUID: Final = uuid.UUID("8be4df61-93ca-11d2-aa0d-00e098032b8c")
EFI_IMAGE_SECURITY_DATABASE_GUID: Final = uuid.UUID(
    "d719b2cb-3d3a-4596-a3bc-dad00e67656f"
)
EFI_CERT_X509_GUID: Final = uuid.UUID("a5c059a1-94e4-4aa7-87b5-ab155c2bf072")
EFI_CERT_SHA256_GUID: Final = uuid.UUID("c1c41626-504c-4092-aca9-41f936934328")
EFI_AUTHENTICATED_VARIABLE_GUID: Final = uuid.UUID(
    "aaf32c78-947b-439a-a180-2e144ec37792"
)
UGT_DB_OWNER_GUID: Final = uuid.UUID("c0fe7e57-0000-4000-8000-0000000000d6")

_EFI_VARIABLE_NV_BS_RT: Final = 0x7
_EFI_VARIABLE_TIME_AUTH: Final = 0x27
_LOAD_OPTION_ACTIVE: Final = 0x1

_FILE_ALIGNMENT: Final = 0x200
_CHECKSUM_OFFSET: Final = 0x40 + 4 + 20 + 64
_CERT_DIRECTORY_OFFSET: Final = 0x40 + 4 + 20 + 112 + 4 * 8

_NBD_EXPORT_NAME: Final = "disk0"
_NBD_REQUEST_MAGIC: Final = 0x25609513
_NBD_REPLY_MAGIC: Final = 0x67446698
_NBD_OPT_REPLY_MAGIC: Final = 0x3E889045565A9
_NBD_OPT_GO: Final = 7
_NBD_REP_ACK: Final = 1
_NBD_REP_INFO: Final = 3
_NBD_INFO_EXPORT: Final = 0
_NBD_CMD_READ: Final = 0
_NBD_CMD_WRITE: Final = 1
_NBD_CMD_DISC: Final = 2
_NBD_CMD_FLUSH: Final = 3

_VAR_ADDED: Final = 0x3F
_VAR_DELETED: Final = 0x3C
_VAR_HEADER_STRUCT: Final = struct.Struct("<HBBIQ16sIII16s")

HOST_PREPARATIONS: Final = frozenset(
    {
        "plain-ovmf",
        "sysprep-app",
        "sysprep-weak-sb",
        "sysprep-digest-sb",
        "preos-digest-sb",
        "preos-weak-sb",
    }
)


class FdeHostError(RuntimeError):
    """Host-side disk or firmware preparation failed."""


def minimal_efi_image(subsystem: int = 10) -> bytes:
    """Return a minimal PE32+ EFI image (`xor eax, eax; ret`).

    Subsystem 10 is EFI_APPLICATION and 11 is EFI_BOOT_SERVICE_DRIVER, which is
    what the firmware requires before it will dispatch a `Driver####` entry.
    """
    dos = b"MZ" + bytes(0x3A) + struct.pack("<I", 0x40)
    coff = b"PE\0\0" + struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 240, 0x22)
    optional = struct.pack(
        "<HBBIIIII", 0x20B, 0, 0, _FILE_ALIGNMENT, 0, 0, 0x1000, 0x1000
    )
    optional += struct.pack(
        "<QIIHHHHHHIIIIHHQQQQII",
        0x100000,
        0x1000,
        _FILE_ALIGNMENT,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0x2000,
        _FILE_ALIGNMENT,
        0,
        subsystem,
        0,
        0,
        0,
        0,
        0,
        0,
        16,
    )
    optional += bytes(16 * 8)
    section = struct.pack(
        "<8sIIIIIIHHI",
        b".text",
        3,
        0x1000,
        _FILE_ALIGNMENT,
        _FILE_ALIGNMENT,
        0,
        0,
        0,
        0,
        0x60000020,
    )
    headers = (dos + coff + optional + section).ljust(_FILE_ALIGNMENT, b"\0")
    return headers + b"\x31\xc0\xc3".ljust(_FILE_ALIGNMENT, b"\0")


def minimal_efi_application() -> bytes:
    """Return a minimal PE32+ EFI application (`xor eax, eax; ret`)."""
    return minimal_efi_image()


def minimal_efi_driver() -> bytes:
    """Return a minimal PE32+ EFI boot-service driver that returns success."""
    return minimal_efi_image(subsystem=11)


def authenticode_sha256_pe(image: bytes) -> bytes:
    """Compute the PE digest UEFI firmware checks against `db` hash entries.

    Mirrors edk2 `DxeImageVerificationLib` `HashPeImage`: the checksum and the
    certificate-table directory entry are skipped, sections are hashed in
    file-offset order, and bytes between the sections and the certificate table
    are hashed as well.
    """
    if image[:2] != b"MZ":
        raise FdeHostError("Image is not a PE file: missing MZ header")
    pe_offset = struct.unpack_from("<I", image, 0x3C)[0]
    if image[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise FdeHostError("Image is not a PE file: missing PE signature")

    coff = pe_offset + 4
    (section_count,) = struct.unpack_from("<H", image, coff + 2)
    (optional_size,) = struct.unpack_from("<H", image, coff + 16)
    optional = coff + 20
    (magic,) = struct.unpack_from("<H", image, optional)
    if magic == 0x10B:
        directories = optional + 96
        directory_count = optional + 92
    elif magic == 0x20B:
        directories = optional + 112
        directory_count = optional + 108
    else:
        raise FdeHostError(f"Unsupported PE optional header magic {magic:#x}")
    checksum = optional + 64
    security_entry = directories + 4 * 8
    (size_of_headers,) = struct.unpack_from("<I", image, optional + 60)
    if size_of_headers > len(image) or security_entry + 8 > size_of_headers:
        raise FdeHostError("PE headers are truncated")

    (rva_count,) = struct.unpack_from("<I", image, directory_count)
    has_security_entry = rva_count > 4
    cert_size = (
        struct.unpack_from("<I", image, security_entry + 4)[0]
        if has_security_entry
        else 0
    )

    headers = bytearray(image[:size_of_headers])
    hasher = hashlib.sha256()
    hasher.update(headers[:checksum])
    if has_security_entry:
        hasher.update(headers[checksum + 4 : security_entry])
        hasher.update(headers[security_entry + 8 :])
    else:
        hasher.update(headers[checksum + 4 :])

    section_table = optional + optional_size
    sections = []
    for index in range(section_count):
        raw_size, raw_pointer = struct.unpack_from(
            "<II", image, section_table + index * 40 + 16
        )
        if raw_size:
            sections.append((raw_pointer, raw_size))

    hashed = size_of_headers
    for raw_pointer, raw_size in sorted(sections):
        if raw_pointer + raw_size > len(image):
            raise FdeHostError("PE section data extends past the image end")
        hasher.update(image[raw_pointer : raw_pointer + raw_size])
        hashed += raw_size

    if len(image) > hashed:
        if len(image) < cert_size + hashed:
            raise FdeHostError("PE certificate table overlaps hashed data")
        if len(image) > cert_size + hashed:
            hasher.update(image[hashed : len(image) - cert_size])
    return hasher.digest()


def sign_efi_application(
    image: bytes, rsa_bits: int, common_name: str
) -> tuple[bytes, bytes]:
    """Generate a throwaway X.509 RSA cert and sign `image`; return (efi, cert_der)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        key_path = tmp / "ca.key"
        crt_path = tmp / "ca.crt"
        der_path = tmp / "ca.der"
        unsigned_path = tmp / "unsigned.efi"
        signed_path = tmp / "signed.efi"
        unsigned_path.write_bytes(image)

        _run_host(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                f"rsa:{rsa_bits}",
                "-sha256",
                "-nodes",
                "-days",
                "3650",
                "-subj",
                f"/CN={common_name}",
                "-keyout",
                str(key_path),
                "-out",
                str(crt_path),
            ]
        )
        _run_host(
            [
                "openssl",
                "x509",
                "-in",
                str(crt_path),
                "-outform",
                "DER",
                "-out",
                str(der_path),
            ]
        )
        _run_host(
            [
                "sbsign",
                "--key",
                str(key_path),
                "--cert",
                str(crt_path),
                "--output",
                str(signed_path),
                str(unsigned_path),
            ]
        )
        _run_host(["sbverify", "--cert", str(crt_path), str(signed_path)])
        return signed_path.read_bytes(), der_path.read_bytes()


def signature_list_x509(cert_der: bytes, owner: uuid.UUID = UGT_DB_OWNER_GUID) -> bytes:
    """Build an EFI_SIGNATURE_LIST carrying one DER-encoded X.509 certificate."""
    sig_size = 16 + len(cert_der)
    list_size = 28 + sig_size
    return (
        EFI_CERT_X509_GUID.bytes_le
        + struct.pack("<III", list_size, 0, sig_size)
        + owner.bytes_le
        + cert_der
    )


def signature_list_sha256(digest: bytes, owner: uuid.UUID = UGT_DB_OWNER_GUID) -> bytes:
    """Build an EFI_SIGNATURE_LIST carrying one SHA-256 Authenticode digest."""
    if len(digest) != 32:
        raise FdeHostError(f"SHA-256 digest must be 32 bytes, got {len(digest)}")
    sig_size = 16 + 32
    list_size = 28 + sig_size
    return (
        EFI_CERT_SHA256_GUID.bytes_le
        + struct.pack("<III", list_size, 0, sig_size)
        + owner.bytes_le
        + digest
    )


def efi_load_option(
    description: str,
    file_path: str,
    part_number: int,
    start_lba: int,
    size_lba: int,
    part_uuid: uuid.UUID,
) -> bytes:
    """Encode an active `EFI_LOAD_OPTION` pointing to `file_path` on GPT."""
    hard_drive = struct.pack(
        "<BBHIQQ16sBB",
        4,
        1,
        42,
        part_number,
        start_lba,
        size_lba,
        part_uuid.bytes_le,
        2,
        2,
    )
    encoded_path = (file_path + "\0").encode("utf-16-le")
    file_node = struct.pack("<BBH", 4, 4, 4 + len(encoded_path)) + encoded_path
    device_path = hard_drive + file_node + bytes((0x7F, 0xFF, 4, 0))
    return (
        struct.pack("<IH", _LOAD_OPTION_ACTIVE, len(device_path))
        + (description + "\0").encode("utf-16-le")
        + device_path
    )


@dataclass
class _NvramRecord:
    offset: int
    state: int
    attributes: int
    monotonic_count: int
    timestamp: bytes
    pubkey_index: int
    name: str
    guid: uuid.UUID
    data: bytes


class NvramStore:
    """Reader/writer for EDK2 `OVMF_VARS_4M` authenticated variable stores."""

    def __init__(self, image: bytearray) -> None:
        if len(image) < 0x100:
            raise FdeHostError("NVRAM image is too small")
        self._buf = image
        self._fv_hdr_len = struct.unpack_from("<H", image, 0x30)[0]
        if self._fv_hdr_len + 28 > len(image):
            raise FdeHostError("NVRAM firmware volume header is invalid")
        vs_guid_b, vs_size, vs_fmt, vs_state = struct.unpack_from(
            "<16sIBB", image, self._fv_hdr_len
        )
        vs_guid = uuid.UUID(bytes_le=vs_guid_b)
        if (
            vs_guid != EFI_AUTHENTICATED_VARIABLE_GUID
            or vs_fmt != 0x5A
            or vs_state != 0xFE
        ):
            raise FdeHostError("NVRAM is not an EDK2 authenticated variable store")
        self._var_start = self._fv_hdr_len + 28
        self._var_end = self._fv_hdr_len + vs_size
        if self._var_end > len(image):
            raise FdeHostError("NVRAM variable store exceeds image bounds")
        self._records, self._free_off = self._parse_records()

    @classmethod
    def from_file(cls, path: Path) -> NvramStore:
        return cls(bytearray(path.read_bytes()))

    def _parse_records(self) -> tuple[list[_NvramRecord], int]:
        records: list[_NvramRecord] = []
        pos = self._var_start
        hdr_sz = _VAR_HEADER_STRUCT.size
        while pos + hdr_sz <= self._var_end:
            start_id = struct.unpack_from("<H", self._buf, pos)[0]
            if start_id != 0x55AA:
                break
            (
                _start_id,
                state,
                _reserved,
                attrs,
                mono,
                ts,
                pk_idx,
                name_sz,
                data_sz,
                vguid_b,
            ) = _VAR_HEADER_STRUCT.unpack_from(self._buf, pos)
            if pos + hdr_sz + name_sz + data_sz > self._var_end:
                raise FdeHostError(f"Corrupt variable record at offset {pos:#x}")
            raw_name = bytes(self._buf[pos + hdr_sz : pos + hdr_sz + name_sz])
            name = raw_name.decode("utf-16-le").rstrip("\x00")
            data = bytes(
                self._buf[pos + hdr_sz + name_sz : pos + hdr_sz + name_sz + data_sz]
            )
            records.append(
                _NvramRecord(
                    offset=pos,
                    state=state,
                    attributes=attrs,
                    monotonic_count=mono,
                    timestamp=ts,
                    pubkey_index=pk_idx,
                    name=name,
                    guid=uuid.UUID(bytes_le=vguid_b),
                    data=data,
                )
            )
            pos = (pos + hdr_sz + name_sz + data_sz + 3) & ~3
        return records, pos

    def get_record(self, name: str, guid: uuid.UUID) -> _NvramRecord | None:
        for rec in reversed(self._records):
            if rec.state == _VAR_ADDED and rec.name == name and rec.guid == guid:
                return rec
        return None

    def set_variable(
        self,
        name: str,
        guid: uuid.UUID,
        data: bytes,
        attributes: int = _EFI_VARIABLE_NV_BS_RT,
        monotonic_count: int = 0,
        timestamp: bytes = bytes(16),
        pubkey_index: int = 0,
    ) -> None:
        for rec in self._records:
            if rec.state == _VAR_ADDED and rec.name == name and rec.guid == guid:
                self._buf[rec.offset + 2] = _VAR_DELETED
                rec.state = _VAR_DELETED

        encoded_name = (name + "\0").encode("utf-16-le")
        hdr = _VAR_HEADER_STRUCT.pack(
            0x55AA,
            _VAR_ADDED,
            0,
            attributes,
            monotonic_count,
            timestamp,
            pubkey_index,
            len(encoded_name),
            len(data),
            guid.bytes_le,
        )
        raw = hdr + encoded_name + data
        aligned_end = (self._free_off + len(raw) + 3) & ~3
        if aligned_end > self._var_end:
            raise FdeHostError(
                f"Insufficient free NVRAM space for {name!r} ({len(raw)} bytes)"
            )
        if any(b != 0xFF for b in self._buf[self._free_off : aligned_end]):
            raise FdeHostError(f"NVRAM tail at {self._free_off:#x} is not erased flash")
        self._buf[self._free_off : self._free_off + len(raw)] = raw
        self._records.append(
            _NvramRecord(
                offset=self._free_off,
                state=_VAR_ADDED,
                attributes=attributes,
                monotonic_count=monotonic_count,
                timestamp=timestamp,
                pubkey_index=pubkey_index,
                name=name,
                guid=guid,
                data=data,
            )
        )
        self._free_off = aligned_end

    def append_db_signature_list(self, signature_list: bytes) -> None:
        existing = self.get_record("db", EFI_IMAGE_SECURITY_DATABASE_GUID)
        if existing is None:
            raise FdeHostError("Existing Secure Boot 'db' variable not found in NVRAM")
        self.replace_db_signature_lists(existing.data + signature_list)

    def replace_db_signature_lists(self, signature_lists: bytes) -> None:
        """Replace the Secure Boot 'db' signature database."""
        existing = self.get_record("db", EFI_IMAGE_SECURITY_DATABASE_GUID)
        if existing is None:
            raise FdeHostError("Existing Secure Boot 'db' variable not found in NVRAM")
        self.set_variable(
            name="db",
            guid=EFI_IMAGE_SECURITY_DATABASE_GUID,
            data=signature_lists,
            attributes=existing.attributes or _EFI_VARIABLE_TIME_AUTH,
            monotonic_count=existing.monotonic_count,
            timestamp=existing.timestamp,
            pubkey_index=existing.pubkey_index,
        )

    def to_bytes(self) -> bytes:
        return bytes(self._buf)


class NbdClient:
    """Minimal synchronous NBD client over a local UNIX socket."""

    def __init__(self, sock_path: Path, export_name: str = _NBD_EXPORT_NAME) -> None:
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.settimeout(30.0)
        self._sock.connect(str(sock_path))
        magic, opt_magic, _hs_flags = struct.unpack(">8s8sH", self._recv_exact(18))
        if magic != b"NBDMAGIC" or opt_magic != b"IHAVEOPT":
            raise FdeHostError("Unexpected NBD handshake magic")
        # NBD_FLAG_C_FIXED_NEWSTYLE | NBD_FLAG_C_NO_ZEROES
        self._sock.sendall(struct.pack(">I", (1 << 0) | (1 << 1)))

        export = export_name.encode("utf-8")
        body = struct.pack(">I", len(export)) + export + struct.pack(">H", 0)
        self._sock.sendall(
            struct.pack(">8sII", b"IHAVEOPT", _NBD_OPT_GO, len(body)) + body
        )
        self.size = 0
        while True:
            rmagic, _ropt, rtype, rlen = struct.unpack(">QIII", self._recv_exact(20))
            if rmagic != _NBD_OPT_REPLY_MAGIC:
                raise FdeHostError("Unexpected NBD option reply magic")
            rdata = self._recv_exact(rlen)
            if rtype == _NBD_REP_INFO:
                if struct.unpack(">H", rdata[:2])[0] == _NBD_INFO_EXPORT:
                    self.size, _tx_flags = struct.unpack(">QH", rdata[2:12])
            elif rtype == _NBD_REP_ACK:
                break
            elif rtype & (1 << 31):
                raise FdeHostError(f"NBD option failed ({rtype:#x})")
        self._handle = 1

    def _recv_exact(self, count: int) -> bytes:
        buf = bytearray()
        while len(buf) < count:
            chunk = self._sock.recv(count - len(buf))
            if not chunk:
                raise FdeHostError("Unexpected EOF on NBD socket")
            buf.extend(chunk)
        return bytes(buf)

    def _next_handle(self) -> int:
        h = self._handle
        self._handle += 1
        return h

    def read(self, offset: int, length: int) -> bytes:
        if length == 0:
            return b""
        h = self._next_handle()
        self._sock.sendall(
            struct.pack(
                ">IHHQQI", _NBD_REQUEST_MAGIC, 0, _NBD_CMD_READ, h, offset, length
            )
        )
        rmagic, err, rh = struct.unpack(">IIQ", self._recv_exact(16))
        if rmagic != _NBD_REPLY_MAGIC or rh != h or err != 0:
            raise FdeHostError(f"NBD read at {offset} ({length}B) failed: err={err}")
        return self._recv_exact(length)

    def write(self, offset: int, payload: bytes) -> None:
        if not payload:
            return
        h = self._next_handle()
        self._sock.sendall(
            struct.pack(
                ">IHHQQI",
                _NBD_REQUEST_MAGIC,
                0,
                _NBD_CMD_WRITE,
                h,
                offset,
                len(payload),
            )
            + payload
        )
        rmagic, err, rh = struct.unpack(">IIQ", self._recv_exact(16))
        if rmagic != _NBD_REPLY_MAGIC or rh != h or err != 0:
            raise FdeHostError(
                f"NBD write at {offset} ({len(payload)}B) failed: err={err}"
            )

    def flush(self) -> None:
        h = self._next_handle()
        self._sock.sendall(
            struct.pack(">IHHQQI", _NBD_REQUEST_MAGIC, 0, _NBD_CMD_FLUSH, h, 0, 0)
        )
        rmagic, err, rh = struct.unpack(">IIQ", self._recv_exact(16))
        if rmagic != _NBD_REPLY_MAGIC or rh != h or err != 0:
            raise FdeHostError(f"NBD flush failed: err={err}")

    def close(self) -> None:
        with contextlib.suppress(OSError, FdeHostError):
            self.flush()
            h = self._next_handle()
            self._sock.sendall(
                struct.pack(">IHHQQI", _NBD_REQUEST_MAGIC, 0, _NBD_CMD_DISC, h, 0, 0)
            )
        self._sock.close()


@contextlib.contextmanager
def open_qcow2_nbd(image_path: Path, *, writable: bool) -> Iterator[NbdClient]:
    """Expose a qcow2 image over a private UNIX socket NBD server."""
    read_only = "off" if writable else "on"
    export = "on" if writable else "off"
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = Path(tmpdir) / "nbd.sock"
        daemon = shutil.which("qemu-storage-daemon")
        if daemon is None:
            raise FdeHostError("qemu-storage-daemon is not installed")
        proc = subprocess.Popen(  # noqa: S603 - fixed qemu-storage-daemon argv
            [
                daemon,
                "--blockdev",
                f"driver=file,node-name=f0,filename={image_path},read-only={read_only}",
                "--blockdev",
                f"driver=qcow2,node-name=q0,file=f0,read-only={read_only}",
                "--nbd-server",
                f"addr.type=unix,addr.path={sock_path}",
                "--export",
                f"type=nbd,id=exp0,node-name=q0,name={_NBD_EXPORT_NAME},"
                f"writable={export}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        client: NbdClient | None = None
        try:
            deadline = time.monotonic() + 10.0
            while True:
                if proc.poll() is not None:
                    stderr = (proc.stderr.read() if proc.stderr else b"").decode(
                        "utf-8", "replace"
                    )
                    raise FdeHostError(f"qemu-storage-daemon exited early: {stderr}")
                if sock_path.exists():
                    try:
                        client = NbdClient(sock_path)
                        break
                    except (ConnectionRefusedError, FileNotFoundError):
                        # The daemon creates the socket before it listens.
                        pass
                if time.monotonic() >= deadline:
                    raise FdeHostError(
                        "Timed out waiting for qemu-storage-daemon socket"
                    )
                time.sleep(0.05)
            yield client
        finally:
            if client is not None:
                client.close()
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


@dataclass(frozen=True)
class GptPartition:
    number: int
    start_lba: int
    size_lba: int
    unique_guid: uuid.UUID
    name: str

    @property
    def byte_offset(self) -> int:
        return self.start_lba * 512


def find_gpt_partition(nbd: NbdClient, name: str) -> GptPartition:
    gpt = nbd.read(512, 512)
    if gpt[:8] != b"EFI PART":
        raise FdeHostError("Missing GPT header at LBA 1")
    part_entry_lba, num_parts, part_sz = struct.unpack_from("<QII", gpt, 72)
    parts_raw = nbd.read(part_entry_lba * 512, num_parts * part_sz)
    for idx in range(1, num_parts + 1):
        entry = parts_raw[(idx - 1) * part_sz : idx * part_sz]
        if uuid.UUID(bytes_le=entry[:16]).int == 0:
            continue
        part_name = entry[56:128].decode("utf-16-le", "replace").rstrip("\x00")
        if part_name == name:
            start_lba, end_lba = struct.unpack_from("<QQ", entry, 32)
            return GptPartition(
                number=idx,
                start_lba=start_lba,
                size_lba=end_lba - start_lba + 1,
                unique_guid=uuid.UUID(bytes_le=entry[16:32]),
                name=part_name,
            )
    raise FdeHostError(f"GPT partition {name!r} not found")


def _encode_83_name(segment: str) -> bytes:
    upper = segment.upper()
    if "." in upper:
        stem, ext = upper.split(".", 1)
    else:
        stem, ext = upper, ""
    if (
        not stem
        or len(stem) > 8
        or len(ext) > 3
        or "." in ext
        or any(ord(ch) < 0x20 or ch in ' "*+,/:;<=>?[\\]|' for ch in upper)
    ):
        raise FdeHostError(f"FAT32 name {segment!r} must be valid 8.3")
    return stem.ljust(8).encode("ascii") + ext.ljust(3).encode("ascii")


def _pack_dirent(
    sfn: bytes, attr: int, first_cluster: int, file_size: int, nt_res: int = 0x18
) -> bytes:
    hi = (first_cluster >> 16) & 0xFFFF
    lo = first_cluster & 0xFFFF
    return struct.pack(
        "<11sBBBHHHHHHHI",
        sfn,
        attr,
        nt_res,
        0,
        0,
        0x5821,
        0x5821,
        hi,
        0,
        0x5821,
        lo,
        file_size,
    )


class _Fat32Volume:
    bps: int
    spc: int
    rsv: int
    nfats: int
    fatsz: int
    root_cluster: int
    fsinfo_sec: int
    cluster_size: int
    fat_bytes: int
    fat_offset: int
    data_offset: int
    max_cluster: int

    def __init__(self, nbd: NbdClient, part_offset: int) -> None:
        self._nbd = nbd
        self._base = part_offset
        bpb = nbd.read(self._base, 512)
        if bpb[510:512] != b"\x55\xaa":
            raise FdeHostError("Invalid FAT32 boot sector signature")
        (
            self.bps,
            self.spc,
            self.rsv,
            self.nfats,
            _root_cnt,
            _tot16,
            _media,
            fat16_sz,
        ) = struct.unpack_from("<HBHBHHBH", bpb, 11)
        tot32, self.fatsz, _flags, _ver, self.root_cluster, self.fsinfo_sec = (
            struct.unpack_from("<IIHHIH", bpb, 32)
        )
        if fat16_sz != 0 or self.fatsz == 0 or self.root_cluster < 2:
            raise FdeHostError("Partition is not FAT32")
        self.cluster_size = self.bps * self.spc
        self.fat_bytes = self.fatsz * self.bps
        self.fat_offset = self._base + self.rsv * self.bps
        self.data_offset = self.fat_offset + self.nfats * self.fat_bytes
        self.max_cluster = (
            (tot32 - self.rsv - self.nfats * self.fatsz) // self.spc
        ) + 1
        self._fat = bytearray(self._nbd.read(self.fat_offset, self.fat_bytes))

    def _cluster_byte_offset(self, cluster: int) -> int:
        return self.data_offset + (cluster - 2) * self.cluster_size

    def _fat_get(self, cluster: int) -> int:
        entry = int(struct.unpack_from("<I", self._fat, cluster * 4)[0])
        return entry & 0x0FFFFFFF

    def _fat_set(self, cluster: int, value: int) -> None:
        existing = int(struct.unpack_from("<I", self._fat, cluster * 4)[0])
        existing &= 0xF0000000
        struct.pack_into("<I", self._fat, cluster * 4, existing | (value & 0x0FFFFFFF))

    def _chain(self, start_cluster: int) -> list[int]:
        if start_cluster < 2:
            return []
        clusters: list[int] = []
        seen: set[int] = set()
        cur = start_cluster
        while 2 <= cur <= self.max_cluster:
            if cur in seen:
                raise FdeHostError("FAT32 cluster loop detected")
            seen.add(cur)
            clusters.append(cur)
            nxt = self._fat_get(cur)
            if nxt >= 0x0FFFFFF8:
                break
            cur = nxt
        return clusters

    def _free_chain(self, start_cluster: int) -> int:
        freed = 0
        for clus in self._chain(start_cluster):
            self._fat_set(clus, 0)
            freed += 1
        return freed

    def _alloc_chain(self, count: int) -> list[int]:
        allocated: list[int] = []
        for clus in range(2, self.max_cluster + 1):
            if self._fat_get(clus) == 0:
                allocated.append(clus)
                if len(allocated) == count:
                    break
        if len(allocated) != count:
            raise FdeHostError(f"FAT32 partition has fewer than {count} free clusters")
        for i, clus in enumerate(allocated):
            nxt = allocated[i + 1] if i + 1 < len(allocated) else 0x0FFFFFFF
            self._fat_set(clus, nxt)
        return allocated

    def _read_dir(self, start_cluster: int) -> tuple[list[int], bytearray]:
        clusters = self._chain(start_cluster)
        raw = bytearray()
        for clus in clusters:
            raw.extend(
                self._nbd.read(self._cluster_byte_offset(clus), self.cluster_size)
            )
        return clusters, raw

    def _write_dir(self, clusters: list[int], raw: bytearray) -> None:
        for idx, clus in enumerate(clusters):
            chunk = bytes(raw[idx * self.cluster_size : (idx + 1) * self.cluster_size])
            self._nbd.write(self._cluster_byte_offset(clus), chunk)

    @staticmethod
    def _find_entry(raw: bytearray, sfn: bytes) -> tuple[int, int, int] | None:
        for off in range(0, len(raw), 32):
            marker = raw[off]
            if marker == 0x00:
                break
            if marker == 0xE5 or raw[off + 11] == 0x0F:
                continue
            if bytes(raw[off : off + 11]) == sfn:
                hi, lo, size = struct.unpack_from("<H4xHI", raw, off + 20)
                return off, (hi << 16) | lo, size
        return None

    @staticmethod
    def _find_free_slot(raw: bytearray) -> int | None:
        for off in range(0, len(raw), 32):
            if raw[off] in (0x00, 0xE5):
                return off
        return None

    def _append_dir_slot(
        self, dir_cluster: int, clusters: list[int], raw: bytearray, entry: bytes
    ) -> None:
        slot = self._find_free_slot(raw)
        if slot is not None:
            raw[slot : slot + 32] = entry
            self._write_dir(clusters, raw)
            return
        new_clus = self._alloc_chain(1)[0]
        self._fat_set(clusters[-1], new_clus)
        new_block = bytearray(self.cluster_size)
        new_block[:32] = entry
        self._nbd.write(self._cluster_byte_offset(new_clus), bytes(new_block))

    def _ensure_subdir(self, parent_cluster: int, name: str) -> int:
        sfn = _encode_83_name(name)
        clusters, raw = self._read_dir(parent_cluster)
        hit = self._find_entry(raw, sfn)
        if hit is not None:
            off, clus, _ = hit
            if not (raw[off + 11] & 0x10):
                raise FdeHostError(f"{name!r} exists on FAT32 and is not a directory")
            return clus

        new_clus = self._alloc_chain(1)[0]
        block = bytearray(self.cluster_size)
        block[0:32] = _pack_dirent(b".          ", 0x10, new_clus, 0, nt_res=0)
        parent_ref = 0 if parent_cluster == self.root_cluster else parent_cluster
        block[32:64] = _pack_dirent(b"..         ", 0x10, parent_ref, 0, nt_res=0)
        self._nbd.write(self._cluster_byte_offset(new_clus), bytes(block))
        self._append_dir_slot(
            parent_cluster, clusters, raw, _pack_dirent(sfn, 0x10, new_clus, 0)
        )
        return new_clus

    def write_file(self, path: str, content: bytes) -> None:
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        if not parts:
            raise FdeHostError("Empty FAT32 file path")
        dir_cluster = self.root_cluster
        for d in parts[:-1]:
            dir_cluster = self._ensure_subdir(dir_cluster, d)

        sfn = _encode_83_name(parts[-1])
        clusters, raw = self._read_dir(dir_cluster)
        hit = self._find_entry(raw, sfn)
        if hit is not None:
            _off, old_clus, _ = hit
            if old_clus >= 2:
                self._free_chain(old_clus)

        needed = max(1, (len(content) + self.cluster_size - 1) // self.cluster_size)
        file_clusters = self._alloc_chain(needed) if content else []
        for idx, clus in enumerate(file_clusters):
            chunk = content[idx * self.cluster_size : (idx + 1) * self.cluster_size]
            self._nbd.write(
                self._cluster_byte_offset(clus), chunk.ljust(self.cluster_size, b"\0")
            )

        first_clus = file_clusters[0] if file_clusters else 0
        dirent = _pack_dirent(sfn, 0x20, first_clus, len(content))
        if hit is not None:
            raw[hit[0] : hit[0] + 32] = dirent
            self._write_dir(clusters, raw)
        else:
            self._append_dir_slot(dir_cluster, clusters, raw, dirent)

        self._commit_fat_and_fsinfo()

    def _commit_fat_and_fsinfo(self) -> None:
        fat_bytes = bytes(self._fat)
        for idx in range(self.nfats):
            self._nbd.write(self.fat_offset + idx * self.fat_bytes, fat_bytes)

        free_count = sum(
            1 for c in range(2, self.max_cluster + 1) if self._fat_get(c) == 0
        )
        next_free = next(
            (c for c in range(2, self.max_cluster + 1) if self._fat_get(c) == 0),
            0xFFFFFFFF,
        )
        fsinfo_off = self._base + self.fsinfo_sec * self.bps
        fsinfo = bytearray(self._nbd.read(fsinfo_off, self.bps))
        if fsinfo[:4] == b"RRaA" and fsinfo[484:488] == b"rrAa":
            struct.pack_into("<II", fsinfo, 488, free_count, next_free)
            self._nbd.write(fsinfo_off, bytes(fsinfo))

    def read_file(self, path: str) -> bytes:
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        if not parts:
            raise FdeHostError("Empty FAT32 file path")
        dir_cluster = self.root_cluster
        for name in parts[:-1]:
            clusters, raw = self._read_dir(dir_cluster)
            hit = self._find_entry(raw, _encode_83_name(name))
            if hit is None:
                raise FdeHostError(f"FAT32 directory {name!r} not found")
            off, clus, _size = hit
            if not (raw[off + 11] & 0x10):
                raise FdeHostError(f"{name!r} exists on FAT32 and is not a directory")
            dir_cluster = clus

        clusters, raw = self._read_dir(dir_cluster)
        hit = self._find_entry(raw, _encode_83_name(parts[-1]))
        if hit is None:
            raise FdeHostError(f"FAT32 file {path!r} not found")
        off, first_clus, size = hit
        if raw[off + 11] & 0x10:
            raise FdeHostError(f"{path!r} is a FAT32 directory, not a file")
        data = bytearray()
        for clus in self._chain(first_clus):
            data += self._nbd.read(self._cluster_byte_offset(clus), self.cluster_size)
        if len(data) < size:
            raise FdeHostError(f"FAT32 file {path!r} is truncated")
        return bytes(data[:size])


def write_fat32_file(
    nbd: NbdClient, partition_name: str, fat_path: str, content: bytes
) -> GptPartition:
    """Write `content` to `fat_path` inside GPT partition `partition_name`."""
    part = find_gpt_partition(nbd, partition_name)
    _Fat32Volume(nbd, part.byte_offset).write_file(fat_path, content)
    return part


def read_fat32_file(nbd: NbdClient, partition_name: str, fat_path: str) -> bytes:
    """Read `fat_path` from GPT partition `partition_name`."""
    part = find_gpt_partition(nbd, partition_name)
    return _Fat32Volume(nbd, part.byte_offset).read_file(fat_path)


def prepare_plain_ovmf_domain_xml(domain_xml: str) -> str:
    """Switch domain XML to plain OVMF without Secure Boot enrolled keys."""
    root = DefusedET.fromstring(domain_xml)
    os_elem = root.find("os")
    if os_elem is None:
        raise FdeHostError("Domain XML has no <os> element")
    os_elem.attrib.pop("firmware", None)
    firmware = os_elem.find("firmware")
    if firmware is not None:
        os_elem.remove(firmware)
    loader = os_elem.find("loader")
    if loader is not None:
        loader.attrib.pop("secure", None)
        loader.text = str(PLAIN_OVMF_CODE)
    return ET.tostring(root, encoding="unicode")


def restore_os_from_source_xml(
    clone_xml: str, source_xml: str, clone_nvram: Path
) -> str:
    """Restore `<os>` firmware settings while keeping the clone NVRAM."""
    clone_root = DefusedET.fromstring(clone_xml)
    source_root = DefusedET.fromstring(source_xml)
    source_os = source_root.find("os")
    clone_os = clone_root.find("os")
    if source_os is None or clone_os is None:
        raise FdeHostError("Domain XML is missing <os>")
    restored_os = DefusedET.fromstring(ET.tostring(source_os, encoding="unicode"))
    nvram_elem = restored_os.find("nvram")
    if nvram_elem is None:
        nvram_elem = ET.SubElement(restored_os, "nvram", {"format": "raw"})
    nvram_elem.text = str(clone_nvram)
    index = list(clone_root).index(clone_os)
    clone_root.remove(clone_os)
    clone_root.insert(index, restored_os)
    return ET.tostring(clone_root, encoding="unicode")


def extract_nvram_path(domain_xml: str) -> Path:
    """Extract the host NVRAM file path from domain XML."""
    root = DefusedET.fromstring(domain_xml)
    nvram_elem = root.find("./os/nvram")
    text = nvram_elem.text if nvram_elem is not None else None
    if not text:
        text = nvram_elem.get("source") if nvram_elem is not None else None
    if not text:
        raise FdeHostError("Domain XML has no NVRAM path")
    return Path(text)


def prepare_clone_host_state(
    steps: tuple[str, ...], clone_disk: Path, clone_nvram: Path
) -> None:
    """Apply stopped-clone host-side firmware and disk preparations."""
    if "preos-weak-sb" in steps:
        # The shim keeps its vendor signature so the boot chain stays intact and
        # grub still chains to the CA the firmware measured for shim. The weak
        # authority comes from a pre-OS driver verified by the same weak CA.
        image, cert_der = sign_efi_application(
            minimal_efi_driver(),
            rsa_bits=1024,
            common_name="UGT Weak RSA-1024 CA",
        )
        with open_qcow2_nbd(clone_disk, writable=True) as nbd:
            part = write_fat32_file(nbd, "ubuntu-seed", "/EFI/ugt/weak.efi", image)
        nvram = NvramStore.from_file(clone_nvram)
        nvram.append_db_signature_list(signature_list_x509(cert_der))
        nvram.set_variable(
            "Driver0001",
            EFI_GLOBAL_VARIABLE_GUID,
            efi_load_option(
                "UGT Weak Signed Driver",
                "\\EFI\\ugt\\weak.efi",
                part.number,
                part.start_lba,
                part.size_lba,
                part.unique_guid,
            ),
            attributes=_EFI_VARIABLE_NV_BS_RT,
        )
        nvram.set_variable(
            "DriverOrder",
            EFI_GLOBAL_VARIABLE_GUID,
            struct.pack("<H", 0x0001),
            attributes=_EFI_VARIABLE_NV_BS_RT,
        )
        clone_nvram.write_bytes(nvram.to_bytes())
        return

    if "plain-ovmf" in steps:
        if not PLAIN_OVMF_VARS.is_file():
            raise FdeHostError(f"Missing plain OVMF vars at '{PLAIN_OVMF_VARS}'")
        shutil.copy2(PLAIN_OVMF_VARS, clone_nvram)
        return

    if "preos-digest-sb" in steps:
        image = minimal_efi_driver()
        with open_qcow2_nbd(clone_disk, writable=True) as nbd:
            part = write_fat32_file(nbd, "ubuntu-seed", "/EFI/ugt/digest.efi", image)
        nvram = NvramStore.from_file(clone_nvram)
        nvram.append_db_signature_list(
            signature_list_sha256(authenticode_sha256_pe(image))
        )
        nvram.set_variable(
            "Driver0001",
            EFI_GLOBAL_VARIABLE_GUID,
            efi_load_option(
                "UGT Pre-OS Digest Driver",
                "\\EFI\\ugt\\digest.efi",
                part.number,
                part.start_lba,
                part.size_lba,
                part.unique_guid,
            ),
            attributes=_EFI_VARIABLE_NV_BS_RT,
        )
        nvram.set_variable(
            "DriverOrder",
            EFI_GLOBAL_VARIABLE_GUID,
            struct.pack("<H", 0x0001),
            attributes=_EFI_VARIABLE_NV_BS_RT,
        )
        clone_nvram.write_bytes(nvram.to_bytes())
        return

    sysprep_step = next(
        (
            s
            for s in steps
            if s in ("sysprep-app", "sysprep-weak-sb", "sysprep-digest-sb")
        ),
        None,
    )
    if sysprep_step is None:
        return

    image = minimal_efi_application()
    if sysprep_step == "sysprep-app":
        efi_bytes, cert_der = sign_efi_application(
            image, rsa_bits=2048, common_name="UGT SysPrep Test CA"
        )
        sig_list = signature_list_x509(cert_der)
        fat_path = "/EFI/sysprep/sysprep.efi"
        efi_path = "\\EFI\\sysprep\\sysprep.efi"
        desc = "UGT SysPrep Application"
    elif sysprep_step == "sysprep-weak-sb":
        efi_bytes, cert_der = sign_efi_application(
            image, rsa_bits=1024, common_name="UGT Weak RSA-1024 CA"
        )
        sig_list = signature_list_x509(cert_der)
        fat_path = "/EFI/sysprep/weak.efi"
        efi_path = "\\EFI\\sysprep\\weak.efi"
        desc = "UGT Weak Signed SysPrep"
    else:
        efi_bytes = image
        sig_list = signature_list_sha256(authenticode_sha256_pe(image))
        fat_path = "/EFI/sysprep/digest.efi"
        efi_path = "\\EFI\\sysprep\\digest.efi"
        desc = "UGT Digest Authorized SysPrep"

    with open_qcow2_nbd(clone_disk, writable=True) as nbd:
        part = write_fat32_file(nbd, "ubuntu-seed", fat_path, efi_bytes)

    nvram = NvramStore.from_file(clone_nvram)
    nvram.append_db_signature_list(sig_list)
    nvram.set_variable(
        "SysPrep0001",
        EFI_GLOBAL_VARIABLE_GUID,
        efi_load_option(
            desc, efi_path, part.number, part.start_lba, part.size_lba, part.unique_guid
        ),
        attributes=_EFI_VARIABLE_NV_BS_RT,
    )
    nvram.set_variable(
        "SysPrepOrder",
        EFI_GLOBAL_VARIABLE_GUID,
        struct.pack("<H", 0x0001),
        attributes=_EFI_VARIABLE_NV_BS_RT,
    )
    clone_nvram.write_bytes(nvram.to_bytes())


def _run_host(command: list[str]) -> None:
    completed = subprocess.run(  # noqa: S603 - fixed helper argv
        command, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise FdeHostError(
            f"{command[0]} failed ({completed.returncode}): {completed.stderr.strip()}"
        )
