// Study Tutor window. The tutoring itself is AI: anna.llm.complete builds the topic map from the user's files,
// writes each lesson and recall question from the matching excerpts, grades free-text answers and writes quizzes.
// All model text reaches the page through text nodes, never innerHTML.

import { AnnaAppRuntime } from "/static/anna-apps/_sdk/latest/index.js";
import { MAX_SEGMENTS, chunkSections, cite, daysBetween, dueTopics, mergeTopics, newTopics, normalVerdict, parseJson,
  prompts, rank, schedule, segments, today, validQuestion } from "./core.js";
import { ACCEPT, extract } from "./extract.js";
import { createStore } from "./store.js";
import { DEMO } from "./demo.js";

const root = document.getElementById("root");
let anna, store;
let course = null;
let tab = "today";

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (value === true) el.setAttribute(key, "");
    else if (value !== false && value != null) el.setAttribute(key, value);
  }
  el.append(...children.flat().filter((c) => c != null));
  return el;
}

function show(...nodes) {
  root.replaceChildren(...nodes.filter(Boolean));
  root.scrollTop = 0;
}

// Models use **bold** and line breaks; show those without ever parsing their text as HTML.
function rich(text) {
  return String(text).split(/\n+/).filter(Boolean).map((line) => h("p", {},
    line.split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 ? h("strong", {}, part) : part))));
}

function loading(message) {
  return h("div", { class: "loading", role: "status" }, h("span", { class: "spinner" }), message);
}

function explainError(error) {
  const code = String(error?.code || error?.data?.code || "");
  if (/quota/i.test(code) || /quota/i.test(error?.message || "")) {
    return "Your Anna AI quota has run out. Add credits or use your own key in Anna, then try again.";
  }
  if (/permission/i.test(code)) return "Anna blocked this request. Check the app's permissions, then try again.";
  if (error instanceof SyntaxError || /JSON/.test(error?.message || "")) {
    return "The AI reply came back in the wrong format. Trying again usually fixes it.";
  }
  return error?.message || "Something went wrong. Please try again.";
}

function errorCard(error, retry, back) {
  return h("div", { class: "card error", role: "alert" },
    h("h2", {}, "That didn't work"),
    h("p", {}, explainError(error)),
    h("div", { class: "actions" },
      retry && h("button", { class: "primary", onclick: retry }, "Try again"),
      back && h("button", { onclick: back }, "Back")));
}

async function ask({ systemPrompt, maxTokens, text }) {
  const reply = await anna.llm.complete({
    systemPrompt, maxTokens, temperature: 0.3,
    messages: [{ role: "user", content: { type: "text", text } }],
  });
  return reply.content.text;
}

// One retry covers the occasional malformed reply; anything else goes to the error card.
async function askJson(prompt) {
  try {
    return parseJson(await ask(prompt));
  } catch (error) {
    if (!(error instanceof SyntaxError) && !/no JSON/.test(error.message)) throw error;
    return parseJson(await ask(prompt));
  }
}

const excerptsFor = (topic) => {
  const found = rank(course.chunks, `${topic.title} ${topic.summary}`);
  return found.length ? found : course.chunks.slice(0, 4);
};
const mistakesFor = (topic) => course.mistakes.filter((m) => m.topicId === topic.id && !m.fixed);
const saveProgress = () => store.saveCourse(course);

// ---- Home ----

async function home() {
  course = null;
  show(loading("Loading your courses…"));
  await anna.window?.set_title?.({ title: "Study Tutor" }).catch(() => {});
  let courses;
  try {
    courses = await store.listCourses();
  } catch (error) {
    return show(errorCard(error, home));
  }
  show(
    h("header", { class: "top" }, h("h1", {}, "Study Tutor")),
    h("p", { class: "lead" }, "An AI tutor that teaches from your own lecture files, grades your answers and tells you what to review each day."),
    courses.length ? h("div", { class: "list" }, courses.map((c) =>
      h("button", { class: "row", onclick: () => openCourse(c.id) }, h("strong", {}, c.name), h("span", { class: "chev" }, "›")))) : null,
    h("div", { class: "actions" },
      h("button", { class: "primary", onclick: newCourse }, "Add a course"),
      courses.some((c) => c.name === DEMO.name) ? null : h("button", { onclick: startDemo }, "Try the demo course")));
}

