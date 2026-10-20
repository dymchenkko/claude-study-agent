#!/usr/bin/env python3
"""Local semantic index over a subject's converted/*.md (EmbeddingGemma 2, text only).

  semantic.py install                                    download llama.cpp + the model (~330 MB, once)
  semantic.py index  <conv_dir> <index_dir>              embed new/changed files only
  semantic.py search <conv_dir> <index_dir> <k> <query>  print top-k chunks with citations
  semantic.py check  [index|search]                      load the model once, print device + timing

Runs on llama.cpp (a small prebuilt `llama-server`, ~15 MB download) with the text-only GGUF of
EmbeddingGemma 2 (Q8_0, 310 MB). Standard library only: no PyTorch, no virtualenv. Each command
starts the server on a free local port, embeds, and stops it, so nothing stays in memory between
searches. Measured on an M2 Pro: start ~1.4 s, one query ~0.02 s, ~0.6 GB RAM; indexing ~0.1 s
per passage on the CPU alone. Top-5 results matched the earlier PyTorch build on 10/10 test queries.

Chunks follow the markers that `study` writes into converted/ files:
  --- page N ---            PDFs         -> loc "p.N"
  <!-- Slide number: N -->  PPTX         -> loc "slide N"
  [hh:mm:ss] paragraph      transcripts  -> loc "[hh:mm:ss]"
  ## Heading                notes (.md), only in files without the markers above -> loc "§ Heading"
Each source file gets one JSON cache in index_dir (keyed by the file's sha256 and the model),
so unchanged files are never re-embedded.

Device per task: STUDY_DEVICE env var (gpu|cpu), else .tools/config.json (written by `study setup`),
else gpu when the llama.cpp build has one (Apple Metal on macOS), else cpu.
"""

import hashlib
import json
import math
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
CONFIG = TOOLS / "config.json"
ENGINE_DIR = TOOLS / "llama"
MODEL_PATH = TOOLS / "models/embeddinggemma-2-Q8_0.gguf"

# pinned: the first builds that know the gemma-embedding2 architecture; checksums from the release
LLAMA_BUILD = "b11734"
LLAMA_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_BUILD}/llama-{LLAMA_BUILD}-bin-"
LLAMA_ASSETS = {  # (os, arch) -> (file suffix, sha256)
    ("Darwin", "arm64"): ("macos-arm64.tar.gz", "c823aad1d1c40728e8f1565663078fa2b3b7fd06bf484fa43e9e48b8b1b2509c"),
    ("Darwin", "x86_64"): ("macos-x64.tar.gz", "696521c81f21816e5b7686aa308425004ee1ec1fc2d2679414e9e6fa0aa8fbfc"),
    ("Linux", "x86_64"): ("ubuntu-x64.tar.gz", "5d20cbcde04ef743b96e91b6173663b1925077a13fa86d0d98e69a5a5b59a16a"),
    ("Linux", "aarch64"): ("ubuntu-arm64.tar.gz", "29f2c5bb869e60ff25848d8f8b3b34dbe1b924c2266d4f54ee84c1106f148b23"),
    ("Windows", "AMD64"): ("win-cpu-x64.zip", "bd6a8a8cb9d6ba115de3519d401f91dd5295b333243db44b6b8a3ce5e53ff8da"),
    ("Windows", "ARM64"): ("win-cpu-arm64.zip", "7f4c5a8a9d0129c4b541c4b057da2e8052f9f6819e105d00f5b26e8bf86205a2"),
}
MODEL_URL = ("https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/resolve/"
             "58faf90940886df2d62be555c8765d00dac362c5/embeddinggemma-2-Q8_0.gguf")
MODEL_SHA = "2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135"
# what sentence-transformers adds for prompt_name="query" / "document" (config_sentence_transformers.json)
QUERY_PROMPT = "task: search result | query: "
DOC_PROMPT = "title: none | text: "
# tokens per request: the longest chunk seen in real courses is ~700; longer ones are cut (see embed)
CTX = {"index": 2048, "search": 512}

