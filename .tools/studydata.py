"""Reading and writing the study files for `study gui`, `study plan` and `study log`.

Standard library only, no agent. Covers progress.md, mistakes.md, syllabus.md, the exam-date and
Reviews lines in a subject's CLAUDE.md, sessions/, events.jsonl and links.json. Pure functions take
text; the few that touch disk take the subject folder.
"""

import json
import re
from datetime import date, datetime
from pathlib import Path

DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
SKIP_DIRS = {"_template", ".tools", ".claude", ".git"}
KINDS = ("lesson", "recall", "quiz", "exam", "drawing", "import")
VERDICTS = ("correct", "partly", "wrong", "imported")
CHAT_KINDS = {"lesson", "recall", "quiz", "exam"}
WEIGHTS = {"high": 3, "med": 2, "medium": 2, "low": 1}


# ---------- small helpers ----------

def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _date(text):
    m = DATE.search(text or "")
    return m.group(1) if m else None


def _valid_date(s):
    try:
        date.fromisoformat(s)
        return True
    except (TypeError, ValueError):
        return False


def days_between(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def topic_key(name):
    """The topic key: the exact progress.md name, trimmed and case-folded."""
    return str(name or "").strip().casefold()


def _norm(s):
    return re.sub(r"[`'\"()]", "", str(s).lower()).strip()


def same_topic(a, b):
    """Mistake topics are short ("Multiplicities"), progress topics longer: match by prefix either way."""
    a, b = _norm(a), _norm(b)
    return bool(a) and bool(b) and (a.startswith(b) or b.startswith(a))


# ---------- markdown tables ----------

def table_rows(md, need):
    """Rows of the first markdown table whose header has every `need` column (prefix match),
    as dicts keyed by the lower-cased header."""
    lines = [l.strip() for l in md.splitlines()]
    for i, line in enumerate(lines[:-1]):
        if not line.startswith("|"):
            continue
        head = [c.lower() for c in _cells(line)]
        if not all(any(h.startswith(n) for h in head) for n in need):
            continue
        rows = []
        for row_line in lines[i + 2:]:
            if not row_line.startswith("|"):
                break
            row = _cells(row_line)
            rows.append({h: (row[k] if k < len(row) else "") for k, h in enumerate(head)})
        return rows
    return []


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _col(rec, prefix):
    return next((v for k, v in rec.items() if k.startswith(prefix)), "")


def _int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def parse_progress(md, today, resumed=None):
    """Topics in course order. `overdue` is days past Next review (None when not due). After a
    resume, overdue days count from the resume date, so a resumed subject can't flood the plan."""
    topics = []
    for r in table_rows(md, ["topic", "level", "next review"]):
        name = _col(r, "topic")
        if not name:
            continue
        level = _int(_col(r, "level")) or 0
        nxt, last = _date(_col(r, "next review")), _date(_col(r, "last studied"))
        overdue = None
        if nxt and nxt <= today:
            overdue = days_between(max(nxt, resumed) if resumed and resumed <= today else nxt, today)
        topics.append({
            "topic": name, "level": level, "last": last, "next": nxt, "overdue": overdue,
            "interval": _int(_col(r, "interval")), "notes": _col(r, "notes"),
        })
    return topics


def parse_mistakes(md):
    out = []
    for r in table_rows(md, ["topic", "fixed"]):
        if not _col(r, "topic"):
            continue
        out.append({
            "date": _col(r, "date"), "topic": _col(r, "topic"),
            "question": _col(r, "question"), "answer": _col(r, "my answer"),
            "why": _col(r, "why"), "source": _col(r, "source"),
            "fixed": "✅" in _col(r, "fixed"),
        })
    return out


def parse_syllabus(md):
    rows = []
    for r in table_rows(md, ["topic", "exam"]):
        if _col(r, "topic"):
            word = (_col(r, "exam").split() or [""])[0].lower().strip("*.,")
            rows.append({"topic": _col(r, "topic"), "weight": WEIGHTS.get(word, 2)})
    return rows


_WORD = re.compile(r"[^\W_]{3,}")


def _tokens(s):
    return set(_WORD.findall(str(s).casefold()))


def topic_weight(topic, syllabus):
    """Exam weight of a progress topic: high 3, med 2, low 1, blank or no match 2. Progress names are
    short forms of the syllabus rows, so match by shared words (at least half of the topic's)."""
    words, best, score = _tokens(topic), None, 0.0
    for row in syllabus:
        if same_topic(topic, row["topic"]):
            return row["weight"]
        if words:
            s = len(words & _tokens(row["topic"])) / len(words)
            if s > score:
                best, score = row, s
    return best["weight"] if best and score >= 0.5 else 2


# ---------- fields in a subject's CLAUDE.md ----------

def _field_re(name):
    return re.compile(r"^(\s*[-*]\s*\*\*" + re.escape(name) + r":?\*\*:?)(.*)$", re.I | re.M)


def field(md, name):
    """Value of a `- **Name:** value` line, or None when the line is missing."""
    m = _field_re(name).search(md)
    return m.group(2).strip() if m else None


def set_field(md, name, value, after=None):
    """Replace one `- **Name:**` line, or insert it below the `after` line (else the first field)."""
    if "\n" in value or "\r" in value:
        raise ValueError("no newlines")
    m = _field_re(name).search(md)
    if m:
        return md[:m.start()] + f"{m.group(1)} {value}" + md[m.end():]
    line = f"- **{name}:** {value}"
    anchor = _field_re(after).search(md) if after else None
    anchor = anchor or re.search(r"^\s*[-*]\s*\*\*[^*\n]+\*\*.*$", md, re.M)
    if anchor:
        return md[:anchor.end()] + "\n" + line + md[anchor.end():]
    return md.rstrip("\n") + "\n\n" + line + "\n"


def parse_exam(claude_md, today):
    """{state, days, label}. state: date (the earliest future ISO date), past, unknown, none, unset."""
    value = field(claude_md, "Exam date") or ""
    # "NO EXAM (recording 2026-09-26)" mentions a date that is not the exam's.
    if re.search(r"no exam|brak egzaminu", value, re.I) or value.strip().lower() == "none":
        return {"state": "none", "days": None, "label": "no exam"}
    if value.strip().lower() == "unknown":
        return {"state": "unknown", "days": None, "label": "exam date unknown"}
    dates = sorted(d for d in DATE.findall(value) if _valid_date(d))
    future = [d for d in dates if d >= today]
    if future:
        return {"state": "date", "days": days_between(today, future[0]), "label": future[0]}
    if dates:
        return {"state": "past", "days": None, "label": f"exam was {dates[-1]}", "last": dates[-1]}
    return {"state": "unset", "days": None, "label": "exam date not set"}


def parse_reviews(claude_md):
    """{paused, since, resumed} from `- **Reviews:** paused since D` / `resumed D`."""
    value = (field(claude_md, "Reviews") or "").lower()
    d = _date(value)
    if value.startswith("paused"):
        return {"paused": True, "since": d, "resumed": None}
    if value.startswith("resumed"):
        return {"paused": False, "since": None, "resumed": d}
    return {"paused": False, "since": None, "resumed": None}


def has_diagrams(claude_md):
    """A real Diagrams entry: text after the label that is not the template placeholder."""
    value = field(claude_md, "Diagrams")
    return bool(value) and not value.lower().startswith("(leave blank")


def check_exam_value(value):
    value = str(value or "").strip()
    if value in ("unknown", "none") or (re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) and _valid_date(value)):
        return value
    raise ValueError("exam date must be YYYY-MM-DD, unknown or none")


