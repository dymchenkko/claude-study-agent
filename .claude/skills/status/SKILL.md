---
name: status
description: Show a short study dashboard - per subject progress, due reviews, weak topics, days to exam. Use when the user asks for status, progress, overview or what to study.
argument-hint: "[subject]"
---

# Status dashboard

Read `CLAUDE.md`, `syllabus.md`, `progress.md`, `mistakes.md` for the subject (or every subject folder in
`~/Study` except `_template`). Show a compact table per subject:

| Subject | Exam in | Topics started/total | Avg level | Due today | Overdue | Unfixed mistakes |

Mark paused subjects (`- **Reviews:** paused since …` in `CLAUDE.md`) as `paused` in the Due/Overdue columns and
leave them out of the totals and weak topics. Then list: top 3 weakest topics (with level), today's plan from
`~/Study/.tools/study plan` (the same 3 picks as the Plan tab in `study gui`; it may write today's plan file),
and a warning if exam is < 14 days away and readiness looks low. Don't change any other files.
