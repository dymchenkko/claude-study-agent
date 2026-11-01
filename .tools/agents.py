"""Runs the tutor for `study gui`: sends a prompt to Claude Code in the study folder and turns its
output into simple events for the page. Another agent would be another class with the same
`start()` and the same events:

  {"type": "session", "sessionId"}   to continue the chat later
  {"type": "text", "text"}           a piece of the reply
  {"type": "tool", "label"}          what the tutor is doing, in plain words
  {"type": "error", "message"}
  {"type": "done", "sessionId", "text"}
"""

import json
import shutil
import subprocess

NOTE = (
    "The student is using the study dashboard, a web page, not the terminal. Replies are shown as "
    "Markdown. The subject open on the page is {subject}: use it unless the student names another. "
    "Ask questions in plain text (no option pickers). Keep updating progress.md, mistakes.md and "
    "sessions/ as usual. You may use the student's Chrome (Claude in Chrome) to look at pages, but do "
    "not submit, post or change anything there unless the student asks for that exact action."
)

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

    def start(self, prompt, subject, session_id=None):
        # print mode cannot ask for permission, so the browser tools are allowed up front
        cmd = [self.binary, "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--include-partial-messages", "--disallowedTools", "AskUserQuestion",
               "--chrome", "--allowedTools", "mcp__claude-in-chrome",
               "--append-system-prompt", NOTE.format(subject=subject)]
        if session_id:
            cmd += ["--resume", session_id]
        return Run(subprocess.Popen(cmd, cwd=self.root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", bufsize=1))


class Run:
    """One prompt. Iterate `events()`; `stop()` may be called from another thread."""

    def __init__(self, proc):
        self.proc, self.stopped = proc, False

    def stop(self):
        self.stopped = True
        if self.proc.poll() is None:
            self.proc.terminate()

    def events(self):
        session, text, other, after_tool, finished = None, "", [], False, False
        for line in self.proc.stdout:
            try:
                e = json.loads(line)
            except ValueError:
                other.append(line)  # stderr: kept for the error message
                continue
            kind, ev = e.get("type"), e.get("event", {})
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
