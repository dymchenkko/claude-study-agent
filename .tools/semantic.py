#!/usr/bin/env python3
"""Local semantic index over a subject's converted/*.md (EmbeddingGemma 2, text only).

  semantic.py index  <conv_dir> <index_dir>              embed new/changed files only
  semantic.py search <conv_dir> <index_dir> <k> <query>  print top-k chunks with citations
  semantic.py check  [index|search]                      load the model once, print device + timing

Chunks follow the markers that `study` writes into converted/ files:
  --- page N ---            PDFs         -> loc "p.N"
  <!-- Slide number: N -->  PPTX         -> loc "slide N"
  [hh:mm:ss] paragraph      transcripts  -> loc "[hh:mm:ss]"
  ## Heading                notes (.md), only in files without the markers above -> loc "§ Heading"
Each source file gets one JSON cache in index_dir (keyed by the file's sha256),
so unchanged files are never re-embedded.

Device per task: STUDY_DEVICE env var, else .tools/config.json (written by `study setup`),
else auto. Auto indexes on the GPU (Apple "mps" or NVIDIA "cuda") and searches on the CPU:
a search embeds one short query, so the CPU is quicker there (no GPU start-up) and uses half
the memory, while indexing embeds hundreds of chunks, where the GPU is ~30x faster.
"""

import hashlib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

# keep output to the results: the tutor reads every line of it
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
logging.getLogger("torch.distributed.elastic.multiprocessing.redirects").setLevel(logging.ERROR)

MODEL_ID = "google/embeddinggemma-2"
# text-only: the vision (170M) and audio (300M) encoders are never used here and give identical
# text vectors when skipped, so 270M of 740M parameters are loaded
TEXT_ONLY = {"vision_config": None, "audio_config": None}
CONFIG = Path(__file__).resolve().parent / "config.json"
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


def pick_device(task):
    """task is 'index' or 'search'."""
    want = os.environ.get("STUDY_DEVICE")
    if not want and CONFIG.exists():
        want = json.loads(CONFIG.read_text()).get(f"{task}_device")
    if want == "off":
        sys.exit("Semantic search is off (study setup --mode off). Use Grep over converted/ instead.")
    if want and want != "auto":
        return want
    if task == "search":
        return "cpu"
    import torch
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def load_model(task):
    from sentence_transformers import SentenceTransformer
    device = pick_device(task)
    # half precision halves memory on GPUs; on CPU float32 is the safe, fast path
    kwargs = dict(device=device, config_kwargs=TEXT_ONLY,
                  model_kwargs={"torch_dtype": "float16"} if device != "cpu" else {})
    try:
        return SentenceTransformer(MODEL_ID, local_files_only=True, **kwargs)  # no network once cached
    except OSError:
        print(f"Downloading {MODEL_ID} (~1.5 GB, once)...", file=sys.stderr, flush=True)
        return SentenceTransformer(MODEL_ID, **kwargs)


def cmd_check(task):
    t0 = time.time()
    model = load_model(task)
    t1 = time.time()
    v = model.encode(["sprawdzenie / test"], prompt_name="query", normalize_embeddings=True)[0]
    t2 = time.time()
    print(f"OK  {task}: device={model.device}  dim={len(v)}  load={t1 - t0:.1f}s  query={t2 - t1:.2f}s")


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
        if cache.exists() and json.loads(cache.read_text()).get("hash") == digest:
            continue
        todo.append((rel, cache, digest, src))

    # drop caches whose source file was deleted
    for cache in idx.rglob("*.json"):
        if cache not in keep:
            cache.unlink()

    if not todo:
        print(f"Index up to date ({len(sources)} files).")
        return

    model = load_model("index")
    total = 0
    for rel, cache, digest, src in todo:
        pieces = chunk_text(src.read_text(errors="replace"))
        chunks = []
        if pieces:
            # the file name is part of the embedded text, so subject terms in titles count
            titled = [f"{rel}\n{body}" for _, body in pieces]
            vecs = model.encode(titled, prompt_name="document", normalize_embeddings=True,
                                batch_size=16)
            # float32 first: rounding float16 overflows (x * 1e5 > 65504) and turns into NaN
            chunks = [{"loc": loc, "text": body, "vec": np.round(v.astype(np.float32), 5).tolist()}
                      for (loc, body), v in zip(pieces, vecs)]
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"hash": digest, "chunks": chunks}, ensure_ascii=False))
        total += len(chunks)
        print(f"  indexed {rel}: {len(chunks)} chunks", flush=True)
    print(f"Indexed {len(todo)} file(s), {total} chunks.")


def cmd_search(conv, idx, k, query):
    conv, idx = Path(conv), Path(idx)
    rows, vecs = [], []
    for cache in sorted(idx.rglob("*.json")):
        rel = cache.relative_to(idx).as_posix()[: -len(".json")]
        name = rel[: -len(".md")] if rel.endswith(".md") else rel  # e.g. pdfs/Lecture3.pdf
        for ch in json.loads(cache.read_text())["chunks"]:
            if ch["text"].startswith(SCAN_NOTE):
                continue  # indexed by an older chunker
            rows.append((name, ch))
            vecs.append(ch["vec"])
    if not rows:
        if any(idx.rglob("*.json")):
            sys.exit("No searchable text: the converted files are empty or scanned PDFs. "
                     "Read the originals in materials/ instead.")
        sys.exit("Index is empty. Run: study index <Subject>")

    model = load_model("search")
    q = model.encode([query], prompt_name="query", normalize_embeddings=True)[0].astype(np.float32)
    scores = np.asarray(vecs, dtype=np.float32) @ q
    for i in np.argsort(-scores)[:k]:
        name, ch = rows[i]
        snippet = " ".join(ch["text"].split())[:280]
        loc = f" {ch['loc']}" if ch["loc"] else ""
        print(f"{scores[i]:.3f}  ({name}{loc})")
        print(f"       {snippet}")


def main(argv):
    if argv[:1] == ["check"]:
        cmd_check(argv[1] if len(argv) > 1 else "search")
    elif argv[:1] == ["index"] and len(argv) == 3:
        cmd_index(argv[1], argv[2])
    elif argv[:1] == ["search"] and len(argv) >= 5:
        cmd_search(argv[1], argv[2], int(argv[3]), " ".join(argv[4:]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
