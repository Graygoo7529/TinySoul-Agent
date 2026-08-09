/**
 * Terminal visuals for the execution domain: the command line itself
 * (`$ cmd` + working directory) and the process output area (exit code,
 * elapsed time, stdout/stderr with truncation markers). The command family
 * uses both; the process family reuses the output area plus its candidate
 * list. Styling rides on the shared .term-block classes.
 */

import { asNumber, asRecord, asString } from "../../../derive/actions/common";
import { LinkChip } from "../semantic";
import { isResourceLink } from "./probe";

/** Display cap for one stream, carried over from the heuristic renderer. */
const STREAM_CAP = 4000;

interface Stream {
  text: string;
  truncated: boolean;
}

/** Streams arrive either as a plain string or as { text, truncated }. */
function streamOf(value: unknown): Stream | undefined {
  const plain = asString(value);
  if (plain !== undefined) return { text: plain, truncated: false };
  const record = asRecord(value);
  if (!record) return undefined;
  const text = asString(record.text);
  if (text === undefined) return undefined;
  return { text, truncated: record.truncated === true };
}

/** True when the payload carries anything TerminalOutput would render. */
export function hasTerminalContent(payload: Record<string, unknown>): boolean {
  return (
    asNumber(payload.exit_code) !== undefined ||
    asNumber(payload.exitCode) !== undefined ||
    asString(payload.job_state) !== undefined ||
    streamOf(payload.stdout) !== undefined ||
    streamOf(payload.output) !== undefined ||
    streamOf(payload.stderr) !== undefined
  );
}

export function CommandLine({ command, cwd }: { command: string; cwd?: string }) {
  return (
    <div className="term-block">
      {cwd && <div className="opacity-50"># {cwd}</div>}
      <span className="term-cmd">$ {command}</span>
    </div>
  );
}

export function TerminalOutput({
  payload,
  tailLines,
}: {
  payload: Record<string, unknown>;
  /** When set, each stream shows only its last N lines (live-bar glimpses). */
  tailLines?: number;
}) {
  const exitCode = asNumber(payload.exit_code) ?? asNumber(payload.exitCode);
  const elapsed = asNumber(payload.elapsed_seconds) ?? asNumber(payload.duration_seconds);
  const stdout = streamOf(payload.stdout) ?? streamOf(payload.output);
  const stderr = streamOf(payload.stderr);
  const jobState = asString(payload.job_state);

  if (exitCode === undefined && !stdout && !stderr && !jobState) return null;

  return (
    <div className="term-block space-y-1">
      {exitCode !== undefined && (
        <div className={exitCode === 0 ? "text-success" : "term-stderr"}>
          exit code {exitCode}
          {elapsed !== undefined ? ` · ${elapsed.toFixed(1)}s` : ""}
        </div>
      )}
      {exitCode === undefined && jobState && <div>state: {jobState}</div>}
      {stdout && <StreamView stream={stdout} tailLines={tailLines} />}
      {stderr && (
        <div className="term-stderr">
          <StreamView stream={stderr} tailLines={tailLines} />
        </div>
      )}
    </div>
  );
}

function StreamView({ stream, tailLines }: { stream: Stream; tailLines?: number }) {
  const overflow = stream.text.length > STREAM_CAP;
  const capped = overflow ? stream.text.slice(0, STREAM_CAP) : stream.text;
  const lines = capped.split("\n");
  const tailed = tailLines !== undefined && lines.length > tailLines;
  const shown = tailed ? lines.slice(-tailLines).join("\n") : capped;
  return (
    <>
      {tailed && <div className="opacity-50">… {lines.length - tailLines} earlier lines</div>}
      <div>{shown}</div>
      {(overflow || stream.truncated) && <div className="opacity-50">… (truncated)</div>}
    </>
  );
}

/** Candidate files produced by a supervised run (process family). */
export function CandidateList({ candidates }: { candidates: unknown[] }) {
  if (candidates.length === 0) return null;
  return (
    <div className="mt-1.5 space-y-1">
      <div className="text-[10px] font-semibold tracking-wide text-fg-faint uppercase">
        Candidates · {candidates.length}
      </div>
      {candidates.map((candidate, i) => (
        <CandidateRow key={i} candidate={candidate} />
      ))}
    </div>
  );
}

function CandidateRow({ candidate }: { candidate: unknown }) {
  const record = asRecord(candidate);
  const link = record
    ? (asString(record.link) ?? asString(record.path) ?? asString(record.source_link))
    : asString(candidate);
  const label = record ? (asString(record.label) ?? asString(record.title)) : undefined;
  return (
    <div className="flex items-center gap-2">
      {link &&
        (isResourceLink(link) ? (
          <LinkChip link={link} />
        ) : (
          <span className="font-mono text-[11px] break-all text-info">{link}</span>
        ))}
      {label && <span className="truncate text-[11px] text-fg-muted">{label}</span>}
      {!link && !label && (
        <span className="font-mono text-[11px] text-fg-muted">
          {JSON.stringify(candidate)}
        </span>
      )}
    </div>
  );
}
