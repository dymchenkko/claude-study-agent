"""Agent adapters for `study gui`: send a prompt to a coding agent running in the study folder and
stream back simple events. The page only ever sees these events, so other agents (OpenCode, Goose,
a hosted backend) can be added as another adapter without touching the page.

Event shapes (dicts):
  {"type": "session", "sessionId"}   the agent's session id (to continue the chat later)
  {"type": "text", "text"}           a piece of the reply, in order
  {"type": "tool", "label"}          what the agent is doing right now, in plain words
  {"type": "done", "sessionId", "text"}
  {"type": "error", "message"}

Standard library only.
"""

import json
import shutil
import subprocess
import threading

GUI_NOTE = (
    "The student is using the study dashboard, a web page, not the terminal. Your replies are shown "
    "as Markdown in a chat panel. The subject open on the page is {subject}: use it unless the "
    "student names another. You cannot show option pickers here: ask questions in plain text and the "
    "student answers in the next message. Keep updating progress.md, mistakes.md and sessions/ as usual."
)


def _tool_label(name, args):
    """A short, student-friendly description of a tool call."""
    args = args or {}
    if name == "Bash":
        cmd = str(args.get("command", ""))
        if " search " in cmd:
            return "Searching your lectures"
        if " draw " in cmd:
            return "Opening the diagram"
        if " ingest" in cmd:
            return "Reading new materials"
        return "Running a helper"
    if name in ("Grep", "Glob"):
        return "Searching your lectures"
    if name == "Read":
        path = str(args.get("file_path", ""))
        for f in ("progress.md", "mistakes.md", "syllabus.md", "CLAUDE.md"):
            if path.endswith(f):
                return f"Reading {f}"
        return "Reading your materials"
    if name in ("Edit", "Write", "MultiEdit"):
        path = str(args.get("file_path", ""))
        if path.endswith("progress.md"):
            return "Updating your progress"
        if path.endswith("mistakes.md"):
            return "Logging a mistake"
        if "/sessions/" in path:
            return "Writing the session notes"
        return "Saving a file"
    if name == "Skill":
        return f"Starting /{args.get('skill', '')}".rstrip("/")
    return f"Using {name}"


class Run:
    """One prompt sent to the agent. Iterate `events()`; call `stop()` from another thread."""

    def __init__(self, proc, parse):
        self.proc, self._parse = proc, parse
        self._stopped = False

    def stop(self):
        self._stopped = True
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def events(self):
        yield from self._parse(self)


class ClaudeAdapter:
    """Claude Code in print mode: `claude -p --output-format stream-json`. Uses the person's own
    Claude login or API key, and the study folder's CLAUDE.md, skills and permissions."""

    name = "claude"

    def __init__(self, root, binary=None):
        self.root = root
        self.binary = binary or shutil.which("claude")

    def available(self):
        return bool(self.binary)

    def start(self, prompt, subject, session_id=None):
        cmd = [self.binary, "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--include-partial-messages", "--disallowedTools", "AskUserQuestion",
               "--append-system-prompt", GUI_NOTE.format(subject=subject)]
        if session_id:
            cmd += ["--resume", session_id]
        proc = subprocess.Popen(cmd, cwd=self.root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        err = []
        reader = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
        reader.start()
        return Run(proc, lambda run: self._parse(run, err, reader))

    def _parse(self, run, err, reader):
        session, text, last_was_text, finished = None, [], False, False
        for line in run.proc.stdout:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            kind = e.get("type")
            if kind == "system" and e.get("subtype") == "init":
                session = e.get("session_id")
                yield {"type": "session", "sessionId": session}
            elif kind == "stream_event":
                ev = e.get("event", {})
                if ev.get("type") == "content_block_start" and ev.get("content_block", {}).get("type") == "text":
                    if text and not last_was_text:  # new text block after tool use: start a new paragraph
                        text.append("\n\n")
                        yield {"type": "text", "text": "\n\n"}
                    last_was_text = True
                elif ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                    piece = ev["delta"].get("text", "")
                    text.append(piece)
                    yield {"type": "text", "text": piece}
            elif kind == "assistant":
                for block in e.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use":
                        last_was_text = False
                        yield {"type": "tool", "label": _tool_label(block.get("name"), block.get("input"))}
            elif kind == "result":
                finished = True
                session = e.get("session_id") or session
                if e.get("is_error"):
                    yield {"type": "error", "message": str(e.get("result") or "The agent stopped with an error.")}
                yield {"type": "done", "sessionId": session, "text": "".join(text)}
        run.proc.wait()
        reader.join(2)
        if not finished:
            if run._stopped:
                yield {"type": "done", "sessionId": session, "text": "".join(text), "stopped": True}
            else:
                msg = "".join(err).strip()[-500:] or f"The agent exited with code {run.proc.returncode}."
                yield {"type": "error", "message": msg}
                yield {"type": "done", "sessionId": session, "text": "".join(text)}


ADAPTERS = {"claude": ClaudeAdapter}


def get_adapter(root, name="claude"):
    return ADAPTERS.get(name, ClaudeAdapter)(root)
