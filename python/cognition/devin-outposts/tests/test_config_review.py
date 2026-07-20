from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values

from devin_outposts.config import Config, ConfigError, redact, resolve_acceptor_id


class AcceptorIdentityTests(unittest.TestCase):
    def test_generated_identity_is_stable_per_outpost_and_distinct_between_outposts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            generated = [uuid.UUID(int=1), uuid.UUID(int=2)]
            with patch("devin_outposts.config.uuid.uuid4", side_effect=generated):
                outpost_a = resolve_acceptor_id(state_dir, "outpost-a", None)
                outpost_b = resolve_acceptor_id(state_dir, "outpost-b", None)

            self.assertNotEqual(outpost_a, outpost_b)
            self.assertEqual(resolve_acceptor_id(state_dir, "outpost-a", None), outpost_a)
            self.assertEqual(resolve_acceptor_id(state_dir, "outpost-b", None), outpost_b)

    def test_explicit_identity_is_preserved_and_persisted_for_its_outpost(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)

            self.assertEqual(
                resolve_acceptor_id(state_dir, "outpost-a", "  deliberate-acceptor-a  "),
                "deliberate-acceptor-a",
            )
            self.assertEqual(
                resolve_acceptor_id(state_dir, "outpost-b", "deliberate-acceptor-b"),
                "deliberate-acceptor-b",
            )
            self.assertEqual(
                resolve_acceptor_id(state_dir, "outpost-a", None),
                "deliberate-acceptor-a",
            )
            self.assertEqual(
                resolve_acceptor_id(state_dir, "outpost-b", None),
                "deliberate-acceptor-b",
            )


class EnvironmentContractTests(unittest.TestCase):
    def test_whitespace_only_required_values_are_reported_missing(self) -> None:
        env = {
            "DEVIN_OUTPOSTS_TOKEN": " \t ",
            "DAYTONA_API_KEY": "   ",
            "OUTPOST_ID": "\n",
            "SNAPSHOT_NAME": "\r\n",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("devin_outposts.config.load_dotenv_if_available"),
        ):
            with self.assertRaises(ConfigError) as caught:
                Config.from_env()

        self.assertEqual(
            str(caught.exception),
            "Missing required environment variables: "
            "DAYTONA_API_KEY, DEVIN_OUTPOSTS_TOKEN, OUTPOST_ID, SNAPSHOT_NAME",
        )

    def test_required_values_are_trimmed_before_being_returned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "DEVIN_OUTPOSTS_TOKEN": "  devin-token  ",
                "DAYTONA_API_KEY": "  daytona-key  ",
                "OUTPOST_ID": "  outpost-a  ",
                "SNAPSHOT_NAME": "  snapshot-a  ",
                "STATE_DIR": temp_dir,
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch("devin_outposts.config.load_dotenv_if_available"),
            ):
                config = Config.from_env()

        self.assertEqual(config.devin_outposts_token, "devin-token")
        self.assertEqual(config.outpost_id, "outpost-a")
        self.assertEqual(config.snapshot_name, "snapshot-a")


class DotenvExampleTests(unittest.TestCase):
    def test_windows_paths_parse_without_losing_spaces_or_backslashes(self) -> None:
        example_path = Path(__file__).resolve().parents[1] / ".env.example"

        values = dotenv_values(example_path)

        self.assertEqual(values["WINDOWS_WORKDIR"], r"C:\repos")
        self.assertEqual(
            values["DEVIN_WINDOWS_CHROME_PATH"],
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        )


class RedactionTests(unittest.TestCase):
    def test_overlapping_secrets_are_replaced_longest_first(self) -> None:
        redacted = redact(
            "long-token-suffix then long-token and long-token-suffix",
            ["", "long-token", "long-token-suffix"],
        )

        self.assertEqual(redacted, "<redacted> then <redacted> and <redacted>")


if __name__ == "__main__":
    unittest.main()
