"""Runs the tutor for `study gui`: sends a prompt to Claude Code in the study folder and turns its
output into simple events for the page. Another agent would be another class with the same
`start()` and the same events:

  {"type": "session", "sessionId"}   to continue the chat later
  {"type": "text", "text"}           a piece of the reply
  {"type": "tool", "label"}          what the tutor is doing, in plain words
  {"type": "blocked"}                Claude's safety filter withheld part of the reply
  {"type": "error", "message"}
  {"type": "done", "sessionId", "text"}
"""

import json
import os
from datetime import datetime
import re
import shutil
import subprocess
from pathlib import Path

# A resumed chat reloads its whole history on every message. Past this size (screenshots and pasted
# terminal output add up fast) the tutor gets slow and is more likely to be blocked, so the server
# starts a fresh session and hands over the last few messages instead.
MAX_SESSION_BYTES = 2_500_000

NOTE = (
    "The student is using the study dashboard, a web page, not the terminal. Replies are shown as "
    "Markdown. The subject open on the page is {subject}: use it unless the student names another. "
    "Ask questions in plain text (no option pickers). Keep updating progress.md, mistakes.md and "
    "sessions/ as usual. You may use the student's Chrome (Claude in Chrome) to look at pages, but do "
    "not submit, post or change anything there unless the student asks for that exact action.\n"
    "Right now it is {now} (the student's local time). Notes, progress.md and chat transcripts were written "
    "on earlier days: words like today, this morning, yesterday, dziś, rano or wczoraj in them mean the date "
    "of that file or entry, not today. Say the real day (\"yesterday morning\", \"on 22.11\") when you refer "
    "to them, and write absolute dates in anything you save."
)

def note(subject, now=None):
    now = now or datetime.now()
    return NOTE.format(subject=subject, now=f"{now:%A} {now:%Y-%m-%d} {now:%H:%M}")


LABELS = {"Grep": "Searching your lectures", "Glob": "Searching your lectures",
          "Read": "Reading your materials", "Edit": "Saving notes", "Write": "Saving notes"}


def _label(name, args):
    if name == "Bash" and " search " in str(args.get("command", "")):
        return "Searching your lectures"
    if name.startswith("mcp__claude-in-chrome__"):
        return "Looking in Chrome"
    return LABELS.get(name, "Working")


class ClaudeAdapter:
    name = "claude"

    def __init__(self, root):
        self.root, self.binary = root, shutil.which("claude")

    def available(self):
        return bool(self.binary)

    def session_file(self, session_id):
        """Where Claude Code keeps this chat: <config>/projects/<cwd with non-alphanumerics as ->/<id>.jsonl"""
        if not session_id or not re.fullmatch(r"[\w-]+", session_id):
            return None
        config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
        return config / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(Path(self.root).resolve())) / f"{session_id}.jsonl"

    def too_long(self, session_id):
        f = self.session_file(session_id)
        try:
            return bool(f) and f.stat().st_size > MAX_SESSION_BYTES
        except OSError:
            return False

    def start(self, prompt, subject, session_id=None):
        # print mode cannot ask for permission, so the browser tools are allowed up front
        cmd = [self.binary, "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--include-partial-messages", "--disallowedTools", "AskUserQuestion",
               "--chrome", "--allowedTools", "mcp__claude-in-chrome",
               "--append-system-prompt", note(subject)]
        if session_id:
            cmd += ["--resume", session_id]
        return Run(subprocess.Popen(cmd, cwd=self.root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", bufsize=1))


def _refused(kind, e, ev):
    """The safety filter stopped a reply: the API ends that message with stop_reason "refusal"."""
    if kind == "stream_event" and ev.get("type") == "message_delta":
        return (ev.get("delta") or {}).get("stop_reason") == "refusal"
    return kind == "assistant" and (e.get("message") or {}).get("stop_reason") == "refusal"


class Run:
    """One prompt. Iterate `events()`; `stop()` may be called from another thread."""

    def __init__(self, proc):
        self.proc, self.stopped = proc, False

    def stop(self):
        self.stopped = True
        if self.proc.poll() is None:
            self.proc.terminate()

    def events(self):
        session, text, other, after_tool, finished, blocked = None, "", [], False, False, False
        for line in self.proc.stdout:
            try:
                e = json.loads(line)
            except ValueError:
                other.append(line)  # stderr: kept for the error message
                continue
            kind, ev = e.get("type"), e.get("event", {})
            if not blocked and _refused(kind, e, ev):
                blocked = True
                yield {"type": "blocked"}
            if kind == "system" and e.get("subtype") == "init":
                session = e.get("session_id")
                yield {"type": "session", "sessionId": session}
            elif kind == "stream_event" and ev.get("type") == "content_block_delta" \
                    and ev["delta"].get("type") == "text_delta":
                piece = ev["delta"]["text"]
                if after_tool and text:  # text after a tool call starts a new paragraph
                    piece = "\n\n" + piece
                after_tool, text = False, text + piece
                yield {"type": "text", "text": piece}
            elif kind == "assistant":
                for block in e.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use":
                        after_tool = True
                        yield {"type": "tool", "label": _label(block["name"], block.get("input") or {})}
            elif kind == "result":
                finished, session = True, e.get("session_id") or session
                if e.get("is_error"):
                    yield {"type": "error", "message": str(e.get("result") or "The tutor stopped with an error.")}
        self.proc.wait()
        if not finished and not self.stopped:
            yield {"type": "error", "message": "".join(other).strip()[-500:]
                   or f"The tutor exited with code {self.proc.returncode}."}
        yield {"type": "done", "sessionId": session, "text": text, "stopped": self.stopped}
