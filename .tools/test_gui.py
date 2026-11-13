"""Tests for the file readers behind `study gui`. Run: python3 .tools/test_gui.py"""

import io
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


class Upload(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "PRI").mkdir()

    def save(self, name, data=b"%PDF-1.4 hi"):
        return gui.save_upload(self.root, "PRI", name, io.BytesIO(data), len(data))

    def test_saves_into_materials(self):
        dest = self.save("Lecture 3.pdf")
        self.assertEqual(dest, self.root / "PRI/materials/Lecture 3.pdf")
        self.assertEqual(dest.read_bytes(), b"%PDF-1.4 hi")

    def test_never_overwrites(self):
        self.save("w1.pdf", b"one")
        self.assertEqual(self.save("w1.pdf", b"two").name, "w1 (2).pdf")
        self.assertEqual(self.save("w1.pdf", b"three").name, "w1 (3).pdf")
        self.assertEqual((self.root / "PRI/materials/w1.pdf").read_bytes(), b"one")

    def test_folders_in_the_name_are_dropped(self):
        self.assertEqual(self.save("../../etc/x.pdf").parent, self.root / "PRI/materials")
        self.assertEqual(self.save("C:\\Users\\me\\y.pdf").name, "y.pdf")

    def test_rejects_unsupported_hidden_and_empty(self):
        for name in ("virus.exe", ".secret.pdf", "noext", ""):
            with self.assertRaises(ValueError):
                self.save(name)
        with self.assertRaises(ValueError):
            self.save("empty.pdf", b"")

    def test_cut_off_upload_leaves_nothing(self):
        with self.assertRaises(ValueError):
            gui.save_upload(self.root, "PRI", "big.pdf", io.BytesIO(b"abc"), 10)
        self.assertEqual(list((self.root / "PRI/materials").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
