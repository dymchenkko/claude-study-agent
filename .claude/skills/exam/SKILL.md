---
name: exam
description: Run a realistic mock exam matching the real exam format, grade it, and produce a weak-spot report and revision plan. Use when the user wants a mock exam, practice exam, exam simulation or exam readiness check.
argument-hint: "<subject> [minutes] [html]"
---

# Mock exam

1. Read the subject's `CLAUDE.md` (exam format, date, emphasis), `syllabus.md`, `progress.md`, `mistakes.md`.
   If the format is unknown, ask once (or default: 20 MCQ + 3 open problems, 60 min).
2. Build the exam from my materials, cumulative across the syllabus, weighted by exam weight and emphasis,
   with ~25 % targeted at weak topics and past mistakes. For each syllabus topic, find its sources with
   `~/Study/.tools/study search <Subject> "<topic>" -k 6` (local model, ~10 s per call; batch the topics into
   one message rather than many calls), then Grep `converted/` for exact formulas and names. Cite every answer.
   Use the search results for the coverage check too: a topic with only low scores (< ~0.6) is thin in the
   materials, so say so in the answer key rather than inventing material. Mix difficulty like a real exam. Keep an answer key
   with sources. Save it to `exams/mock-exams/<date>.md` (key in a section at the bottom).
3. Run it: show all questions (or write an HTML version if `html`), state the time limit, start time
   (`date`), and say "answer when ready". No hints during the exam.
4. Grade: per-question marks, total and %, time used. For open problems give partial credit with a rubric.
5. **Report:** readiness verdict (Not ready / Borderline / Ready), score by topic, top 3 weak spots with the
   misconception behind each, and a concrete revision plan until the exam date (which /learn and /review to
   run on which days). Save the report into the same file.
6. Update `progress.md`, `mistakes.md` and the session log.
