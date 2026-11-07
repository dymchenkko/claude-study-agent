"""Topic links from the local embedding model: `study links <Subject>`.

No LLM. Every topic gets a vector, its pages' embeddings averaged, taken from the semantic index
(.tools/index/<Subject>/) that `study search` already uses:
  1. progress.md topic -> its syllabus.md row (same leading id like "W3", same words, or same position)
  2. the row's Sources ("wyklad_1 p.13-19; Lecture.mp4 [00:01:00]-[00:06:03]") -> index chunks
  3. no row, or no chunk found -> the top chunks a search for the topic name returns (starts the model)
Two topics whose pages mostly overlap (Jaccard >= 0.5, e.g. grammar points taught on the same pages)
are never linked: the material can't tell which comes first. Vectors are centred (minus the subject's
mean vector), so what every topic shares, like the course's vocabulary, doesn't count as a link. Then, in course order, each topic is linked from its most similar
EARLIER topics (at most --max, cosine >= --min), skipping one already reachable through a link just
kept. Similar material is a hint, not proof of a prerequisite: read the list, delete what's wrong.
"""

import json
import math
import re
import unicodedata
from pathlib import Path

import studydata as sd

MIN_SIM, MAX_LINKS, SEARCH_K, SAME_PAGES = 0.35, 2, 6, 0.5

_DASH = "[–—-]"
_STAMP_RANGE = re.compile(rf"\[(\d+:\d+:\d+)\]\s*{_DASH}\s*\[(\d+:\d+:\d+)\]")
_STAMP = re.compile(r"\[(\d+:\d+:\d+)\]")
_LOC_START = re.compile(r"\s(?:pp?\.|slides?\b|§)|\s?\[\d+:\d+")
_NUMS = re.compile(rf"(\d+)(?:\s*{_DASH}\s*(\d+))?")
_FILE_WORD = re.compile(r"[^\W_]+")
_EXT = re.compile(r"\.(pdf|pptx|docx|xlsx|mp4|mov|mkv|webm|m4a|mp3|wav|md|txt)\b", re.I)


# ---------- syllabus ----------

def syllabus_rows(md):
    """Rows of EVERY table with a Sources column (a syllabus may split lectures and labs into two),
    as {"id", "topic", "sources"}. The topic column is the first that isn't #, Sources or Exam."""
    rows, lines = [], [l.strip() for l in md.splitlines()]
    i = 0
    while i < len(lines) - 1:
        head = [c.lower() for c in sd._cells(lines[i])] if lines[i].startswith("|") else []
        if not any(h.startswith("source") for h in head):
            i += 1
            continue
        src = next(k for k, h in enumerate(head) if h.startswith("source"))
        num = next((k for k, h in enumerate(head) if h in ("#", "id", "nr", "no")), None)
        name = next((k for k, h in enumerate(head) if k not in (src, num) and not h.startswith("exam")), None)
        i += 2
        while i < len(lines) and lines[i].startswith("|"):
            cells = sd._cells(lines[i])
            get = lambda k: cells[k] if k is not None and k < len(cells) else ""  # noqa: E731
            if get(name):
                rows.append({"id": get(num), "topic": get(name), "sources": get(src)})
            i += 1
    return rows


def match_rows(topics, rows):
    """progress topic index -> syllabus row index (or None). Tried in order: the topic starts with the
    row's id ("W3 Modele..." / row "W3"), the names share a prefix or at least half the topic's words,
    and finally position, when both lists are the same length."""
    out = {}
    ids = {r["id"].casefold(): k for k, r in enumerate(rows) if r["id"] and not r["id"].isdigit()}
    for i, t in enumerate(topics):
        first = (t["topic"].split() or [""])[0].casefold()
        if first in ids:
            out[i] = ids[first]
            continue
        words, best, score = sd._tokens(t["topic"]), None, 0.0
        for k, r in enumerate(rows):
            if sd.same_topic(t["topic"], r["topic"]):
                best, score = k, 1.0
                break
            if words:
                s = len(words & sd._tokens(r["topic"])) / len(words)
                if s > score:
                    best, score = k, s
        if best is not None and score >= 0.5:
            out[i] = best
    if len(topics) == len(rows):
        for i in range(len(topics)):
            out.setdefault(i, i)
    return out


# ---------- sources -> index chunks ----------

def _secs(stamp):
    h, m, s = (int(x) for x in stamp.split(":"))
    return h * 3600 + m * 60 + s


