/**
 * Minimal line-level diff for the patch family renderers.
 *
 * A classic LCS over the two line arrays; deletions are preferred on ties so
 * a changed region always surfaces as a del-run immediately followed by its
 * add-run, which the DiffBlock renders as paired red/green blocks. Inputs
 * beyond DIFF_MAX_CELLS fall back to a whole-text replace instead of
 * allocating a quadratic table.
 */

export interface DiffRow {
  type: "same" | "add" | "del";
  text: string;
  /** 1-based line number in the old text (same/del rows). */
  oldLine?: number;
  /** 1-based line number in the new text (same/add rows). */
  newLine?: number;
}

/** Above oldLines × newLines cells, skip the LCS table and emit a replace. */
export const DIFF_MAX_CELLS = 2_000_000;

function splitLines(text: string): string[] {
  if (text === "") return [];
  const lines = text.split("\n");
  // A trailing newline terminates the last line; it is not an extra empty one.
  if (lines[lines.length - 1] === "") lines.pop();
  return lines;
}

export function diffLines(oldText: string, newText: string): DiffRow[] {
  const oldLines = splitLines(oldText);
  const newLines = splitLines(newText);

  if (oldLines.length === 0 && newLines.length === 0) return [];
  if (oldLines.length === 0) {
    return newLines.map((text, i) => ({ type: "add", text, newLine: i + 1 }));
  }
  if (newLines.length === 0) {
    return oldLines.map((text, i) => ({ type: "del", text, oldLine: i + 1 }));
  }
  if (oldLines.length * newLines.length > DIFF_MAX_CELLS) {
    return [
      ...oldLines.map((text, i) => ({ type: "del" as const, text, oldLine: i + 1 })),
      ...newLines.map((text, i) => ({ type: "add" as const, text, newLine: i + 1 })),
    ];
  }

  const n = oldLines.length;
  const m = newLines.length;
  // dp[i * (m + 1) + j] = LCS length of oldLines[i:] and newLines[j:].
  const dp = new Uint32Array((n + 1) * (m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i * (m + 1) + j] =
        oldLines[i] === newLines[j]
          ? dp[(i + 1) * (m + 1) + j + 1] + 1
          : Math.max(dp[(i + 1) * (m + 1) + j], dp[i * (m + 1) + j + 1]);
    }
  }

  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (oldLines[i] === newLines[j]) {
      rows.push({ type: "same", text: oldLines[i], oldLine: i + 1, newLine: j + 1 });
      i++;
      j++;
    } else if (dp[(i + 1) * (m + 1) + j] >= dp[i * (m + 1) + j + 1]) {
      rows.push({ type: "del", text: oldLines[i], oldLine: i + 1 });
      i++;
    } else {
      rows.push({ type: "add", text: newLines[j], newLine: j + 1 });
      j++;
    }
  }
  while (i < n) {
    rows.push({ type: "del", text: oldLines[i], oldLine: i + 1 });
    i++;
  }
  while (j < m) {
    rows.push({ type: "add", text: newLines[j], newLine: j + 1 });
    j++;
  }
  return rows;
}
