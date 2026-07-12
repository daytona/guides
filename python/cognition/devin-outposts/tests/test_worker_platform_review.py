from __future__ import annotations

import unittest

from devin_outposts.worker_windows import (
    LOGGER,
    download_windows_text,
    windows_download_script,
)


class WindowsDownloadScriptTests(unittest.TestCase):
    def test_remote_verification_checks_help_exit_before_success_marker(self) -> None:
        script = windows_download_script(
            remote_sha="0123456789abcdef",
            checksum="a" * 64,
            executable=r"C:\ProgramData\devin-outposts\remote\devin-remote.exe",
        )

        help_index = script.index("& $destination --help | Out-Null")
        exit_check_index = script.index(
            "if ($LASTEXITCODE -ne 0)",
            help_index,
        )
        failure_exit_index = script.index("exit 1", exit_check_index)
        verified_index = script.index("Write-Output 'REMOTE_VERIFIED'")

        self.assertLess(help_index, exit_check_index)
        self.assertLess(exit_check_index, failure_exit_index)
        self.assertLess(failure_exit_index, verified_index)


class DownloadWindowsTextTests(unittest.TestCase):
    def test_download_failure_returns_empty_and_logs_sanitized_context(self) -> None:
        class FailingFilesystem:
            def download_file(self, path: str) -> bytes:
                self.requested_path = path
                raise RuntimeError("secret-token-from-service")

        class Sandbox:
            fs = FailingFilesystem()

        path = r"C:\ProgramData\devin-outposts\sessions\session-1\worker.pid"
        sandbox = Sandbox()
        with self.assertLogs(LOGGER, level="WARNING") as captured:
            content = download_windows_text(sandbox, path)

        self.assertEqual(content, "")
        self.assertEqual(
            sandbox.fs.requested_path,
            "C:/ProgramData/devin-outposts/sessions/session-1/worker.pid",
        )
        log_output = "\n".join(captured.output)
        self.assertIn(sandbox.fs.requested_path, log_output)
        self.assertIn("RuntimeError", log_output)
        self.assertNotIn("secret-token-from-service", log_output)


if __name__ == "__main__":
    unittest.main()
