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
            "Study Tutor turns Anna into a personal university tutor. It teaches topic by topic from your own "
            "course materials with citations, gives small practical tasks, remembers what you know with "
            "spaced repetition, and builds mock exams in your real exam format.\n\n"
            "Mention `#study-tutor` and say `today`, `learn <topic>`, `review`, `quiz`, `exam` or `status`. "
            "Your materials and progress stay in a folder on your computer (`~/Study`), so it runs on a "
            "local Anna Agent."),
        "category": "education",
        "homepage_url": "https://github.com/dymchenkko/claude-study-agent",
        "support_url": "https://github.com/dymchenkko/claude-study-agent/issues",
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
    if args.check:
        stale = sorted(set(files) ^ set(on_disk) | {p for p in files if on_disk.get(p) != files[p]})
        if stale:
            sys.exit("anna/app/ is out of date, run `python3 anna/build.py`:\n  " + "\n  ".join(stale))
        print(f"anna/app/ is up to date ({len(files)} files)")
        return
    shutil.rmtree(OUT, ignore_errors=True)
    for rel, content in files.items():
        (OUT / rel).parent.mkdir(parents=True, exist_ok=True)
        (OUT / rel).write_text(content)
    print(f"Wrote {len(files)} files to anna/app/")


if __name__ == "__main__":
    main()
