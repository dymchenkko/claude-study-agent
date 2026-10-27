---
name: study-status
description: "Show a short study dashboard - per subject progress, due reviews, weak topics, days to exam. Use when the user asks for status, progress, overview or what to study."
metadata: {"matrix": {"emoji": "📊", "execution_mode": "bash", "category_name": "education"}}
---

# Status dashboard

Arguments, from the user's message: `[subject]`

Read `CLAUDE.md`, `syllabus.md`, `progress.md`, `mistakes.md` for the subject (or every subject folder in
`$STUDY_ROOT` except `_template`). Show a compact table per subject:

| Subject | Exam in | Topics started/total | Avg level | Due today | Overdue | Unfixed mistakes |

Then list: top 3 weakest topics (with level), today's recommendation in one line (e.g. `today Biology`), and a
warning if exam is < 14 days away and readiness looks low. Don't change any files.
