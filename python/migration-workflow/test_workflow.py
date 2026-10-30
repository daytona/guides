"""Offline acceptance checks; no provider credentials or live sandboxes."""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from workflow import run_workflow


class WorkflowTests(unittest.TestCase):
    def test_failed_commands_and_corrupt_files_never_report_success_and_always_clean_up(self):
        cases = [
            ("exited", 0, "migration ok\n", True),
            ("exited", 1, "migration ok\n", False),
            ("timed_out", 0, "migration ok\n", False),
            ("exited", 0, "different", False),
        ]
        for reason, exit_code, output, succeeds in cases:
            with self.subTest(reason=reason, exit_code=exit_code, output=output):
                deleted = []
                ready = []
                sandbox = SimpleNamespace(
                    id="example-sandbox",
                    wait=lambda **kw: ready.append(True),
                    fs=SimpleNamespace(write_text=lambda *a: self.assertEqual(ready, [True]), read_text=lambda *a: output),
                    process=SimpleNamespace(run=lambda **kw: SimpleNamespace(reason=reason, exit_code=exit_code)),
                    delete=lambda: deleted.append(True),
                )
                client = SimpleNamespace(v2=SimpleNamespace(create=lambda *a, **kw: sandbox))
                if succeeds:
                    self.assertEqual(run_workflow(client, "example-image")["output"], "migration ok\n")
                else:
                    with self.assertRaises(RuntimeError):
                        run_workflow(client, "example-image")
                self.assertEqual(deleted, [True])

    def test_startup_failure_cleans_up_without_accessing_guest(self):
        deleted = []
        def fail(**kwargs):
            raise RuntimeError("startup deadline exceeded")
        sandbox = SimpleNamespace(id="failed-start", wait=fail, delete=lambda: deleted.append(True))
        client = SimpleNamespace(v2=SimpleNamespace(create=lambda *a, **kw: sandbox))
        with self.assertRaisesRegex(RuntimeError, "startup deadline exceeded"):
            run_workflow(client, "example-image")
        self.assertEqual(deleted, [True])

    def test_cli_refuses_cloud_execution_without_run(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("workflow.py"))],
                                env={"PATH": os.environ.get("PATH", "")}, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Pass --run to create a billable disposable sandbox.", result.stderr)


if __name__ == "__main__":
    unittest.main()
