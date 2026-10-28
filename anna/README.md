# Study Tutor for Anna

This folder packages the study tutor as an [Anna App](https://staging.anna.partners/developers/apps/app-intro.md).
It lives only on the `anna-app` branch and is never merged into `main`. The skills are still generated from
`CLAUDE.md` and `.claude/skills/`, so to pick up tutor improvements from `main`, merge `main` into `anna-app`,
then run `python3 anna/build.py` and commit the regenerated `app/`.

| Source | Becomes |
|---|---|
| `CLAUDE.md` (tutor rules) + `anna/anna-rules.md` | `app/executas/study-tutor/SKILL.md` |
| `.claude/skills/<x>/SKILL.md` | `app/executas/study-<x>/SKILL.md` (today, learn, review, quiz, exam, ingest, status, setup) |
| `anna/addendum.md` | `system_prompt_addendum` in `app/manifest.json` (max 4000 characters) |
| `anna/study-tools/` | `app/executas/study-tools/` — the Tool plugin, copied without its tests |

The build only makes small wording changes to the skills. `~/Study` becomes `$STUDY_ROOT`, slash commands like
`/learn` become plain requests like `learn`, and `argument-hint` moves into the skill body. Each skill gets
Anna's `metadata` line.

## study-tools

A Tool Executa (JSON-RPC 2.0 over stdio, standard-library Python) that does the file work a model gets wrong.
Testing on Anna showed the model overwriting `progress.md` and faking a missing `.tools/study`; these tools make
both impossible.

| Tool | What it does |
|---|---|
| `study_open` | Finds the study folder (`$STUDY_ROOT`, `~/Study`, or `$ANNA_WORKSPACE_DIR/Study`), downloads it from GitHub if missing, lists subjects |
| `study_search` | Runs the real `.tools/study search`; says when semantic search is not set up so the tutor greps instead |
| `progress_update` | Changes one row of `progress.md`: `correct` / `partial` / `wrong` apply the 1 → 3 → 7 → 16 → 35 ladder, `learned` sets the teach-back level |
| `mistake_add`, `mistake_fixed` | Append to `mistakes.md`, mark rows `Fixed? ✅` |
| `session_log` | Append bullets to `sessions/<today>.md` |

```bash
python3 -m unittest discover -s anna/study-tools   # ladder, row safety, a stdio session
cd anna/app/executas/study-tools
anna-app executa dev --describe                     # needs uv; without it add
                                                    # --spec 'tool_id=tool-dev-study-tools,type=python,command=python3 study_tools.py'
```

### Releasing the binaries

`.github/workflows/study-tools-release.yml` builds `study-tools-<platform>.tar.gz` (PyInstaller `--onedir`:
`bin/study-tools`, `bin/_internal/`, `manifest.json`) for macOS arm64 / x86_64 and Linux x86_64 / aarch64, and
attaches them to a GitHub pre-release that is never marked latest. To release, on `anna-app` (never `main`):

1. Bump `version` in `anna/study-tools/executa.json`, `pyproject.toml` and `VERSION` in `study_tools.py`, and the
   tag in the `binary_urls` of `executa.json`; run `python3 anna/build.py`; commit.
2. `git push origin anna-app && git tag study-tools-v<version> && git push origin study-tools-v<version>`

`./build_binary.sh` builds the current platform locally (needs `pip install pyinstaller`).

## Build

```bash
python3 anna/build.py          # regenerate anna/app/ after editing CLAUDE.md, a skill, addendum.md or study-tools
python3 anna/build.py --check  # fails if anna/app/ is out of date
```

## Try it and publish

Needs Node 22+, [uv](https://docs.astral.sh/uv/) and the Anna CLI (`npm i -g @anna-ai/cli`).

```bash
cd anna/app
anna-app validate              # manifest schema + bundled executa checks
anna-app apps publish          # publishes each executa, then the app (needs developer access)
```

**Test in Zen Mode.** Main Soul is one long conversation per account: "New chat" keeps adding to it, and Anna
reuses the skill text it loaded earlier in it, so edits to a skill don't show up there. Switch the chat input
to **Zen Mode** to start a fresh conversation that loads the skills again.

## Limits of this version

- **study-tools is published as a private tool** (`tool-dymchenko-study-tools-maz2f4cv`, see
  `study-tools/.anna/executa.json`) from `anna-app executa publish --profile binary`, and works on a cloud
  agent. Publishing the whole App (`anna-app apps publish`) needs Verified Developer status; until then the
  skills and the tool are installed one by one in the Executa Hub.
- **Memory lives in the agent's workspace.** A Cloud Agent's volume is reclaimed after ~3 days idle; keeping
  progress safe there means mirroring `progress.md` / `mistakes.md` to Anna's persistent storage (APS).
- **Ingest needs the local converters** (`pdftotext`, `markitdown`, `ffmpeg`, `whisper-cli`), as in Claude
  Code. Run `setup` to check them.
- **The model is Anna's choice** (Gemini 3 Flash Preview by default). Rules that rely on reading original PDFs
  or images directly may work less well than in Claude Code. The `converted/` text is the reliable source.
