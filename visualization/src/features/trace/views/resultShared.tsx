/**
 * Result-family views (plan §9.1) — the shared pieces consumed by every family view.
 */

import { t, useI18n } from "../../../i18n";
import type { ReactElement, ReactNode } from "react";
import type { JsonObject } from "../../../api/v2/types";
import { JsonTree } from "../../../components/ui/JsonTree";
import { asNumber, asObject, asStringArray } from "../model/facts";
import type { ResultViewProps } from "../model/registry";

// ---------------------------------------------------------------------------
// Shared pieces
// ---------------------------------------------------------------------------

/** A routable reference rendered as an open button. */
export function ReferenceButton({
  reference,
  label,
  onOpen,
}: {
  reference: string;
  label?: string;
  onOpen?: (reference: string) => void;
}): ReactElement {
  if (onOpen === undefined) {
    return (
      <span
        className="block truncate font-mono text-[12px] text-fg-muted"
        title={reference}
      >
        {label ?? reference}
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={() => onOpen(reference)}
      title={reference}
      className="block max-w-full truncate text-left font-mono text-[12px] text-accent hover:underline"
    >
      {label ?? reference}
    </button>
  );
}

export function FactRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="contents">
      <dt className="text-fg-faint">{label}</dt>
      <dd className="min-w-0 break-words text-fg-muted">{value}</dd>
    </div>
  );
}

export function FactGrid({ children }: { children: ReactNode }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
      {children}
    </dl>
  );
}

/**
 * The requested→actual line range of a bounded text read (workspace.read).
 * The backend resolves unbounded requests to a sentinel end line; that tail
 * reads as "end" instead of a giant number.
 */
export function readRangeLine(requested: JsonObject, actual: JsonObject | null): string {
  const start = asNumber(requested.start_line);
  const end = asNumber(requested.end_line);
  const endText =
    end === null ? "?" : end >= 2 ** 31 - 1 ? t("trace.rangeEnd") : String(end);
  const requestedText = t("trace.lineRange", { start: start ?? "?", end: endText });
  if (actual === null) return t("trace.requestedRange", { range: requestedText });
  const position = (value: unknown): string => {
    const point = asObject(value);
    if (point === null) return "–";
    const line = asNumber(point.line);
    const column = asNumber(point.column);
    return line !== null
      ? `${line}${column !== null ? `:${column}` : ""}`
      : "–";
  };
  return t("trace.actualRange", { requested: requestedText, start: position(actual.start), end: position(actual.end) });
}

/** workspace.analyze coverage: complete/files_loaded/source_chars. */
export function analysisCoverageLine(coverage: JsonObject): string | null {
  const parts: string[] = [];
  if (coverage.complete === true) parts.push(t("trace.coverageComplete"));
  if (coverage.complete === false) parts.push(t("trace.coveragePartial"));
  const filesLoaded = asNumber(coverage.files_loaded);
  if (filesLoaded !== null) {
    parts.push(t("trace.fileCount", { count: filesLoaded }));
  }
  const sourceChars = asNumber(coverage.source_chars);
  if (sourceChars !== null) {
    parts.push(t("trace.sourceChars", { count: sourceChars }));
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

/** Bounded pre-wrap text; longer bodies stay behind the collapsible. */
export function Excerpt({ text, max = 600 }: { text: string; max?: number }) {
  const truncated = text.length > max;
  return (
    <div className="rounded-md border border-line/60 bg-bg-sunken px-2.5 py-1.5 text-[12px] leading-5 break-words whitespace-pre-wrap text-fg-muted">
      {truncated ? `${text.slice(0, max)}…` : text}
    </div>
  );
}

/** Every string field of the payload that looks like a routable reference. */
export function referenceFields(payload: JsonObject): { key: string; value: string }[] {
  const out: { key: string; value: string }[] = [];
  for (const [key, value] of Object.entries(payload)) {
    if (typeof value !== "string" || value === "") continue;
    if (
      /^(workspace|home|memory):/.test(value) ||
      key === "link" ||
      key.endsWith("_ref") ||
      key === "ref" ||
      key.endsWith("_ref")
    ) {
      out.push({ key, value });
    }
  }
  return out;
}

export function LinksBlock({
  payload,
  onOpen,
  title = "Resources",
}: {
  payload: JsonObject;
  onOpen?: (reference: string) => void;
  title?: string;
}) {
  const fields = referenceFields(payload);
  const links = asStringArray(payload.result_refs);
  const workspaceLinks = asStringArray(payload.workspace_refs);
  if (fields.length === 0 && links.length === 0 && workspaceLinks.length === 0) {
    return null;
  }
  return (
    <div className="space-y-1">
      <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
        {title}
      </div>
      {fields.map(({ key, value }) => (
        <ReferenceButton key={key} reference={value} onOpen={onOpen} />
      ))}
      {[...links, ...workspaceLinks].map((link) => (
        <ReferenceButton key={link} reference={link} onOpen={onOpen} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// generic fallback
// ---------------------------------------------------------------------------

export function EmptyResult() {
  const { t } = useI18n();
  return (
    <div className="rounded-lg border border-line bg-bg-elev px-3 py-2 text-[12px] text-fg-faint">
      {t("trace.noPayload")}</div>
  );
}

/**
 * The universal structured view: readable JSON of the settled result (and
 * the call params when there is nothing else). Unknown actions land here;
 * the result is never swallowed.
 */
export function GenericView({ result, params }: Omit<ResultViewProps, "action">) {
  useI18n();
  if (result === null && params === null) return <EmptyResult />;
  return (
    <div className="space-y-2">
      <div className="rounded-lg border border-dashed border-line px-2.5 py-1.5 text-[11px] text-fg-faint">
        {t("trace.unknownAction")}</div>
      {result !== null && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            {t("runtime.result")}</div>
          <JsonTree value={result} defaultExpanded={false} />
        </div>
      )}
      {result === null && params !== null && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            {t("settings.callParams")}</div>
          <JsonTree value={params} defaultExpanded={false} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------