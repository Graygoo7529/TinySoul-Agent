/**
 * c479ca0's compact action inset. Only the input/result boundary uses v2;
 * diff rows, terminal tails and bounded search hits retain the baseline layout.
 * Full result-family views stay in the trace drawer.
 */
import { useMemo, useState, type ReactElement } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Markdown } from "../../components/markdown/Markdown";
import { Crossfade } from "../../components/ui/Crossfade";
import { diffLines } from "../../utils/diff";
import { EASE_CALM } from "../../utils/motion";
import { actionFamily } from "../trace/registry";
import { analysisGist } from "../trace/analysisModel";
import { webPageStateLabel, webResult } from "../trace/webModel";
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
      const interpreter = asString(params.interpreter);
      return <div className="term-block relative">
        {interpreter && <span className="absolute right-1.5 top-1 rounded border border-accent/40 bg-accent-soft px-1 font-mono text-[10px] text-accent">{interpreter}</span>}
        {asString(params.cwd_ref) && <div className="opacity-50"># {asString(params.cwd_ref)}</div>}
        <span className="term-cmd">$ {command}</span>
      </div>;
    }
    if (data.actionId === "memory.memorize" && Array.isArray(params.operations)) {
      const kinds = params.operations.map((op) => asString(asObject(op)?.kind)).filter(Boolean);
      return kinds.length ? <div className="flex flex-wrap gap-1">{kinds.map((kind, i) =>
        <span key={i} className="rounded bg-hover px-1.5 py-px font-mono text-[10px] text-fg-muted">{kind}</span>)}</div> : null;
    }
    if (data.actionId === "core.reason") {
      const blocks = Array.isArray(params.guide_blocks) ? params.guide_blocks : [];
      const guide = asObject(blocks[0]);
      const text = asString(guide?.text);
      const line = text?.split("\n").map((part) => part.trim()).find((part) => part !== "") ?? null;
      return line !== null
        ? <div className="min-w-0">
            <div className="text-[10px] font-medium text-accent">推理任务</div>
            <div className="line-clamp-2 break-words text-[11px] text-fg-muted">{line}</div>
          </div>
        : null;
    }
    if (data.actionId === "subagent.delegate") {
      const brief = asString(params.brief);
      const line = brief?.split("\n").map((part) => part.trim()).find((part) => part !== "") ?? null;
      const connectionId = asString(params.connection_id);
      if (line === null && connectionId === null) return null;
      return <div className="min-w-0">
        {connectionId !== null && <div className="text-[10px] font-medium text-accent">委派 {connectionId}</div>}
        {line !== null && <div className="line-clamp-2 break-words text-[11px] text-fg-muted">{line}</div>}
      </div>;
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
  if (data.actionId === "core.reason") return <ReasonResultGlimpse payload={payload} />;
  const lowFrequency = lowFrequencyGist(data);
  if (lowFrequency !== undefined) return lowFrequency;
  if (family === "analysis") {
    const gist = analysisGist(data.actionId, payload);
    if (gist !== null) return <div className="min-w-0">
      <div className="text-[10px] font-medium text-accent">
        {gist.kind === "report" ? "分析报告" : "资源描述"} · {gist.text.length.toLocaleString()} 字符
      </div>
      {gist.title !== null && <div className="mt-0.5 truncate text-[11px] font-medium text-fg">{gist.title}</div>}
      {gist.summary !== null && <div className="line-clamp-2 break-words text-[11px] text-fg-muted">{gist.summary}</div>}
    </div>;
  }
  if (data.actionId === "web.discover_pages") {
    const discovery = webResult(data.actionId, payload);
    if (discovery?.kind === "discover" && discovery.pages.length > 0) {
      return <div className="space-y-0.5">{discovery.pages.slice(0, SEARCH_GLIMPSE_ITEMS).map((page, index) => {
        if (page.title === null) return null;
        const stateClass = page.state === "visited"
          ? "bg-success-soft text-success"
          : page.state === "failed"
            ? "bg-danger-soft text-danger"
            : "bg-hover text-fg-faint";
        return <div key={page.url ?? index} className="flex min-w-0 items-start gap-1.5 text-[11px]">
          <span className={`shrink-0 rounded px-1 py-px text-[9px] ${stateClass}`}>
            {webPageStateLabel(page.state)}
          </span>
          <div className="min-w-0">
            <div className="truncate text-fg">{page.title}</div>
            {page.state === "failed" && page.failureReason !== null && (
              <div className="line-clamp-1 text-danger/80">{page.failureReason}</div>
            )}
          </div>
        </div>;
      })}</div>;
    }
  }
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

type ChipTone = "accent" | "green" | "gray" | "red";

function Chip({ text, tone = "gray" }: { text: string; tone?: ChipTone }) {
  const className = tone === "accent"
    ? "bg-accent-soft text-accent"
    : tone === "green"
      ? "bg-success-soft text-success"
      : tone === "red"
        ? "bg-danger-soft text-danger"
        : "bg-hover text-fg-muted";
  return <span className={`rounded px-1.5 py-px font-mono text-[9px] ${className}`}>{text}</span>;
}

function ChipRow({ items }: { items: { text: string; tone?: ChipTone }[] }) {
  return <div className="flex flex-wrap gap-1">{items.map((item, index) => <Chip key={index} text={item.text} tone={item.tone} />)}</div>;
}

function GistText({ text }: { text: string }) {
  return <div className="line-clamp-2 break-words text-[11px] text-fg-muted">{text}</div>;
}

function markdownExcerpt(text: string): string {
  const lines = text.split("\n").slice(0, 4).join("\n");
  return lines.length > 240 ? `${lines.slice(0, 240)}…` : lines;
}

function lowFrequencyGist(data: ActionGlimpseData): ReactElement | null | undefined {
  const payload = data.payload;
  if (payload === null || payload === undefined) return undefined;
  const params = asObject(data.params) ?? {};
  if (data.actionId === "core.wait") {
    const kind = asString(payload.event_kind);
    const label = kind === "job" ? "等待 Job 事件" : kind === "timer" ? "等待定时器" : kind === "event" ? "等待环境事件" : "等待";
    const timeout = asNumber(payload.timeout_seconds);
    const topic = asString(payload.topic);
    const source = asString(payload.source);
    const eventId = asString(payload.event_id);
    return <div className="space-y-1">
      <ChipRow items={[{ text: label, tone: "accent" }, ...(timeout !== null ? [{ text: `${timeout}s` }] : [])]} />
      {(topic !== null || source !== null || eventId !== null) && <GistText text={eventId ?? topic ?? source ?? ""} />}
    </div>;
  }
  if (data.actionId === "core.job.status" || data.actionId === "core.job.stop") {
    const jobId = asString(payload.job_id);
    const state = asString(payload.state);
    const summary = asString(payload.summary);
    return <div className="space-y-1">
      <ChipRow items={[
        ...(jobId !== null ? [{ text: jobId, tone: "accent" as const }] : []),
        ...(state !== null ? [{ text: state, tone: state === "completed" ? "green" as const : state === "failed" || state === "stopped" ? "red" as const : "gray" as const }] : []),
      ]} />
      {summary !== null && summary !== "" && <GistText text={summary} />}
    </div>;
  }
  if (data.actionId === "subagent.delegate") {
    const connectionId = asString(payload.connection_id);
    const jobId = asString(payload.job_id);
    const state = asString(payload.state);
    return <div className="space-y-1">
      <ChipRow items={[
        ...(connectionId !== null ? [{ text: connectionId, tone: "accent" as const }] : []),
        ...(jobId !== null ? [{ text: jobId, tone: "accent" as const }] : []),
        { text: "已受理", tone: "accent" },
        ...(state !== null ? [{ text: state, tone: "gray" as const }] : []),
      ]} />
    </div>;
  }
  if (data.actionId === "subagent.connect") {
    const connectionId = asString(payload.connection_id);
    const agentId = asString(payload.agent_id);
    return <div className="space-y-1">
      <div className="text-[10px] font-medium text-accent">已连接</div>
      <ChipRow items={[
        ...(connectionId !== null ? [{ text: connectionId, tone: "accent" as const }] : []),
        ...(agentId !== null ? [{ text: agentId }] : []),
      ]} />
    </div>;
  }
  if (data.actionId === "subagent.agents") {
    const agents = Array.isArray(payload.agents) ? payload.agents : [];
    const items = agents.flatMap((entry) => {
      const id = asString(asObject(entry)?.agent_id);
      return id !== null ? [{ text: id }] : [];
    });
    return items.length > 0 ? <div className="space-y-1"><div className="text-[10px] font-medium text-accent">可委派 Agent</div><ChipRow items={items.slice(0, 3)} /></div> : undefined;
  }
  if (data.actionId === "subagent.respond") {
    const jobId = asString(payload.job_id);
    const requestId = asString(payload.request_id);
    return <div className="space-y-1">
      <div className="text-[10px] font-medium text-accent">已回应</div>
      <ChipRow items={[...(jobId !== null ? [{ text: jobId, tone: "accent" as const }] : []), ...(requestId !== null ? [{ text: requestId }] : [])]} />
    </div>;
  }
  if (data.actionId === "subagent.collect") {
    const text = asString(payload.text);
    const jobId = asString(payload.job_id);
    const resultRef = asString(payload.result_ref);
    return <div className="space-y-1">
      {jobId !== null && <div className="text-[10px] font-medium text-accent">读取输出 {jobId}</div>}
      {text !== null && text !== "" ? <GistText text={text} /> : resultRef !== null ? <div className="font-mono text-[11px] text-accent">{resultRef}</div> : null}
    </div>;
  }
  if (data.actionId === "subagent.disconnect") {
    const connectionId = asString(payload.connection_id);
    return <div className="space-y-1"><div className="text-[10px] font-medium text-accent">已断开</div>{connectionId !== null && <ChipRow items={[{ text: connectionId, tone: "accent" }]} />}</div>;
  }
  if (data.actionId === "expand.describe_servers") {
    const servers = Array.isArray(payload.servers) ? payload.servers : [];
    const items = servers.flatMap((entry) => {
      const id = asString(asObject(entry)?.server_id);
      return id !== null ? [{ text: id }] : [];
    });
    return items.length > 0 ? <div className="space-y-1"><div className="text-[10px] font-medium text-accent">MCP 服务</div><ChipRow items={items.slice(0, 3)} /></div> : undefined;
  }
  if (data.actionId === "expand.describe_tools") {
    const tools = Array.isArray(payload.tools) ? payload.tools : [];
    const items = tools.flatMap((entry) => {
      const id = asString(asObject(entry)?.tool_name);
      return id !== null ? [{ text: id }] : [];
    });
    return items.length > 0 ? <div className="space-y-1"><div className="text-[10px] font-medium text-accent">MCP 工具</div><ChipRow items={items.slice(0, 3)} /></div> : undefined;
  }
  if (data.actionId === "expand.call") {
    const server = asString(params.server_id);
    const tool = asString(params.tool_name);
    const content = Array.isArray(payload.content) ? payload.content : [];
    const first = content.map(asObject).find((entry) => asString(entry?.text) !== null);
    const text = first !== undefined && first !== null ? asString(first.text) : null;
    const resultRef = asString(payload.result_ref);
    return <div className="space-y-1">
      {(server !== null || tool !== null) && <div className="font-mono text-[10px] font-medium text-accent">{server ?? ""}{server !== null && tool !== null ? ":" : ""}{tool ?? ""}</div>}
      {text !== null ? <GistText text={text} /> : resultRef !== null ? <div className="font-mono text-[11px] text-accent">{resultRef}</div> : null}
    </div>;
  }
  if (data.actionId === "core.session.organize") {
    const created = asObject(payload.created_refs);
    const first = created !== null ? Object.entries(created)[0] : undefined;
    if (first !== undefined) {
      const [name, ref] = first;
      return <div className="space-y-0.5"><div className="text-[10px] font-medium text-accent">新建解释 {name}</div>{typeof ref === "string" && <div className="font-mono text-[11px] text-accent">{ref}</div>}</div>;
    }
    const changed = Array.isArray(payload.changed_refs) ? payload.changed_refs.filter((value): value is string => typeof value === "string") : [];
    return changed.length > 0 ? <div className="space-y-0.5"><div className="text-[10px] font-medium text-accent">变更引用</div>{changed.slice(0, 2).map((ref) => <div key={ref} className="truncate font-mono text-[11px] text-accent">{ref}</div>)}</div> : undefined;
  }
  if (data.actionId === "memory.write" || data.actionId === "memory.write_daily") {
    const markdown = asString(params.markdown);
    const ref = asString(payload.ref);
    return <div className="space-y-1">
      <ChipRow items={[{ text: "已写入", tone: "green" }]} />
      {markdown !== null && markdown.trim() !== ""
        ? <Markdown className="md-calm text-[11px]" origin={{ ref: "" }}>{markdownExcerpt(markdown)}</Markdown>
        : ref !== null ? <div className="font-mono text-[11px] text-accent">{ref}</div> : null}
    </div>;
  }
  if (data.actionId === "home.diff") {
    const items = Array.isArray(payload.items) ? payload.items : [];
    for (const entry of items) {
      const item = asObject(entry);
      if (item === null) continue;
      const before = asString(asObject(item.actual)?.text) ?? "";
      const after = asString(asObject(item.runtime)?.text) ?? "";
      if (before !== after) return <DiffGlimpse oldText={before} newText={after} />;
    }
    return undefined;
  }
  if (data.actionId === "home.review") {
    const items = Array.isArray(payload.items) ? payload.items : [];
    const item = asObject(items[0]);
    if (item === null) return undefined;
    const ref = asString(item.ref);
    const decision = asString(item.decision);
    const reason = asString(item.reason);
    return <div className="space-y-1">
      <ChipRow items={[
        ...(decision !== null ? [{ text: decision, tone: decision === "accept" ? "green" as const : "gray" as const }] : []),
        ...(item.reviewed === false ? [{ text: "not reviewed" }] : []),
      ]} />
      {ref !== null && <div className="font-mono text-[11px] text-accent">{ref}</div>}
      {reason !== null && reason !== "" && <GistText text={reason} />}
    </div>;
  }
  return undefined;
}

function ReasonResultGlimpse({ payload }: { payload: Record<string, unknown> }) {
  let scalar: { key: string; value: string } | null = null;
  for (const [key, value] of Object.entries(payload)) {
    if (typeof value === "string" && value.trim() !== "") {
      const text = value.trim();
      scalar = { key, value: text.length > 180 ? `${text.slice(0, 180)}…` : text };
      break;
    }
    if (typeof value === "number" && Number.isFinite(value)) {
      scalar = { key, value: String(value) };
      break;
    }
    if (typeof value === "boolean") {
      scalar = { key, value: String(value) };
      break;
    }
  }
  return <div className="min-w-0">
    <div className="flex items-center gap-1.5 text-[10px]">
      <span className="rounded bg-accent-soft px-1.5 py-px font-mono text-accent">JSON</span>
      {scalar === null && <span className="text-fg-faint">对象 · {Object.keys(payload).length} 个字段</span>}
    </div>
    {scalar !== null && (
      <div className="mt-0.5 break-words font-mono text-[11px] text-fg-muted">
        <span className="text-accent">{scalar.key}</span>: {scalar.value}
      </div>
    )}
  </div>;
}

function WriteResultGlimpse({ actionId, payload }: { actionId: string; payload: Record<string, unknown> }) {
  const link = asString(payload.ref) ?? asString(payload.path);
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
export function DiffGlimpse({
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
