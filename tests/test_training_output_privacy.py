"""Training artifacts must never be created inside unrelated Git checkouts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from training.corpus import CorpusError
from training.train_lora import _output_path


class TrainingOutputPrivacyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_unrelated_repository_checkout_refused(self) -> None:
        repo = self.root / "other-repository"
        (repo / ".git").mkdir(parents=True)
        (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        output = repo / "private-adapter"
        with self.assertRaisesRegex(CorpusError, "outside Git checkouts"):
            _output_path(str(output))
        self.assertFalse(output.exists())

    def test_unrelated_git_worktree_marker_refused(self) -> None:
        worktree = self.root / "other-worktree"
        worktree.mkdir()
        (worktree / ".git").write_text(
            "gitdir: /git/other/worktrees/example\n", encoding="utf-8"
        )
        output = worktree / "private-adapter"
        with self.assertRaisesRegex(CorpusError, "outside Git checkouts"):
            _output_path(str(output))
        self.assertFalse(output.exists())

    def test_bare_repository_refused(self) -> None:
        repo = self.root / "bare.git"
        (repo / "objects").mkdir(parents=True)
        (repo / "refs").mkdir()
        (repo / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        with self.assertRaisesRegex(CorpusError, "outside Git checkouts"):
            _output_path(str(repo / "private-adapter"))

    def test_symlinked_parent_refused_without_creating_artifacts(self) -> None:
        linked = self.root / "alias"
        try:
            linked.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"filesystem does not permit test symlinks: {exc}")
        output = linked / "private-adapter"
        with self.assertRaisesRegex(CorpusError, "symlinks and reparse points"):
            _output_path(str(output))
        self.assertFalse((self.root / "private-adapter").exists())

    def test_parent_traversal_and_unc_paths_refused(self) -> None:
        for candidate in (str(self.root / "sub" / ".." / "private"),
                          r"\\server\share\private", "//server/share/private",
                          str(self.root / "private") + ":stream"):
            with self.subTest(candidate=candidate):
                with self.assertRaises(CorpusError):
                    _output_path(candidate)

    def test_sensible_private_directory_remains_valid(self) -> None:
        output = self.root / "private-adapter"
        self.assertEqual(_output_path(str(output)), output.resolve())
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