def write_exam(folder, value):
    path = Path(folder) / "CLAUDE.md"
    path.write_text(set_field(_read(path), "Exam date", check_exam_value(value)), encoding="utf-8")


def write_reviews(folder, paused, today):
    if not _valid_date(today):
        raise ValueError("bad date")
    path = Path(folder) / "CLAUDE.md"
    value = f"paused since {today}" if paused else f"resumed {today}"
    path.write_text(set_field(_read(path), "Reviews", value, after="Exam date"), encoding="utf-8")


# ---------- sessions ----------

def subject_names(root):
    return sorted(p.name for p in Path(root).iterdir()
                  if p.is_dir() and p.name not in SKIP_DIRS and not p.name.startswith(".")
                  and (p / "CLAUDE.md").is_file())


def session_dates(folder):
    """Dates of sessions/YYYY-MM-DD.md and YYYY-MM-DD-chat.md, deduplicated, ascending."""
    return sorted({d for p in (Path(folder) / "sessions").glob("*.md") if (d := _date(p.name))})


def last_session(folder):
    dates = session_dates(folder)
    return dates[-1] if dates else None


def session_notes(folder):
    """The newest sessions/YYYY-MM-DD.md as written, without its title. Chat transcripts are skipped."""
    logs = sorted(p for p in (Path(folder) / "sessions").glob("*.md") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem))
    if not logs:
        return None
    text = re.sub(r"\A\s*#[^\n]*\n", "", _read(logs[-1])).strip()
    return {"date": logs[-1].stem, "text": text} if text else None