def _file_words(s):
    s = unicodedata.normalize("NFKD", s.casefold())  # macOS names come decomposed; ź and z match
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"(?<=\d)[-./](?=\d)", "", s)  # 2026-09-26 and 20260926 are one word
    return set(_FILE_WORD.findall(_EXT.sub(" ", s)))


def _ext(s):
    found = _EXT.findall(s)
    return found[0].lower() if found else None


def parse_sources(text):
    """[(file words, extension | None, pages set | None, [(start s, end s)] | None)] for one Sources cell.
    Pieces are split on ; and ·; a piece without a page, slide or [time] means the whole file."""
    out = []
    for piece in re.split(r"[;·]", text or ""):
        piece = piece.strip()
        if not piece:
            continue
        m = _LOC_START.search(piece)
        name, loc = (piece[:m.start()], piece[m.start():]) if m else (piece, "")
        words = _file_words(name)
        if not words:
            continue
        spans = [(_secs(a), _secs(b)) for a, b in _STAMP_RANGE.findall(loc)]
        rest = _STAMP_RANGE.sub(" ", loc)
        spans += [(_secs(a), _secs(a) + 300) for a in _STAMP.findall(rest)]  # a lone stamp: 5 minutes
        pages = set()
        for a, b in _NUMS.findall(_STAMP.sub(" ", rest)):
            a, b = int(a), int(b or a)
            if 0 < a <= b <= a + 300:
                pages.update(range(a, b + 1))
        out.append((words, _ext(name), pages or None, spans or None))
    return out


def best_file(words, names, ext=None):
    """The index file whose name holds most of the source's words (at least 60%), then the one with
    fewest other words. A named extension (.pdf vs .mp4 of the same lecture) must match. Ties: None."""
    scored = []
    for n in names:
        if ext and _ext(n.rsplit("/", 1)[-1]) != ext:
            continue
        fw = _file_words(n)  # with its folders: a source may cite homework/task-1/...
        scored.append(((len(words & fw) / len(words), -len(fw - words)), n))
    scored.sort(reverse=True)
    if not scored or scored[0][0][0] < 0.6 or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return None
    return scored[0][1]


def chunk_in(loc, pages, spans):
    if pages is None and spans is None:
        return True
    if pages is not None and (m := re.match(r"(?:p\.|slide )(\d+)$", loc)):
        return int(m.group(1)) in pages
    if spans is not None and (m := re.match(r"\[(\d+:\d+:\d+)\]$", loc)):
        t = _secs(m.group(1))
        return any(a <= t <= b for a, b in spans)
    return False


def source_chunks(text, files):
    """{(file, chunk number): vector} for the chunks a Sources cell points at.
    files: {index name: [chunk dicts]}."""
    out = {}
    for words, ext, pages, spans in parse_sources(text):
        name = best_file(words, files, ext)
        if name:
            out.update({(name, k): c["vec"] for k, c in enumerate(files[name])
                        if chunk_in(c["loc"], pages, spans)})
    return out


# ---------- vectors -> links ----------

def mean_unit(vecs):
    if not vecs:
        return None
    v = [sum(x) / len(vecs) for x in zip(*vecs)]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def centred(vecs):
    """Subtract the mean of the present vectors, renormalise. None stays None."""
    have = [v for v in vecs if v is not None]
    if len(have) < 2:
        return vecs
    mean = [sum(x) / len(have) for x in zip(*have)]
    return [mean_unit([[a - b for a, b in zip(v, mean)]]) if v is not None else None for v in vecs]


def cos(a, b):
    return sum(x * y for x, y in zip(a, b))


