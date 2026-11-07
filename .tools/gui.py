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
import planner
import studydata as sd
from studydata import (days_between, parse_exam, parse_mistakes, parse_progress, session_notes,  # noqa: F401
                       subject_names, table_rows)

PAGE = Path(__file__).resolve().parent / "gui" / "index.html"
RHYTHM_DAYS = 42
REPLAY_MIN_STARTED = 5


# ---------- reading the study files (pure functions, no agent) ----------

def subject_detail(root, name, today):
    folder = Path(root) / name
    claude = sd._read(folder / "CLAUDE.md")
    reviews = sd.parse_reviews(claude)
    topics = parse_progress(sd._read(folder / "progress.md"), today, reviews["resumed"])
    mistakes = parse_mistakes(sd._read(folder / "mistakes.md"))
    syllabus = sd.parse_syllabus(sd._read(folder / "syllabus.md"))
    events, bad = sd.read_events(folder)
    links, warnings = sd.read_links(folder, topics)
    slipping = sd.slips(events)
    if bad:
        warnings.append(f"{bad} line(s) in events.jsonl could not be read and were skipped")
    index = {sd.topic_key(t["topic"]): i for i, t in enumerate(topics)}
    unmatched = 0
    replay = []
    for e in events:
        i = index.get(sd.topic_key(e["topic"]))
        if i is None:
            unmatched += 1
            continue
        replay.append({"day": e["ts"][:10], "i": i, "level": e.get("level_after"),
                       "interval": e.get("interval_after"), "kind": e["kind"]})
    if unmatched:
        warnings.append(f"{unmatched} event(s) name a topic that is not in progress.md and are left off the map")
    for t in topics:
        t["slip"] = sd.topic_key(t["topic"]) in slipping
        t["weight"] = sd.topic_weight(t["topic"], syllabus)
        t["fresh"] = sd.freshness(days_between(t["last"], today) if t["last"] else None, t["interval"])
    last = sd.last_session(folder)
    started = sum(1 for t in topics if t["level"] > 0 or t["last"])
    return {
        "name": name,
        "exam": parse_exam(claude, today),
        "reviews": reviews,
        "diagrams": sd.has_diagrams(claude),
        "lastSession": last,
        "awayDays": days_between(last, today) if last else None,
        "sessionDays": sd.session_dates(folder),
        "topics": topics,
        "mistakes": mistakes,
        "notes": session_notes(folder),
        "links": links,
        "hasLinksFile": (folder / "links.json").exists(),
        "depths": sd.depths(len(topics), links),
        "moved": sd.what_moved(events),
        "unlogged": sd.unlogged(topics, events) if events else 0,
        "hasEvents": bool(events),
        "replay": replay if started >= REPLAY_MIN_STARTED else None,
        "replayApprox": any(e["kind"] == "import" for e in events),
        "warnings": warnings,
    }


def subject_summary(detail):
    topics, mistakes = detail["topics"], detail["mistakes"]
    return {
        "name": detail["name"],
        "exam": detail["exam"],
        "lastSession": detail["lastSession"],
        "awayDays": detail["awayDays"],
        "topics": len(topics),
        "started": sum(1 for t in topics if t["level"] > 0 or t["last"]),
        "due": sum(1 for t in topics if t["overdue"] is not None),
        "openMistakes": sum(1 for m in mistakes if not m["fixed"]),
        "paused": detail["reviews"]["paused"],
        "pausedSince": detail["reviews"]["since"],
        "sessionDays": detail["sessionDays"],
        # one entry per topic in course order: the sidebar draws it as a tiny course strip
        "strip": [{"level": t["level"], "due": t["overdue"] is not None} for t in topics],
    }


# ---------- Plan: rhythm, prompts and today's picks ----------

