import assert from "node:assert/strict";
import { test } from "node:test";
import { deflateRawSync } from "node:zlib";
import { extract } from "../extract.js";

// A minimal zip: enough structure for extract.js, with real deflate so the decompression path runs.
function zip(entries) {
  const locals = [], centrals = [];
  let offset = 0;
  for (const [name, text] of Object.entries(entries)) {
    const nameBytes = Buffer.from(name), data = deflateRawSync(Buffer.from(text));
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(8, 8);
    local.writeUInt32LE(data.length, 18); local.writeUInt16LE(nameBytes.length, 26);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0); central.writeUInt16LE(8, 10); central.writeUInt32LE(data.length, 20);
    central.writeUInt16LE(nameBytes.length, 28); central.writeUInt32LE(offset, 42);
    locals.push(local, nameBytes, data);
    centrals.push(central, nameBytes);
    offset += 30 + nameBytes.length + data.length;
  }
  const directory = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(Object.keys(entries).length, 10);
  end.writeUInt32LE(directory.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, directory, end]);
}

test("pptx gives one section per slide, in slide order", async () => {
  const slide = (text) => `<p:sld><a:p><a:r><a:t>${text}</a:t></a:r></a:p></p:sld>`;
  const file = new File([zip({ "ppt/slides/slide10.xml": slide("Ten"), "ppt/slides/slide2.xml": slide("Two &amp; more"), "ppt/theme/theme1.xml": "<x/>" })], "W1.pptx");
  const sections = await extract(file);
  assert.deepEqual(sections.map((s) => [s.loc, s.text]), [["slide 2", "Two & more"], ["slide 10", "Ten"]]);
});

test("docx keeps paragraphs apart", async () => {
  const xml = '<w:body><w:p><w:r><w:t>First</w:t></w:r><w:r><w:t xml:space="preserve"> line</w:t></w:r></w:p><w:p><w:r><w:t>Second</w:t></w:r></w:p></w:body>';
  const [section] = await extract(new File([zip({ "word/document.xml": xml })], "notes.docx"));
  assert.equal(section.text, "First line\n\nSecond");
});

test("plain text works and bad files give a readable error", async () => {
  assert.equal((await extract(new File(["hello"], "n.md")))[0].text, "hello");
  await assert.rejects(extract(new File(["x"], "a.exe")), /Use a PDF/);
  await assert.rejects(extract(new File(["  "], "empty.txt")), /No text found/);
  await assert.rejects(extract(new File(["not a zip, just text that is long enough to scan"], "bad.docx")), /damaged/);
});
