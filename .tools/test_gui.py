"""Tests for the file readers behind `study gui`. Run: python3 .tools/test_gui.py"""

import io
import json
import tempfile
import unittest
import unittest.mock
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

    def test_screenshots_go_to_screens_not_materials(self):
        data = b"\x89PNG fake"
        dest = gui.save_upload(self.root, "PRI", "Screenshot 2026-11-18.png", io.BytesIO(data), len(data), "screen")
        self.assertEqual(dest, self.root / "PRI/screens/Screenshot 2026-11-18.png")
        self.assertFalse((self.root / "PRI/materials").exists())
        self.assertEqual(gui.screen_file(self.root, "PRI", "Screenshot 2026-11-18.png"), dest)

    def test_screens_only_take_images(self):
        with self.assertRaises(ValueError):
            gui.save_upload(self.root, "PRI", "notes.pdf", io.BytesIO(b"x"), 1, "screen")
        with self.assertRaises(ValueError):
            gui.save_upload(self.root, "PRI", "huge.png", io.BytesIO(b"x"), gui.MAX_SCREEN + 1, "screen")

    def test_screen_file_stays_in_screens(self):
        gui.save_upload(self.root, "PRI", "a.png", io.BytesIO(b"x"), 1, "screen")
        for bad in ("../progress.md", "../screens/a.png", ".hidden.png", "a.txt", "missing.png"):
            self.assertIsNone(gui.screen_file(self.root, "PRI", bad))


class Deadlines(unittest.TestCase):
    MD = ("# Deadlines\n\n| Item | Kind | Date | Points | Got | Need | Notes |\n|---|---|---|---|---|---|---|\n"
          "| Kolokwium 1 | test | 29.11.2026 | 40 | | 25 | |\n| Sprawdzian 2 | test | | 40 | | | zjazd 6 |\n"
          "| Lab 1 | quiz? | 2026-10-10 | 5 | done | | |\n")

    def test_parse(self):
        rows = gui.sd.parse_deadlines(self.MD, "2026-11-22")
        self.assertEqual([(r["item"], r["kind"], r["date"], r["days"], r["done"]) for r in rows],
                         [("Kolokwium 1", "test", "2026-11-29", 7, False), ("Sprawdzian 2", "test", None, None, False),
                          ("Lab 1", "homework", "2026-10-10", -43, True)])

    def test_set_date_only_touches_that_row(self):
        out = gui.sd.set_deadline_date(self.MD, "sprawdzian 2", "2026-12-13")
        self.assertIn("| Sprawdzian 2 | test | 2026-12-13 | 40 |", out)
        self.assertEqual(out.replace("2026-12-13", ""), self.MD.replace("| Sprawdzian 2 | test | | 40 | | | zjazd 6 |",
                                                                        "| Sprawdzian 2 | test |  | 40 |  |  | zjazd 6 |"))
        with self.assertRaises(KeyError):
            gui.sd.set_deadline_date(self.MD, "Nope", "2026-12-13")
        with self.assertRaises(ValueError):
            gui.sd.set_deadline_date(self.MD, "Kolokwium 1", "13.12.2026")


class Handover(unittest.TestCase):
    def test_empty_or_junk_gives_nothing(self):
        for recent in (None, [], "text", [None, 3, {"role": "me", "text": "  "}]):
            self.assertEqual(gui.handover(recent), "")

    def test_keeps_last_messages_and_end_of_long_replies(self):
        recent = [{"role": "me", "text": f"q{i}"} for i in range(5)] + [{"role": "tutor", "text": "x" * 2000 + "TASK"}]
        out = gui.handover(recent)
        self.assertNotIn("q1", out)
        self.assertIn("Student: q4", out)
        self.assertIn("TASK", out)
        self.assertLess(len(out), 2000)


class Blocked(unittest.TestCase):
    def run_lines(self, *events):
        import agents

        class Proc:
            stdout = [json.dumps(e) + "\n" for e in events]
            returncode = 0
            def wait(self): pass
            def poll(self): return 0
        return [e["type"] for e in agents.Run(Proc()).events()]

    def test_refusal_is_reported_once(self):
        refusal = {"type": "stream_event", "event": {"type": "message_delta", "delta": {"stop_reason": "refusal"}}}
        assistant = {"type": "assistant", "message": {"stop_reason": "refusal", "content": []}}
        done = {"type": "result", "session_id": "s"}
        self.assertEqual(self.run_lines(refusal, assistant, done), ["blocked", "done"])

    def test_normal_reply_is_not_blocked(self):
        ok = {"type": "stream_event", "event": {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}}
        self.assertEqual(self.run_lines(ok, {"type": "result"}), ["done"])


class LongSession(unittest.TestCase):
    def test_size_check(self):
        import agents
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": d}):
            a = agents.ClaudeAdapter(d)
            f = a.session_file("abc-1")
            f.parent.mkdir(parents=True)
            f.write_bytes(b"x" * 10)
            self.assertFalse(a.too_long("abc-1"))
            with unittest.mock.patch.object(agents, "MAX_SESSION_BYTES", 5):
                self.assertTrue(a.too_long("abc-1"))
            self.assertFalse(a.too_long("missing"))
            self.assertIsNone(a.session_file("../etc"))


if __name__ == "__main__":
    unittest.main()
