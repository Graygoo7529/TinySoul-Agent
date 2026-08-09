/**
 * Read family views: the requested link + line range (input) and the read
 * text with a line-number gutter plus truncation / end-of-file markers
 * (output). Covers workspace.read and home.resource.read.
 */

import { asNumber, asRecord, asString } from "../../../derive/actions/common";
import { LinkChip } from "../semantic";
import { GenericBlock } from "./GenericBlock";

const TEXT_CAP = 4000;

export function ReadInput({
  link,
  start,
  end,
}: {
  link?: string;
  start?: number;
  end?: number;
}) {
  return (
    <div className="flex items-center gap-2">
      {link && <LinkChip link={link} />}
      {start !== undefined && end !== undefined && (
        <span className="font-mono text-[10px] text-fg-faint">
          lines {start}-{end}
        </span>
      )}
    </div>
  );
}

export function ReadBlock({ payload }: { payload: Record<string, unknown> }) {
  const text = asString(payload.text);
  if (text === undefined) return <GenericBlock value={payload} />;
  // actual is { start, end } per protocol; older payloads used a bare count.
  const actual = asRecord(payload.actual);
  const firstLineNo = asNumber(actual?.start) ?? 1;
  const truncated = payload.truncated === true;
  const eof = payload.eof_reached === true;
  const overflow = text.length > TEXT_CAP;
  const lines = (overflow ? text.slice(0, TEXT_CAP) : text).split("\n");
  return (
    <div>
      <div className="overflow-x-auto rounded-lg border border-line bg-bg-sunken py-1 font-mono text-[11px] leading-5">
        {lines.map((line, i) => (
          <div key={i} className="flex px-2">
            <span className="w-9 shrink-0 text-right text-fg-faint select-none">
              {firstLineNo + i}
            </span>
            <span className="w-3 shrink-0" />
            <span className="min-w-0 flex-1 break-all whitespace-pre-wrap text-fg-muted">
              {line}
            </span>
          </div>
        ))}
      </div>
      {(truncated || overflow || eof) && (
        <div className="mt-1 font-mono text-[10px] text-fg-faint">
          {truncated || overflow ? "… truncated" : ""}
          {(truncated || overflow) && eof ? " · " : ""}
          {eof ? "end of file" : ""}
        </div>
      )}
    </div>
  );
}
