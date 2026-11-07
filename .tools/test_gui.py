"""Tests for the file readers behind `study gui`. Run: python3 .tools/test_gui.py"""

import tempfile
import unittest
from pathlib import Path

import gui


class SessionNotes(unittest.TestCase):
    def folder(self, **logs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        sessions = Path(tmp.name) / "sessions"
        sessions.mkdir()
        for name, text in logs.items():
            (sessions / f"{name.replace('_', '-')}.md").write_text(text, encoding="utf-8")
        return Path(tmp.name)

    def test_no_sessions_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(gui.session_notes(Path(tmp)))

    def test_newest_log_without_its_title(self):
        folder = self.folder(**{"2026_10_01": "# PRI\n\n- old\n", "2026_10_25": "# PRI — 2026-10-25\n\n- new\n"})
        self.assertEqual(gui.session_notes(folder), {"date": "2026-10-25", "text": "- new"})

    def test_chat_transcripts_are_skipped(self):
        folder = self.folder(**{"2026_10_25": "- real\n", "2026_11_01_chat": "**You:** hi\n"})
        self.assertEqual(gui.session_notes(folder)["date"], "2026-10-25")

    def test_only_a_chat_transcript(self):
        self.assertIsNone(gui.session_notes(self.folder(**{"2026_11_01_chat": "**You:** hi\n"})))

    def test_title_only_log_is_empty(self):
        self.assertIsNone(gui.session_notes(self.folder(**{"2026_10_25": "# PRI\n"})))

    def test_log_without_a_title_stays_whole(self):
        self.assertEqual(gui.session_notes(self.folder(**{"2026_10_25": "- one\n- two\n"}))["text"], "- one\n- two")


if __name__ == "__main__":
    unittest.main()
