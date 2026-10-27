---
name: study-learn
description: "Tutor a specific topic from the course materials with short explanations and practical micro-tasks, then record progress. Use when the user wants to learn, understand or study a named topic."
metadata: {"matrix": {"emoji": "📖", "execution_mode": "bash", "category_name": "education", "requires": {"bins": ["python3"]}}}
---

# Learn a topic

Arguments, from the user's message: `<subject> <topic>`

1. Resolve subject and topic. Read the subject's `CLAUDE.md`, `progress.md`, `mistakes.md`.
   If it has a **Diagrams** entry, diagram tasks follow the Diagrams rules in the `study-tutor` skill.
2. Find the topic in my materials. Run `$STUDY_ROOT/.tools/study search <Subject> "<topic in plain words>" -k 6`
   (meaning-based, works across languages; cite the `(file loc)` it prints). Then Grep `converted/` for
   exact terms, formulas and names the search missed. Read the matching pages/slides/transcript sections.
   Open the original in `materials/` if diagrams or formulas matter. If the best scores are low (< ~0.6), the
   topic is probably not in my materials: say so before using general knowledge.
3. **Diagnose (1 question):** ask one quick question to see what I already know. Skip what I know.
4. Break the topic into 3–6 small ideas (show the list as a mini roadmap). For each idea:
   - explain in ≤ 150 words with a concrete example and citation,
   - give ONE micro-task (2–5 min): predict, fill-in, spot-the-error, tiny worked example, explain-back,
     match/sort, mini calculation — vary the type,
   - grade (✅/⚠️/❌), one-sentence feedback, adapt difficulty.
5. **Close:** ask me to explain the whole topic in 3–4 sentences (teach-back). Grade it.
6. Update memory as described in the `study-tutor` skill (progress, mistakes, session log). New topic starts at
   Level from the teach-back (❌→1, ⚠️→2, ✅→3), Interval 1, Next review tomorrow.

Stop any time I say stop — but always save memory first.
