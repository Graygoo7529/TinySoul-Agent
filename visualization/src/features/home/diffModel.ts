/**
 * Unified-diff presentation model (plan §11).
 *
 * The backend /home/diff returns standard unified diff chunks (actual →
 * effective). The page renders them in two modes: unified (as emitted, with
 * line classes) and side-by-side (actual left, effective right, real line
 * numbers). Parsing is line-based and lossless: anything not recognized as a
 * hunk/header stays a "meta" line so the diff is never silently altered.
 */

export type DiffLineKind = "meta" | "hunk" | "context" | "add" | "del";

export interface DiffLine {
  kind: DiffLineKind;
  text: string;
}

export interface SideCell {
  lineNo: number;
  text: string;
  kind: "context" | "add" | "del";
}

export interface SideRow {
  left: SideCell | null;
  right: SideCell | null;
  /** Hunk headers span both columns. */
  hunk: string | null;
}

/** Split diff text into classified lines (unified mode rows). */
export function parseDiffLines(text: string): DiffLine[] {
  const lines: DiffLine[] = [];
  for (const raw of text.split("\n")) {
    if (raw.startsWith("@@")) {
      lines.push({ kind: "hunk", text: raw });
    } else if (raw.startsWith("+") && !raw.startsWith("+++")) {
      lines.push({ kind: "add", text: raw.slice(1) });
    } else if (raw.startsWith("-") && !raw.startsWith("---")) {
      lines.push({ kind: "del", text: raw.slice(1) });
    } else if (raw.startsWith(" ")) {
      lines.push({ kind: "context", text: raw.slice(1) });
    } else {
      // ---/+++ headers, "\ No newline at end of file", trailing empties.
      lines.push({ kind: "meta", text: raw });
    }
  }
  return lines;
}

const HUNK_HEADER = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

/** Fold classified diff lines into aligned side-by-side rows. */
export function toSideRows(lines: DiffLine[]): SideRow[] {
  const rows: SideRow[] = [];
  let leftNo = 0;
  let rightNo = 0;
  // Consecutive del/add runs pair line-by-line (modified lines share a row).
  let pendingDel: SideCell[] = [];
  let pendingAdd: SideCell[] = [];

  const flushPairing = (): void => {
    const count = Math.max(pendingDel.length, pendingAdd.length);
    for (let index = 0; index < count; index += 1) {
      rows.push({
        left: pendingDel[index] ?? null,
        right: pendingAdd[index] ?? null,
        hunk: null,
      });
    }
    pendingDel = [];
    pendingAdd = [];
  };

  for (const line of lines) {
    switch (line.kind) {
      case "hunk": {
        flushPairing();
        const match = HUNK_HEADER.exec(line.text);
        if (match !== null) {
          leftNo = Number.parseInt(match[1]!, 10);
          rightNo = Number.parseInt(match[2]!, 10);
        }
        rows.push({ left: null, right: null, hunk: line.text });
        break;
      }
      case "context": {
        flushPairing();
        rows.push({
          left: { lineNo: leftNo, text: line.text, kind: "context" },
          right: { lineNo: rightNo, text: line.text, kind: "context" },
          hunk: null,
        });
        leftNo += 1;
        rightNo += 1;
        break;
      }
      case "del": {
        pendingDel.push({ lineNo: leftNo, text: line.text, kind: "del" });
        leftNo += 1;
        break;
      }
      case "add": {
        pendingAdd.push({ lineNo: rightNo, text: line.text, kind: "add" });
        rightNo += 1;
        break;
      }
      case "meta":
        flushPairing();
        if (line.text.trim() !== "") {
          rows.push({ left: null, right: null, hunk: line.text });
        }
        break;
    }
  }
  flushPairing();
  return rows;
}
