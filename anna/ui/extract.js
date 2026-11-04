// Turn a file the user picked into sections of text with a page or slide label. Runs in the window, so course
// files are read locally; only the excerpts a lesson needs are sent to the model.

const decoder = new TextDecoder();

// A .pptx or .docx is a zip of XML. DecompressionStream reads it, so the bundle needs no zip library.
async function unzip(buffer, wanted) {
  const view = new DataView(buffer);
  let end = buffer.byteLength - 22;
  while (end >= 0 && view.getUint32(end, true) !== 0x06054b50) end--;
  if (end < 0) throw new Error("This file is damaged or is not a real Office file.");
  const count = view.getUint16(end + 10, true);
  let at = view.getUint32(end + 16, true);
  const files = {};
  for (let i = 0; i < count; i++) {
    const method = view.getUint16(at + 10, true);
    const size = view.getUint32(at + 20, true);
    const nameLength = view.getUint16(at + 28, true);
    const extraLength = view.getUint16(at + 30, true);
    const commentLength = view.getUint16(at + 32, true);
    const offset = view.getUint32(at + 42, true);
    const name = decoder.decode(new Uint8Array(buffer, at + 46, nameLength));
    if (wanted(name)) {
      const start = offset + 30 + view.getUint16(offset + 26, true) + view.getUint16(offset + 28, true);
      const data = new Uint8Array(buffer, start, size);
      files[name] = method === 0 ? decoder.decode(data) : await inflate(data);
    }
    at += 46 + nameLength + extraLength + commentLength;
  }
  return files;
}

async function inflate(data) {
  const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Response(stream).text();
}

const unescapeXml = (text) => text.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"')
  .replace(/&apos;/g, "'").replace(/&amp;/g, "&");

function paragraphs(xml, paragraphTag, textTag) {
  const texts = new RegExp(`<${textTag}(?: [^>]*)?>([^<]*)</${textTag}>`, "g");
  return xml.split(`</${paragraphTag}>`)
    .map((p) => unescapeXml([...p.matchAll(texts)].map((m) => m[1]).join("")).trim())
    .filter(Boolean).join("\n\n");
}

async function pptx(file) {
  const files = await unzip(await file.arrayBuffer(), (name) => /^ppt\/slides\/slide\d+\.xml$/.test(name));
  const number = (name) => Number(name.match(/(\d+)\.xml$/)[1]);
  return Object.keys(files).sort((a, b) => number(a) - number(b)).map((name) => (
    { doc: file.name, loc: `slide ${number(name)}`, text: paragraphs(files[name], "a:p", "a:t") }));
}

async function docx(file) {
  const files = await unzip(await file.arrayBuffer(), (name) => name === "word/document.xml");
  if (!files["word/document.xml"]) throw new Error("This Word file has no document text.");
  return [{ doc: file.name, loc: "", text: paragraphs(files["word/document.xml"], "w:p", "w:t") }];
}

async function pdf(file) {
  const pdfjs = await import("./vendor/pdf.min.js");
  pdfjs.GlobalWorkerOptions.workerSrc = new URL("./vendor/pdf.worker.min.js", import.meta.url).href;
  const loading = pdfjs.getDocument({ data: await file.arrayBuffer(), isEvalSupported: false });
  const document = await loading.promise;
  const sections = [];
  for (let n = 1; n <= document.numPages; n++) {
    const page = await document.getPage(n);
    const { items } = await page.getTextContent();
    const text = items.map((item) => item.str + (item.hasEOL ? "\n" : " ")).join("");
    sections.push({ doc: file.name, loc: `p.${n}`, text });
  }
  await loading.destroy();
  return sections;
}

export const ACCEPT = ".pdf,.pptx,.docx,.txt,.md";

export async function extract(file) {
  const name = file.name.toLowerCase();
  let sections;
  if (name.endsWith(".pdf")) sections = await pdf(file);
  else if (name.endsWith(".pptx")) sections = await pptx(file);
  else if (name.endsWith(".docx")) sections = await docx(file);
  else if (name.endsWith(".txt") || name.endsWith(".md")) sections = [{ doc: file.name, loc: "", text: await file.text() }];
  else throw new Error("Use a PDF, PPTX, DOCX, TXT or MD file.");
  sections = sections.filter((s) => s.text.trim());
  if (!sections.length) {
    throw new Error(`No text found in ${file.name}. Scanned pages have no text layer, so paste the text instead.`);
  }
  return sections;
}