def read_state(root):
    """.tools/gui-state.json: answers like "Not now". Malformed or missing: start empty."""
    try:
        data = json.loads((Path(root) / ".tools" / "gui-state.json").read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("dismissed"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"dismissed": []}


def dismiss(root, key):
    state = read_state(root)
    if key not in state["dismissed"]:
        state["dismissed"].append(key)
    path = Path(root) / ".tools" / "gui-state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def exam_prompt_key(name, exam):
    """The exam-date question comes back once per new state: unset, or each passed date."""
    if exam["state"] == "unset":
        return f"exam:{name}:unset"
    if exam["state"] == "past":
        return f"exam:{name}:past:{exam.get('last')}"
    return None


def prompts(root, summaries):
    dismissed = set(read_state(root)["dismissed"])
    exam, pause = [], []
    for s in summaries:
        key = exam_prompt_key(s["name"], s["exam"])
        if key and key not in dismissed and s["topics"]:
            exam.append({"subject": s["name"], "key": key, "past": s["exam"]["state"] == "past"})
        key = f"pause:{s['name']}"
        if s["exam"]["state"] == "none" and s["due"] >= 5 and not s["paused"] and key not in dismissed:
            pause.append({"subject": s["name"], "key": key, "due": s["due"]})
    return {"exam": exam, "pause": pause}


def rhythm(summaries, today, days=RHYTHM_DAYS):
    """Session days per subject over the last `days` days, for the Plan timeline."""
    start = date.fromordinal(date.fromisoformat(today).toordinal() - days + 1).isoformat()
    active = [s for s in summaries if not s["paused"]]
    all_days = {d for s in summaries for d in s["sessionDays"] if start <= d <= today}
    return {
        "start": start, "days": days,
        "overdue": sum(s["due"] for s in active), "started": sum(s["started"] for s in active),
        "sessionDays": len(all_days),
        "rows": [{"name": s["name"], "days": [days_between(start, d) for d in s["sessionDays"] if start <= d <= today],
                  "last": s["lastSession"], "due": s["due"], "started": s["started"], "paused": s["paused"]}
                 for s in summaries if s["topics"]],
    }


def overview(root, today, rebuild=False):
    names = subject_names(root)
    details = [subject_detail(root, n, today) for n in names]
    summaries = [subject_summary(d) for d in details]
    return {"subjects": summaries, "rhythm": rhythm(summaries, today), "prompts": prompts(root, summaries),
            "plan": planner.today_plan(root, today, rebuild)}


def import_history(root, today):
    """First start: seed each subject's events.jsonl from progress.md (only once, see studydata)."""
    for n in subject_names(root):
        folder = Path(root) / n
        sd.import_events(folder, parse_progress(sd._read(folder / "progress.md"), today))


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
                return self._json(dict(overview(root, today), today=today, root=str(root), agent=adapter.name,
                                       agentReady=adapter.available()))
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
            if not self._same_origin():
                return self._json({"error": "requests must come from the study gui page"}, 403)
            if url.path == "/api/chat":
                return self._chat(body)
            if url.path in ("/api/exam", "/api/reviews", "/api/dismiss"):
                return self._write(url.path, body)
            if url.path == "/api/chat/stop":
                with lock:
                    run = runs.get(body.get("runId"))
                if run:
                    run.stop()
                return self._json({"stopped": bool(run)})
            return self._json({"error": "not found"}, 404)

        def _same_origin(self):
            """Writes need the per-run token (checked above) and an Origin of this very server."""
            port = self.server.server_address[1]
            return self.headers.get("Origin") in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

        def _write(self, path, body):
            today = date.today().isoformat()
            if path == "/api/dismiss":
                key = str(body.get("key", ""))
                if not re.fullmatch(r"(exam|pause):[^\n\r]{1,200}", key):
                    return self._json({"error": "bad key"}, 400)
                dismiss(root, key)
                return self._json({"ok": True})
            subject = str(body.get("subject", ""))
            if subject not in subject_names(root):
                return self._json({"error": f"no subject {subject}"}, 404)
            try:
                if path == "/api/exam":
                    sd.write_exam(root / subject, body.get("value"))
                else:
                    action = body.get("action")
                    if action not in ("pause", "resume"):
                        raise ValueError("action must be pause or resume")
                    sd.write_reviews(root / subject, action == "pause", today)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            planner.today_plan(root, today, rebuild=True)  # keeps finished picks
            return self._json({"ok": True})

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
    import_history(Path(root), date.today().isoformat())
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
