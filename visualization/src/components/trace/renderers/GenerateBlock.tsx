/**
 * Generate family views: the authoring input (instruction or full text) and
 * the result metadata grid (link/revision/size/digest plus created/rewritten
 * style flags). Covers workspace.create/rewrite, execution.*_script and
 * home.*.write; the patch family shares the metadata grid for its outputs.
 */

import { MetaGrid, metaEntries } from "./MetaGrid";
import { GenericBlock } from "./GenericBlock";

export function GenerateInput({
  instruction,
  text,
}: {
  instruction?: string;
  text?: string;
}) {
  const body = instruction ?? text;
  if (!body) return null;
  return (
    <div className="max-h-48 overflow-y-auto rounded-lg bg-bg-elev px-2.5 py-1.5 text-[12px] whitespace-pre-wrap break-words text-fg-muted">
      {body}
    </div>
  );
}

const FLAG_KEYS = ["created", "rewritten", "appended", "patched", "promoted"] as const;
const META_KEYS = [
  "link",
  "revision",
  "size",
  "digest",
  "kind",
  "summary",
  "state",
  "baseline_digest",
];

export function GenerateOutput({ payload }: { payload: Record<string, unknown> }) {
  const flags = FLAG_KEYS.filter((key) => payload[key] === true);
  const entries = metaEntries(payload, META_KEYS);
  if (flags.length === 0 && entries.length === 0) return <GenericBlock value={payload} />;
  return (
    <div className="space-y-1.5">
      {flags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {flags.map((flag) => (
            <span
              key={flag}
              className="rounded-md bg-success-soft px-1.5 py-0.5 text-[10px] font-medium text-success"
            >
              {flag}
            </span>
          ))}
        </div>
      )}
      <MetaGrid entries={entries} />
    </div>
  );
}
