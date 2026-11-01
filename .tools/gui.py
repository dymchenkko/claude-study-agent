"""`study gui`: a local web page over the study folder.

Standard library only. The page reads the subject files through a small JSON API and chats with
the tutor through an agent adapter (agents.py), streamed as server-sent events. Nothing is stored
anywhere but the study folder. Listens on 127.0.0.1 with a random token in the URL.
"""

import json
import re
import secrets
import threading
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import agents

PAGE = Path(__file__).resolve().parent / "gui" / "index.html"
DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
SKIP_DIRS = {"_template", ".tools", ".claude", ".git"}


# ---------- reading the study files (pure functions, no agent) ----------

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


def _date(text):
    m = DATE.search(text or "")
    return m.group(1) if m else None


def days_between(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def parse_progress(md, today):
    topics = []
    for r in table_rows(md, ["topic", "level", "next review"]):
        name = _col(r, "topic")
        if not name:
            continue
        try:
            level = int(_col(r, "level"))
        except ValueError:
            level = 0
        nxt, last = _date(_col(r, "next review")), _date(_col(r, "last studied"))
        topics.append({
            "topic": name, "level": level, "last": last, "next": nxt,
            "overdue": days_between(nxt, today) if nxt and nxt <= today else None,
            "notes": _col(r, "notes"),
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


def parse_exam(claude_md, today):
    line = next((l for l in claude_md.splitlines() if re.search(r"exam date", l, re.I)), "")
    value = re.sub(r".*exam date:?\**:?", "", line, flags=re.I).strip()
    # "NO EXAM (recording 2026-09-26)" mentions a date that is not the exam's.
    if re.search(r"no exam|brak egzaminu", value, re.I):
        return {"days": None, "label": "no exam"}
    d = _date(value)
    if d:
        return {"days": days_between(today, d), "label": d}
    return {"days": None, "label": "exam date not set"}


def last_session(folder):
    dates = sorted(d for p in (folder / "sessions").glob("*.md") if (d := _date(p.name)))
    return dates[-1] if dates else None


def _read(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def subject_names(root):
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and p.name not in SKIP_DIRS and not p.name.startswith(".")
                  and (p / "CLAUDE.md").is_file())


def subject_detail(root, name, today):
    folder = root / name
    topics = parse_progress(_read(folder / "progress.md"), today)
    mistakes = parse_mistakes(_read(folder / "mistakes.md"))
    last = last_session(folder)
    return {
        "name": name,
        "exam": parse_exam(_read(folder / "CLAUDE.md"), today),
        "lastSession": last,
        "awayDays": days_between(last, today) if last else None,
        "topics": topics,
        "mistakes": mistakes,
    }


def subject_summary(detail):
    topics, mistakes = detail["topics"], detail["mistakes"]
    return {
        "name": detail["name"],
        "exam": detail["exam"],
        "lastSession": detail["lastSession"],
        "awayDays": detail["awayDays"],
        "topics": len(topics),
        "started": sum(1 for t in topics if t["level"] > 0),
        "due": sum(1 for t in topics if t["overdue"] is not None),
        "openMistakes": sum(1 for m in mistakes if not m["fixed"]),
        # one entry per topic in course order: the sidebar draws it as a tiny course strip
        "strip": [{"level": t["level"], "due": t["overdue"] is not None} for t in topics],
    }


# ---------- chat transcripts ----------

def save_transcript(root, subject, prompt, reply, now=None):
    """Append one exchange to <Subject>/sessions/YYYY-MM-DD-chat.md (the chat is a real session)."""
    now = now or datetime.now()
    path = root / subject / "sessions" / f"{now:%Y-%m-%d}-chat.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    head = "" if path.exists() else f"# {subject} — chat {now:%Y-%m-%d}\n\nSaved by `study gui`.\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{head}\n## {now:%H:%M}\n\n**You:** {prompt.strip()}\n\n**Tutor:**\n\n{reply.strip() or '_(no reply)_'}\n")
    return path


# ---------- the server ----------

def make_handler(root, token):
    adapter = agents.ClaudeAdapter(root)
    runs, lock = {}, threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet
            pass

        def _send(self, code, body, ctype):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

        def _authorised(self, url):
            if parse_qs(url.query).get("t", [""])[0] == token:
                return True
            self._send(403, "Open the link printed by `study gui`.", "text/plain")
            return False

        def do_GET(self):
            url = urlparse(self.path)
            if not self._authorised(url):
                return
            today = date.today().isoformat()
            parts = [unquote(p) for p in url.path.strip("/").split("/") if p]
            if not parts:
                return self._send(200, PAGE.read_text(encoding="utf-8"), "text/html; charset=utf-8")
            if parts == ["api", "subjects"]:
                names = subject_names(root)
                return self._json({"today": today, "root": str(root), "agent": adapter.name,
                                   "agentReady": adapter.available(), "subjects": [
                                       subject_summary(subject_detail(root, n, today)) for n in names]})
            if len(parts) == 3 and parts[:2] == ["api", "subjects"]:
                if parts[2] not in subject_names(root):
                    return self._json({"error": f"no subject {parts[2]}"}, 404)
                return self._json(subject_detail(root, parts[2], today))
            return self._json({"error": "not found"}, 404)

        def do_POST(self):
            url = urlparse(self.path)
            if not self._authorised(url):
                return
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or b"{}")
            except ValueError:
                return self._json({"error": "bad JSON"}, 400)
            if url.path == "/api/chat":
                return self._chat(body)
            if url.path == "/api/chat/stop":
                with lock:
                    run = runs.get(body.get("runId"))
                if run:
                    run.stop()
                return self._json({"stopped": bool(run)})
            return self._json({"error": "not found"}, 404)

        def _event(self, obj):
            self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.flush()

        def _chat(self, body):
            prompt, subject = str(body.get("prompt", "")).strip(), str(body.get("subject", ""))
            if not prompt:
                return self._json({"error": "empty message"}, 400)
            if subject not in subject_names(root):
                return self._json({"error": f"no subject {subject}"}, 404)
            if not adapter.available():
                return self._json({"error": f"{adapter.name} is not installed or not on PATH"}, 503)
            run_id = secrets.token_hex(8)
            run = adapter.start(prompt, subject, body.get("sessionId") or None)
            with lock:
                runs[run_id] = run
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            reply = ""
            try:
                self._event({"type": "start", "runId": run_id})
                for ev in run.events():
                    if ev["type"] == "done":
                        reply = ev.get("text", "")
                    self._event(ev)
            except (BrokenPipeError, ConnectionResetError):
                run.stop()  # the page was closed: don't leave the agent running
            finally:
                with lock:
                    runs.pop(run_id, None)
                if reply.strip():  # failed or empty runs are not a study session
                    save_transcript(root, subject, prompt, reply)

    return Handler


def serve(root, port=0, open_browser=True):
    token = secrets.token_urlsafe(16)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(Path(root), token))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={token}"
    print(f"Study GUI for {root}\n  {url}\nCtrl+C to stop.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
