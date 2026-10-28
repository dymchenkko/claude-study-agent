#!/usr/bin/env python3
"""Build the Anna App in anna/app/ from the Claude Code sources, so there is one copy of the tutor to edit.

  CLAUDE.md               -> executas/study-tutor/SKILL.md   (the tutor rules, plus anna/anna-rules.md)
  .claude/skills/<x>/     -> executas/study-<x>/SKILL.md     (today, learn, review, quiz, ...)
  anna/addendum.md        -> manifest.json system_prompt_addendum
  anna/study-tools/       -> executas/study-tools/           (the Tool plugin, copied without its tests)

Run `python3 anna/build.py` after changing any of those, and `python3 anna/build.py --check` to verify that
anna/app/ is up to date (exits 1 if not). Standard library only.
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "anna/app"
VERSION = "0.1.0"
SLUG = "study-tutor"
REPO = "https://github.com/dymchenkko/claude-study-agent"
RAW = "https://raw.githubusercontent.com/dymchenkko/claude-study-agent/anna-app"  # served from the pushed branch
SCREENSHOTS = ["screenshot-1-today.png", "screenshot-2-review.png"]

EMOJI = {"tutor": "🎓", "today": "📅", "learn": "📖", "review": "🔁", "quiz": "❓",
         "exam": "📝", "ingest": "📥", "status": "📊", "setup": "🛠️"}
COMMANDS = "|".join(EMOJI)
# .anna/executa.json holds the published tool_id, so publishing the app reuses that tool instead of minting one.
TOOL_FILES = ["study_tools.py", "pyproject.toml", "executa.json", ".anna/executa.json"]

TUTOR_DESCRIPTION = ("Core rules of the study tutor: the study folder layout, how to teach from the user's own "
                     "course materials with citations and micro-tasks, spaced-repetition memory and exam prep. "
                     "Load first whenever the user studies, learns, reviews or prepares for an exam.")


def anna_text(text):
    """Rewrite Claude Code wording for the Anna agent; the meaning stays the same."""
    text = text.replace("`~/Study/CLAUDE.md`", "the `study-tutor` skill")
    text = text.replace("~/Study", "$STUDY_ROOT")
    # Anna's web firewall rejects uploads containing "curl … | sh" (403 Blocked); say it in two steps instead.
    text = re.sub(r"`curl (?:-\S+ )*(https://\S+) \| sh`", r"download `\1` with curl, then run it with `sh`", text)
    # Slash commands are typed in Claude Code; in Anna the user just asks ("quiz", "today Biology").
    return re.sub(rf"(?<![\w.~$/-])/({COMMANDS})\b", r"\1", text)


def split_frontmatter(text):
    _, head, body = text.split("---\n", 2)
    meta = {}
    for line in head.splitlines():
        key, _, value = line.partition(": ")
        meta[key] = value.strip().strip('"')
    return meta, body


def skill_md(name, description, body, mode, runs_study):
    matrix = {"emoji": EMOJI[name], "execution_mode": mode, "category_name": "education"}
    if runs_study:
        matrix["requires"] = {"bins": ["python3"]}
    return (f"---\nname: study-{name}\ndescription: {json.dumps(description, ensure_ascii=False)}\n"
            f"metadata: {json.dumps({'matrix': matrix}, ensure_ascii=False)}\n---\n\n{body}")


def executa_json(name, description):
    return json.dumps({"slug": f"study-{name}", "name": f"Study {name.capitalize()}", "version": VERSION,
                       "executa_type": "skill", "description": description}, indent=2, ensure_ascii=False) + "\n"


def build():
    """Return {path relative to anna/app: content}."""
    files = {}
    # The Anna-only rules go right before the layout, so the agent reads them before anything else.
    tutor = anna_text((ROOT / "CLAUDE.md").read_text())
    tutor = tutor.replace("## Layout", (ROOT / "anna/anna-rules.md").read_text() + "\n## Layout", 1)
    skills = {"tutor": (TUTOR_DESCRIPTION, tutor, "prompt")}
    for src in sorted((ROOT / ".claude/skills").glob("*/SKILL.md")):
        meta, body = split_frontmatter(src.read_text())
        body = anna_text(body)
        if meta.get("argument-hint"):
            # Keep the hint under the title: Anna has no argument field, the user says it in the message.
            title, _, rest = body.lstrip("\n").partition("\n")
            body = f"{title}\n\nArguments, from the user's message: `{meta['argument-hint']}`\n{rest}"
        skills[meta["name"]] = (meta["description"], body, "bash")

    for name, (description, body, mode) in skills.items():
        runs_study = ".tools/study" in body
        files[f"executas/study-{name}/SKILL.md"] = skill_md(name, description, body, mode, runs_study)
        files[f"executas/study-{name}/executa.json"] = executa_json(name, description)
    # The study-tools plugin is copied as is; its tests stay in anna/study-tools/.
    for name in TOOL_FILES:
        files[f"executas/study-tools/{name}"] = (ROOT / "anna/study-tools" / name).read_text()
    handles = ["study-tools"] + [f"study-{name}" for name in skills]

    addendum = (ROOT / "anna/addendum.md").read_text().strip()
    if len(addendum) > 4000:
        sys.exit(f"anna/addendum.md is {len(addendum)} characters; Anna allows 4000")
    manifest = {
        "schema": 1,
        "required_executas": [{"tool_id": f"bundled:{h}", "version": "latest"} for h in handles],
        "optional_executas": [],
        "system_prompt_addendum": addendum,
        "tags": ["education", "study", "exam-prep", "spaced-repetition"],
    }
    files["manifest.json"] = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    app = {
        "slug": SLUG,
        "name": "Study Tutor",
        "version": VERSION,
        "tagline": "A tutor that teaches from your own lecture slides, PDFs and recordings.",
        "description": (
            "Study Tutor turns Anna into a personal university tutor that teaches from course materials, not "
            "from general knowledge. It goes topic by topic with page citations, gives one small practical task "
            "at a time, grades your answers, and schedules reviews with spaced repetition "
            "(1 → 3 → 7 → 16 → 35 days).\n\n"
            "**Try it:** mention #Study Tutor and say `today`, `learn <topic>`, `review`, `quiz`, `exam` or "
            "`status`. The first time, it sets up a study folder in your agent's workspace with a demo Cell "
            "Biology course, so you can start right away.\n\n"
            "**What's inside:** nine skills (daily session, learn, review, quiz, mock exam, status and more) "
            "and the Study Tools plugin, which searches the course materials and records progress, mistakes "
            "and session notes one row at a time, so your study history is never overwritten.\n\n"
            "**Your own courses:** a course is a folder of lecture PDFs, slides, notes or recordings converted "
            "to searchable text. Today this works with a local Anna Agent and the open-source study folder; "
            "importing your own files on a cloud agent is not supported yet. On a cloud agent, files live in "
            "the agent workspace, which Anna reclaims after a few days without use.\n\n"
            "Open source (MIT): https://github.com/dymchenkko/claude-study-agent"),
        "category": "education",
        "homepage_url": f"{REPO}/tree/anna-app/anna",
        "support_url": f"{REPO}/issues",
        # Paths are relative to anna/app/; the build wipes anna/app/, so the images live in anna/listing/.
        "logo_file": "../listing/logo.png",
        "screenshots": [f"{RAW}/anna/listing/{name}" for name in SCREENSHOTS],
        "bundled_executas": {h: {"path": f"./executas/{h}"} for h in handles},
    }
    files["app.json"] = json.dumps(app, indent=2, ensure_ascii=False) + "\n"
    return files


def main():
    ap = argparse.ArgumentParser(description="Build the Anna App in anna/app/ from CLAUDE.md and .claude/skills.")
    ap.add_argument("--check", action="store_true", help="only verify anna/app/ is up to date")
    args = ap.parse_args()
    files = build()
    on_disk = {str(p.relative_to(OUT)): p.read_text() for p in OUT.rglob("*") if p.is_file()} if OUT.exists() else {}
    # `anna-app apps publish` writes the app's and each executa's minted ids to .anna/ folders; keep those across
    # rebuilds, or the next publish would mint duplicates.
    kept = {p: c for p, c in on_disk.items() if ".anna" in Path(p).parts and p not in files}
    on_disk = {p: c for p, c in on_disk.items() if p not in kept}
    if args.check:
        stale = sorted(set(files) ^ set(on_disk) | {p for p in files if on_disk.get(p) != files[p]})
        if stale:
            sys.exit("anna/app/ is out of date, run `python3 anna/build.py`:\n  " + "\n  ".join(stale))
        print(f"anna/app/ is up to date ({len(files)} files)")
        return
    shutil.rmtree(OUT, ignore_errors=True)
    for rel, content in {**files, **kept}.items():
        (OUT / rel).parent.mkdir(parents=True, exist_ok=True)
        (OUT / rel).write_text(content)
    print(f"Wrote {len(files)} files to anna/app/")


if __name__ == "__main__":
    main()
