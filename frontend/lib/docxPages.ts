/**
 * Real pages in the preview, where Word starts them.
 *
 * docx-preview only starts a page at an explicit break: a section, a manual
 * page break, or a *style* with "page break before". Word also starts one when
 * a paragraph itself says "page break before" (a common way to open a chapter
 * or a cover's next page), and whenever the text runs past the bottom of the
 * page. Without those, a whole document came out as one page many pages tall:
 * the cover ran straight into the next page's tables, and nothing looked like
 * the document. Two steps fix it, around the render:
 *
 * - ``prepareDocx`` (before): puts a page break in front of every paragraph
 *   that asks for one, so docx-preview itself starts the page — with the
 *   right header and footer — and marks table header rows Word repeats.
 * - ``paginate`` (after): splits every page whose content overflows the text
 *   area, moving whole paragraphs and table rows to new pages, keeping a
 *   heading with what follows it and repeating a table's header rows.
 *
 * Only the preview changes; templates, downloads and generated documents are
 * the files exactly as built.
 */

const W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
// Bookmark names docx-preview renders as <span id="…">: how the marks survive it.
const BREAK = "_dfPageBreak";
const HEADER_ROW = "_dfHeaderRow";

function kid(el: Element | null | undefined, name: string): Element | null {
  if (!el) return null;
  for (const c of el.children) if (c.namespaceURI === W && c.localName === name) return c;
  return null;
}

/** An OOXML on/off property: on when present, unless its val says off. */
function isOn(el: Element | null): boolean {
  if (!el) return false;
  const v = el.getAttributeNS(W, "val");
  return v === null || v === "" || !["0", "false", "off"].includes(v.toLowerCase());
}

function bookmark(xml: XMLDocument, id: number, name: string): Element {
  const bm = xml.createElementNS(W, "w:bookmarkStart");
  bm.setAttributeNS(W, "w:id", String(id));
  bm.setAttributeNS(W, "w:name", name);
  return bm;
}

/** Paragraph styles whose own or inherited properties start a new page. */
function stylesWithPageBreak(styles: XMLDocument | null): {
  breaking: Set<string>;
  defaultId: string;
} {
  const breaking = new Set<string>();
  let defaultId = "";
  if (!styles) return { breaking, defaultId };
  const byId = new Map<string, Element>();
  for (const s of styles.getElementsByTagNameNS(W, "style")) {
    if (s.getAttributeNS(W, "type") !== "paragraph") continue;
    const id = s.getAttributeNS(W, "styleId") || "";
    byId.set(id, s);
    const isDefault = (s.getAttributeNS(W, "default") || "").toLowerCase();
    if (["1", "true", "on"].includes(isDefault)) defaultId = id;
  }
  const memo = new Map<string, boolean>();
  const breaks = (id: string, depth: number): boolean => {
    if (memo.has(id)) return memo.get(id)!;
    const s = byId.get(id);
    let value = false;
    if (s && depth < 20) {
      const own = kid(kid(s, "pPr"), "pageBreakBefore");
      const base = kid(s, "basedOn")?.getAttributeNS(W, "val");
      value = own ? isOn(own) : base ? breaks(base, depth + 1) : false;
    }
    memo.set(id, value);
    return value;
  };
  for (const id of byId.keys()) if (breaks(id, 0)) breaking.add(id);
  return { breaking, defaultId };
}

/** Body paragraphs, including those in a block content control (a contents list). */
function bodyParagraphs(body: Element): Element[] {
  const out: Element[] = [];
  for (const c of body.children) {
    if (c.namespaceURI !== W) continue;
    if (c.localName === "p") out.push(c);
    else if (c.localName === "sdt") {
      for (const p of kid(c, "sdtContent")?.children || []) {
        if (p.namespaceURI === W && p.localName === "p") out.push(p);
      }
    }
  }
  return out;
}

