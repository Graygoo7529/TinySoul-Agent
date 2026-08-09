/**
 * Active-memory views: recall renders the cited metadata row plus the
 * recalled Markdown; memorize lists the operations (kind-tinted) with a text
 * excerpt each. The write-side metadata (revision/digest/…) rides MetaGrid.
 */

import { asRecord, asString } from "../../../derive/actions/common";
import { firstLine } from "../../../derive/activitySemantics";
import { Markdown } from "../../markdown/Markdown";
import { GenericBlock } from "./GenericBlock";
import { MetaGrid, metaEntries } from "./MetaGrid";

export function RecallBlock({ payload }: { payload: Record<string, unknown> }) {
  const markdown = asString(payload.markdown);
  const entries = metaEntries(payload, ["link", "kind", "cite"]);
  // Scalar metadata fields join the grid (title, created, …).
  const metadata = asRecord(payload.metadata);
  if (metadata) {
    for (const [key, value] of Object.entries(metadata)) {
      if (
        typeof value === "string" ||
        typeof value === "number" ||
        typeof value === "boolean"
      ) {
        entries.push({ label: key, value: String(value) });
      }
    }
  }
  if (!markdown && entries.length === 0) return <GenericBlock value={payload} />;
  return (
    <div className="space-y-1.5">
      <MetaGrid entries={entries} />
      {markdown && (
        <div className="max-h-64 overflow-y-auto rounded-lg border border-line bg-bg-elev px-3 py-2">
          <Markdown>{markdown}</Markdown>
        </div>
      )}
    </div>
  );
}

const opTones: Record<string, string> = {
  append: "bg-success-soft text-success",
  replace: "bg-warning-soft text-warning",
  remove: "bg-danger-soft text-danger",
  clear: "bg-danger-soft text-danger",
};

/** memorize operations list (input side). */
export function MemorizeOps({ operations }: { operations: unknown[] }) {
  if (operations.length === 0) return null;
  return (
    <div className="space-y-1">
      {operations.map((op, i) => (
        <MemorizeOpRow key={i} op={op} />
      ))}
    </div>
  );
}

function MemorizeOpRow({ op }: { op: unknown }) {
  const record = asRecord(op);
  if (!record) return null;
  const kind = asString(record.kind) ?? "op";
  const tone = opTones[kind] ?? "bg-hover text-fg-muted";
  const text = asString(record.text);
  const oldText = asString(record.old_text);
  const newText = asString(record.new_text);
  const excerpt =
    oldText && newText
      ? `${firstLine(oldText, 60)} → ${firstLine(newText, 60)}`
      : firstLine(text ?? newText ?? oldText ?? "", 120);
  return (
    <div className="flex items-baseline gap-2">
      <span
        className={`shrink-0 rounded px-1.5 py-px font-mono text-[10px] font-medium ${tone}`}
      >
        {kind}
      </span>
      {excerpt && (
        <span
          className="min-w-0 flex-1 truncate text-[12px] text-fg-muted"
          title={text ?? newText ?? oldText}
        >
          {excerpt}
        </span>
      )}
    </div>
  );
}