# ---------- events.jsonl ----------

def parse_events(text):
    """(events sorted by ts, number of malformed lines skipped)."""
    events, bad = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
            ok = (isinstance(e, dict) and isinstance(e.get("ts"), str) and _valid_date(e["ts"][:10])
                  and isinstance(e.get("topic"), str) and e.get("kind") in KINDS and e.get("verdict") in VERDICTS)
        except ValueError:
            ok = False
        if ok:
            events.append(e)
        else:
            bad += 1
    events.sort(key=lambda e: e["ts"])
    return events, bad


def read_events(folder):
    return parse_events(_read(Path(folder) / "events.jsonl"))


def import_events(folder, topics):
    """Seed events.jsonl from progress.md once: one import event per started topic, dated its Last
    studied. Nothing is written when the file exists or no topic has been studied yet."""
    path = Path(folder) / "events.jsonl"
    started = [t for t in topics if t["last"]]
    if path.exists() or not started:
        return False
    with path.open("w", encoding="utf-8") as f:
        for t in sorted(started, key=lambda t: t["last"]):
            f.write(json.dumps({"ts": f"{t['last']}T00:00:00", "topic": t["topic"], "kind": "import",
                                "verdict": "imported", "level_after": t["level"],
                                "interval_after": t["interval"]}, ensure_ascii=False) + "\n")
    return True


