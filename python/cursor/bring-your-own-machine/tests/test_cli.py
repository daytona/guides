from __future__ import annotations

import io
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from cursor_byom import build_snapshot as build_snapshot_module
from cursor_byom import monitor as monitor_module
from cursor_byom import spawn as spawn_module


ENTRY_POINTS = (
    ("spawn-cursor-byom-worker", spawn_module, spawn_module.Config, "from_env"),
    (
        "monitor-cursor-byom-worker",
        monitor_module,
        monitor_module.MonitorConfig,
        "from_env",
    ),
    (
        "build-cursor-byom-snapshot",
        build_snapshot_module,
        build_snapshot_module,
        "load_dotenv",
    ),
)


class CliContractTests(unittest.TestCase):
    def test_help_exits_zero_without_loading_configuration_or_constructing_daytona(
        self,
    ) -> None:
        for command, module, config_owner, config_parser_name in ENTRY_POINTS:
            with self.subTest(command=command), ExitStack() as stack:
                config_parser = stack.enter_context(
                    patch.object(config_owner, config_parser_name)
                )
                daytona = stack.enter_context(patch.object(module, "Daytona"))
                output = io.StringIO()
                stack.enter_context(patch("sys.stdout", output))

                with self.assertRaises(SystemExit) as raised:
                    module.main(["--help"])

                self.assertEqual(raised.exception.code, 0)
                config_parser.assert_not_called()
                daytona.assert_not_called()
                copyable_examples = [
                    line.strip()
                    for line in output.getvalue().splitlines()
                    if line.strip() == command
                ]
                self.assertEqual(copyable_examples, [command])

    def test_unknown_argument_exits_two_without_side_effects(self) -> None:
        for command, module, config_owner, config_parser_name in ENTRY_POINTS:
            with self.subTest(command=command), ExitStack() as stack:
                config_parser = stack.enter_context(
                    patch.object(config_owner, config_parser_name)
                )
                daytona = stack.enter_context(patch.object(module, "Daytona"))
                stack.enter_context(patch("sys.stderr", io.StringIO()))

                with self.assertRaises(SystemExit) as raised:
                    module.main(["--unknown"])

                self.assertEqual(raised.exception.code, 2)
                config_parser.assert_not_called()
                daytona.assert_not_called()


if __name__ == "__main__":
    unittest.main()