async function openCourse(id) {
  show(loading("Opening your course…"));
  try {
    course = await store.loadCourse(id);
    if (!course) return home();
    tab = "today";
    await anna.window?.set_title?.({ title: course.name }).catch(() => {});
    courseView();
  } catch (error) {
    show(errorCard(error, () => openCourse(id), home));
  }
}

function blankCourse(name) {
  return { id: `c${Date.now().toString(36)}`, name, created: today(), topics: [], mistakes: [], documents: [], chunks: [], stats: { answers: 0, correct: 0 } };
}

function newCourse() {
  const name = h("input", { id: "course-name", maxlength: "80", placeholder: "For example: Cell Biology" });
  const create = () => {
    if (!name.value.trim()) return name.focus();
    course = blankCourse(name.value.trim());
    addMaterial();
  };
  show(h("header", { class: "top" }, h("button", { class: "ghost", onclick: home }, "‹ Back"), h("h1", {}, "New course")),
    h("div", { class: "card" }, h("label", { for: "course-name" }, "Course name"), name,
      h("div", { class: "actions" }, h("button", { class: "primary", onclick: create }, "Continue"))));
  name.focus();
}

function startDemo() {
  course = blankCourse(DEMO.name);
  ingest(DEMO.sections, DEMO.sections.map((s) => s.doc));
}

// ---- Adding material ----

function addMaterial() {
  const back = () => (course.topics.length ? courseView() : home());
  const files = h("input", { id: "files", type: "file", accept: ACCEPT, multiple: true });
  const pasted = h("textarea", { id: "paste", rows: "7", placeholder: "Or paste lecture notes here" });
  const problem = h("p", { class: "problem", role: "alert" });
  const go = async () => {
    problem.textContent = "";
    const picked = [...files.files];
    if (!picked.length && !pasted.value.trim()) { problem.textContent = "Choose a file or paste some text first."; return; }
    show(loading("Reading your files…"));
    try {
      const sections = [];
      for (const file of picked) sections.push(...await extract(file));
      if (pasted.value.trim()) sections.push({ doc: "Pasted notes", loc: "", text: pasted.value });
      await ingest(sections, [...picked.map((f) => f.name), ...(pasted.value.trim() ? ["Pasted notes"] : [])]);
    } catch (error) {
      show(errorCard(error, addMaterial, back));
    }
  };
  show(h("header", { class: "top" }, h("button", { class: "ghost", onclick: back }, "‹ Back"), h("h1", {}, "Add material")),
    h("p", { class: "lead" }, `Add slides, PDFs or notes to ${course.name}. The AI reads them and builds your topic map.`),
    h("div", { class: "card" },
      h("label", { for: "files" }, "Files (PDF, PPTX, DOCX, TXT, MD)"), files,
      h("label", { for: "paste" }, "Text"), pasted, problem,
      h("div", { class: "actions" }, h("button", { class: "primary", onclick: go }, "Build my topic map"))));
}

async function ingest(sections, names) {
  const chunks = chunkSections(sections);
  const { parts, skipped } = segments(chunks);
  try {
    let topics = course.topics;
    for (let i = 0; i < parts.length; i++) {
      show(loading(`The AI is reading your material (part ${i + 1} of ${parts.length})…`));
      const reply = await askJson(prompts.topics(parts[i]));
      topics = mergeTopics(topics, reply.topics || []);
    }
    if (!topics.length) throw new Error("The AI found no topics to teach in this material. Try a file with more lecture content.");
    course.topics = topics;
    course.chunks = [...course.chunks, ...chunks];
    course.documents = [...new Set([...course.documents, ...names])];
    course.note = skipped ? `This material is long: topics came from ${MAX_SEGMENTS} evenly spaced parts. Lessons can still use all of it.` : "";
    show(loading("Saving your course…"));
    await store.saveCourse(course, { text: true });
    tab = "topics";
    courseView();
  } catch (error) {
    show(errorCard(error, () => ingest(sections, names), home));
  }
}

