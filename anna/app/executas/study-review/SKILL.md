---
name: study-review
description: "Spaced-repetition review of topics that are due and past mistakes, quick active-recall questions, reschedules each topic. Use when the user asks to review, revise, repeat or do flashcards."
metadata: {"matrix": {"emoji": "🔁", "execution_mode": "bash", "category_name": "education", "requires": {"bins": ["python3"]}}}
---

# Spaced-repetition review (default 8 questions)

Arguments, from the user's message: `[subject|all] [count]`

1. Subject from argument; `all` or none → gather due rows from every `$STUDY_ROOT/*/progress.md`.
2. Queue: unfixed rows in `mistakes.md` first, then topics with Next review ≤ today (most overdue first),
   then lowest Level. If nothing is due, say so and offer 3 questions on the weakest topics instead.
3. Ask ONE question at a time — short active recall (define, why, what happens if, calculate, compare).
   Vary the format; no MCQ unless the topic is about telling similar things apart.
   Before asking, find the source for the question: for a mistake, use `$STUDY_ROOT/.tools/study search <Subject>
   "<the misconception in plain words>" -k 3` (local model, ~2 s) and Grep `converted/` for exact terms. Cite
   what you find in the answer.
4. After my answer: ✅/⚠️/❌, the correct answer in 1–3 lines with a source citation.
5. Reschedule each topic with the ladder 1 → 3 → 7 → 16 → 35 days: ✅ → next step (Level +1, max 5),
   ⚠️ → same interval again, ❌ → 1 day (Level −1, min 1) and log it in `mistakes.md`.
   A mistake answered ✅ → mark `Fixed? ✅`.
6. Save `progress.md` / `mistakes.md` / session log, then show: `n reviewed · x correct · next due: …`.