MIN_CHARS = 30
FLUSH_CHARS = 900
SCAN_NOTE = "> NOTE: little text extracted"  # written by `study` for scanned PDFs, not content

PAGE = re.compile(r"^--- page (\d+) ---$")
SLIDE = re.compile(r"^<!-- Slide number: (\d+) -->$")
STAMP = re.compile(r"^\[(\d+:\d+:\d+)\]")
HEADING = re.compile(r"^#{2,3} +(.+)$")


def chunk_text(text):
    """Yield (loc, text) pairs; loc is '' when the file has no markers."""
    out, loc, buf = [], "", []
    marked = any(PAGE.match(l.strip()) or SLIDE.match(l.strip()) or STAMP.match(l.strip())
                 for l in text.splitlines())

    def flush():
        body = "\n".join(buf).strip()
        if len(body) >= MIN_CHARS:
            out.append((loc, body))
        buf.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("# ") and not out and not buf:
            continue  # file title line written by `study`
        if line.startswith(("Source: ", SCAN_NOTE, "> OCR: ")):
            continue  # absolute path / notices written by `study`, not content
        if m := PAGE.match(line):
            flush(); loc = f"p.{m.group(1)}"; continue
        if m := SLIDE.match(line):
            flush(); loc = f"slide {m.group(1)}"; continue
        if m := STAMP.match(line):
            flush(); loc = f"[{m.group(1)}]"
        if not marked and (m := HEADING.match(line)):
            flush(); loc = f"§ {m.group(1).strip()}"
        if not line:
            if sum(len(x) for x in buf) >= FLUSH_CHARS:
                flush()
            continue
        buf.append(line)
    flush()
    return out


# ---- engine: download once, then start/stop per command ----

def server_bin():
    name = "llama-server.exe" if platform.system() == "Windows" else "llama-server"
    return next(ENGINE_DIR.rglob(name), None) if ENGINE_DIR.exists() else None


def installed():
    return server_bin() is not None and MODEL_PATH.exists()


