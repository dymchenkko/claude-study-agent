"""Tests for study_tools.py. Run: python3 -m unittest discover anna/study-tools"""

import datetime
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import study_tools as st  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
PLUGIN = Path(__file__).with_name("study_tools.py")
TODAY = datetime.date(2026, 10, 27)
PROGRESS = (REPO / "Example-Subject/progress.md").read_text()
MISTAKES = (REPO / "Example-Subject/mistakes.md").read_text()


def row(text, topic):
    return next(line for line in text.splitlines() if line.startswith(f"| {topic} |"))


class ProgressTest(unittest.TestCase):
    def test_learned_sets_level_and_tomorrow(self):
        text, values = st.update_progress(PROGRESS, "osmosis", "learned", TODAY, level=2)
        self.assertEqual(values["Topic"], "Osmosis and tonicity (animal vs plant cells)")
        self.assertEqual((values["Level"], values["Interval (d)"], values["Next review"]), ("2", "1", "2026-10-28"))

    def test_keeps_header_notes_and_other_rows(self):
        text, _ = st.update_progress(PROGRESS, "Fermentation", "learned", TODAY, level=3)
        before, after = PROGRESS.splitlines(), text.splitlines()
        self.assertEqual(len(before), len(after))
        self.assertEqual([a for a, b in zip(before, after) if a != b], [row(PROGRESS, "Fermentation")])

    def test_ladder(self):
        text, v = st.update_progress(PROGRESS, "Fermentation", "learned", TODAY, level=3)
        steps = []
        for outcome in ["correct", "correct", "partial", "wrong", "correct"]:
            text, v = st.update_progress(text, "Fermentation", outcome, TODAY)
            steps.append((v["Level"], v["Interval (d)"]))
        self.assertEqual(steps, [("4", "3"), ("5", "7"), ("5", "7"), ("4", "1"), ("5", "3")])

    def test_ladder_tops_out_at_35(self):
        text, _ = st.update_progress(PROGRESS, "Fermentation", "learned", TODAY, level=1)
        for _ in range(7):
            text, v = st.update_progress(text, "Fermentation", "correct", TODAY)
        self.assertEqual((v["Level"], v["Interval (d)"]), ("5", "35"))

    def test_new_topic_is_appended_after_last_row(self):
        text, _ = st.update_progress(PROGRESS, "Water potential", "learned", TODAY, level=1, note="new | topic")
        lines = text.splitlines()
        self.assertTrue(lines[-1].startswith("| Water potential | 1 | 2026-10-27 |"))
        self.assertIn("new \\| topic", lines[-1])
        _, v = st.update_progress(text, "Water potential", "correct", TODAY)
        self.assertEqual(v["Notes"], "new \\| topic")

    def test_ambiguous_topic_is_refused(self):
        with self.assertRaisesRegex(st.ToolError, "several rows"):
            st.update_progress(PROGRESS, "transport", "correct", TODAY)

    def test_learned_needs_level(self):
        with self.assertRaises(st.ToolError):
            st.update_progress(PROGRESS, "Fermentation", "learned", TODAY)


class MistakesTest(unittest.TestCase):
    def test_add_then_fix(self):
        text = st.add_mistake(MISTAKES, TODAY, "Osmosis", "Where does water go in salt?", "in", "mixed up sides",
                              "Lecture1-Membrane-transport.pdf p.2")
        self.assertTrue(text.splitlines()[-1].endswith("| Lecture1-Membrane-transport.pdf p.2 |  |"))
        text, n = st.fix_mistakes(text, "water go")
        self.assertEqual(n, 1)
        self.assertTrue(text.splitlines()[-1].endswith("| ✅ |"))
        with self.assertRaises(st.ToolError):
            st.fix_mistakes(text, "water go")


class TopicsTest(unittest.TestCase):
    def test_adds_only_new_topics_at_level_0(self):
        text, added = st.add_topics(PROGRESS, ["Fermentation", "Water potential", "water potential", "Turgor"])
        self.assertEqual(added, ["Water potential", "Turgor"])
        before, after = PROGRESS.splitlines(), text.splitlines()
        self.assertEqual(after[:len(before)], before)
        self.assertEqual(after[-2:], ["| Water potential | 0 |  |  |  |  |", "| Turgor | 0 |  |  |  |  |"])