// ---- Course ----

function courseView() {
  const date = today();
  const due = dueTopics(course.topics, date);
  const fresh = newTopics(course.topics);
  const open = course.mistakes.filter((m) => !m.fixed);
  const tabs = [["today", "Today"], ["topics", "Topics"], ["quiz", "Quiz"], ["mistakes", `Mistakes${open.length ? ` (${open.length})` : ""}`]];
  const body = { today: todayTab, topics: topicsTab, quiz: quizTab, mistakes: mistakesTab }[tab](due, fresh, open);
  show(h("header", { class: "top" }, h("button", { class: "ghost", onclick: home }, "‹ Courses"), h("h1", {}, course.name)),
    h("nav", { class: "tabs" }, tabs.map(([id, label]) =>
      h("button", { class: id === tab ? "on" : "", onclick: () => { tab = id; courseView(); } }, label))),
    body);
}

function todayTab(due, fresh) {
  const mastered = course.topics.filter((t) => t.level >= 3).length;
  const { answers, correct } = course.stats;
  return h("div", {},
    h("div", { class: "stats" },
      stat(due.length, "reviews due"), stat(fresh.length, "new topics"), stat(mastered, "well known"),
      stat(answers ? `${Math.round(100 * correct / answers)}%` : "–", "correct")),
    due.length || fresh.length ? h("div", { class: "card" },
      h("h2", {}, due.length ? "Start with your reviews" : `Next: ${fresh[0].title}`),
      h("p", {}, due.length ? `${due.length} topic${due.length > 1 ? "s are" : " is"} due. Answering from memory now is what makes it stick.` : fresh[0].summary),
      h("div", { class: "actions" }, h("button", { class: "primary", onclick: () => (due.length ? recall(due[0]) : lesson(fresh[0])) }, due.length ? "Start review" : "Start lesson")))
      : h("div", { class: "card" }, h("h2", {}, "You're done for today"), h("p", {}, nextReviewText())));
}

function nextReviewText() {
  const dates = course.topics.map((t) => t.next).filter(Boolean).sort();
  return dates.length ? `Your next review is in ${daysBetween(today(), dates[0])} day(s). A quiz is a good way to keep going.` : "Add more material to get new topics.";
}

const stat = (value, label) => h("div", { class: "stat" }, h("b", {}, String(value)), h("span", {}, label));

function topicsTab() {
  const date = today();
  return h("div", {},
    course.note ? h("p", { class: "note" }, course.note) : null,
    h("div", { class: "list" }, course.topics.map((t) => h("button", { class: "row", onclick: () => (t.last ? recall(t) : lesson(t)) },
      h("span", { class: "grow" }, h("strong", {}, t.title), h("small", {}, t.summary)),
      h("span", { class: `badge ${t.next && t.next <= date ? "due" : ""}` }, t.last ? (t.next <= date ? "Due" : `Level ${t.level}`) : "New")))),
    h("p", { class: "note" }, `From: ${course.documents.join(", ")}`),
    h("div", { class: "actions" },
      h("button", { onclick: addMaterial }, "Add material"),
      h("button", { class: "danger", onclick: confirmDelete }, "Delete course")));
}

function confirmDelete() {
  show(h("div", { class: "card" }, h("h2", {}, `Delete ${course.name}?`),
    h("p", {}, "This removes the course text, your progress and your mistakes. It can't be undone."),
    h("div", { class: "actions" },
      h("button", { class: "danger", onclick: async () => {
        show(loading("Deleting…"));
        try { await store.deleteCourse(course); home(); } catch (error) { show(errorCard(error, confirmDelete, courseView)); }
      } }, "Delete"),
      h("button", { onclick: courseView }, "Cancel"))));
}