/** Mark where pages start and which table rows repeat, for the renderer. */
export async function prepareDocx(buf: ArrayBuffer): Promise<ArrayBuffer> {
  try {
    const { default: JSZip } = await import("jszip");
    const zip = await JSZip.loadAsync(buf);
    const docFile = zip.file("word/document.xml");
    if (!docFile) return buf;
    const parser = new DOMParser();
    const xml = parser.parseFromString(await docFile.async("string"), "application/xml");
    if (xml.getElementsByTagName("parsererror").length) return buf;
    const stylesFile = zip.file("word/styles.xml");
    const styles = stylesFile
      ? parser.parseFromString(await stylesFile.async("string"), "application/xml")
      : null;
    const { breaking, defaultId } = stylesWithPageBreak(styles);
    const body = xml.getElementsByTagNameNS(W, "body")[0];
    if (!body) return buf;

    let n = 0;
    const firstBlock = [...body.children].find((c) => c.namespaceURI === W);
    for (const p of bodyParagraphs(body)) {
      const pPr = kid(p, "pPr");
      if (!isOn(kid(pPr, "pageBreakBefore"))) continue;
      // docx-preview already breaks for a style that asks for it.
      const style = kid(pPr, "pStyle")?.getAttributeNS(W, "val") || defaultId;
      if (breaking.has(style)) continue;
      if (p === firstBlock || p.parentElement?.parentElement === firstBlock) continue;
      // The break goes in a paragraph of its own just before, so the page
      // starts at this one; the mark lets ``paginate`` remove that paragraph.
      const holder = xml.createElementNS(W, "w:p");
      const run = xml.createElementNS(W, "w:r");
      const br = xml.createElementNS(W, "w:br");
      br.setAttributeNS(W, "w:type", "page");
      run.append(br);
      holder.append(bookmark(xml, 990000 + n, `${BREAK}${n}`), run);
      p.parentNode!.insertBefore(holder, p);
      n++;
    }

    let rows = 0;
    for (const tr of xml.getElementsByTagNameNS(W, "tr")) {
      if (!isOn(kid(kid(tr, "trPr"), "tblHeader"))) continue;
      const p = tr.getElementsByTagNameNS(W, "p")[0];
      if (!p) continue;
      const mark = bookmark(xml, 995000 + rows, `${HEADER_ROW}${rows}`);
      const pPr = kid(p, "pPr");
      if (pPr) pPr.after(mark);
      else p.prepend(mark);
      rows++;
    }

    if (!n && !rows) return buf;
    zip.file("word/document.xml", new XMLSerializer().serializeToString(xml));
    return await zip.generateAsync({ type: "arraybuffer" });
  } catch {
    return buf; // a preview with fewer page breaks beats no preview
  }
}

// Paragraphs Word keeps on the same page as the next one: headings, titles and
// the captions written above tables.
const KEEP_WITH_NEXT = /\bdocx_[a-z0-9]*(heading|title|head)[a-z0-9]*\b|\bdocx_tablecaption\b/i;

function keepsWithNext(el: HTMLElement): boolean {
  return el.tagName === "P" && KEEP_WITH_NEXT.test(el.className) && !!(el.textContent || "").trim();
}

function px(v: string): number {
  return parseFloat(v) || 0;
}

/**
 * On-screen size of one CSS pixel of the page. Positions are measured on
 * screen, lengths are read from styles; an ancestor's zoom (the app draws
 * everything at 93%) scales the first but not the second.
 */
function screenScale(page: HTMLElement): number {
  const css = px(getComputedStyle(page).width);
  const shown = page.getBoundingClientRect().width;
  return css > 0 && shown > 0 ? shown / css : 1;
}

/** On-screen height the page leaves for its text, between the margins, header and footer. */
function textArea(page: HTMLElement, scale: number): number {
  const cs = getComputedStyle(page);
  let room = (px(cs.minHeight) - px(cs.paddingTop) - px(cs.paddingBottom)) * scale;
  for (const el of page.children) {
    if (el.tagName === "ARTICLE") continue;
    const s = getComputedStyle(el);
    if (s.position === "absolute") continue;
    room -= (el as HTMLElement).getBoundingClientRect().height + (px(s.marginTop) + px(s.marginBottom)) * scale;
  }
  return room;
}

/** One block, or some rows of a table, on a page. */
interface Piece {
  el: HTMLElement;
  rows?: [number, number]; // a table's rows from..to (exclusive)
  all?: HTMLTableRowElement[]; // the table's rows as rendered, before any moved
  nHead?: number; // leading rows Word repeats on every page
}

function measure(el: HTMLElement, scale: number) {
  const r = el.getBoundingClientRect();
  return { top: r.top - px(getComputedStyle(el).marginTop) * scale, bottom: r.bottom };
}

