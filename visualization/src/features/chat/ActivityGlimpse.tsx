/**
 * c479ca0's compact action inset. Only the input/result boundary uses v2;
 * diff rows, terminal tails and bounded search hits retain the baseline layout.
 * Full result-family views stay in the trace drawer.
 */
import { useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Crossfade } from "../../components/ui/Crossfade";
import { diffLines } from "../../utils/diff";
import { EASE_CALM } from "../../utils/motion";
import { actionFamily } from "../trace/registry";
import { asObject, asString, asNumber } from "../trace/facts";
import { pushActionDetail } from "../trace/entries";
import { ActivityStep as Step } from "./ActivityStep";
import { useHoldChatFollow } from "./useConversationScroll";
import type { ActionGlimpseData, ActivityStep } from "./presentation";

const DIFF_GLIMPSE_ROWS = 5;
const DIFF_GLIMPSE_ROWS_EXPANDED = 14;
const SEARCH_GLIMPSE_ITEMS = 3;

export function ActivityGlimpse({ item, live, glimpseExpanded, onToggleGlimpse, epoch, turnId, day }: {
  item: ActivityStep; live: boolean; glimpseExpanded: boolean; onToggleGlimpse: () => void;
  epoch: number; turnId: string; day: string | null;
}) {
  const reduced = useReducedMotion();
  if (item.content.type !== "action_plan" && item.content.type !== "action_result") return <Step item={item} animate={live} />;
  const data = item.content.glimpse;
  const body = glimpseBody(data);
  if (!body) return <Step item={item} animate={live} />;
  return <Step item={item} animate={live} onToggleGlimpse={onToggleGlimpse} glimpseExpanded={glimpseExpanded}
    glimpse={<AnimatePresence initial={false}>{glimpseExpanded && <motion.div key={item.id} data-activity-gist={data.stage}
      style={{ overflow: "hidden" }} initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
      transition={{ duration: reduced ? 0 : 0.35, ease: EASE_CALM }}>
      <div className="grow-in"><Crossfade id={`${data.callId}:${data.stage}`} className="mt-1 rounded-lg border border-line/70 bg-bg-sunken/70 px-2.5 py-1.5">
        {body}
        {data.callId && <button type="button" className="mt-1 text-[10px] text-accent hover:underline"
          onClick={() => pushActionDetail(epoch, turnId, day, { callId: data.callId!, action: data.actionId, ordinal: 0 })}>Details</button>}
      </Crossfade></div>
    </motion.div>}</AnimatePresence>} />;
}
/** Null means the row has no compact inset; never mount an empty disclosure. */
export function glimpseBody(data: ActionGlimpseData) {
  if (data.actionId === "core.ask" || data.actionId === "core.answer") return null;
  const params = asObject(data.params) ?? {};
  const payload = data.payload;
  const family = actionFamily(data.actionId);
  const patches = data.actionId === "workspace.edit" && Array.isArray(params.edits)
    ? params.edits.map(asObject).filter((entry) => entry !== null)
    : asString(params.old_text) !== null ? [params] : [];
  if (data.stage === "plan") {
    if (patches.length) return <div className="space-y-1">{patches.map((patch, i) =>
      <DiffGlimpse key={i} oldText={asString(patch.old_text) ?? ""} newText={asString(patch.new_text) ?? ""} />)}</div>;
    if (family === "execution") {
      const command = asString(params.command) ?? asString(params.source_ref);
      if (!command) return null;
      return <div className="term-block">
        {asString(params.cwd_ref) && <div className="opacity-50"># {asString(params.cwd_ref)}</div>}
        <span className="term-cmd">$ {command}</span>
      </div>;
    }
    if (data.actionId === "memory.memorize" && Array.isArray(params.operations)) {
      const kinds = params.operations.map((op) => asString(asObject(op)?.kind)).filter(Boolean);
      return kinds.length ? <div className="flex flex-wrap gap-1">{kinds.map((kind, i) =>
        <span key={i} className="rounded bg-hover px-1.5 py-px font-mono text-[10px] text-fg-muted">{kind}</span>)}</div> : null;
    }
    const instruction = asString(params.instruction) ?? asString(params.text) ?? asString(asObject(params.source)?.query);
    return instruction ? <div className="line-clamp-2 break-words text-[11px] text-fg-muted">{instruction}</div> : null;
  }
  if (data.result?.status === "failure" || data.result?.status === "timeout") {
    const feedback = asString(data.failure?.feedback) ?? data.result.preview;
    return feedback ? <div className="line-clamp-2 text-[11px] text-danger">{feedback}</div> : null;
  }
  if (!payload) return null;
  if (family === "write") return <WriteResultGlimpse actionId={data.actionId} payload={payload} />;
  if (family === "execution") return <TerminalGlimpse payload={payload} />;
  const items = Array.isArray(payload.items) ? payload.items : Array.isArray(payload.results) ? payload.results : [];
  if (items.length) return <div className="space-y-0.5">{items.slice(0, SEARCH_GLIMPSE_ITEMS).map((raw, i) => {
    const item = asObject(raw);
    const label = asString(item?.title) ?? asString(item?.ref) ?? asString(item?.ref) ?? asString(item?.url);
    const evidence = Array.isArray(item?.evidence) ? item.evidence : [];
    const preview = evidence.map((value) => asString(asObject(value)?.text)).find(Boolean) ?? asString(item?.snippet);
    return label ? <div key={i} className="min-w-0 text-[11px]">
      <div className="truncate text-fg">{label}</div>
      {preview && <div className="line-clamp-1 text-fg-muted">{preview}</div>}
    </div> : null;
  })}</div>;
  const title = asString(payload.title);
  const text = asString(payload.excerpt) ?? asString(payload.content) ?? asString(payload.text) ?? asString(payload.summary);
  return title || text ? <div className="min-w-0">
    {title && <div className="truncate text-[11px] font-medium text-fg">{title}</div>}
    {text && <div className="line-clamp-2 break-words text-[11px] text-fg-muted">{text}</div>}
  </div> : null;
}

function WriteResultGlimpse({ actionId, payload }: { actionId: string; payload: Record<string, unknown> }) {
  const link = asString(payload.ref) ?? asString(payload.ref) ?? asString(payload.path);
  const changed = typeof payload.changed === "boolean" ? payload.changed : null;
  const written = asNumber(payload.written);
  const isHome = actionId.startsWith("home.");
  const chars = asNumber(payload.chars) ?? (isHome ? asNumber(payload.size) : null);
  const bytes = asNumber(payload.bytes) ?? (!isHome ? asNumber(payload.size) : null);
  const operations = Array.isArray(payload.operations) ? payload.operations.length : null;
  const items = Array.isArray(payload.items) ? payload.items : [];
  const operation = asString(payload.operation) ?? (changed === true ? "changed" : changed === false ? "unchanged" : payload.written === true || written !== null ? "written" : operations !== null ? `${operations} operations` : chars !== null || bytes !== null ? "updated" : null);
  const detail = asString(payload.summary) ?? asString(payload.message);
  if (!link && !operation && written === null && chars === null && bytes === null && !detail && items.length === 0) return null;
  return <div className="min-w-0 text-[11px]">
    <div className="flex min-w-0 items-center gap-2">
      <span className={changed === false ? "text-fg-muted" : "text-success"}>{operation ?? "completed"}</span>
      {written !== null && <span className="font-mono text-fg-faint">{written} written</span>}
      {chars !== null && <span className="font-mono text-fg-faint">{chars} chars</span>}
      {bytes !== null && <span className="font-mono text-fg-faint">{bytes} bytes</span>}
      {link && <span className="truncate text-fg-muted" title={link}>{link}</span>}
    </div>
    {detail && <div className="line-clamp-1 text-fg-muted">{detail}</div>}
    {items.length > 0 && <div className="mt-0.5 space-y-0.5">
      {items.slice(0, SEARCH_GLIMPSE_ITEMS).map((raw, index) => {
        const item = asObject(raw);
        const label = asString(item?.title) ?? asString(item?.ref) ?? asString(item?.ref) ?? asString(item?.path);
        return label ? <div key={index} className="truncate text-fg-muted">{label}</div> : null;
      })}
    </div>}
  </div>;
}

/** Original two-line terminal tail and six-line manual expansion, using v2 streams. */
function TerminalGlimpse({ payload }: { payload: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false);
  const holdFollow = useHoldChatFollow();
  const streams = (["stdout", "stderr"] as const).flatMap((name) => {
    const text = asString(payload[name]);
    return text ? [{ name, lines: text.trimEnd().split("\n") }] : [];
  });
  const lineCount = streams.reduce((sum, stream) => sum + stream.lines.length, 0);
  const exitCode = asNumber(payload.exit_code);
  if (exitCode === null && !lineCount) return null;
  const cap = expanded ? 6 : 2;
  return <div>
    <div className="term-block space-y-1">
      {exitCode !== null && <div className={exitCode === 0 ? "text-success" : "term-stderr"}>exit code {exitCode}</div>}
      {streams.map(({ name, lines }) => <div key={name} className={name === "stderr" ? "term-stderr" : ""}>
        {lines.length > cap && <div className="opacity-50">… {lines.length - cap} earlier lines</div>}
        <div>{lines.slice(-cap).join("\n")}</div>
        {payload[`${name}_truncated`] === true && <div className="opacity-50">… (truncated)</div>}
      </div>)}
    </div>
    {lineCount > 2 && <button onClick={() => { holdFollow(); setExpanded(!expanded); }}
      className="mt-0.5 text-[10px] text-fg-faint transition-colors hover:text-fg-muted">
      {expanded ? "收起输出" : `展开输出（${lineCount} 行）`}
    </button>}
  </div>;
}

/** Compact change list with a +N/−M stat; `statOnly` hides the line rows.
    Beyond the preview cap the row list expands on demand. */
function DiffGlimpse({
  oldText,
  newText,
  statOnly = false,
}: {
  oldText: string;
  newText: string;
  statOnly?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const holdFollow = useHoldChatFollow();
  const rows = useMemo(() => diffLines(oldText, newText), [oldText, newText]);
  const changes = rows.filter((row) => row.type !== "same");
  if (changes.length === 0) return null;
  const adds = changes.filter((row) => row.type === "add").length;
  const dels = changes.length - adds;
  const cap = expanded ? DIFF_GLIMPSE_ROWS_EXPANDED : DIFF_GLIMPSE_ROWS;
  const shown = statOnly ? [] : changes.slice(0, cap);
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-2 font-mono text-[10px]">
        <span className="text-success">+{adds}</span>
        <span className="text-danger">−{dels}</span>
        {statOnly && <span className="text-fg-faint">行变更</span>}
        {!statOnly && changes.length > DIFF_GLIMPSE_ROWS && (
          <button
            onClick={() => { holdFollow(); setExpanded(!expanded); }}
            className="text-fg-faint transition-colors hover:text-fg-muted"
          >
            {expanded ? "收起" : "展开"}
          </button>
        )}
      </div>
      {shown.length > 0 && (
        <div className="mt-0.5 font-mono text-[10.5px] leading-4.5">
          {shown.map((row, i) => (
            <div
              key={i}
              className={`truncate ${row.type === "del" ? "text-danger/80" : "text-success/80"}`}
            >
              {row.type === "del" ? "−" : "+"} {row.text}
            </div>
          ))}
          {changes.length > shown.length && (
            <div className="text-fg-faint">… {changes.length - shown.length} 处更多变更</div>
          )}
        </div>
      )}
    </div>
  );
}
