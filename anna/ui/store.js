// Courses live in Anna's per-user storage (APS), so they survive the cloud workspace being reclaimed.
//   courses/index           [{id, name}]
//   courses/<id>/course     topics, mistakes, documents, stats
//   courses/<id>/text/<n>   the course text, split into rows of about 24 KB

const ROW_CHARS = 24000;

export function createStore(anna) {
  const read = async (key, fallback) => {
    const row = await anna.storage.get({ key });
    return row && row.exists !== false && row.value != null ? row.value : fallback;
  };
  const write = (key, value) => anna.storage.set({ key, value });

  return {
    listCourses: () => read("courses/index", []),

    async loadCourse(id) {
      const course = await read(`courses/${id}/course`, null);
      if (!course) return null;
      const rows = await Promise.all(Array.from({ length: course.textRows || 0 },
        (_, n) => read(`courses/${id}/text/${n}`, [])));
      return { ...course, chunks: rows.flat() };
    },

    // Progress changes after every answer; the course text does not, so it is written only when asked.
    async saveCourse(course, { text = false } = {}) {
      const { chunks, ...meta } = course;
      if (text) {
        const rows = [];
        let row = [], size = 0;
        for (const chunk of chunks) {
          if (size + chunk.text.length > ROW_CHARS && row.length) { rows.push(row); row = []; size = 0; }
          row.push(chunk);
          size += chunk.text.length;
        }
        if (row.length) rows.push(row);
        await Promise.all(rows.map((value, n) => write(`courses/${course.id}/text/${n}`, value)));
        meta.textRows = rows.length;
        course.textRows = rows.length;
      }
      await write(`courses/${course.id}/course`, meta);
      const index = await read("courses/index", []);
      const entry = { id: course.id, name: course.name };
      const at = index.findIndex((c) => c.id === course.id);
      if (at >= 0) index[at] = entry; else index.push(entry);
      await write("courses/index", index);
    },

    async deleteCourse(course) {
      const keys = [`courses/${course.id}/course`];
      for (let n = 0; n < (course.textRows || 0); n++) keys.push(`courses/${course.id}/text/${n}`);
      await Promise.all(keys.map((key) => anna.storage.delete({ key }).catch(() => {})));
      const index = await read("courses/index", []);
      await write("courses/index", index.filter((c) => c.id !== course.id));
    },
  };
}