function mistakesTab(_due, _fresh, open) {
  if (!course.mistakes.length) return h("div", { class: "card" }, h("h2", {}, "No mistakes yet"), h("p", {}, "When you miss something, the AI records the misunderstanding here and aims later questions at it."));
  return h("div", { class: "list" }, [...course.mistakes].reverse().map((m) => h("div", { class: "mistake" },
    h("strong", {}, m.topic), h("p", {}, m.question), h("p", { class: "why" }, m.why),
    h("small", {}, `${m.date}${m.source ? ` · ${m.source}` : ""}${m.fixed ? " · ✅ fixed" : ""}`))));
}

// ---- Teaching ----

function sessionHeader(topic) {
  return h("header", { class: "top" }, h("button", { class: "ghost", onclick: courseView }, "‹ Back"), h("h1", {}, topic.title));
}

async function lesson(topic, simpler = false) {
  show(sessionHeader(topic), loading("Your tutor is preparing the lesson…"));
  const chunks = excerptsFor(topic);
  try {
    const reply = await askJson(prompts.lesson(topic, chunks, mistakesFor(topic), simpler));
    task(topic, chunks, reply);
  } catch (error) {
    show(sessionHeader(topic), errorCard(error, () => lesson(topic, simpler), courseView));
  }
}

async function recall(topic) {
  show(sessionHeader(topic), loading("Your tutor is writing a question…"));
  const chunks = excerptsFor(topic);
  try {
    const reply = await askJson(prompts.recall(topic, chunks, mistakesFor(topic)));
    task(topic, chunks, reply);
  } catch (error) {
    show(sessionHeader(topic), errorCard(error, () => recall(topic), courseView));
  }
}

function task(topic, chunks, reply) {
  const answer = h("textarea", { id: "answer", rows: "5", placeholder: "Your answer" });
  const problem = h("p", { class: "problem", role: "alert" });
  const submit = () => {
    if (!answer.value.trim()) { problem.textContent = "Write an answer first. A guess is fine."; return; }
    grade(topic, chunks, reply, answer.value.trim());
  };
  show(sessionHeader(topic),
    reply.explanation ? h("div", { class: "card" }, rich(reply.explanation)) : null,
    h("div", { class: "card task" }, h("h2", {}, "Your task"), rich(reply.task),
      reply.source ? h("small", {}, `Source: ${reply.source}`) : null,
      h("label", { for: "answer" }, "Answer"), answer, problem,
      h("div", { class: "actions" },
        h("button", { class: "primary", onclick: submit }, "Check my answer"),
        h("button", { onclick: () => grade(topic, chunks, reply, "I don't know") }, "I don't know"))));
  answer.focus();
}

async function grade(topic, chunks, reply, answer) {
  show(sessionHeader(topic), loading("Your tutor is reading your answer…"));
  try {
    const result = await askJson(prompts.grade(topic, reply.task, answer, chunks));
    const verdict = normalVerdict(result.verdict);
    record(topic, verdict, { question: reply.task, why: result.misconception || result.feedback, source: result.source || reply.source });
    await saveProgress();
    feedback(topic, verdict, result);
  } catch (error) {
    show(sessionHeader(topic), errorCard(error, () => grade(topic, chunks, reply, answer), courseView));
  }
}

function record(topic, verdict, { question, why, source }) {
  const at = course.topics.findIndex((t) => t.id === topic.id);
  if (at >= 0) course.topics[at] = schedule(course.topics[at], verdict, today());
  course.stats.answers += 1;
  if (verdict === "correct") {
    course.stats.correct += 1;
    course.mistakes.filter((m) => m.topicId === topic.id).forEach((m) => { m.fixed = true; });
  } else if (verdict === "wrong") {
    course.mistakes.push({ topicId: topic.id, topic: topic.title, question, why, source, date: today(), fixed: false });
  }
}

function feedback(topic, verdict, result) {
  const updated = course.topics.find((t) => t.id === topic.id) || topic;
  const label = { correct: "✅ Correct", partial: "⚠️ Partly right", wrong: "❌ Not quite" }[verdict];
  show(sessionHeader(topic),
    h("div", { class: `card verdict ${verdict}` }, h("h2", {}, label), rich(result.feedback || ""),
      result.source ? h("small", {}, `Source: ${result.source}`) : null,
      h("small", {}, `Next review of this topic: ${updated.next}`)),
    h("div", { class: "actions" },
      verdict === "correct" ? null : h("button", { class: "primary", onclick: () => lesson(topic, true) }, "Explain it more simply"),
      h("button", { class: verdict === "correct" ? "primary" : "", onclick: nextStep }, "Next")));
}

