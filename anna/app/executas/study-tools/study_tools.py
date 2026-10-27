#!/usr/bin/env python3
"""study-tools: an Anna Executa plugin (JSON-RPC 2.0 over stdio) for the study folder.

The skills teach; this plugin does the file work that a model gets wrong: it finds or downloads the study
folder, runs the real `.tools/study search`, and changes progress.md, mistakes.md and the session log one row
at a time, applying the review ladder in code. Standard library only.

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
import urllib.request
from pathlib import Path

VERSION = "0.1.0"
REPO_TARBALL = "https://github.com/dymchenkko/claude-study-agent/archive/refs/heads/main.tar.gz"
LADDER = [1, 3, 7, 16, 35]
OUTCOMES = ["correct", "partial", "wrong", "learned"]


def _param(name, type_, description, required=True, **extra):
    return {"name": name, "type": type_, "description": description, "required": required, **extra}


SUBJECT = _param("subject", "string", "Subject folder name, e.g. Example-Subject (case-insensitive).")
MANIFEST = {
    "name": "study-tools",
    "display_name": "Study Tools",
    "version": VERSION,
    "description": "Study folder tools for the study tutor: open or download the study folder, search the "
                   "course materials, and record progress, mistakes and session notes safely.",
    "homepage": "https://github.com/dymchenkko/claude-study-agent",
    "icon": "🎓",
    "category": "education",
    "license": "MIT",
    "tools": [
        {"name": "study_open",
         "description": "Call first. Finds the study folder (downloads it if missing) and lists the subjects "
                        "with their file paths.",
         "parameters": []},
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
    sd = subject_dir(root, args["subject"])
    if tool == "study_search":
        python = shutil.which("python3") if getattr(sys, "frozen", False) else sys.executable
        r = subprocess.run([python, str(root / ".tools/study"), "search", sd.name, args["query"],
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
