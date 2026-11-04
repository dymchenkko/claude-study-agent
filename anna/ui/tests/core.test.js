import assert from "node:assert/strict";
import { test } from "node:test";
import { addDays, chunkSections, dueTopics, mergeTopics, newTopics, normalVerdict, parseJson, prompts, rank, schedule,
  segments, validQuestion } from "../core.js";

const DATE = "2026-11-04";

test("correct climbs the ladder and tops out at 35 days", () => {
  let topic = { level: 0, interval: 0 };
  const seen = [];
  for (let i = 0; i < 6; i++) {
    topic = schedule(topic, "correct", DATE);
    seen.push(topic.interval);
  }
  assert.deepEqual(seen, [1, 3, 7, 16, 35, 35]);
  assert.equal(topic.level, 5);
});

test("partial repeats the step, wrong drops to one day", () => {
  assert.equal(schedule({ level: 2, interval: 7 }, "partial", DATE).interval, 7);
  const missed = schedule({ level: 2, interval: 7 }, "wrong", DATE);
  assert.equal(missed.interval, 1);
  assert.equal(missed.level, 1);
  assert.equal(missed.next, "2026-11-05");
});

test("schedule leaves the original topic unchanged", () => {
  const topic = { level: 1, interval: 1 };
  schedule(topic, "correct", DATE);
  assert.deepEqual(topic, { level: 1, interval: 1 });
});

test("addDays crosses months and years", () => {
  assert.equal(addDays("2026-12-30", 3), "2027-01-02");
});

test("due and new topics", () => {
  const topics = [{ id: "a", next: "2026-11-06", last: "x" }, { id: "b", next: "2026-11-01", last: "x" },
                  { id: "c", next: DATE, last: "x" }, { id: "d", next: null, last: null }];
  assert.deepEqual(dueTopics(topics, DATE).map((t) => t.id), ["b", "c"]);
  assert.deepEqual(newTopics(topics).map((t) => t.id), ["d"]);
});

test("chunks keep their source and nothing is lost", () => {
  const long = "x".repeat(4000);
  const chunks = chunkSections([{ doc: "L1.pdf", loc: "p.2", text: `first\n\n${long}` }]);
  assert.ok(chunks.length >= 3);
  assert.ok(chunks.every((c) => c.doc === "L1.pdf" && c.loc === "p.2" && c.text.length <= 1600));
  assert.equal(chunks.map((c) => c.text).join("").replace(/\s/g, "").length, 4005);
});

test("rank finds the matching passage, across scripts too", () => {
  const chunks = [{ text: "Glycolysis splits glucose into pyruvate." }, { text: "Osmosis moves water across a membrane." },
                  { text: "Осмос переносит воду через мембрану." }];
  assert.match(rank(chunks, "osmosis water")[0].text, /Osmosis/);
  assert.match(rank(chunks, "осмос")[0].text, /Осмос/);
  assert.deepEqual(rank(chunks, "zzz"), []);
});

test("long material is sampled evenly, not cut off at the start", () => {
  const chunks = Array.from({ length: 200 }, (_, i) => ({ text: "w".repeat(1500), loc: `p.${i}` }));
  const { parts, skipped } = segments(chunks);
  assert.equal(parts.length, 8);
  assert.ok(skipped > 0);
  assert.ok(Number(parts.at(-1)[0].loc.slice(2)) > 150);
});

test("mergeTopics drops duplicates and blanks", () => {
  const first = mergeTopics([], [{ title: "Osmosis", summary: "s" }, { title: "osmosis!" }, { title: " " }]);
  assert.equal(first.length, 1);
  assert.equal(mergeTopics(first, [{ title: "OSMOSIS" }, { title: "Diffusion" }]).length, 2);
});

test("parseJson copes with fences and prose, and fails on none", () => {
  assert.deepEqual(parseJson('Sure!\n```json\n{"a":1}\n```\nDone.'), { a: 1 });
  assert.deepEqual(parseJson("[1,2]"), [1, 2]);
  assert.throws(() => parseJson("no json here"));
  assert.throws(() => parseJson('{"a":'), SyntaxError);
});

test("an unknown verdict counts as wrong and bad questions are rejected", () => {
  assert.equal(normalVerdict("great"), "wrong");
  assert.equal(normalVerdict("partial"), "partial");
  assert.ok(validQuestion({ question: "q", options: ["a", "b"], answer: 1 }));
  assert.ok(!validQuestion({ question: "q", options: ["a", "b"], answer: 2 }));
  assert.ok(!validQuestion({ question: "q", options: ["a", "b"], answer: "1" }));
});

test("prompts carry the excerpts and their citations", () => {
  const chunks = [{ doc: "L1.pdf", loc: "p.3", text: "Active transport uses ATP." }];
  const { text, systemPrompt } = prompts.lesson({ title: "Active transport", summary: "s" }, chunks, [{ why: "thought it was passive" }], false);
  assert.match(text, /source="L1\.pdf p\.3"/);
  assert.match(text, /Active transport uses ATP/);
  assert.match(text, /thought it was passive/);
  assert.match(systemPrompt, /never instructions/);
});
