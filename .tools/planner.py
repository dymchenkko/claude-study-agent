"""Today's plan: at most three 5-minute picks across subjects. One source of truth for `study gui`
(Plan) and `/today` (through `study plan --json`), so the two never disagree.

score = weight x urgency x hub x (mistakes + weakness + overdue + slip)
  weight   per topic, syllabus Exam weight: high 3, med 2, low 1, blank 2
  hub      1 + 0.1 per topic that builds on it (links.json), max 1.5: a gap there hurts more
  urgency  per subject: no exam 0.25, unknown 1, > 45 days 1, 15-45 days 1.5, <= 14 days 2
  mistakes 2 x open mistakes, max 6 · weakness 5 - level · overdue min(days, 14) / 14 x 4 · slip 3

Two slots go to the best reviews, the third to the next new topic (a lesson), at most 2 picks per
subject.

Links (links.json, "from is needed before to") change two things:
  root cause  a struggling review (level <= 2 or open mistakes) whose prerequisite, direct or further
              back, is weaker (lower level, or the same level with open mistakes of its own) becomes a
              review of that prerequisite ("Fix X first: Y builds on it"), or a lesson when the
              prerequisite was never studied. Same score as the original. Links are only similarity,
              so an equally shaky prerequisite is not enough to push the topic's own review aside.
  lessons     the next new topic is the first whose prerequisites are all solid (level >= 3); when
              none is, the first new topic in course order, as without links.
Picks are saved per date in .tools/today-plan.json so the list stays stable for the day.
"""

import json
from collections import Counter
from pathlib import Path

import studydata as sd

SLOTS, PER_SUBJECT, MINUTES = 3, 2, 5


def urgency(exam):
    if exam["state"] == "none":
        return 0.25
    if exam["state"] == "date":
        return 2 if exam["days"] <= 14 else 1.5 if exam["days"] <= 45 else 1
    return 1


def subject_state(root, name, today):
    """Everything the planner needs about one subject, read from its files."""
    folder = Path(root) / name
    claude = sd._read(folder / "CLAUDE.md")
    reviews = sd.parse_reviews(claude)
    topics = sd.parse_progress(sd._read(folder / "progress.md"), today, reviews["resumed"])
    mistakes = sd.parse_mistakes(sd._read(folder / "mistakes.md"))
    syllabus = sd.parse_syllabus(sd._read(folder / "syllabus.md"))
    events, _ = sd.read_events(folder)
    slipping = sd.slips(events)
    edges, _ = sd.read_links(folder, topics)
    for i, t in enumerate(topics):
        t["needs"] = [a for a, b in edges if b == i]
        t["unlocks"] = sum(1 for a, _ in edges if a == i)
        t["weight"] = sd.topic_weight(t["topic"], syllabus)
        t["open"] = sum(1 for m in mistakes if not m["fixed"] and sd.same_topic(m["topic"], t["topic"]))
        t["slip"] = sd.topic_key(t["topic"]) in slipping
        t["started"] = t["level"] > 0 or bool(t["last"])
    return {"name": name, "exam": sd.parse_exam(claude, today), "reviews": reviews,
            "diagrams": sd.has_diagrams(claude), "lastSession": sd.last_session(folder), "topics": topics}


def score(t, urg):
    """(score, the largest term's name)."""
    terms = {"mistakes": min(2 * t["open"], 6), "slip": 3 if t["slip"] else 0,
             "overdue": min(t["overdue"] or 0, 14) / 14 * 4 if t["overdue"] is not None else 0,
             "weakness": max(5 - t["level"], 0)}
    top = max(terms, key=lambda k: terms[k])  # ties keep this order: mistakes, slip, overdue, weakness
    hub = 1 + 0.1 * min(t.get("unlocks", 0), 5)
    return t["weight"] * urg * hub * sum(terms.values()), top


def reason(t, top):
    if top == "mistakes":
        return f"{t['open']} open mistake{'s' if t['open'] != 1 else ''}"
    if top == "slip":
        return "Right in chat, wrong on your diagram"
    if top == "overdue":
        return "Due today" if not t["overdue"] else f"{t['overdue']} day{'s' if t['overdue'] != 1 else ''} overdue"
    return f"Still shaky (level {t['level']})"


def prompt(kind, subject, topic, builds=None):
    # Plain language, so it doesn't depend on slash commands working through `claude -p`.
    text = {"review": f"Review only {topic} in {subject}, 3 questions, following the review rules",
            "lesson": f"Learn {topic} in {subject}",
            "drawing": f"Give me a drawing task on {topic} in {subject}"}[kind]
    return text + (f". {builds} builds on it, so I'm shaky there because of this" if builds else "")


def _pick(state, t, kind, why, value, builds=None):
    return {"subject": state["name"], "topic": t["topic"], "kind": kind, "reason": why,
            "score": round(value, 1), "prompt": prompt(kind, state["name"], t["topic"], builds)}


def struggling(t):
    return t["level"] <= 2 or t["open"] > 0


def root_cause(topics, t):
    """The prerequisite to fix before `t`, or None. Walks needs back through links.json: a studied one
    that is shaky (level <= 2 or open mistakes) and weaker than `t` (lower level, or the same level with
    open mistakes) wins, the weakest first, then the most open mistakes, then course order. Only when
    there is none, the earliest never-studied one."""
    seen, stack = set(), list(t.get("needs", ()))
    while stack:
        i = stack.pop()
        if i not in seen:
            seen.add(i)
            stack.extend(topics[i].get("needs", ()))
    pre = [topics[i] for i in sorted(seen)]
    shaky = [p for p in pre if p["started"] and struggling(p)
             and (p["level"] < t["level"] or (p["level"] == t["level"] and p["open"] > 0))]
    if shaky:
        return min(shaky, key=lambda p: (p["level"], -p["open"]))
    return next((p for p in pre if not p["started"]), None)


