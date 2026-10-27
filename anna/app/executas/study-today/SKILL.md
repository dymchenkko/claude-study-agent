---
name: study-today
description: "Start a daily ~15-minute study session - due reviews first, then the next topic with micro-tasks. Use when the user says \"today\", \"let's study\", \"daily session\" or opens without a specific request."
metadata: {"matrix": {"emoji": "📅", "execution_mode": "bash", "category_name": "education"}}
---

# Daily session (default 15 min)

Arguments, from the user's message: `[subject] [minutes]`

1. Pick the subject from the argument. If none: read every `$STUDY_ROOT/*/progress.md` and pick the subject with
   the most overdue reviews, or the nearest exam date (from each `CLAUDE.md`). Say which and why in one line.
2. Read the subject's `CLAUDE.md`, `progress.md`, `mistakes.md` and the latest file in `sessions/`.
   If it has a **Diagrams** entry, diagram tasks follow the Diagrams rules in the `study-tutor` skill.
3. Plan and show it in 3 lines max, e.g. `Warm-up: 3 reviews · Main: <topic> · Finish: 1 exam-style question`.
4. **Warm-up (≈3 min):** up to 3 due items (Next review ≤ today), unfixed mistakes first. One question at a time.
5. **Main (≈10 min):** continue the topic from the last session log, or the next unstarted topic in
   `syllabus.md`. Follow the teaching rules in the `study-tutor` skill: explain small → micro-task → grade → adapt.
6. **Finish (≈2 min):** one exam-style question on today's topic.
7. Update `progress.md`, `mistakes.md` and write `sessions/<today>.md` (append if it exists).
   End with: what improved, what's due tomorrow, and a one-line suggestion for next time.

If `syllabus.md` has no topics yet, tell me to run `ingest <subject>` first (or offer to run it).
