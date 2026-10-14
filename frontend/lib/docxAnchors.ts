/**
 * Put anchored pictures where Word puts them, in the in-app Word preview.
 *
 * docx-preview places a "behind text" / "in front of text" picture relative
 * to the paragraph it is anchored to and ignores what the document says it is
 * relative to (the page, a margin) and whether it sits behind the text. A
 * cover-page frame anchored "from the top margin" then lands wherever its
 * paragraph happens to be. The document itself says exactly where each one
 * goes, so this reads that from the file and moves the rendered picture there.
 *
 * Viewing only: the file is never changed. Anything it can't match with
 * certainty (the drawings it reads don't line up one-to-one with the ones
 * docx-preview rendered) is left exactly as docx-preview drew it.
 */

const W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
const WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing";
const MC = "http://schemas.openxmlformats.org/markup-compatibility/2006";
const EMU_PER_PX = 9525;

interface Axis {
  from: string;
  offset: number | null; // px
  align: string | null;
}

interface Drawing {
  floating: boolean; // anchored, with no text wrapping around it
  behind: boolean;
  inCell: boolean; // laid out relative to its table cell instead
  h: Axis;
  v: Axis;
  width: number; // px
  height: number;
}

function axis(el: Element | undefined, fallback: string): Axis {
  const offset = el?.getElementsByTagNameNS(WP, "posOffset")[0]?.textContent;
  return {
    from: el?.getAttribute("relativeFrom") || fallback,
    offset: offset != null && offset !== "" ? Number(offset) / EMU_PER_PX : null,
    align: el?.getElementsByTagNameNS(WP, "align")[0]?.textContent || null,
  };
}

function readDrawing(drawing: Element): Drawing {
  const anchor = drawing.getElementsByTagNameNS(WP, "anchor")[0];
  const extent = drawing.getElementsByTagNameNS(WP, "extent")[0];
  const flag = (name: string) => ["1", "true"].includes(anchor?.getAttribute(name) || "");
  return {
    floating: !!anchor && !!anchor.getElementsByTagNameNS(WP, "wrapNone")[0],
    behind: flag("behindDoc"),
    inCell: flag("layoutInCell") && hasAncestor(drawing, W, "tc"),
    h: axis(anchor?.getElementsByTagNameNS(WP, "positionH")[0], "column"),
    v: axis(anchor?.getElementsByTagNameNS(WP, "positionV")[0], "paragraph"),
    width: Number(extent?.getAttribute("cx") || 0) / EMU_PER_PX,
    height: Number(extent?.getAttribute("cy") || 0) / EMU_PER_PX,
  };
}

function hasAncestor(el: Element, ns: string, name: string): boolean {
  for (let p = el.parentElement; p; p = p.parentElement) {
    if (p.namespaceURI === ns && p.localName === name) return true;
  }
  return false;
}

/** Inside which branch of an mc:AlternateContent, if any. */
function branch(el: Element): "choice" | "fallback" | null {
  for (let p = el.parentElement; p; p = p.parentElement) {
    if (p.namespaceURI === MC && p.localName === "Choice") return "choice";
    if (p.namespaceURI === MC && p.localName === "Fallback") return "fallback";
  }
  return null;
}

/**
 * The body's drawings in document order, twice: as docx-preview would see
 * them if it renders the mc:Choice branch of alternate content, and if it
 * falls back. Which one applies is decided by matching the rendered count.
 */
async function readBodyDrawings(buf: ArrayBuffer): Promise<Drawing[][]> {
  const { default: JSZip } = await import("jszip");
  const zip = await JSZip.loadAsync(buf);
  const xml = await zip.file("word/document.xml")?.async("string");
  if (!xml) return [];
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  const all = [...doc.getElementsByTagNameNS(W, "drawing")];
  const pick = (skip: "choice" | "fallback") =>
    all.filter((d) => branch(d) !== skip).map(readDrawing);
  return [pick("fallback"), pick("choice")];
}

/** Where on the page an axis puts the picture, in px from the page's edge. */
function position(
  a: Axis,
  size: number,
  page: number,
  marginStart: number,
  marginEnd: number,
  paragraphStart: number,
  names: { start: string; end: string },
): number | null {
  let base: number;
  let room: number;
  switch (a.from) {
    case "page":
      [base, room] = [0, page];
      break;
    case names.start:
      [base, room] = [0, marginStart];
      break;
    case names.end:
      [base, room] = [page - marginEnd, marginEnd];
      break;
    case "margin":
    case "column":
      [base, room] = [marginStart, page - marginStart - marginEnd];
      break;
    case "paragraph":
    case "line":
      [base, room] = [paragraphStart, 0];
      break;
    default:
      return null; // character, inside/outside margin: leave it be
  }
  if (a.offset != null) return base + a.offset;
  if (a.align === "center") return base + (room - size) / 2;
  if (a.align === "right" || a.align === "bottom") return base + room - size;
  return base;
}

/** Find docx-preview's drawing wrappers in the page bodies, in order. */
function renderedDrawings(host: HTMLElement): HTMLElement[] {
  return [...host.querySelectorAll<HTMLElement>("section.docx article div")].filter(
    (d) => d.style.position === "relative" && d.style.textIndent === "0px",
  );
}

export async function placeAnchoredDrawings(host: HTMLElement, buf: ArrayBuffer): Promise<void> {
  let lists: Drawing[][];
  try {
    lists = await readBodyDrawings(buf);
  } catch {
    return; // not a readable package: the preview stays as rendered
  }
  const rendered = renderedDrawings(host);
  const drawings = lists.find((l) => l.length === rendered.length);
  if (!drawings || !rendered.length) return;

  drawings.forEach((d, i) => {
    if (!d.floating || d.inCell) return;
    const el = rendered[i];
    const page = el.closest<HTMLElement>("section.docx");
    if (!page) return;
    const cs = getComputedStyle(page);
    const pageBox = page.getBoundingClientRect();
    const para = (el.closest("p") || el.parentElement) as HTMLElement;
    const paraBox = para.getBoundingClientRect();
    const left = position(
      d.h, d.width, page.clientWidth,
      parseFloat(cs.paddingLeft), parseFloat(cs.paddingRight),
      paraBox.left - pageBox.left, { start: "leftMargin", end: "rightMargin" },
    );
    const top = position(
      d.v, d.height, page.clientHeight,
      parseFloat(cs.paddingTop), parseFloat(cs.paddingBottom),
      paraBox.top - pageBox.top, { start: "topMargin", end: "bottomMargin" },
    );
    if (left == null || top == null) return;

    // Out of the text flow, onto the page itself. "Behind text" goes under
    // the page's text but stays above the page (isolation keeps the white
    // sheet from covering it).
    page.style.position = "relative";
    page.style.isolation = "isolate";
    Object.assign(el.style, {
      position: "absolute",
      display: "block",
      left: `${left}px`,
      top: `${top}px`,
      width: `${d.width}px`,
      height: `${d.height}px`,
      margin: "0",
      zIndex: d.behind ? "-1" : "1",
    });
    page.appendChild(el);
  });
}
