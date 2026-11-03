"""Private manuscript report destinations must never be repository artifacts."""

from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from aeonith.workflow import main


class WorkflowPrivateOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manuscript = self.root / "source.md"
        self.manuscript.write_text("Private original sentence.", encoding="utf-8")

    def _invoke(self, output: Path) -> tuple[int, str]:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            code = main(["--input", str(self.manuscript), "--output", str(output)])
        return code, stderr.getvalue()

    def _init_git(self, folder: Path, *, bare: bool = False) -> None:
        folder.mkdir()
        subprocess.run(["git", "init", "--quiet", "--bare" if bare else "--initial-branch=main", str(folder)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_rejects_unrelated_git_checkout_before_creating_report(self) -> None:
        checkout = self.root / "unrelated"
        self._init_git(checkout)
        output = checkout / "review.md"
        code, error = self._invoke(output)
        self.assertEqual(code, 2, error)
        self.assertFalse(output.exists())

    def test_rejects_bare_git_repo_before_creating_report(self) -> None:
        checkout = self.root / "bare.git"
        self._init_git(checkout, bare=True)
        output = checkout / "review.md"
        code, error = self._invoke(output)
        self.assertEqual(code, 2, error)
        self.assertFalse(output.exists())

    def test_rejects_git_worktree_file_marker(self) -> None:
        checkout = self.root / "linked"
        checkout.mkdir()
        (checkout / ".git").write_text("gitdir: /outside/private/worktrees/example\n", encoding="utf-8")
        output = checkout / "review.md"
        code, error = self._invoke(output)
        self.assertEqual(code, 2, error)
        self.assertFalse(output.exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_rejects_symlinked_parent_even_when_target_is_outside_git(self) -> None:
        private = self.root / "private"
        private.mkdir()
        alias = self.root / "alias"
        try:
            alias.symlink_to(private, target_is_directory=True)
        except (NotImplementedError, OSError):
            self.skipTest("symlink creation unavailable")
        output = alias / "review.md"
        code, error = self._invoke(output)
        self.assertEqual(code, 2, error)
        self.assertFalse((private / "review.md").exists())

    def test_windows_private_file_output_requires_unimplemented_acl_boundary(self) -> None:
        output = self.root / "review.md"
        with patch("aeonith.private_output._is_windows", return_value=True):
            code, error = self._invoke(output)
        self.assertEqual(code, 2, error)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
