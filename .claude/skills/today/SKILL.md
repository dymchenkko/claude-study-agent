---
name: today
description: Start a daily ~15-minute study session - due reviews first, then the next topic with micro-tasks. Use when the user says "today", "let's study", "daily session" or opens without a specific request.
argument-hint: "[subject] [minutes]"
---

# Daily session (default 15 min = 3 picks of ~5 min)

Today's plan is shared with the Plan tab of `study gui`, so both always show the same picks.

1. Run `~/Study/.tools/study plan --json` (add the subject name if I gave one, and `--minutes N` if I gave
   minutes: N / 5 picks, at least 1, at most 3). `todo` is the list of unfinished picks for this session,
   `paused` lists subjects whose reviews are paused.
2. Decide the flow:
   - **A paused subject named in the argument:** say its reviews are paused and ask whether to resume
     (replace its `- **Reviews:**` line with `- **Reviews:** resumed <today>`). Don't start until I confirm;
     if I say no, offer the picks of other subjects instead.
   - **`todo` has picks:** use the pick flow below.
   - **A subject was named and has no picks today:** run the classic flow below for that subject.
   - **No picks left (all done, or the plan is empty):** say so in one line. Offer the classic flow for the
     non-paused subject with the most overdue topics. If every subject is paused, say that and offer to resume one.
3. Show the plan in 3 lines max, one per pick: `1. PRI · Association class — 2 open mistakes (review)`.

## Pick flow (one pick at a time, in order, across subjects)

For each pick:
1. Read that pick's subject files: `CLAUDE.md`, `progress.md`, `mistakes.md`, the latest file in `sessions/`.
   If it has a **Diagrams** entry, diagram tasks follow the Diagrams rules in `~/Study/CLAUDE.md`.
2. Do the pick (~5 min), following the teaching rules:
   - `review`: up to 3 short recall questions on that topic only, unfixed mistakes first (as in /review).
   - `lesson`: start the topic as in /learn, small: one idea, one micro-task, grade, adapt.
   - `drawing`: one drawing task on that topic in draw.io (the chat answers were right, the diagram slipped).
3. Save right away, before moving on: `progress.md`, `mistakes.md`, append to `sessions/<today>.md` of that
   pick's subject, and `study log` (Event log rule in `~/Study/CLAUDE.md`). A pick counts as done when its
   topic's Last studied is today, so stopping early loses nothing.

**Finish (≈2 min, once at the end):** one exam-style question on the finished pick where I scored best.
Log it like the rest (it is a recall on that topic). End with: what improved, what's due tomorrow, and a
one-line suggestion for next time.

## Classic flow (one subject, no picks)

1. Read the subject's `CLAUDE.md`, `progress.md`, `mistakes.md` and the latest file in `sessions/`.
   If its reviews are paused, skip the warm-up.
2. Plan in 3 lines max, e.g. `Warm-up: 3 reviews · Main: <topic> · Finish: 1 exam-style question`.
3. **Warm-up (≈3 min):** up to 3 due items (Next review ≤ today), unfixed mistakes first. One question at a time.
4. **Main (≈10 min):** continue the topic from the last session log, or the next unstarted topic in
   `syllabus.md`. Follow the teaching rules in `~/Study/CLAUDE.md`: explain small → micro-task → grade → adapt.
5. **Finish (≈2 min):** one exam-style question on today's main topic.
6. Update `progress.md`, `mistakes.md`, write `sessions/<today>.md` (append if it exists) and run `study log`.
   End with: what improved, what's due tomorrow, and a one-line suggestion for next time.

If `syllabus.md` has no topics yet, tell me to run `/ingest <subject>` first (or offer to run it).
