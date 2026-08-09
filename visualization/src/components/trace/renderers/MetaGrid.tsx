/**
 * Generic key/value grid for action result metadata (link, revision, size,
 * digest…). Link-like values render as LinkChip, long hex digests shorten,
 * numbers group with separators. Used by the patch/generate/memory output
 * blocks wherever the protocol answers with a metadata record.
 */

import type { ReactNode } from "react";
import { asNumber, asString } from "../../../derive/actions/common";
import { formatNumber, shorten } from "../../../utils/format";
import { LinkChip } from "../semantic";
import { isResourceLink } from "./probe";

export interface MetaEntry {
  label: string;
  value: ReactNode;
}

/** Build grid entries from a payload, in key order, skipping absent keys. */
export function metaEntries(
  payload: Record<string, unknown>,
  keys: string[],
): MetaEntry[] {
  const entries: MetaEntry[] = [];
  for (const key of keys) {
    const value = metaValue(payload[key]);
    if (value !== undefined) entries.push({ label: key, value });
  }
  return entries;
}

function metaValue(value: unknown): ReactNode | undefined {
  const text = asString(value);
  if (text !== undefined) {
    if (isResourceLink(text)) return <LinkChip link={text} />;
    if (text.length > 24 && /^[0-9a-f]+$/i.test(text)) return shorten(text);
    return text;
  }
  const number = asNumber(value);
  if (number !== undefined) return formatNumber(number);
  if (typeof value === "boolean") return value ? "yes" : "no";
  return undefined;
}

export function MetaGrid({ entries }: { entries: MetaEntry[] }) {
  const visible = entries.filter(
    (entry) => entry.value !== undefined && entry.value !== null && entry.value !== "",
  );
  if (visible.length === 0) return null;
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 rounded-lg border border-line bg-bg-elev px-2.5 py-2">
      {visible.map((entry) => (
        <div key={entry.label} className="contents">
          <dt className="text-[11px] text-fg-faint">{entry.label}</dt>
          <dd className="min-w-0 truncate font-mono text-[11px] text-fg-muted">
            {entry.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
