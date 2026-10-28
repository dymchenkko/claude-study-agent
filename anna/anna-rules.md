## Running on Anna
These rules come first; they fix what went wrong in testing.
- **Use the study-tools tools when you have them.** Start with `study_open` (finds or downloads the study
  folder and lists subjects). Search with `study_search` instead of running `.tools/study search`; if it says
  search is not set up, grep the `converted/` folder it names. Record results only through `progress_update`
  (outcome `correct` / `partial` / `wrong` for a recall question, `learned` with level 1–3 after a teach-back),
  `mistake_add`, `mistake_fixed` and `session_log`: they apply the review ladder and change one row at a time.
  Read files with cat as usual. If a tool returns an error, tell me and stop; don't edit the file by hand instead.
- **My own files.** When I attach course files in chat (PDF, PPTX, DOCX, MD, TXT), import each one with
  `material_add`: the subject, the attachment's download URL and its original file name. If the subject does
  not exist yet, ask me for its name and exam date and create it with `subject_new` first (then fill in its
  CLAUDE.md). Then continue the ingest skill from reading the new converted files: update `syllabus.md` and add
  the new topics with `topics_add`. Video and audio can't be imported on a cloud agent yet; say so.
- **Without those tools:** `$STUDY_ROOT` is `~/Study` on a local agent and `$ANNA_WORKSPACE_DIR/Study` on a
  cloud agent. If it does not exist, download it (there is no git on cloud agents) and say so in one line:
  `cd "$ANNA_WORKSPACE_DIR" && curl -sL https://github.com/dymchenkko/claude-study-agent/archive/refs/heads/main.tar.gz | tar xz && mv claude-study-agent-main Study`
  Before changing `progress.md` or `mistakes.md`, print it; change only the rows you touched (or append one),
  keep the header, the notes and every other row, write the whole file back, and print it again to check.
  Never write them with `echo … >` or a heredoc that replaces the file. Append to the session log.
- **Never fake anything.** Never write a stand-in for `.tools/study`, a tool or any materials. If a command
  fails or the materials are missing, show the error, say what is missing, and stop until I decide. Teaching
  from general knowledge needs my yes first.
- **Cite exact file names** as they appear under `converted/`, without the `.md` the conversion adds, e.g.
  `(Lecture1-Membrane-transport.pdf p.2)`.
- **Levels follow the skill.** In `study-learn` the Level comes from the teach-back; if I stop before it,
  record `learned` with level 1.
