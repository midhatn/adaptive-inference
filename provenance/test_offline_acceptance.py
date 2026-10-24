"""Substantive network-denial and existing-destination regression checks."""
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

from offline_acceptance import OfflineGuard, run_acceptance


class OfflineAcceptanceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git"), "Git is required")
    def test_guard_rejects_real_git_transport_python_socket_and_other_children(self):
        original = subprocess.Popen
        with tempfile.TemporaryDirectory() as directory:
            with OfflineGuard() as guard:
                self.assertTrue(guard.positive_control(directory)["passed"])
                with self.assertRaises(PermissionError):
                    socket.socket()
                with self.assertRaises(PermissionError):
                    subprocess.run([sys.executable, "-c", "raise SystemExit(0)"], check=True)
                with self.assertRaises(PermissionError):
                    subprocess.run([str(guard.git), "-c", "protocol.https.allow=always", "--version"], check=True)
                self.assertEqual(guard.socket_attempts, 1)
            self.assertIs(subprocess.Popen, original)
            self.assertFalse(guard.active)

    def test_existing_output_refused_before_any_modification(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "preserve.txt"
            marker.write_text("existing data", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already exists"):
                run_acceptance(directory)
            self.assertEqual(marker.read_text(encoding="utf-8"), "existing data")
            self.assertFalse((Path(directory) / "result.json").exists())


if __name__ == "__main__":
    unittest.main()
