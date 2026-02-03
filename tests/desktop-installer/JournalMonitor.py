from robot.api import logger
from robot.api.deco import keyword, library
from robot.libraries.BuiltIn import BuiltIn
import os
import subprocess


@library
class JournalMonitor:
    process = None

    @keyword
    def start(
        self,
        username="ubuntu",
        password="ubuntu",
        filename="journal.log",
    ):
        if self.process:
            return

        output_dir = BuiltIn().get_variable_value("${OUTPUT_DIR}", "")
        if output_dir == "":
            logger.error("OUTPUT_DIR not set")
            return

        cid = BuiltIn().get_variable_value("${CID}", "")
        if cid == "":
            logger.error("CID not set")
            return

        journal_file = os.path.join(output_dir, filename)
        cmd = [
            "sshpass",
            "-e",
            "ssh",
            "-o",
            f"ProxyCommand=/usr/bin/socat - VSOCK-CONNECT:{cid}:22",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            f"{username}@localhost",
            "journalctl",
            "--boot",
            "--no-tail",
            "--follow",
        ]

        with open(journal_file, "wb+") as f:
            try:
                self.process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdout=f,
                    env={"SSHPASS": password},
                )
            except Exception as e:
                logger.error(f"could not spawn subprocess: {e}")
                return

            try:
                self.process.wait(1)
                stderr = self.process.stderr.read().decode()
                logger.error(f"monitor exited early: {stderr}")
            except subprocess.TimeoutExpired:
                pass

    @keyword
    def stop(self):
        if self.process is None:
            return
        self.process.terminate()
        self.process.wait()
        self.process = None