/** Split one rendered page into as many pages as its content needs. */
function splitPage(page: HTMLElement, donor: HTMLElement): HTMLElement {
  const articles = page.querySelectorAll<HTMLElement>(":scope > article");
  if (articles.length !== 1) return page;
  const article = articles[0];
  const scale = screenScale(page);
  const room = textArea(page, scale);
  if (!(room > 40 * scale)) return page;

  // Measure everything first, in the one long layout; then decide; then move.
  const blocks = [...article.children] as HTMLElement[];
  const pages: Piece[][] = [[]];
  let start = article.getBoundingClientRect().top;
  const newPage = (at: number) => {
    pages.push([]);
    start = at;
  };

  for (const el of blocks) {
    const box = measure(el, scale);
    let current = pages[pages.length - 1];
    if (box.bottom - start <= room + 0.5) {
      current.push({ el });
      continue;
    }
    if (el instanceof HTMLTableElement && el.rows.length > 1) {
      // Split the table between rows, repeating its header rows on each page.
      const rows = [...el.rows];
      let nHead = 0;
      while (nHead < rows.length && rows[nHead].querySelector(`span[id^="${HEADER_ROW}"]`)) nHead++;
      const headH = rows.slice(0, nHead).reduce((h, r) => h + r.getBoundingClientRect().height, 0);
      let from = 0;
      for (let i = nHead; i < rows.length; i++) {
        const r = rows[i].getBoundingClientRect();
        if (r.bottom - start <= room + 0.5) continue;
        if (from === 0 && i === nHead) {
          // Not even its first row fits: the whole table starts the next page
          // (unless it already starts this one, and simply is that tall).
          if (current.length) {
            newPage(measure(el, scale).top);
            current = pages[pages.length - 1];
          }
          continue;
        }
        if (i === from) continue; // a single row taller than the page stays whole
        current.push({ el, rows: [from, i], all: rows, nHead });
        newPage(r.top - headH);
        current = pages[pages.length - 1];
        from = i;
      }
      current.push({ el, rows: [from, rows.length], all: rows, nHead });
      continue;
    }
    if (current.length === 0) {
      // Taller than a whole page on its own: it stays, and runs past the bottom.
      current.push({ el });
      newPage(box.bottom);
      continue;
    }
    // Keep a heading (or a table's caption) with what follows it.
    const moved: Piece[] = [];
    while (current.length > 1 && !current[current.length - 1].rows && keepsWithNext(current[current.length - 1].el)) {
      moved.unshift(current.pop()!);
    }
    newPage(moved.length ? measure(moved[0].el, scale).top : box.top);
    pages[pages.length - 1].push(...moved, { el });
  }
  if (pages.length < 2 && !pages[0].some((p) => p.rows && p.rows[0] > 0)) return page;

  // Build the pages: the first keeps the original section, the rest are copies
  // with the header and footer a following page carries.
  const header = donor.querySelector<HTMLElement>(":scope > header");
  const footer = donor.querySelector<HTMLElement>(":scope > footer");
  let last = page;
  pages.forEach((pieces, index) => {
    let into = article;
    if (index > 0) {
      const section = page.cloneNode(false) as HTMLElement;
      into = article.cloneNode(false) as HTMLElement;
      if (header) section.append(header.cloneNode(true));
      section.append(into);
      if (footer) section.append(footer.cloneNode(true));
      last.after(section);
      last = section;
    }
    for (const piece of pieces) {
      if (!piece.rows) {
        into.append(piece.el);
        continue;
      }
      const table = piece.el as HTMLTableElement;
      const [from, to] = piece.rows;
      if (from === 0) {
        into.append(table); // the original keeps its first rows
        continue;
      }
      const part = table.cloneNode(false) as HTMLTableElement;
      for (const col of table.querySelectorAll(":scope > colgroup")) part.append(col.cloneNode(true));
      const all = piece.all ?? [];
      for (let i = 0; i < (piece.nHead ?? 0); i++) part.append(all[i].cloneNode(true));
      for (let i = from; i < to; i++) part.append(all[i]);
      into.append(part);
    }
  });
  return last;
}

/** Lay the rendered document out on pages the size of the document's own. */
export function paginate(host: HTMLElement): void {
  // The paragraphs that only carried an injected page break.
  host.querySelectorAll(`span[id^="${BREAK}"]`).forEach((s) => s.closest("p")?.remove());
  const pages = [...host.querySelectorAll<HTMLElement>("section.docx")];
  pages.forEach((page, i) => {
    // The first page may have a header of its own ("different first page"):
    // a page it runs onto takes the next page's header and footer instead.
    const donor = i === 0 && pages[1] ? pages[1] : page;
    splitPage(page, donor);
  });
}