def download(url, dest, sha):
    """Download to dest via a .part file, refuse it unless the sha256 matches."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h, done, shown = hashlib.sha256(), 0, -1
    with urllib.request.urlopen(url) as r, open(part, "wb") as f:
        size = int(r.headers.get("Content-Length") or 0)
        while block := r.read(1 << 20):
            f.write(block); h.update(block); done += len(block)
            pct = done * 10 // size if size else -1
            if pct != shown and size:
                print(f"   {dest.name}: {done // 2**20} / {size // 2**20} MB", flush=True)
                shown = pct
    if h.hexdigest() != sha:
        part.unlink()
        sys.exit(f"Checksum mismatch for {url}: download refused. Try again later.")
    part.replace(dest)


def cmd_install():
    key = (platform.system(), platform.machine())
    if key not in LLAMA_ASSETS:
        sys.exit(f"No prebuilt llama.cpp for {key[0]} {key[1]}. Use `study setup --mode off` (Grep only).")
    if not server_bin():
        suffix, sha = LLAMA_ASSETS[key]
        print(f"-> downloading llama.cpp {LLAMA_BUILD} ({suffix})", flush=True)
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / suffix
            download(LLAMA_URL + suffix, archive, sha)
            shutil.rmtree(ENGINE_DIR, ignore_errors=True)
            if suffix.endswith(".zip"):
                with zipfile.ZipFile(archive) as z:
                    z.extractall(ENGINE_DIR)
            else:
                with tarfile.open(archive) as t:
                    if hasattr(tarfile, "data_filter"):
                        t.extractall(ENGINE_DIR, filter="data")  # no paths outside ENGINE_DIR
                    else:
                        t.extractall(ENGINE_DIR)
    if not MODEL_PATH.exists():
        print("-> downloading EmbeddingGemma 2 (text only, 310 MB)", flush=True)
        download(MODEL_URL, MODEL_PATH, MODEL_SHA)
    print(f"OK  installed: {server_bin().relative_to(TOOLS)}, {MODEL_PATH.relative_to(TOOLS)}")


def pick_device(task):
    """task is 'index' or 'search'. Returns 'gpu' (the build's default) or 'cpu'."""
    want = os.environ.get("STUDY_DEVICE")
    if not want and CONFIG.exists():
        want = json.loads(CONFIG.read_text()).get(f"{task}_device")
    if want == "off":
        sys.exit("Semantic search is off (study setup --mode off). Use Grep over converted/ instead.")
    return "cpu" if want == "cpu" else "gpu"  # older configs say mps / cuda: treat as gpu


class Engine:
    """llama-server on a free local port for the length of a `with` block."""

    def __init__(self, task):
        if not installed():
            sys.exit("Semantic search is not installed. Run: study setup")
        self.device, self.ctx = pick_device(task), CTX[task]

    def __enter__(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        exe = server_bin()
        args = [str(exe), "-m", str(MODEL_PATH), "--embeddings", "--host", "127.0.0.1",
                "--port", str(port), "-c", str(self.ctx), "-b", str(self.ctx), "-ub", str(self.ctx),
                "-np", "1", "--no-webui"]
        if self.device == "cpu":
            args += ["-ngl", "0", "--device", "none"]
        env = dict(os.environ)
        if platform.system() == "Linux":
            env["LD_LIBRARY_PATH"] = f"{exe.parent}:{env.get('LD_LIBRARY_PATH', '')}"
        self.log = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(args, stdout=self.log, stderr=self.log, env=env)
        deadline = time.time() + 120  # the first start on a new machine can be slow
        while True:
            try:
                with urllib.request.urlopen(self.url + "/health", timeout=2) as r:
                    if r.status == 200:
                        return self
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            if self.proc.poll() is not None or time.time() > deadline:
                self.__exit__()
                self.log.seek(0)
                tail = self.log.read().decode(errors="replace").strip().splitlines()[-5:]
                sys.exit("llama-server did not start:\n  " + "\n  ".join(tail))
            time.sleep(0.05)

    def __exit__(self, *exc):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def _post(self, texts):
        req = urllib.request.Request(self.url + "/v1/embeddings", data=json.dumps({"input": texts}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return [unit(d["embedding"]) for d in sorted(json.load(r)["data"], key=lambda d: d["index"])]

    def embed(self, texts):
        """Unit vectors. A text longer than the context is cut, like sentence-transformers does."""
        try:
            return self._post(texts)
        except urllib.error.HTTPError:
            if len(texts) > 1:
                return [v for t in texts for v in self.embed([t])]
            if len(texts[0]) < 200:
                raise
            return self.embed([texts[0][: len(texts[0]) * 3 // 4]])


def unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cmd_check(task):
    t0 = time.time()
    with Engine(task) as eng:
        t1 = time.time()
        v = eng.embed([QUERY_PROMPT + "sprawdzenie / test"])[0]
        t2 = time.time()
    print(f"OK  {task}: device={eng.device}  dim={len(v)}  load={t1 - t0:.1f}s  query={t2 - t1:.2f}s")


def cmd_index(conv, idx):
    conv, idx = Path(conv), Path(idx)
    idx.mkdir(parents=True, exist_ok=True)
    sources = sorted(p for p in conv.rglob("*.md") if p.is_file())
    keep = set()
    todo = []
    for src in sources:
        rel = src.relative_to(conv).as_posix()
        cache = idx / (rel + ".json")
        keep.add(cache)
        digest = hashlib.sha256(src.read_bytes()).hexdigest()
        if cache.exists():
            old = json.loads(cache.read_text())
            if old.get("hash") == digest and old.get("model") == MODEL_PATH.name:
                continue  # caches from the PyTorch build have no "model" key: re-embedded once
        todo.append((rel, cache, digest, src))

    # drop caches whose source file was deleted
    for cache in idx.rglob("*.json"):
        if cache not in keep:
            cache.unlink()

    if not todo:
        print(f"Index up to date ({len(sources)} files).")
        return

    total = 0
    with Engine("index") as eng:
        for rel, cache, digest, src in todo:
            pieces = chunk_text(src.read_text(errors="replace"))
            chunks = []
            if pieces:
                # the file name is part of the embedded text, so subject terms in titles count
                titled = [f"{DOC_PROMPT}{rel}\n{body}" for _, body in pieces]
                vecs = [v for i in range(0, len(titled), 16) for v in eng.embed(titled[i:i + 16])]
                chunks = [{"loc": loc, "text": body, "vec": [round(x, 5) for x in v]}
                          for (loc, body), v in zip(pieces, vecs)]
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"hash": digest, "model": MODEL_PATH.name, "chunks": chunks},
                                        ensure_ascii=False))
            total += len(chunks)
            print(f"  indexed {rel}: {len(chunks)} chunks", flush=True)
    print(f"Indexed {len(todo)} file(s), {total} chunks.")


class Searcher:
    """Load the index rows once and keep the embedding engine warm, for repeated queries (REPL)."""

    def __init__(self, conv, idx):
        self.conv, self.idx = Path(conv), Path(idx)
        if any(json.loads(c.read_text()).get("model") != MODEL_PATH.name for c in self.idx.rglob("*.json")):
            print("Rebuilding this index for the new search engine (once, ~0.1 s per passage)...", flush=True)
            cmd_index(self.conv, self.idx)
        self.rows = []
        for cache in sorted(self.idx.rglob("*.json")):
            rel = cache.relative_to(self.idx).as_posix()[: -len(".json")]
            name = rel[: -len(".md")] if rel.endswith(".md") else rel  # e.g. pdfs/Lecture3.pdf
            for ch in json.loads(cache.read_text())["chunks"]:
                if not ch["text"].startswith(SCAN_NOTE):
                    self.rows.append((name, ch))
        if not self.rows:
            if any(self.idx.rglob("*.json")):
                sys.exit("No searchable text: the converted files are empty or scanned PDFs.")
            sys.exit("Index is empty. Run: study index <Subject>")
        self._eng = Engine("search")

    def __enter__(self):
        self._eng.__enter__()
        return self

    def __exit__(self, *exc):
        self._eng.__exit__(*exc)

    def topk(self, query, k):
        q = self._eng.embed([QUERY_PROMPT + query[:1500]])[0]
        return sorted(((sum(a * b for a, b in zip(ch["vec"], q)), name, ch) for name, ch in self.rows),
                      key=lambda r: -r[0])[:k]


def rank(conv, idx, k, query):
    """One-shot top-k [(score, name, chunk)] for a query. Importable by `study` (ask/drain)."""
    with Searcher(conv, idx) as s:
        return s.topk(query, k)


def cmd_search(conv, idx, k, query):
    for score, name, ch in rank(conv, idx, k, query):
        snippet = " ".join(ch["text"].split())[:280]
        loc = f" {ch['loc']}" if ch["loc"] else ""
        print(f"{score:.3f}  ({name}{loc})")
        print(f"       {snippet}")


def main(argv):
    if argv[:1] == ["install"]:
        cmd_install()
    elif argv[:1] == ["check"]:
        cmd_check(argv[1] if len(argv) > 1 else "search")
    elif argv[:1] == ["index"] and len(argv) == 3:
        cmd_index(argv[1], argv[2])
    elif argv[:1] == ["search"] and len(argv) >= 5:
        cmd_search(argv[1], argv[2], int(argv[3]), " ".join(argv[4:]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
