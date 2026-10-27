# Study Tutor for Anna

This folder packages the study tutor as an [Anna App](https://staging.anna.partners/developers/apps/app-intro.md).
It lives only on the `anna-app` branch and is never merged into `main`. The sources are still `CLAUDE.md` and
`.claude/skills/`, and everything in `app/` is generated from them. To pick up tutor improvements from `main`,
merge `main` into `anna-app`, then run `python3 anna/build.py` and commit the regenerated `app/`.

| Source | Becomes |
|---|---|
| `CLAUDE.md` (tutor rules) | `app/executas/study-tutor/SKILL.md` |
| `.claude/skills/<x>/SKILL.md` | `app/executas/study-<x>/SKILL.md` (today, learn, review, quiz, exam, ingest, status, setup) |
| `anna/addendum.md` | `system_prompt_addendum` in `app/manifest.json` (max 4000 characters) |

The build only makes small wording changes. `~/Study` becomes `$STUDY_ROOT`, slash commands like `/learn`
become plain requests like `learn`, and `argument-hint` moves into the skill body. Each skill gets Anna's
`metadata` line.

## Build

```bash
python3 anna/build.py          # regenerate anna/app/ after editing CLAUDE.md, a skill or addendum.md
python3 anna/build.py --check  # fails if anna/app/ is out of date
```

## Try it and publish

Needs Node 22+, [uv](https://docs.astral.sh/uv/) and the Anna CLI (`npm i -g @anna-ai/cli`).

```bash
cd anna/app
anna-app validate              # manifest schema + bundled executa checks
anna-app apps publish          # publishes each skill, then the app (needs developer access)
```

`anna-app dev` runs an App's tool processes and UI. This App has neither yet, since it is skills only. To try
the skills before publishing, point a local Anna Agent at them with `MATRIX_SKILLS_DIR=anna/app/executas`.
Then `#study-tutor` it and ask for `today`.

## Limits of this first version

- **Local Anna Agent only.** The skills read and write `~/Study` (materials, `progress.md`, `mistakes.md`)
  and run `~/Study/.tools/study`, so the study system must be installed on the same machine. A Cloud Agent has
  neither, and its volume is reclaimed after ~3 days idle. Supporting it means moving the memory files to
  Anna's persistent storage (APS) and wrapping `.tools/study` as a Tool Executa (step 2).
- **Ingest needs the local converters** (`pdftotext`, `markitdown`, `ffmpeg`, `whisper-cli`), as in Claude
  Code. Run `setup` to check them.
- **The model is Anna's choice.** Rules that rely on reading original PDFs or images directly may work less
  well than in Claude Code. The `converted/` text is the reliable source.
