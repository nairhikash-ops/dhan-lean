import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from dhan_lean.security.token_store import (
    check_token_configured,
    save_dhan_token,
    TokenStoreError,
    PermissionDeniedError,
    SymlinkNotAllowedError,
    InvalidTokenError,
)


class TestTokenStore(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.env_file = self.dir_path / "dhan.env"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_save_token_success_and_permissions(self) -> None:
        token_val = "sample_secret_token_12345"
        save_dhan_token(self.env_file, token_val)

        self.assertTrue(self.env_file.exists())
        self.assertTrue(check_token_configured(self.env_file))

        # Check mode 0600 on POSIX systems
        if sys.platform != "win32":
            mode = stat.S_IMODE(os.stat(self.env_file).st_mode)
            self.assertEqual(mode, 0o600)

        content = self.env_file.read_text(encoding="utf-8")
        self.assertIn("DHAN_ACCESS_TOKEN=sample_secret_token_12345", content)


    def test_preserve_existing_variables_and_comments(self) -> None:
        initial_content = "# Configuration File\nOTHER_VAR=123\nDHAN_ACCESS_TOKEN=old_token\nFOO=bar\n"
        self.env_file.write_text(initial_content, encoding="utf-8")

        new_token = "new_secret_token_999"
        save_dhan_token(self.env_file, new_token)

        content = self.env_file.read_text(encoding="utf-8")
        self.assertIn("# Configuration File", content)
        self.assertIn("OTHER_VAR=123", content)
        self.assertIn("FOO=bar", content)
        self.assertIn("DHAN_ACCESS_TOKEN=new_secret_token_999", content)
        self.assertNotIn("old_token", content)

    def test_duplicate_entries_collapsed_to_one(self) -> None:
        duplicate_content = "DHAN_ACCESS_TOKEN=dup1\nFOO=1\nDHAN_ACCESS_TOKEN=dup2\nBAR=2\nDHAN_ACCESS_TOKEN=dup3\n"
        self.env_file.write_text(duplicate_content, encoding="utf-8")

        new_token = "single_token_val"
        save_dhan_token(self.env_file, new_token)

        content = self.env_file.read_text(encoding="utf-8")
        token_lines = [line for line in content.splitlines() if line.startswith("DHAN_ACCESS_TOKEN=")]
        self.assertEqual(len(token_lines), 1)
        self.assertEqual(token_lines[0], "DHAN_ACCESS_TOKEN=single_token_val")
        self.assertIn("FOO=1", content)
        self.assertIn("BAR=2", content)

    def test_reject_empty_or_whitespace_token(self) -> None:
        with self.assertRaises(InvalidTokenError):
            save_dhan_token(self.env_file, "")

        with self.assertRaises(InvalidTokenError):
            save_dhan_token(self.env_file, "   ")

    def test_reject_control_characters_cr_lf_null(self) -> None:
        with self.assertRaises(InvalidTokenError):
            save_dhan_token(self.env_file, "token\rwith_cr")

        with self.assertRaises(InvalidTokenError):
            save_dhan_token(self.env_file, "token\nwith_lf")

        with self.assertRaises(InvalidTokenError):
            save_dhan_token(self.env_file, "token\0with_null")

    def test_reject_excessive_length_token(self) -> None:
        long_token = "a" * 5000
        with self.assertRaises(InvalidTokenError):
            save_dhan_token(self.env_file, long_token)

    def test_symlinked_credential_path_rejected(self) -> None:
        if hasattr(os, "symlink"):
            target_file = self.dir_path / "real_dhan.env"
            target_file.write_text("DHAN_ACCESS_TOKEN=initial", encoding="utf-8")
            symlink_file = self.dir_path / "symlink_dhan.env"
            try:
                os.symlink(target_file, symlink_file)
                with self.assertRaises(SymlinkNotAllowedError):
                    save_dhan_token(symlink_file, "new_token")

                with self.assertRaises(SymlinkNotAllowedError):
                    check_token_configured(symlink_file)
            except OSError:
                pass  # Skip if system permissions prevent symlink creation

    def test_temp_file_cleaned_up_on_failure(self) -> None:
        # Cause save_dhan_token to fail during validation
        initial_files = set(self.dir_path.glob("*"))
        with self.assertRaises(InvalidTokenError):
            save_dhan_token(self.env_file, "invalid\ntoken")

        current_files = set(self.dir_path.glob("*"))
        tmp_files = [f for f in current_files if "dhan_env_tmp_" in f.name]
        self.assertEqual(len(tmp_files), 0)

    def test_permission_failure_handled_safely(self) -> None:
        from unittest.mock import patch
        with patch("tempfile.mkstemp", side_effect=PermissionError("Access denied")):
            with self.assertRaises(PermissionDeniedError) as cm:
                save_dhan_token(self.env_file, "valid_token_123")
            self.assertNotIn("valid_token_123", str(cm.exception))


    def test_token_never_appears_in_exception_messages(self) -> None:
        secret_token = "MY_VERY_SECRET_TOKEN_XYZ"
        with self.assertRaises(InvalidTokenError) as cm:
            save_dhan_token(self.env_file, f"{secret_token}\n")

        self.assertNotIn(secret_token, str(cm.exception))


if __name__ == "__main__":
    unittest.main()