def log_event(folder, topics, topic, kind, verdict, level, interval, now=None):
    """Append one event (after importing history if the file is new). Returns (event, warning)."""
    if kind not in KINDS or kind == "import":
        raise ValueError(f"kind must be one of {', '.join(k for k in KINDS if k != 'import')}")
    if verdict not in VERDICTS or verdict == "imported":
        raise ValueError("verdict must be correct, partly or wrong")
    import_events(folder, topics)
    known = {topic_key(t["topic"]): t["topic"] for t in topics}
    name = known.get(topic_key(topic))
    ev = {"ts": (now or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S"), "topic": name or topic.strip(),
          "kind": kind, "verdict": verdict, "level_after": level, "interval_after": interval}
    warning = None
    if not name:
        ev["unmatched"] = True
        warning = f"'{topic}' is not a topic in progress.md; logged anyway as unmatched"
    with (Path(folder) / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev, warning


def slips(events):
    """Topic keys that slip when drawn: newest drawing verdict wrong or partly while the newest chat
    verdict (lesson, recall, quiz, exam) is correct."""
    drawn, chat = {}, {}
    for e in events:
        k = topic_key(e["topic"])
        if e["kind"] == "drawing":
            drawn[k] = e["verdict"]
        elif e["kind"] in CHAT_KINDS:
            chat[k] = e["verdict"]
    return {k for k, v in drawn.items() if v in ("wrong", "partly") and chat.get(k) == "correct"}


def what_moved(events):
    """Level changes on the newest day with real (non-import) events: {date, items}, or None."""
    real = [e for e in events if e["kind"] != "import"]
    if not real:
        return None
    day = real[-1]["ts"][:10]
    items = {}
    for e in events:
        k = topic_key(e["topic"])
        if e["ts"][:10] < day:
            items.setdefault(k, {"topic": e["topic"], "before": None})["before"] = e.get("level_after")
        elif e["kind"] != "import" and e["ts"][:10] == day:
            it = items.setdefault(k, {"topic": e["topic"], "before": None})
            it["after"] = e.get("level_after")
            it.setdefault("verdicts", []).append(e["verdict"])
            it.setdefault("kinds", [])
            if e["kind"] not in it["kinds"]:
                it["kinds"].append(e["kind"])
    out = []
    for it in items.values():
        if "after" not in it:
            continue
        v = it.pop("verdicts")
        it["verdict"] = "wrong" if "wrong" in v else "partly" if "partly" in v else "correct"
        out.append(it)
    return {"date": day, "items": out}


def unlogged(topics, events):
    """Topics whose Last studied is newer than their newest event: sessions the event log missed."""
    newest = {}
    for e in events:
        newest[topic_key(e["topic"])] = e["ts"][:10]
    return sum(1 for t in topics if t["last"] and newest.get(topic_key(t["topic"]), "") < t["last"])


def freshness(days_since, interval):
    """Estimated memory strength 0..1: 2^(-days / (4 x interval)). None when not started."""
    if days_since is None or not interval:
        return None
    return 2 ** (-max(days_since, 0) / (4 * interval))


# ---------- links.json ----------

def parse_links(text, topics):
    """(edges as [from_index, to_index], warnings). Bad JSON gives no links and a warning; self
    links and unknown topics are dropped; a cycle is broken by ignoring the edge that closes it."""
    if text is None:
        return [], []
    try:
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError
    except ValueError:
        return [], ["links.json is not valid JSON (a list of {\"from\", \"to\"}), so no links are shown"]
    index = {topic_key(t["topic"]): i for i, t in enumerate(topics)}
    out, nxt, dropped, cyc = [], {}, 0, 0

    def reaches(a, b):
        stack, seen = [a], set()
        while stack:
            x = stack.pop()
            if x == b:
                return True
            if x not in seen:
                seen.add(x)
                stack.extend(nxt.get(x, ()))
        return False

    for item in data:
        a = index.get(topic_key(item.get("from"))) if isinstance(item, dict) else None
        b = index.get(topic_key(item.get("to"))) if isinstance(item, dict) else None
        if a is None or b is None or a == b:
            dropped += 1
            continue
        if b in nxt.get(a, ()):
            continue
        if reaches(b, a):
            cyc += 1
            continue
        nxt.setdefault(a, []).append(b)
        out.append([a, b])
    warnings = []
    if dropped:
        warnings.append(f"{dropped} link(s) in links.json name an unknown topic or link a topic to itself")
    if cyc:
        warnings.append(f"{cyc} link(s) in links.json would make a loop and were ignored")
    return out, warnings


def read_links(folder, topics):
    path = Path(folder) / "links.json"
    return parse_links(_read(path) if path.exists() else None, topics)


def depths(n, edges):
    """Prerequisite depth per topic: 0 for topics nothing points to, else 1 + the deepest prerequisite."""
    pre = {}
    for a, b in edges:
        pre.setdefault(b, []).append(a)
    memo = {}

    def depth(i):
        if i not in memo:
            memo[i] = 0
            memo[i] = 1 + max((depth(p) for p in pre.get(i, ())), default=-1)
        return memo[i]

    return [depth(i) for i in range(n)]
