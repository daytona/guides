from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from daytona_api_client import SnapshotState

from devin_outposts.build_linux_snapshot import EXIT_COLLISION, main


class LinuxSnapshotReuseTests(unittest.TestCase):
    def run_with_existing_snapshot(
        self, state: SnapshotState
    ) -> tuple[int, str, str, Mock]:
        snapshot = SimpleNamespace(name="review-snapshot", state=state)
        daytona = Mock()
        daytona.snapshot.list.return_value = SimpleNamespace(
            items=[snapshot], total_pages=1
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch("devin_outposts.build_linux_snapshot.load_env_file"),
            patch(
                "devin_outposts.build_linux_snapshot.dockerfile_sha8",
                return_value="12345678",
            ),
            patch(
                "devin_outposts.build_linux_snapshot.snapshot_name",
                return_value="review-snapshot",
            ),
            patch("devin_outposts.build_linux_snapshot.Daytona", return_value=daytona),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = main()

        return result, stdout.getvalue(), stderr.getvalue(), daytona

    def test_active_existing_snapshot_is_reused(self) -> None:
        result, stdout, stderr, daytona = self.run_with_existing_snapshot(
            SnapshotState.ACTIVE
        )

        self.assertEqual(result, 0)
        self.assertIn("Reusing snapshot: review-snapshot state=active", stdout)
        self.assertEqual(stderr, "")
        daytona.snapshot.create.assert_not_called()

    def test_unusable_existing_snapshot_is_a_collision(self) -> None:
        for state in (
            SnapshotState.BUILD_FAILED,
            SnapshotState.ERROR,
            SnapshotState.INACTIVE,
        ):
            with self.subTest(state=state):
                result, stdout, stderr, daytona = self.run_with_existing_snapshot(state)

                self.assertEqual(result, EXIT_COLLISION)
                self.assertIn("Snapshot name: review-snapshot", stdout)
                self.assertEqual(
                    stderr,
                    "Snapshot name collision: review-snapshot "
                    f"state={state.value}; expected active\n",
                )
                daytona.snapshot.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
