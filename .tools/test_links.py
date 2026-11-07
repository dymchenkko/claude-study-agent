"""Tests for `study links` (topic links from the embedding index, no model needed).
Run: python3 .tools/test_links.py"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import links

HEAD = "| Topic | Level | Last studied | Next review | Interval (d) | Notes |\n|---|---|---|---|---|---|\n"


def progress(*names):
    return HEAD + "".join(f"| {n} | 0 | – | – | – | |\n" for n in names)


SYLLABUS = """# X — Topic map

## Lectures

| # | Topic | Sources | Exam weight |
|---|-------|---------|-------------|
| W1 | Basic terms: CIA triad | wyklad_1 p.13–19 | high |
| W2 | Security models | wyklad_1 p.23–24, 26 | high |

## Labs

| # | Scenario | Sources | Exam weight |
|---|-------|---------|-------------|
| L1 | Linux basics | 1. Linux basics p.2 · 1p. Linux PENTEST p.3 | med |
| L2 | Talk | Lecture 0.pdf p.5; Lecture 0.mp4 [00:01:00]–[00:02:00] | low |
"""


class FakeEngine:
    def __init__(self, vec):
        self.vec = vec

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def embed(self, texts):
        return [self.vec for _ in texts]


class Syllabus(unittest.TestCase):
    def test_reads_every_table_with_sources(self):
        rows = links.syllabus_rows(SYLLABUS)
        self.assertEqual([r["id"] for r in rows], ["W1", "W2", "L1", "L2"])
        self.assertEqual(rows[2]["topic"], "Linux basics")  # "Scenario" column counts as the topic
        self.assertEqual(rows[1]["sources"], "wyklad_1 p.23–24, 26")

    def test_match_by_id_then_words_then_position(self):
        rows = links.syllabus_rows(SYLLABUS)
        topics = [{"topic": t} for t in ["L1 Linux", "Security models", "W1 CIA", "something else"]]
        self.assertEqual(links.match_rows(topics, rows), {0: 2, 1: 1, 2: 0, 3: 3})  # last: same length
        self.assertNotIn(3, links.match_rows(topics[:3] + [{"topic": "zzz"}, {"topic": "q"}], rows))


class Sources(unittest.TestCase):
    def test_pages_ranges_and_lists(self):
        [(words, ext, pages, spans)] = links.parse_sources("wyklad_1 p.23–24, 26")
        self.assertEqual((words, ext, pages, spans), ({"wyklad", "1"}, None, {23, 24, 26}, None))

    def test_stamps_slides_and_split_pieces(self):
        a, b = links.parse_sources("Lecture 0.pdf p.5; Lecture 0.mp4 [00:01:00]–[00:02:00]")
        self.assertEqual((a[1], a[2]), ("pdf", {5}))
        self.assertEqual((b[1], b[2], b[3]), ("mp4", None, [(60, 120)]))
        [(_, _, pages, _)] = links.parse_sources("w4 diagrams.pptx slides 3–5")
        self.assertEqual(pages, {3, 4, 5})
        [(_, _, _, spans)] = links.parse_sources("talk.mp4 [00:10:00]")
        self.assertEqual(spans, [(600, 900)])  # a lone stamp covers 5 minutes

    def test_best_file(self):
        names = ["pdfs/Lecture 0.pdf", "videos/Lecture 0.mp4", "pdfs/wyklad_1_wprowadzenie.pdf",
                 "hw/analiza-dzwieku-1/MUL - Analiza dźwęku - czesc 1.pdf",
                 "hw/analiza-dzwieku-1/MUL - Analiza dźwęku - czesc 1 — sprawozdanie.docx"]
        self.assertEqual(links.best_file({"lecture", "0"}, names, "mp4"), "videos/Lecture 0.mp4")
        self.assertIsNone(links.best_file({"lecture", "0"}, names))  # pdf or mp4? a tie: skip
        self.assertEqual(links.best_file({"wyklad", "1"}, names), "pdfs/wyklad_1_wprowadzenie.pdf")
        [(words, ext, _, _)] = links.parse_sources("HW1 `hw/analiza-dzwieku-1/…czesc 1.pdf` p.13")
        self.assertEqual(links.best_file(words, names, ext), names[3])  # accents and folders match
        self.assertIsNone(links.best_file({"nothing", "here"}, names))

    def test_chunk_in(self):
        self.assertTrue(links.chunk_in("p.5", {5}, None))
        self.assertFalse(links.chunk_in("p.6", {5}, None))
        self.assertTrue(links.chunk_in("slide 3", {3}, None))
        self.assertTrue(links.chunk_in("[00:01:30]", None, [(60, 120)]))
        self.assertFalse(links.chunk_in("[00:03:00]", None, [(60, 120)]))
        self.assertTrue(links.chunk_in("§ Intro", None, None))  # no locator: the whole file


class Propose(unittest.TestCase):
    def test_links_earlier_similar_topics_only(self):
        vecs = [[1, 0, 0], [0, 1, 0], [0.9, 0.1, 0], [0, 0, 1]]
        out = [(a, b) for a, b, _ in links.propose(vecs, min_sim=0.3)]
        self.assertIn((0, 2), out)
        self.assertTrue(all(a < b for a, b in out))
        self.assertNotIn((2, 0), out)

    def test_skips_a_topic_already_reachable(self):
        # 0 -> 1 -> 2 is a chain; 2 is also close to 0, but 0 is reachable through 1
        vecs = [[1, 0.2, 0, 0], [1, 1, 0, 0], [0.8, 1.2, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        out = [(a, b) for a, b, _ in links.propose(vecs, min_sim=0.1)]
        self.assertIn((1, 2), out)
        self.assertNotIn((0, 2), out)

    def test_same_pages_are_never_linked_and_none_is_skipped(self):
        vecs = [[1, 0, 0], [1, 0, 0], None, [0, 1, 0], [0, 0, 1]]
        pages = [{"a", "b"}, {"a", "b"}, set(), {"c"}, {"d"}]
        self.assertEqual(links.propose(vecs, min_sim=0.1, pages=pages), [])

    def test_merge_keeps_existing(self):
        old = json.dumps([{"from": "A", "to": "B"}, {"from": "B", "to": "C"}])
        new = [{"from": "a ", "to": "b"}, {"from": "C", "to": "D"}, {"from": "A", "to": "C"}]
        text, added = links.merge(old, new)
        self.assertEqual(added, 1)  # A -> C links two known topics: maybe deleted by hand, so not re-added
        self.assertEqual(json.loads(text)[-1], {"from": "C", "to": "D"})
        self.assertEqual(links.merge("not json", new)[1], 3)


class Command(unittest.TestCase):
    def test_end_to_end_with_fake_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, idx = Path(tmp) / "X", Path(tmp) / "index"
            folder.mkdir()
            (folder / "progress.md").write_text(progress("W1 CIA", "W2 Models", "L1 Linux", "Orphan"))
            (folder / "syllabus.md").write_text(SYLLABUS)
            (idx / "pdfs").mkdir(parents=True)

            def chunk(loc, vec):
                return {"loc": loc, "text": "x", "vec": vec}
            (idx / "pdfs/wyklad_1_wprowadzenie.pdf.md.json").write_text(json.dumps({"chunks": [
                chunk("p.13", [1, 0, 0]), chunk("p.23", [0.9, 0.3, 0])]}))
            (idx / "pdfs/1. Linux basics.pdf.md.json").write_text(json.dumps({"chunks": [
                chunk("p.2", [0, 0, 1])]}))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                found = links.cmd_links(folder, idx, write=True,
                                        engine_factory=lambda: FakeEngine([0, 1, 0]))
            self.assertIn((0, 1), [(a, b) for a, b, _ in found])
            self.assertIn("3 from syllabus pages, 1 by searching", out.getvalue())
            saved = json.loads((folder / "links.json").read_text())
            self.assertIn({"from": "W1 CIA", "to": "W2 Models"}, saved)


if __name__ == "__main__":
    unittest.main()