def overlap(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def propose(vecs, min_sim=MIN_SIM, max_links=MAX_LINKS, pages=None):
    """[(from, to, similarity)] in course order: each topic from its most similar earlier topics.
    pages: per topic, the set of chunk ids behind its vector; pairs sharing most of them are skipped."""
    vecs = centred(vecs)
    pages = pages or [set()] * len(vecs)
    pre, out = {}, []

    def ancestors(i, seen):
        for p in pre.get(i, ()):
            if p not in seen:
                seen.add(p)
                ancestors(p, seen)
        return seen

    for j, vj in enumerate(vecs):
        if vj is None:
            continue
        cands = sorted(((cos(vi, vj), i) for i, vi in enumerate(vecs[:j]) if vi is not None), reverse=True)
        kept, covered = [], set()
        for s, i in cands:
            if s < min_sim or len(kept) == max_links:
                break
            if i in covered or overlap(pages[i], pages[j]) >= SAME_PAGES:
                continue
            kept.append(i)
            covered |= {i} | ancestors(i, set())
            out.append((i, j, s))
        pre[j] = kept
    return out


# ---------- the command ----------

def load_index(idx):
    files = {}
    for cache in sorted(Path(idx).rglob("*.json")):
        rel = cache.relative_to(idx).as_posix()[: -len(".json")]
        files[rel[: -len(".md")] if rel.endswith(".md") else rel] = json.loads(cache.read_text())["chunks"]
    return files


def topic_vectors(folder, idx, topics, engine_factory):
    """(vectors, chunk id sets, how) per topic; how is 'sources', 'search' or None (nothing found)."""
    files = load_index(idx)
    rows = syllabus_rows(sd._read(Path(folder) / "syllabus.md"))
    match = match_rows(topics, rows)
    vecs, ids, how, missing = [], [], [], []
    for i in range(len(topics)):
        found = source_chunks(rows[match[i]]["sources"], files) if i in match else {}
        vecs.append(mean_unit(list(found.values())))
        ids.append(set(found))
        how.append("sources" if found else None)
        if not found:
            missing.append(i)
    chunks = [((n, k), c["vec"]) for n, cs in files.items() for k, c in enumerate(cs)]
    if missing and chunks:
        import semantic
        queries = [semantic.QUERY_PROMPT + " ".join(
            [topics[i]["topic"]] + ([rows[match[i]]["topic"]] if i in match else []))[:1500] for i in missing]
        with engine_factory() as eng:
            qs = eng.embed(queries)
        for i, q in zip(missing, qs):
            top = sorted(chunks, key=lambda c: -cos(c[1], q))[:SEARCH_K]
            vecs[i], ids[i], how[i] = mean_unit([v for _, v in top]), {k for k, _ in top}, "search"
    return vecs, ids, how


def merge(existing_text, new_pairs):
    """links.json text with new {"from","to"} pairs appended; existing links are never removed. Only
    pairs touching a topic that links.json doesn't mention yet are added, so a link deleted by hand
    between two linked topics doesn't come back on the next run (--replace recomputes everything)."""
    try:
        old = json.loads(existing_text) if existing_text else []
        old = old if isinstance(old, list) else []
    except ValueError:
        old = []
    have = {(sd.topic_key(o.get("from")), sd.topic_key(o.get("to"))) for o in old if isinstance(o, dict)}
    known = {k for pair in have for k in pair}
    added = [p for p in new_pairs if (sd.topic_key(p["from"]), sd.topic_key(p["to"])) not in have
             and not {sd.topic_key(p["from"]), sd.topic_key(p["to"])} <= known]
    return json.dumps(old + added, ensure_ascii=False, indent=2) + "\n", len(added)


def cmd_links(folder, idx, write=False, replace=False, min_sim=MIN_SIM, max_links=MAX_LINKS, engine_factory=None):
    from datetime import date
    folder = Path(folder)
    topics = sd.parse_progress(sd._read(folder / "progress.md"), date.today().isoformat())
    if len(topics) < 2:
        raise SystemExit(f"{folder.name}/progress.md has fewer than 2 topics: nothing to link.")
    if not any(Path(idx).rglob("*.json")):
        raise SystemExit(f"No search index for {folder.name}. Run: study index {folder.name}")
    if engine_factory is None:
        import semantic
        engine_factory = lambda: semantic.Engine("search")  # noqa: E731
    vecs, ids, how = topic_vectors(folder, idx, topics, engine_factory)
    links = propose(vecs, min_sim, max_links, ids)
    name = lambda i: topics[i]["topic"]  # noqa: E731
    for a, b, s in links:
        print(f"{s:.2f}  {name(a)}  →  {name(b)}")
    found = how.count("sources")
    print(f"{len(links)} link(s) for {len(topics)} topics · {found} from syllabus pages, "
          f"{how.count('search')} by searching the topic name, {how.count(None)} without material")
    pairs = [{"from": name(a), "to": name(b)} for a, b, _ in links]
    path = folder / "links.json"
    if not (write or replace):
        print("Dry run. Add --write to add links for topics not in links.json yet (keeps existing links), "
              "--replace to overwrite it.")
        return links
    text, added = (json.dumps(pairs, ensure_ascii=False, indent=2) + "\n", len(pairs)) if replace \
        else merge(sd._read(path) if path.exists() else "", pairs)
    path.write_text(text, encoding="utf-8")
    print(f"{'Wrote' if replace else 'Added'} {added} link(s) to {folder.name}/links.json")
    return links