function nextStep() {
  const due = dueTopics(course.topics, today());
  const fresh = newTopics(course.topics);
  if (due.length) return recall(due[0]);
  if (fresh.length) return lesson(fresh[0]);
  tab = "today";
  courseView();
}

// ---- Quiz ----

function quizTab() {
  const studied = course.topics.filter((t) => t.last);
  const pool = studied.length ? studied : course.topics;
  return h("div", { class: "card" }, h("h2", {}, "Quiz yourself"),
    h("p", {}, `The AI writes 5 multiple-choice questions on ${studied.length ? "the topics you've studied" : "this course"}, with wrong options based on real misconceptions.`),
    h("div", { class: "actions" }, h("button", { class: "primary", onclick: () => startQuiz(pool) }, "Start quiz")));
}

async function startQuiz(pool) {
  const weakFirst = [...pool].sort((a, b) => (a.level || 0) - (b.level || 0)).slice(0, 5);
  const chunks = [...new Set(weakFirst.flatMap((t) => rank(course.chunks, `${t.title} ${t.summary}`, 3)))].slice(0, 12);
  show(loading("The AI is writing your quiz…"));
  try {
    const mistakes = course.mistakes.filter((m) => !m.fixed);
    const reply = await askJson(prompts.quiz(weakFirst, chunks.length ? chunks : course.chunks.slice(0, 6), mistakes, 5));
    const questions = (reply.questions || []).filter(validQuestion);
    if (!questions.length) throw new SyntaxError("JSON: no usable questions");
    question(questions, 0, 0);
  } catch (error) {
    show(errorCard(error, () => startQuiz(pool), courseView));
  }
}

function question(questions, at, score) {
  const q = questions[at];
  const pick = async (choice) => {
    const right = choice === q.answer;
    const topic = course.topics.find((t) => t.title === q.topic);
    if (topic) record(topic, right ? "correct" : "wrong", { question: q.question, why: q.why, source: q.source });
    const buttons = [...root.querySelectorAll(".option")];
    buttons.forEach((b, i) => {
      b.disabled = true;
      if (i === q.answer) b.classList.add("right");
      else if (i === choice) b.classList.add("wrong");
    });
    const nextScore = score + (right ? 1 : 0);
    const last = at + 1 === questions.length;
    root.append(h("div", { class: "card" }, rich(q.why || ""), q.source ? h("small", {}, `Source: ${q.source}`) : null,
      h("div", { class: "actions" }, h("button", { class: "primary", onclick: () => (last ? quizDone(nextScore, questions.length) : question(questions, at + 1, nextScore)) }, last ? "See my score" : "Next question"))));
    await saveProgress().catch((error) => root.append(errorCard(error)));
  };
  show(h("header", { class: "top" }, h("button", { class: "ghost", onclick: courseView }, "‹ Quit"), h("h1", {}, `Question ${at + 1} of ${questions.length}`)),
    h("div", { class: "card" }, rich(q.question)),
    h("div", { class: "list" }, q.options.map((option, i) => h("button", { class: "row option", onclick: () => pick(i) }, String(option)))));
}

function quizDone(score, total) {
  show(h("div", { class: "card" }, h("h2", {}, `You got ${score} of ${total}`),
    h("p", {}, score === total ? "All correct. Your review dates have moved further out." : "Your misses are in the Mistakes tab, and those topics come back for review tomorrow."),
    h("div", { class: "actions" }, h("button", { class: "primary", onclick: () => { tab = "today"; courseView(); } }, "Done"))));
}

// ---- Start ----

try {
  anna = await AnnaAppRuntime.connect();
  store = createStore(anna);
  await home();
} catch (error) {
  show(errorCard(error, () => location.reload()));
}
