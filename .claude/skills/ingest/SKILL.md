---
name: ingest
description: Convert newly added lecture materials (slides, PDFs, videos, notes) to searchable text and update the subject's topic map. Use after the user adds files to materials/ or asks to add/import/process materials or a lecture video URL.
argument-hint: "<subject> [video-url]"
---

# Ingest materials

1. Resolve the subject (create it with `~/Study/.tools/study new "<Subject>"` if I ask for a new one).
2. Run `~/Study/.tools/study ingest "<Subject>"` (add `--url <URL>` for a video link).
   Video transcription runs locally and takes a few minutes per lecture — tell me before starting long ones
   and run it in the background if there are several.
3. Read the NEW converted files. If a PDF was flagged as scanned/image-based, read the original PDF directly.
4. Update `syllabus.md`: add or refine topic rows in course order with precise sources
   (`file p.x–y`, `slide n`, `[hh:mm:ss]`) and an exam-weight guess (high/med/low) based on emphasis,
   repetition across lectures and the lecturer notes in `CLAUDE.md`. Merge duplicates; don't delete rows.
5. Add new topics to `progress.md` with Level 0 and no dates.
6. Summarise: files converted, topics added, anything that failed or needs my attention, and suggest `/learn`
   on the first new topic.
