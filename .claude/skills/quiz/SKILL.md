---
name: quiz
description: Generate a multiple-choice or practice quiz from the course materials, in chat or as a self-grading HTML file, and record results. Use when the user asks for a quiz, test, MCQ, practice questions or problems.
argument-hint: "<subject> [topic|weak|all] [n] [html]"
---

# Quiz (default 10 questions, in chat)

1. Resolve subject and scope: a topic, `weak` (Level ≤ 2 + unfixed mistakes), or `all` (weighted by exam weight).
   Read `CLAUDE.md` for the exam's question style and mirror it.
2. Build questions **only from my materials**: find sources with `~/Study/.tools/study search <Subject> "<topic>" -k 6`
   and Grep `converted/` for exact terms, then read the sources. Mix:
   ~70 % MCQ (4 options, one correct, distractors from real misconceptions and `mistakes.md`, no "all of the above"),
   ~30 % short practice problems / short answer. Each question stores its source citation.
3. **Chat mode (default):** show questions in blocks of 5; I answer compactly like `1b 2d 3a …` or text.
   Then grade all, show score, and for each miss: correct answer, why my option is tempting but wrong, source.
4. **HTML mode (`html`):** write `exams/quizzes/<date>-<topic>.html` — a single self-contained file (no external
   resources) with the questions, instant feedback per question, explanations + sources, a score, and a
   "Copy results" button producing text like `QUIZ RESULTS <topic>: 1✅ 2❌(chose b) …`. Open it with
   `open <file>`. When I paste the results back, grade-log them as below.
5. Update memory: each question counts as a recall for its topic (reschedule per the ladder in
   `~/Study/CLAUDE.md`), log misses in `mistakes.md`, append a line to the session log.
