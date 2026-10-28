#!/usr/bin/env python3
"""study-tools: an Anna Executa plugin (JSON-RPC 2.0 over stdio) for the study folder.

The skills teach; this plugin does the file work that a model gets wrong: it finds or downloads the study
folder, runs the real `.tools/study search`, and changes progress.md, mistakes.md and the session log one row
at a time, applying the review ladder in code. It also brings the user's own files in: material_add downloads
a chat attachment into materials/ and converts it to converted/*.md, with `.tools/study ingest` where its
converters are installed (local agent) and built in otherwise (cloud agent: pypdf for PDFs, zip+XML for
PPTX/DOCX). Standard library plus pypdf.

Smoke test:
  echo '{"jsonrpc":"2.0","method":"describe","id":1}' | python3 study_tools.py
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

VERSION = "0.2.0"
REPO_TARBALL = "https://github.com/dymchenkko/claude-study-agent/archive/refs/heads/main.tar.gz"
LADDER = [1, 3, 7, 16, 35]
OUTCOMES = ["correct", "partial", "wrong", "learned"]
# materials/ subfolder per file type, as in _template; converted/ mirrors it with ".md" appended.
KINDS = {".pdf": "pdfs", ".pptx": "slides", ".docx": "notes", ".md": "notes", ".txt": "notes"}
MEDIA = {".mp4", ".mov", ".mkv", ".webm", ".m4a", ".mp3", ".wav"}
MAX_DOWNLOAD = 100 * 1024 * 1024
THIN_PAGE = 50  # characters; fewer means a scanned page or one without a text layer
NOTE_NO_TEXT = ("> NOTE: little text extracted — likely scanned or image-based. "
                "Read the original PDF directly.")


def _param(name, type_, description, required=True, **extra):
    return {"name": name, "type": type_, "description": description, "required": required, **extra}


SUBJECT = _param("subject", "string", "Subject folder name, e.g. Example-Subject (case-insensitive).")
MANIFEST = {
    "name": "study-tools",
    "display_name": "Study Tools",
    "version": VERSION,
    "description": "Study folder tools for the study tutor: open or download the study folder, create "
                   "subjects, import the user's own course files, search the course materials, and record "
                   "progress, mistakes and session notes safely.",
    "homepage": "https://github.com/dymchenkko/claude-study-agent",
    "icon": "🎓",
    "category": "education",
    "license": "MIT",
    "tools": [
        {"name": "study_open",
         "description": "Call first. Finds the study folder (downloads it if missing) and lists the subjects "
                        "with their file paths.",
         "parameters": []},
        {"name": "subject_new",
         "description": "Create a new subject (course) folder from the template: CLAUDE.md, syllabus.md, "
                        "progress.md, mistakes.md, materials/, converted/.",
         "parameters": [_param("name", "string", "Subject name, e.g. Cell-Biology (letters, digits, - _ .).")]},
        {"name": "material_add",
         "description": "Import one course file the user attached in chat: downloads it into the subject's "
                        "materials/ and converts it to searchable converted/*.md with page / slide markers. "
                        "Pass the attachment's download URL and its original file name. PDF, PPTX, DOCX, MD "
                        "and TXT; video and audio are not supported on a cloud agent yet.",
         "timeout": 300,
         "parameters": [SUBJECT, _param("url", "string", "HTTPS download URL of the attached file."),
                        _param("filename", "string", "Original file name, e.g. Lecture3.pdf.")]},
        {"name": "topics_add",
         "description": "Add new topics to progress.md as Level 0 rows, after reading new materials. "
                        "Existing rows are left as they are.",
         "parameters": [SUBJECT, _param("topics", "array", "Topic names in course order.",
                                        items={"type": "string"})]},
        {"name": "study_search",
         "description": "Meaning-based search over a subject's converted materials. Returns passages with "
                        "(file loc) citations, or a note that search is not set up (then grep converted/).",
         "timeout": 120,
         "parameters": [SUBJECT, _param("query", "string", "The topic in plain words."),
                        _param("k", "integer", "Number of passages.", required=False, default=6)]},
        {"name": "progress_update",
         "description": "Record a result for one topic in progress.md; only that row changes. outcome: "
                        "correct / partial / wrong for a recall question (applies the 1-3-7-16-35 day "
                        "ladder), or learned with level 1-3 after a teach-back. Adds the topic if it is new.",
         "parameters": [SUBJECT, _param("topic", "string", "Topic name as in progress.md."),
                        _param("outcome", "string", "What happened.", enum=OUTCOMES),
                        _param("level", "integer", "Only for learned: 1, 2 or 3 from the teach-back.",
                               required=False),
                        _param("note", "string", "Short note for the Notes column.", required=False)]},
        {"name": "mistake_add",
         "description": "Append a wrong answer to mistakes.md with the misconception behind it.",
         "parameters": [SUBJECT, _param("topic", "string", "Topic."),
                        _param("question", "string", "The question, short."),
                        _param("my_answer", "string", "What the student answered."),
                        _param("why_wrong", "string", "The misconception."),
                        _param("source", "string", "Citation, e.g. Lecture1-Membrane-transport.pdf p.2.")]},
        {"name": "mistake_fixed",
         "description": "Mark unfixed mistakes.md rows as fixed when the student now gets them right.",
         "parameters": [SUBJECT, _param("question", "string", "Part of the question text to match.")]},
        {"name": "session_log",
         "description": "Append 3-6 bullets to today's session log: covered, shaky, next time.",
         "parameters": [SUBJECT, _param("notes", "array", "Bullet texts.", items={"type": "string"})]},
    ],
    "runtime": {"type": "uv"},
}


class ToolError(Exception):
    """An expected failure the model should see and act on."""


class UnknownTool(Exception):
    pass


# ---------- study folder ----------

def study_root():
    if os.environ.get("STUDY_ROOT"):
        return Path(os.environ["STUDY_ROOT"]).expanduser()
    home = Path.home() / "Study"
    if home.exists() or not os.environ.get("ANNA_WORKSPACE_DIR"):
        return home
    return Path(os.environ["ANNA_WORKSPACE_DIR"]) / "Study"


def ensure_root():
    """Return (root, downloaded). Downloads the repo when the folder is missing; never fakes it."""
    root = study_root()
    if (root / ".tools/study").exists():
        return root, False
    if root.exists():
        raise ToolError(f"{root} exists but has no .tools/study; set STUDY_ROOT or move the folder")
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent) as tmp:
        archive = Path(tmp) / "repo.tar.gz"
        with urllib.request.urlopen(REPO_TARBALL, timeout=60) as resp, open(archive, "wb") as f:
            shutil.copyfileobj(resp, f)
        with tarfile.open(archive) as tar:
            try:
                tar.extractall(tmp, filter="data")
            except TypeError:  # Python without extraction filters (before 3.10.12 / 3.11.4)
                tar.extractall(tmp)
        os.replace(Path(tmp) / "claude-study-agent-main", root)
    return root, True


def subject_dir(root, name):
    for d in root.iterdir():
        if d.is_dir() and d.name.lower() == name.lower() and (d / "CLAUDE.md").exists():
            return d
    subjects = ", ".join(s.name for s in subjects_in(root)) or "none"
    raise ToolError(f"no subject {name!r}; subjects: {subjects}")


def subjects_in(root):
    return sorted(d for d in root.iterdir() if d.is_dir() and d.name != "_template" and (d / "CLAUDE.md").exists())


def write_atomic(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


# ---------- markdown tables ----------

def cell(text):
    return str(text).replace("\n", " ").replace("|", "\\|").strip()


def split_row(line):
    # Cells may contain escaped pipes (\|), which are not column breaks.
    return [p.strip() for p in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def find_table(lines, first_header):
    """Return (header_index, last_row_index) of the table whose first column is first_header."""
    for i, line in enumerate(lines):
        if line.startswith("|") and split_row(line)[0] == first_header:
            end = i + 1
            while end + 1 < len(lines) and lines[end + 1].startswith("|"):
                end += 1
            return i, end
    raise ToolError(f"no table with a '{first_header}' column")


def update_progress(text, topic, outcome, today, level=None, note=None):
    """Return (new_text, row_dict). Changes one row of the progress table, or appends one."""
    if outcome not in OUTCOMES:
        raise ToolError(f"outcome must be one of {OUTCOMES}")
    if outcome == "learned" and level not in (1, 2, 3):
        raise ToolError("learned needs level 1, 2 or 3 from the teach-back")
    lines = text.splitlines()
    head, end = find_table(lines, "Topic")
    cols = split_row(lines[head])
    rows = list(range(head + 2, end + 1))
    want = topic.strip().lower()
    names = {i: split_row(lines[i])[0] for i in rows}
    hits = [i for i in rows if names[i].lower() == want] or [i for i in rows if want in names[i].lower()]
    if len(hits) > 1:
        raise ToolError("topic matches several rows, use the full name: " + "; ".join(names[i] for i in hits))
    if hits:
        idx = hits[0]
        values = dict(zip(cols, split_row(lines[idx]) + [""] * len(cols)))
    else:
        idx = None
        values = dict.fromkeys(cols, "")
        values["Topic"] = cell(topic)

    old_level = int(values.get("Level") or 0)
    interval = int(values.get("Interval (d)") or 0)
    if outcome == "learned":
        new_level, interval = level, 1
    elif outcome == "correct":
        new_level = min(old_level + 1, 5)
        interval = next((d for d in LADDER if d > interval), LADDER[-1])
    elif outcome == "partial":
        new_level, interval = max(old_level, 1), interval or 1
    else:
        new_level, interval = max(old_level - 1, 1), 1
    values.update({"Level": str(new_level), "Last studied": today.isoformat(),
                   "Next review": (today + datetime.timedelta(days=interval)).isoformat(),
                   "Interval (d)": str(interval)})
    if note is not None and "Notes" in values:
        values["Notes"] = cell(note)
    line = "| " + " | ".join(values[c] for c in cols) + " |"
    if idx is None:
        lines.insert(end + 1, line)
    else:
        lines[idx] = line
    return "\n".join(lines) + "\n", values


def add_mistake(text, today, topic, question, my_answer, why_wrong, source):
    lines = text.splitlines()
    _, end = find_table(lines, "Date")
    row = [today.isoformat(), topic, question, my_answer, why_wrong, source, ""]
    lines.insert(end + 1, "| " + " | ".join(cell(v) for v in row) + " |")
    return "\n".join(lines) + "\n"


def fix_mistakes(text, question):
    lines = text.splitlines()
    head, end = find_table(lines, "Date")
    cols = split_row(lines[head])
    q, fixed = cols.index("Question (short)"), cols.index("Fixed?")
    count = 0
    for i in range(head + 2, end + 1):
        parts = split_row(lines[i]) + [""] * len(cols)
        if question.lower() in parts[q].lower() and "✅" not in parts[fixed]:
            parts[fixed] = "✅"
            lines[i] = "| " + " | ".join(parts[:len(cols)]) + " |"
            count += 1
    if not count:
        raise ToolError(f"no unfixed mistake whose question contains {question!r}")
    return "\n".join(lines) + "\n", count


def add_topics(text, topics):
    """Return (new_text, added). Appends Level 0 rows for topics not in the progress table yet."""
    lines = text.splitlines()
    head, end = find_table(lines, "Topic")
    cols = split_row(lines[head])
    have = {split_row(lines[i])[0].lower() for i in range(head + 2, end + 1)}
    added = []
    for topic in topics:
        name = cell(topic)
        if name and name.lower() not in have:
            have.add(name.lower())
            added.append(name)
            values = dict.fromkeys(cols, "")
            values.update({"Topic": name, "Level": "0"})
            end += 1
            lines.insert(end, "| " + " | ".join(values[c] for c in cols) + " |")
    return "\n".join(lines) + "\n", added


# ---------- importing the user's files ----------

def safe_filename(name):
    name = Path(str(name).replace("\\", "/")).name.strip()
    if not name or name.startswith(".") or not re.fullmatch(r"[\w .()+,&'-]+", name):
        raise ToolError(f"unusable file name {name!r}; use letters, digits, spaces and - _ . ( )")
    return name


def download(url, dest):
    if urllib.parse.urlparse(url).scheme != "https":
        raise ToolError("the file URL must be https")
    with urllib.request.urlopen(url, timeout=120) as resp, open(dest, "wb") as f:
        size = 0
        while chunk := resp.read(1 << 20):
            size += len(chunk)
            if size > MAX_DOWNLOAD:
                raise ToolError(f"file is larger than {MAX_DOWNLOAD >> 20} MB")
            f.write(chunk)
    return size


def readable(text):
    """Characters of real text; 0 when it is mostly undecodable glyphs (same rule as .tools/study)."""
    s = "".join(text.split())
    bad = sum(ch == "�" or ord(ch) < 32 for ch in s)
    return 0 if bad > len(s) * 0.1 else len(s)


def pdf_pages(src):
    from pypdf import PdfReader  # bundled into the binary; only needed where pdftotext is missing
    # NFKC turns ligatures ("ﬂuid") into plain letters, so grep finds "fluid".
    return [unicodedata.normalize("NFKC", page.extract_text() or "") for page in PdfReader(src).pages]


def ooxml_parts(src, kind):
    """Text of a PPTX (one part per slide) or DOCX (one part per paragraph), read from its XML."""
    with zipfile.ZipFile(src) as z:
        if kind == "slides":
            names = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                           key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
            tag, unit = "t", "p"  # a:t runs inside a:p paragraphs
        else:
            names, tag, unit = ["word/document.xml"], "t", "p"  # w:t runs inside w:p paragraphs
        parts = []
        for name in names:
            root = ET.fromstring(z.read(name))
            paras = ["".join(t.text or "" for t in p.iter() if t.tag.endswith("}" + tag))
                     for p in root.iter() if p.tag.endswith("}" + unit)]
            parts.append("\n".join(x for x in paras if x.strip()))
    return parts


def convert_builtin(src, out, source_label):
    """Write converted/*.md for src in the format `.tools/study ingest` uses. Returns a short summary."""
    ext, notes = src.suffix.lower(), []
    if ext == ".pdf":
        pages = pdf_pages(src)
        thin = sum(readable(p) < THIN_PAGE for p in pages)
        if thin > len(pages) / 2:
            notes.append(NOTE_NO_TEXT)
        body = "\n\n".join(f"--- page {i} ---\n{p.strip()}" for i, p in enumerate(pages, 1) if readable(p))
        summary = {"pages": len(pages), "pages_without_text": thin}
    elif ext in (".pptx", ".docx"):
        parts = ooxml_parts(src, KINDS[ext])
        if ext == ".pptx":
            body = "\n\n".join(f"<!-- Slide number: {i} -->\n{p}" for i, p in enumerate(parts, 1))
            summary = {"slides": len(parts)}
        else:
            body = parts[0] if parts else ""
            summary = {"paragraphs": body.count("\n") + 1 if body else 0}
    else:
        body = src.read_text(errors="replace")
        summary = {"lines": body.count("\n") + 1}
    head = "".join(n + "\n\n" for n in notes)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(out, f"# {src.name}\n\nSource: {source_label}\n\n{head}{body.strip()}\n")
    summary["chars"] = len(body)
    if notes:
        summary["note"] = notes[0]
    return summary


def add_material(root, sd, url, filename):
    name = safe_filename(filename)
    ext = Path(name).suffix.lower()
    if ext in MEDIA:
        raise ToolError("video and audio can't be transcribed on a cloud agent yet; attach slides, PDFs or notes")
    if ext not in KINDS:
        raise ToolError(f"unsupported file type {ext or '(none)'}; use PDF, PPTX, DOCX, MD or TXT")
    src = sd / "materials" / KINDS[ext] / name
    if src.exists():
        raise ToolError(f"{src.relative_to(root)} already exists; rename the file to add it again")
    src.parent.mkdir(parents=True, exist_ok=True)
    tmp = src.with_name(f".{name}.part")
    try:
        size = download(url, tmp)
        os.replace(tmp, src)
    finally:
        tmp.unlink(missing_ok=True)
    out = sd / "converted" / KINDS[ext] / (name + ".md")
    rel = str(src.relative_to(root))
    # The real ingest (pdftotext + OCR, markitdown, semantic index) wherever its converters exist.
    needs = {".pdf": "pdftotext", ".pptx": "markitdown", ".docx": "markitdown"}.get(ext)
    if needs and shutil.which(needs):
        r = subprocess.run([study_python(), str(root / ".tools/study"), "ingest", sd.name],
                           capture_output=True, text=True, timeout=280)
        if r.returncode == 0 and out.exists():
            return {"material": rel, "converted": str(out.relative_to(root)), "bytes": size,
                    "converter": "study ingest", "log": r.stdout.strip()[-1500:]}
    summary = convert_builtin(src, out, rel)
    return {"material": rel, "converted": str(out.relative_to(root)), "bytes": size, "converter": "built-in",
            **summary}


def study_python():
    # A frozen binary's sys.executable is the binary itself; .tools/study needs a real Python.
    return shutil.which("python3") if getattr(sys, "frozen", False) else sys.executable


# ---------- tools ----------

def run_tool(tool, args, today=None):
    if tool not in {t["name"] for t in MANIFEST["tools"]}:
        raise UnknownTool(f"unknown tool: {tool}")
    today = today or datetime.date.today()
    root, downloaded = ensure_root()
    if tool == "study_open":
        subjects = [{"name": s.name, "path": str(s)} for s in subjects_in(root)]
        return {"study_root": str(root), "downloaded_now": downloaded, "subjects": subjects,
                "today": today.isoformat()}
    if tool == "subject_new":
        name = args["name"].strip()
        if not re.fullmatch(r"[\w][\w .-]{0,79}", name) or name.startswith("_"):
            raise ToolError("subject names use letters, digits, spaces and - _ . (not starting with _)")
        r = subprocess.run([study_python(), str(root / ".tools/study"), "new", name],
                           capture_output=True, text=True, timeout=60)
        if r.returncode:
            raise ToolError((r.stdout + r.stderr).strip() or f"study new exited with {r.returncode}")
        return {"subject": name, "path": str(root / name), "output": r.stdout.strip()}
    sd = subject_dir(root, args["subject"])
    if tool == "material_add":
        return add_material(root, sd, args["url"], args["filename"])
    if tool == "topics_add":
        path = sd / "progress.md"
        text, added = add_topics(path.read_text(), args["topics"])
        write_atomic(path, text)
        return {"added": added}
    if tool == "study_search":
        r = subprocess.run([study_python(), str(root / ".tools/study"), "search", sd.name, args["query"],
                            "-k", str(args.get("k") or 6)], capture_output=True, text=True, timeout=110)
        message = (r.stdout + r.stderr).strip()
        if r.returncode and "not set up" in message:
            # Expected on a fresh machine or cloud agent: the tutor falls back to grep.
            return {"search_ready": False, "output": message, "fallback": f"grep -rn over {sd / 'converted'}"}
        if r.returncode:
            raise ToolError(message or f"search exited with {r.returncode}")
        return {"search_ready": True, "output": r.stdout.strip()}
    if tool == "progress_update":
        path = sd / "progress.md"
        level = int(args["level"]) if args.get("level") not in (None, "") else None
        text, row = update_progress(path.read_text(), args["topic"], args["outcome"], today,
                                    level, args.get("note"))
        write_atomic(path, text)
        return {"row": row}
    if tool == "mistake_add":
        path = sd / "mistakes.md"
        write_atomic(path, add_mistake(path.read_text(), today, args["topic"], args["question"],
                                       args["my_answer"], args["why_wrong"], args["source"]))
        return {"logged": True}
    if tool == "mistake_fixed":
        path = sd / "mistakes.md"
        text, count = fix_mistakes(path.read_text(), args["question"])
        write_atomic(path, text)
        return {"marked_fixed": count}
    if tool == "session_log":
        path = sd / "sessions" / f"{today.isoformat()}.md"
        path.parent.mkdir(exist_ok=True)
        old = path.read_text() if path.exists() else f"# Session {today.isoformat()}\n"
        bullets = "".join(f"- {cell(n)}\n" for n in args["notes"])
        write_atomic(path, old.rstrip("\n") + "\n\n" + bullets)
        return {"path": str(path)}


def handle(req):
    method = req.get("method")
    if method == "describe":
        return {"result": MANIFEST}
    if method == "health":
        return {"result": {"status": "ready"}}
    if method != "invoke":
        return {"error": {"code": -32601, "message": f"unknown method: {method}"}}
    params = req.get("params") or {}
    try:
        data = run_tool(params.get("tool", ""), params.get("arguments") or {})
        return {"result": {"success": True, "data": data}}
    except (ToolError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"result": {"success": False, "error": str(exc)}}
    except KeyError as exc:
        return {"error": {"code": -32602, "message": f"missing argument: {exc.args[0]}"}}
    except UnknownTool as exc:
        return {"error": {"code": -32601, "message": str(exc)}}
    except Exception as exc:  # noqa: BLE001
        return {"error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            req, payload = {}, {"error": {"code": -32700, "message": str(exc)}}
        else:
            payload = handle(req)
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req.get("id"), **payload}, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