def ready(topics, t):
    """Every prerequisite of a new topic is solid (level >= 3)."""
    return all(topics[i]["started"] and topics[i]["level"] >= 3 for i in t.get("needs", ()))


def lesson_order(states):
    """Future exam date first (soonest first), then unknown / unset / past, then no exam. Ties: the
    oldest last session (never = oldest), then name, so lessons spread across subjects."""
    group = {"date": 0, "none": 2}
    return sorted(states, key=lambda s: (group.get(s["exam"]["state"], 1), s["exam"]["days"] or 0,
                                         s["lastSession"] or "", s["name"]))


def build_picks(states, slots=SLOTS, taken=()):
    """Pick up to `slots` topics. `taken` = (subject, topic) pairs already in today's plan."""
    active = [s for s in states if not s["reviews"]["paused"]]
    count = Counter(subj for subj, _ in taken)
    used = {(subj, sd.topic_key(top)) for subj, top in taken}
    picks = []

    def free(s, t):
        return count[s["name"]] < PER_SUBJECT and (s["name"], sd.topic_key(t["topic"])) not in used

    def add(s, t, kind, why, value, builds=None):
        picks.append(_pick(s, t, kind, why, value, builds))
        count[s["name"]] += 1
        used.add((s["name"], sd.topic_key(t["topic"])))

    reviews = []
    for s in active:
        urg = urgency(s["exam"])
        for t in s["topics"]:
            if t["started"] and (t["overdue"] is not None or t["open"]):
                value, top = score(t, urg)
                kind = "drawing" if t["slip"] and s["diagrams"] else "review"
                root = root_cause(s["topics"], t) if struggling(t) else None
                if root:
                    verb, kind = ("Fix", "review") if root["started"] else ("Learn", "lesson")
                    reviews.append((value, s, root, kind, f"{verb} {root['topic']} first: {t['topic']} builds on it",
                                    t["topic"]))
                else:
                    reviews.append((value, s, t, kind, reason(t, top), None))
    best = {}  # one entry per topic: the highest score, and the root-cause reason when there is one
    for r in reviews:
        key = (r[1]["name"], sd.topic_key(r[2]["topic"]))
        old = best.get(key)
        if old is None:
            best[key] = r
        else:
            why = r if r[5] and not old[5] else old if old[5] else r
            best[key] = (max(r[0], old[0]),) + why[1:]
    reviews = sorted(best.values(), key=lambda r: (-r[0], r[1]["name"], r[2]["topic"]))

    def take_reviews(limit):
        for value, s, t, kind, why, builds in reviews:
            if len(picks) >= limit:
                return
            if free(s, t):
                add(s, t, kind, why, value, builds)

    take_reviews(min(2, slots))
    order = lesson_order(active)
    while len(picks) < slots:
        added = False
        for s in order:
            if len(picks) >= slots:
                break
            new = [t for t in s["topics"] if not t["started"] and free(s, t)]
            nxt = next((t for t in new if ready(s["topics"], t)), new[0] if new else None)
            if nxt and count[s["name"]] < PER_SUBJECT:
                add(s, nxt, "lesson", "Next new topic", 0)
                added = True
        if not added:
            break
    take_reviews(slots)  # no new topics left anywhere: more reviews fill the slots
    return picks


# ---------- today's plan, saved per date ----------

def _plan_path(root):
    return Path(root) / ".tools" / "today-plan.json"


def _load(root, today):
    try:
        data = json.loads(_plan_path(root).read_text(encoding="utf-8"))
        if data.get("date") == today and isinstance(data.get("picks"), list) and all(
                isinstance(p, dict) and {"subject", "topic", "kind", "prompt"} <= p.keys() for p in data["picks"]):
            return data["picks"]
    except (OSError, ValueError, AttributeError):
        pass
    return None  # missing, from another day, or malformed: rebuild


def _save(root, today, picks):
    path = _plan_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    keep = [{k: p[k] for k in ("subject", "topic", "kind", "reason", "score", "prompt")} for p in picks]
    path.write_text(json.dumps({"date": today, "picks": keep}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def today_plan(root, today, rebuild=False, states=None):
    """{date, picks, minutes}. A pick is done when its topic's Last studied is today. Rebuilding
    (after a pause, resume or exam date) keeps finished picks and refills the rest."""
    states = states if states is not None else [subject_state(root, n, today) for n in sd.subject_names(root)]
    by_name = {s["name"]: s for s in states}

    def done(p):
        s = by_name.get(p["subject"])
        t = s and next((t for t in s["topics"] if sd.topic_key(t["topic"]) == sd.topic_key(p["topic"])), None)
        return bool(t and t["last"] == today)

    picks = None if rebuild else _load(root, today)
    if picks is not None and any(p["subject"] not in by_name for p in picks):
        picks = None
    if picks is None:
        old = _load(root, today) or []
        kept = [p for p in old if p["subject"] in by_name and done(p)]
        picks = kept + build_picks(states, SLOTS - len(kept), [(p["subject"], p["topic"]) for p in kept])
        _save(root, today, picks)
    picks = [dict(p, done=done(p), minutes=MINUTES) for p in picks]
    return {"date": today, "picks": picks, "minutes": MINUTES * len(picks)}


def for_session(plan, subject=None, minutes=None):
    """The unfinished picks `/today` works through: one subject's only, and minutes / 5 of them
    (at least 1, at most 3) when minutes are given."""
    todo = [p for p in plan["picks"] if not p["done"] and (not subject or p["subject"].lower() == subject.lower())]
    if minutes:
        todo = todo[:max(1, min(SLOTS, minutes // MINUTES))]
    return todo
