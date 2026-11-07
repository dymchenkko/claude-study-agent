"""Tests for the planner, events, links and freshness behind `study gui` / `study plan` / `study log`.
Run: python3 .tools/test_planner.py"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import planner
import studydata as sd

TODAY = "2026-11-07"
HEAD = "| Topic | Level | Last studied | Next review | Interval (d) | Notes |\n|---|---|---|---|---|---|\n"


def progress(*rows):
    return HEAD + "".join(f"| {t} | {lv} | {last} | {nxt} | {iv} | |\n" for t, lv, last, nxt, iv in rows)


def make_subject(root, name, rows, exam="", mistakes=(), extra=""):
    folder = Path(root) / name
    (folder / "sessions").mkdir(parents=True)
    (folder / "CLAUDE.md").write_text(f"# Subject: {name}\n\n- **Course name / code:** x\n- **Exam date:** {exam}\n{extra}", encoding="utf-8")
    (folder / "progress.md").write_text(progress(*rows), encoding="utf-8")
    (folder / "mistakes.md").write_text(
        "| Date | Topic | Question | My answer | Why | Source | Fixed? |\n|---|---|---|---|---|---|---|\n"
        + "".join(f"| 2026-10-01 | {t} | q | a | w | s | |\n" for t in mistakes), encoding="utf-8")
    return folder


class Tmp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)


class Progress(unittest.TestCase):
    def test_interval_and_overdue(self):
        t = sd.parse_progress(progress(("A", 2, "2026-10-01", "2026-10-04", 3)), TODAY)[0]
        self.assertEqual((t["interval"], t["overdue"]), (3, 34))

    def test_resume_counts_overdue_from_resume_date(self):
        t = sd.parse_progress(progress(("A", 2, "2026-10-01", "2026-10-04", 3)), TODAY, resumed="2026-11-05")[0]
        self.assertEqual(t["overdue"], 2)

    def test_dashes_are_not_started(self):
        t = sd.parse_progress(progress(("A", 0, "—", "—", "—")), TODAY)[0]
        self.assertEqual((t["last"], t["overdue"], t["interval"]), (None, None, None))

    def test_empty(self):
        self.assertEqual(sd.parse_progress("", TODAY), [])


class Exam(unittest.TestCase):
    def ex(self, value):
        return sd.parse_exam(f"- **Exam date:** {value}\n", TODAY)

    def test_states(self):
        self.assertEqual(self.ex("")["state"], "unset")
        self.assertEqual(self.ex("(last/reserve session date — fill in)")["state"], "unset")
        self.assertEqual(self.ex("unknown")["state"], "unknown")
        self.assertEqual(self.ex("none")["state"], "none")
        self.assertEqual(self.ex("NO EXAM (recording 2026-09-26)")["state"], "none")

    def test_earliest_future_date_wins(self):
        e = self.ex("2026-10-01 first term, 2026-12-20 resit, 2026-11-30 main")
        self.assertEqual((e["state"], e["label"], e["days"]), ("date", "2026-11-30", 23))

    def test_all_past(self):
        self.assertEqual(self.ex("2026-10-01")["state"], "past")

    def test_urgency(self):
        u = lambda v: planner.urgency(self.ex(v))
        self.assertEqual([u("none"), u(""), u("2027-03-01"), u("2026-12-07"), u("2026-11-10")], [0.25, 1, 1, 1.5, 2])


class Fields(unittest.TestCase):
    MD = "# S\n\n- **Course name / code:** c\n- **Exam date:** \n- **Diagrams:** (leave blank if none; e.g. UML)\n"

    def test_set_replaces_one_line(self):
        out = sd.set_field(self.MD, "Exam date", "2026-12-01")
        self.assertIn("- **Exam date:** 2026-12-01\n- **Diagrams:**", out)

    def test_reviews_line_goes_below_exam(self):
        out = sd.set_field(self.MD, "Reviews", "paused since 2026-11-07", after="Exam date")
        self.assertIn("- **Exam date:** \n- **Reviews:** paused since 2026-11-07\n", out)
        self.assertEqual(sd.parse_reviews(out), {"paused": True, "since": "2026-11-07", "resumed": None})
        again = sd.set_field(out, "Reviews", "resumed 2026-11-08", after="Exam date")
        self.assertEqual(again.count("Reviews"), 1)
        self.assertEqual(sd.parse_reviews(again)["resumed"], "2026-11-08")

    def test_rejects_newlines_and_bad_values(self):
        self.assertRaises(ValueError, sd.set_field, self.MD, "Exam date", "x\ny")
        for bad in ("2026-13-01", "tomorrow", "2026-1-1", None):
            self.assertRaises(ValueError, sd.check_exam_value, bad)
        self.assertEqual(sd.check_exam_value(" unknown "), "unknown")

    def test_template_placeholder_is_not_a_diagram_subject(self):
        self.assertFalse(sd.has_diagrams(self.MD))
        self.assertTrue(sd.has_diagrams("- **Diagrams:** UML class diagrams\n"))
        self.assertFalse(sd.has_diagrams("- **Diagrams:**\n"))
        self.assertFalse(sd.has_diagrams("# no line\n"))


class Weight(unittest.TestCase):
    SYL = sd.parse_syllabus("| # | Topic | Sources | Exam weight |\n|---|---|---|---|\n"
                            "| 1 | Digital signal levels: TTL, CMOS | x | low |\n"
                            "| 2 | Karnaugh maps: building from a truth table | x | high |\n"
                            "| 3 | Gray code and the grouping rule | x | |\n")

    def test_matches_short_progress_names(self):
        self.assertEqual(sd.topic_weight("Karnaugh maps", self.SYL), 3)
        self.assertEqual(sd.topic_weight("Signal levels TTL/CMOS", self.SYL), 1)

    def test_blank_or_unmatched_is_two(self):
        self.assertEqual(sd.topic_weight("Gray code & grouping rule", self.SYL), 2)
        self.assertEqual(sd.topic_weight("Something else entirely", self.SYL), 2)


class Events(Tmp):
    def test_import_once_and_only_with_started_topics(self):
        topics = sd.parse_progress(progress(("A", 2, "2026-10-01", "2026-10-02", 1), ("B", 0, "", "", "")), TODAY)
        self.assertFalse(sd.import_events(self.root, [t for t in topics if not t["last"]]))
        self.assertFalse((self.root / "events.jsonl").exists())
        self.assertTrue(sd.import_events(self.root, topics))
        self.assertFalse(sd.import_events(self.root, topics))
        events, bad = sd.read_events(self.root)
        self.assertEqual((len(events), bad, events[0]["kind"], events[0]["ts"]), (1, 0, "import", "2026-10-01T00:00:00"))

    def test_log_matches_topic_case_insensitively_and_flags_unknown(self):
        topics = sd.parse_progress(progress(("Association class", 2, "2026-10-01", "2026-10-02", 1)), TODAY)
        ev, warn = sd.log_event(self.root, topics, " association CLASS ", "recall", "correct", 3, 3, datetime(2026, 11, 7, 10))
        self.assertEqual((ev["topic"], warn), ("Association class", None))
        ev, warn = sd.log_event(self.root, topics, "Nope", "quiz", "wrong", 1, 1)
        self.assertTrue(ev["unmatched"] and warn)
        self.assertEqual(len(sd.read_events(self.root)[0]), 3)  # import + 2

    def test_log_validates_kind_and_verdict(self):
        self.assertRaises(ValueError, sd.log_event, self.root, [], "A", "import", "correct", 1, 1)
        self.assertRaises(ValueError, sd.log_event, self.root, [], "A", "recall", "imported", 1, 1)
        self.assertRaises(ValueError, sd.log_event, self.root, [], "A", "chat", "correct", 1, 1)

    def test_malformed_lines_are_counted(self):
        good = json.dumps({"ts": "2026-11-01T10:00:00", "topic": "A", "kind": "recall", "verdict": "correct"})
        events, bad = sd.parse_events(f"{good}\nnot json\n{{\"ts\": \"x\"}}\n\n[1]\n")
        self.assertEqual((len(events), bad), (1, 3))
        self.assertEqual(sd.parse_events(""), ([], 0))

    def ev(self, ts, topic, kind, verdict, level=2):
        return {"ts": ts, "topic": topic, "kind": kind, "verdict": verdict, "level_after": level, "interval_after": 1}

    def test_slips(self):
        evs = [self.ev("2026-11-01T10:00:00", "A", "quiz", "correct"), self.ev("2026-11-01T11:00:00", "A", "drawing", "wrong"),
               self.ev("2026-11-01T10:00:00", "B", "drawing", "partly"), self.ev("2026-11-02T10:00:00", "B", "recall", "wrong"),
               self.ev("2026-11-01T10:00:00", "C", "drawing", "wrong"), self.ev("2026-11-02T10:00:00", "C", "import", "imported"),
               self.ev("2026-11-01T10:00:00", "D", "recall", "correct"), self.ev("2026-11-01T11:00:00", "D", "drawing", "correct")]
        self.assertEqual(sd.slips(evs), {"a"})

    def test_what_moved_uses_the_newest_real_day(self):
        evs = [self.ev("2026-10-01T00:00:00", "A", "import", "imported", 1),
               self.ev("2026-11-05T10:00:00", "A", "recall", "correct", 2),
               self.ev("2026-11-05T10:05:00", "A", "drawing", "partly", 2),
               self.ev("2026-11-05T11:00:00", "B", "lesson", "correct", 1),
               self.ev("2026-11-06T00:00:00", "C", "import", "imported", 3)]
        mv = sd.what_moved(evs)
        self.assertEqual(mv["date"], "2026-11-05")
        a, b = mv["items"]
        self.assertEqual((a["before"], a["after"], a["verdict"], a["kinds"]), (1, 2, "partly", ["recall", "drawing"]))
        self.assertEqual((b["before"], b["after"]), (None, 1))
        self.assertIsNone(sd.what_moved([self.ev("2026-10-01T00:00:00", "A", "import", "imported")]))

    def test_unlogged(self):
        topics = sd.parse_progress(progress(("A", 2, "2026-11-05", "2026-11-06", 1), ("B", 1, "2026-11-01", "2026-11-02", 1),
                                            ("C", 0, "", "", "")), TODAY)
        self.assertEqual(sd.unlogged(topics, [self.ev("2026-11-01T09:00:00", "B", "recall", "correct")]), 1)


class Freshness(unittest.TestCase):
    def test_halves_every_four_intervals(self):
        self.assertEqual(sd.freshness(0, 3), 1)
        self.assertAlmostEqual(sd.freshness(12, 3), 0.5)
        self.assertIsNone(sd.freshness(None, 3))
        self.assertIsNone(sd.freshness(5, None))


class Links(unittest.TestCase):
    TOPICS = [{"topic": n} for n in ("A", "B", "C", "D")]

    def links(self, data):
        return sd.parse_links(json.dumps(data) if not isinstance(data, str) else data, self.TOPICS)

    def test_missing_file_and_bad_json(self):
        self.assertEqual(sd.parse_links(None, self.TOPICS), ([], []))
        self.assertEqual(self.links("{oops")[0], [])
        self.assertEqual(len(self.links("{oops")[1]), 1)
        self.assertEqual(self.links({"from": "A"})[0], [])

    def test_cleanup(self):
        edges, warns = self.links([{"from": "a", "to": "B"}, {"from": "B", "to": "B"}, {"from": "B", "to": "Zed"},
                                   {"from": "A", "to": "B"}, "junk", {"from": "B", "to": "C"}, {"from": "C", "to": "A"}])
        self.assertEqual(edges, [[0, 1], [1, 2]])
        self.assertEqual(len(warns), 2)  # 3 dropped (self, unknown, junk) and 1 loop

    def test_depths(self):
        self.assertEqual(sd.depths(4, [[0, 1], [1, 2], [0, 2]]), [0, 1, 2, 0])
        self.assertEqual(sd.depths(0, []), [])

    def test_35_topics_chain(self):
        topics = [{"topic": f"T{i}"} for i in range(35)]
        edges, _ = sd.parse_links(json.dumps([{"from": f"T{i}", "to": f"T{i + 1}"} for i in range(34)]), topics)
        self.assertEqual(sd.depths(35, edges)[-1], 34)


class Planner(Tmp):
    def plan(self):
        states = [planner.subject_state(self.root, n, TODAY) for n in sd.subject_names(self.root)]
        return planner.build_picks(states)

    def test_two_reviews_then_a_lesson(self):
        make_subject(self.root, "PRI", [("Assoc class", 3, "2026-10-25", "2026-10-26", 1), ("Derived", 3, "2026-10-01", "2026-10-04", 3),
                                        ("Fresh", 3, "2026-11-06", "2026-11-09", 3), ("New one", 0, "", "", "")], mistakes=["Assoc", "Assoc class"])
        make_subject(self.root, "MUL", [("Bit depth", 1, "2026-10-05", "2026-10-06", 1), ("Sound", 0, "", "", "")])
        picks = self.plan()
        self.assertEqual([(p["subject"], p["topic"], p["kind"]) for p in picks],
                         [("PRI", "Assoc class", "review"), ("MUL", "Bit depth", "review"), ("MUL", "Sound", "lesson")])
        self.assertEqual(picks[0]["reason"], "2 open mistakes")
        self.assertEqual(picks[0]["prompt"], "Review only Assoc class in PRI, 3 questions, following the review rules")

    def test_at_most_two_per_subject_and_paused_subjects_skipped(self):
        make_subject(self.root, "A", [(f"T{i}", 1, "2026-10-01", "2026-10-02", 1) for i in range(5)])
        make_subject(self.root, "P", [("X", 1, "2026-09-01", "2026-09-02", 1), ("Y", 0, "", "", "")],
                     extra="- **Reviews:** paused since 2026-11-01\n")
        picks = self.plan()
        self.assertEqual([p["subject"] for p in picks], ["A", "A"])  # no lesson left in A, P paused

    def test_lesson_order_prefers_nearest_exam_then_oldest_session(self):
        for name, exam in (("Late", "2027-02-01"), ("Soon", "2026-11-20"), ("NoExam", "none"), ("Unknown", "unknown")):
            make_subject(self.root, name, [("t", 0, "", "", "")], exam=exam)
        states = [planner.subject_state(self.root, n, TODAY) for n in sd.subject_names(self.root)]
        self.assertEqual([s["name"] for s in planner.lesson_order(states)], ["Soon", "Late", "Unknown", "NoExam"])
        self.assertEqual([p["subject"] for p in planner.build_picks(states)], ["Soon", "Late", "Unknown"])

    def test_unknown_subjects_spread_by_oldest_session(self):
        a = make_subject(self.root, "Aaa", [("t1", 0, "", "", ""), ("t2", 0, "", "", "")])
        make_subject(self.root, "Bbb", [("t1", 0, "", "", ""), ("t2", 0, "", "", "")])
        (a / "sessions" / "2026-11-06.md").write_text("- x\n")
        picks = self.plan()
        self.assertEqual([p["subject"] for p in picks], ["Bbb", "Aaa", "Bbb"])

    def test_slip_on_a_diagram_subject_becomes_a_drawing(self):
        f = make_subject(self.root, "PRI", [("Assoc", 2, "2026-11-01", "2026-11-02", 1)], extra="- **Diagrams:** UML\n")
        (f / "events.jsonl").write_text("\n".join(json.dumps(e) for e in [
            {"ts": "2026-11-01T10:00:00", "topic": "Assoc", "kind": "quiz", "verdict": "correct"},
            {"ts": "2026-11-01T11:00:00", "topic": "Assoc", "kind": "drawing", "verdict": "wrong"}]) + "\n")
        p = self.plan()[0]
        self.assertEqual((p["kind"], p["reason"]), ("drawing", "Right in chat, wrong on your diagram"))

    def test_empty_root(self):
        self.assertEqual(self.plan(), [])
        self.assertEqual(planner.today_plan(self.root, TODAY)["picks"], [])

    def test_saved_plan_is_stable_and_rebuild_keeps_done_picks(self):
        f = make_subject(self.root, "S", [("Done today", 1, TODAY, "2026-11-08", 1), ("Old", 1, "2026-10-01", "2026-10-02", 1),
                                          ("New", 0, "", "", "")])
        planner._save(self.root, TODAY, [planner._pick({"name": "S"}, {"topic": "Done today"}, "review", "r", 1)])
        plan = planner.today_plan(self.root, TODAY)
        self.assertEqual([(p["topic"], p["done"]) for p in plan["picks"]], [("Done today", True)])  # stable for the day
        plan = planner.today_plan(self.root, TODAY, rebuild=True)
        self.assertEqual([p["topic"] for p in plan["picks"]], ["Done today", "Old"])  # cap of 2 per subject
        self.assertEqual(planner.for_session(plan), [plan["picks"][1]])
        (f / "progress.md").write_text("garbage", encoding="utf-8")
        (self.root / ".tools" / "today-plan.json").write_text("{bad", encoding="utf-8")
        self.assertEqual(planner.today_plan(self.root, TODAY)["picks"], [])  # malformed: rebuilt

    def test_minutes(self):
        plan = {"picks": [{"subject": "A", "done": False}, {"subject": "B", "done": False}, {"subject": "A", "done": True}]}
        self.assertEqual(len(planner.for_session(plan, minutes=5)), 1)
        self.assertEqual(len(planner.for_session(plan, minutes=2)), 1)
        self.assertEqual(len(planner.for_session(plan, minutes=60)), 2)
        self.assertEqual(planner.for_session(plan, subject="a"), [plan["picks"][0]])


if __name__ == "__main__":
    unittest.main()
