---
name: review
description: Spaced-repetition review of topics that are due and past mistakes, quick active-recall questions, reschedules each topic. Use when the user asks to review, revise, repeat or do flashcards.
argument-hint: "[subject|all] [count]"
---

# Spaced-repetition review (default 8 questions)

1. Subject from argument; `all` or none → gather due rows from every `~/Study/*/progress.md`, skipping subjects
   whose `CLAUDE.md` says `- **Reviews:** paused since …`. If I name a paused subject, say it is paused and ask
   whether to resume it (resume = replace that line with `- **Reviews:** resumed <today>`); don't review it
   unless I say yes. A prompt like "Review only <topic> in <subject>, 3 questions" means exactly that: that one
   topic, 3 questions, then step 5 and 6.
2. Queue: unfixed rows in `mistakes.md` first, then topics with Next review ≤ today (most overdue first),
   then lowest Level. If nothing is due, say so and offer 3 questions on the weakest topics instead.
3. Ask ONE question at a time — short active recall (define, why, what happens if, calculate, compare).
   Vary the format; no MCQ unless the topic is about telling similar things apart.
   Before asking, find the source for the question: for a mistake, use `~/Study/.tools/study search <Subject>
   "<the misconception in plain words>" -k 3` (local model, ~2 s) and Grep `converted/` for exact terms. Cite
   what you find in the answer.
4. After my answer: ✅/⚠️/❌, the correct answer in 1–3 lines with a source citation.
5. Reschedule each topic with the ladder 1 → 3 → 7 → 16 → 35 days: ✅ → next step (Level +1, max 5),
   ⚠️ → same interval again, ❌ → 1 day (Level −1, min 1) and log it in `mistakes.md`.
   A mistake answered ✅ → mark `Fixed? ✅`.
6. Save `progress.md` / `mistakes.md` / session log, run `study log … --kind recall` once per topic (Event log
   rule in `~/Study/CLAUDE.md`), then show: `n reviewed · x correct · next due: …`.
