---
name: learn
description: Tutor a specific topic from the course materials with short explanations and practical micro-tasks, then record progress. Use when the user wants to learn, understand or study a named topic.
argument-hint: "<subject> <topic>"
---

# Learn a topic

1. Resolve subject and topic. Read the subject's `CLAUDE.md`, `progress.md`, `mistakes.md`.
2. Find the topic in my materials: Grep `converted/` for key terms, read the matching pages/slides/transcript
   sections. Open the original in `materials/` if diagrams or formulas matter. Note the sources.
3. **Diagnose (1 question):** ask one quick question to see what I already know. Skip what I know.
4. Break the topic into 3–6 small ideas (show the list as a mini roadmap). For each idea:
   - explain in ≤ 150 words with a concrete example and citation,
   - give ONE micro-task (2–5 min): predict, fill-in, spot-the-error, tiny worked example, explain-back,
     match/sort, mini calculation — vary the type,
   - grade (✅/⚠️/❌), one-sentence feedback, adapt difficulty.
5. **Close:** ask me to explain the whole topic in 3–4 sentences (teach-back). Grade it.
6. Update memory as described in `~/Study/CLAUDE.md` (progress, mistakes, session log). New topic starts at
   Level from the teach-back (❌→1, ⚠️→2, ✅→3), Interval 1, Next review tomorrow.

Stop any time I say stop — but always save memory first.
