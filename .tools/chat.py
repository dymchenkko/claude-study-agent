#!/usr/bin/env python3
"""Tiny local 'front desk' model (Qwen3.5 0.8B) over the same llama.cpp as the embeddings.

It is deliberately NOT a reasoner. Given the student's question and the passages already retrieved
from their own materials, it either relays one short grounded sentence, or replies exactly DEFER so
the question is escalated to the strong model. Standard library only; the chat server is started on
a free port for one call and stopped again, so nothing stays resident.
"""
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import semantic  # reuse server_bin() and the downloader

TOOLS = Path(__file__).resolve().parent
CHAT_MODEL = TOOLS / "models/Qwen3.5-0.8B-Q8_0.gguf"
CHAT_URL = ("https://huggingface.co/ggml-org/Qwen3.5-0.8B-GGUF/resolve/"
            "main/Qwen3.5-0.8B-Q8_0.gguf")
CHAT_SHA = "37ae482d336108d23516fa35e8e0c4126688d81018b87178a18d752a1357814f"

SYSTEM = (
    "You are the offline front desk of a student's personal study tool. "
    "You do NOT reason, explain, compare, calculate, or answer from your own knowledge. "
    "You only relay facts that are written in the PASSAGES the student already owns.\n"
    "- If the question is a simple lookup whose answer is stated in the passages, reply with ONE "
    "short sentence, in the same language as the question, using only the passages.\n"
    "- If answering would need any reasoning, comparison or synthesis, or the passages do not "
    "contain the answer, reply with exactly: DEFER\n"
    "Never invent. When unsure, reply DEFER."
)
THINK = re.compile(r"<think>.*?</think>", re.S)


def installed():
    return CHAT_MODEL.exists() and semantic.server_bin() is not None


def install():
    if not semantic.server_bin():
        semantic.cmd_install()  # pulls llama.cpp if missing
    if not CHAT_MODEL.exists():
        print("-> downloading Qwen3.5 0.8B (local front-desk model, ~830 MB)", flush=True)
        semantic.download(CHAT_URL, CHAT_MODEL, CHAT_SHA)
    print(f"OK  local model: {CHAT_MODEL.relative_to(TOOLS)}")


class _Server:
    def __enter__(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        exe = semantic.server_bin()
        args = [str(exe), "-m", str(CHAT_MODEL), "--host", "127.0.0.1", "--port", str(port),
                "-c", "4096", "-np", "1", "--no-webui"]
        env = dict(os.environ)
        if sys.platform.startswith("linux"):
            env["LD_LIBRARY_PATH"] = f"{exe.parent}:{env.get('LD_LIBRARY_PATH', '')}"
        self.log = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(args, stdout=self.log, stderr=self.log, env=env)
        deadline = time.time() + 120
        while True:
            try:
                if urllib.request.urlopen(self.url + "/health", timeout=2).status == 200:
                    return self
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            if self.proc.poll() is not None or time.time() > deadline:
                self.__exit__()
                self.log.seek(0)
                sys.exit("local chat model did not start:\n  "
                         + "\n  ".join(self.log.read().decode(errors="replace").splitlines()[-5:]))
            time.sleep(0.05)

    def __exit__(self, *exc):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def complete(self, system, user, schema=None, max_tokens=110, temperature=0):
        body = {"messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "temperature": temperature, "max_tokens": max_tokens, "repeat_penalty": 1.3,
                # Qwen3.5 is a reasoning model; without this it spends the whole budget "thinking"
                # and returns empty content. The front desk must not reason anyway.
                "chat_template_kwargs": {"enable_thinking": False}}
        if schema is not None:  # force exact JSON shape (constrained decoding)
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "r", "schema": schema}}
        req = urllib.request.Request(self.url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.load(r)["choices"][0]["message"]["content"]


ROUTER_SYSTEM = (
    "You are the ROUTER of a student's offline study tool. You do NOT answer, explain or solve. "
    "You pick exactly one tool as JSON:\n"
    "- search: the student wants a fact, term or definition that is probably written in their course "
    "slides. Set query to the key term to look up (a few words).\n"
    "- escalate: the request needs reasoning, problem solving, comparison, worked homework, or 'why/how' "
    "explanation — anything a slide lookup cannot settle. Set query to the student's request, briefly.\n"
    "Output only the JSON object."
)
ROUTE_SCHEMA = {
    "type": "object",
    "properties": {"tool": {"type": "string", "enum": ["search", "escalate"]},
                   "query": {"type": "string"}},
    "required": ["tool", "query"],
    "additionalProperties": False,
}


def _parse_route(raw, message):
    try:
        d = json.loads(THINK.sub("", raw).strip())
        if d.get("tool") in ("search", "escalate"):
            return d["tool"], (d.get("query") or message).strip()
    except Exception:
        pass
    return "escalate", message


ROUTE_VOTES = int(os.environ.get("STUDY_ROUTE_VOTES", "5"))        # sample the router N times
ROUTE_ESCALATE_MIN = int(os.environ.get("STUDY_ROUTE_ESCALATE_MIN", "2"))  # >= this many "escalate" -> defer


def _route_votes(server, message):
    """Self-consistency routing: sample the router a few times with temperature and let the model's
    own disagreement be the signal. A small model is confidently wrong on single shots, but a real
    spread of 'escalate' votes means it isn't sure — so we defer. Language-agnostic, no keyword list."""
    tools, query = [], message
    for _ in range(ROUTE_VOTES):
        tool, q = _parse_route(server.complete(ROUTER_SYSTEM, f"STUDENT: {message}",
                                               schema=ROUTE_SCHEMA, max_tokens=80, temperature=0.8), message)
        tools.append(tool)
        if tool == "search":
            query = q
    tool = "escalate" if tools.count("escalate") >= ROUTE_ESCALATE_MIN else "search"
    return tool, query


class Session:
    """A warm chat server for a REPL: one process, many routing turns."""

    def __enter__(self):
        self._s = _Server().__enter__()
        return self

    def __exit__(self, *exc):
        self._s.__exit__(*exc)

    def route(self, message):
        return _route_votes(self._s, message)


def route(message):
    """Self-consistency vote. Returns (tool, query); defers when the model isn't consistent."""
    with _Server() as s:
        return _route_votes(s, message)


def respond(question, passages):
    """Return ('answer', text) for a grounded one-liner, or ('defer', raw) to escalate."""
    ctx = "\n\n".join(p[:1200] for p in passages)[:3500]
    user = f"PASSAGES:\n{ctx}\n\nQUESTION: {question} /no_think"
    with _Server() as s:
        raw = s.complete(SYSTEM, user)
    out = THINK.sub("", raw).strip()
    if not out or out.upper().startswith("DEFER"):
        return ("defer", out)
    return ("answer", out)


if __name__ == "__main__":
    if sys.argv[1:2] == ["install"]:
        install()
    else:
        print(__doc__)