def make_ooxml(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, xml in files.items():
            z.writestr(name, xml)


A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


class MaterialTest(unittest.TestCase):
    """material_add with the download stubbed (it copies a local file) and no external converters."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "Study"
        shutil.copytree(REPO / "_template", self.root / "Course")
        self.sd = self.root / "Course"
        self.files = Path(self.tmp.name) / "files"
        self.files.mkdir()
        self._download, self._which = st.download, st.shutil.which
        st.download = lambda url, dest: shutil.copyfile(self.files / Path(url).name, dest) and dest.stat().st_size
        st.shutil.which = lambda cmd: None  # as on a cloud agent: no pdftotext, no markitdown

    def tearDown(self):
        st.download, st.shutil.which = self._download, self._which
        self.tmp.cleanup()

    def add(self, name):
        return st.add_material(self.root, self.sd, f"https://files.example/{name}", name)

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "pypdf not installed")
    def test_pdf_has_page_markers_like_study_ingest(self):
        shutil.copy(REPO / "Example-Subject/materials/pdfs/Lecture1-Membrane-transport.pdf", self.files / "L1.pdf")
        r = self.add("L1.pdf")
        self.assertEqual((r["converter"], r["pages"], r["pages_without_text"]), ("built-in", 3, 0))
        md = (self.sd / "converted/pdfs/L1.pdf.md").read_text()
        self.assertTrue(md.startswith("# L1.pdf\n\nSource: Course/materials/pdfs/L1.pdf\n\n--- page 1 ---\n"))
        self.assertEqual(md.count("--- page "), 3)
        self.assertIn("selectively permeable", md.replace("\n", " "))
        self.assertIn("(the fluid", md)  # ligature normalized, so grep finds it
        self.assertTrue((self.sd / "materials/pdfs/L1.pdf").exists())

    def test_pptx_slides_and_docx_paragraphs(self):
        slide = f'<p:sld xmlns:p="x" {A}><a:p><a:r><a:t>Slide {{}} title</a:t></a:r></a:p>' \
                f'<a:p><a:r><a:t>Point </a:t></a:r><a:r><a:t>{{}}</a:t></a:r></a:p></p:sld>'
        make_ooxml(self.files / "Week2.pptx", {f"ppt/slides/slide{n}.xml": slide.format(n, n) for n in (2, 1, 10)})
        r = self.add("Week2.pptx")
        md = (self.sd / "converted/slides/Week2.pptx.md").read_text()
        self.assertEqual(r["slides"], 3)
        self.assertLess(md.index("Slide 1 title"), md.index("Slide 2 title"), md.index("Slide 10 title"))
        self.assertIn("<!-- Slide number: 3 -->\nSlide 10 title\nPoint 10", md)
        make_ooxml(self.files / "Notes.docx", {"word/document.xml": f'<w:document {W}><w:body>'
                   '<w:p><w:r><w:t>Krebs </w:t></w:r><w:r><w:t>cycle</w:t></w:r></w:p>'
                   '<w:p><w:r><w:t>2 ATP per glucose</w:t></w:r></w:p></w:body></w:document>'})
        self.add("Notes.docx")
        self.assertIn("Krebs cycle\n2 ATP per glucose", (self.sd / "converted/notes/Notes.docx.md").read_text())

    def test_refusals(self):
        (self.files / "a.pdf").write_bytes(b"%PDF")
        for name, msg in [("../../etc/passwd.pdf", None), (".hidden.pdf", "unusable"), ("talk.mp4", "video"),
                          ("data.xlsx", "unsupported")]:
            if msg:
                with self.assertRaisesRegex(st.ToolError, msg):
                    st.add_material(self.root, self.sd, "https://f/x", name)
        self.assertEqual(st.safe_filename("../../etc/passwd.pdf"), "passwd.pdf")
        (self.sd / "materials/pdfs").mkdir(exist_ok=True)
        (self.sd / "materials/pdfs/a.pdf").write_bytes(b"old")
        with self.assertRaisesRegex(st.ToolError, "already exists"):
            self.add("a.pdf")
        self.assertEqual((self.sd / "materials/pdfs/a.pdf").read_bytes(), b"old")
        st.download = self._download
        with self.assertRaisesRegex(st.ToolError, "https"):
            st.add_material(self.root, self.sd, "http://f/b.pdf", "b.pdf")


class StdioTest(unittest.TestCase):
    """Drive the plugin over stdin/stdout like the Anna Agent does."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "Study"
        shutil.copytree(REPO / "Example-Subject", root / "Example-Subject")
        (root / ".tools").mkdir()
        (root / ".tools/study").write_text("")  # only its presence matters for these tools
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *requests):
        env = {**os.environ, "STUDY_ROOT": str(self.root)}
        lines = "".join(json.dumps(r) + "\n" for r in requests)
        out = subprocess.run([sys.executable, str(PLUGIN)], input=lines, capture_output=True, text=True,
                             env=env, timeout=30, check=True).stdout
        return [json.loads(line) for line in out.splitlines()]

    def invoke(self, i, tool, **arguments):
        return {"jsonrpc": "2.0", "id": i, "method": "invoke", "params": {"tool": tool, "arguments": arguments}}

    def test_session(self):
        replies = self.call(
            {"jsonrpc": "2.0", "id": 1, "method": "describe"},
            self.invoke(2, "study_open"),
            self.invoke(3, "progress_update", subject="example-subject", topic="osmosis", outcome="learned", level=2),
            self.invoke(4, "session_log", subject="Example-Subject", notes=["Osmosis: direction ok", "Next: tonicity"]),
            self.invoke(5, "progress_update", subject="Nope", topic="x", outcome="correct"),
            self.invoke(6, "progress_update", subject="Example-Subject", topic="osmosis"),
            self.invoke(7, "no_such_tool"),
        )
        self.assertEqual([r["id"] for r in replies], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(len(replies[0]["result"]["tools"]), 9)
        self.assertEqual(replies[1]["result"]["data"]["subjects"][0]["name"], "Example-Subject")
        self.assertEqual(replies[2]["result"]["data"]["row"]["Level"], "2")
        self.assertIn("no subject 'Nope'", replies[4]["result"]["error"])
        self.assertEqual(replies[5]["error"]["code"], -32602)
        self.assertEqual(replies[6]["error"]["code"], -32601)
        progress = (self.root / "Example-Subject/progress.md").read_text()
        self.assertEqual(len(progress.splitlines()), len(PROGRESS.splitlines()))
        log = next((self.root / "Example-Subject/sessions").glob("*.md")).read_text()
        self.assertIn("- Next: tonicity", log)

    def test_missing_tools_is_an_error_not_a_fake(self):
        (self.root / ".tools/study").unlink()
        reply = self.call(self.invoke(1, "study_open"))[0]
        self.assertFalse(reply["result"]["success"])
        self.assertIn("no .tools/study", reply["result"]["error"])
        self.assertFalse((self.root / ".tools/study").exists())


if __name__ == "__main__":
    unittest.main()
