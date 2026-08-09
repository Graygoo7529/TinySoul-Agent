/**
 * Line-level old/new diff for the patch family (workspace.patch,
 * execution.patch_script, home.*.patch, plus workspace.append whose text is
 * a pure addition). Deleted lines get a danger wash, additions a success
 * wash, both with line-number gutters; long unchanged runs collapse behind
 * an expand toggle.
 */

import { useMemo, useState } from "react";
import { diffLines, type DiffRow } from "../../../utils/diff";

/** Unchanged runs longer than this collapse to head/tail plus a toggle. */
const COLLAPSE_THRESHOLD = 6;
const COLLAPSE_EDGE = 2;

interface Segment {
  type: "same" | "change";
  rows: DiffRow[];
}

/** Merge consecutive del/add rows into one change segment. */
function segmentRows(rows: DiffRow[]): Segment[] {
  const segments: Segment[] = [];
  for (const row of rows) {
    const type = row.type === "same" ? "same" : "change";
    const last = segments[segments.length - 1];
    if (last && last.type === type) last.rows.push(row);
    else segments.push({ type, rows: [row] });
  }
  return segments;
}

export function DiffBlock({ oldText, newText }: { oldText: string; newText: string }) {
  const rows = useMemo(() => diffLines(oldText, newText), [oldText, newText]);
  if (rows.length === 0) return null;
  const segments = segmentRows(rows);
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-bg-sunken py-1 font-mono text-[11px] leading-5">
      {segments.map((segment, i) =>
        segment.type === "same" ? (
          <SameSegment key={i} rows={segment.rows} />
        ) : (
          segment.rows.map((row, j) => <DiffRowView key={j} row={row} />)
        ),
      )}
    </div>
  );
}

function SameSegment({ rows }: { rows: DiffRow[] }) {
  const [expanded, setExpanded] = useState(false);
  if (rows.length <= COLLAPSE_THRESHOLD || expanded) {
    return (
      <>
        {rows.map((row, i) => (
          <DiffRowView key={i} row={row} />
        ))}
      </>
    );
  }
  return (
    <>
      {rows.slice(0, COLLAPSE_EDGE).map((row, i) => (
        <DiffRowView key={`h${i}`} row={row} />
      ))}
      <button
        onClick={() => setExpanded(true)}
        className="block w-full bg-hover/50 px-2 text-left text-[10px] text-fg-faint select-none hover:text-fg-muted"
      >
        ⋯ {rows.length - COLLAPSE_EDGE * 2} unchanged lines
      </button>
      {rows.slice(-COLLAPSE_EDGE).map((row, i) => (
        <DiffRowView key={`t${i}`} row={row} />
      ))}
    </>
  );
}

function DiffRowView({ row }: { row: DiffRow }) {
  const tone =
    row.type === "del"
      ? "bg-danger-soft/70"
      : row.type === "add"
        ? "bg-success-soft/70"
        : "";
  const marker = row.type === "del" ? "-" : row.type === "add" ? "+" : " ";
  const markerTone =
    row.type === "del"
      ? "text-danger"
      : row.type === "add"
        ? "text-success"
        : "text-fg-faint";
  return (
    <div className={`flex px-2 ${tone}`}>
      <span className="w-9 shrink-0 text-right text-fg-faint select-none">
        {row.oldLine ?? ""}
      </span>
      <span className="w-9 shrink-0 text-right text-fg-faint select-none">
        {row.newLine ?? ""}
      </span>
      <span className={`w-4 shrink-0 text-center select-none ${markerTone}`}>{marker}</span>
      <span className="min-w-0 flex-1 break-all whitespace-pre-wrap text-fg">{row.text}</span>
    </div>
  );
}
