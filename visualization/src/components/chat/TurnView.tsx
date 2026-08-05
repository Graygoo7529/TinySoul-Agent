import { AlertTriangle, Bot, History, PanelRightOpen } from "lucide-react";
import type { ChatTurn } from "../../derive/model";
import { useAppStore } from "../../store/appStore";
import { formatDuration, formatTokens } from "../../utils/format";
import { Button } from "../ui/Button";
import { Markdown } from "../markdown/Markdown";
import { TurnStatusBadge } from "../trace/semantic";
import { LiveStatus } from "./LiveStatus";

/**
 * One user turn in the conversation: the user message bubble(s) followed by
 * the agent row — live status while running, rendered final answer when done,
 * plus a footer with turn metadata and the trace-drawer entry.
 */
export function TurnView({ turn }: { turn: ChatTurn }) {
  const openTurnDetail = useAppStore((s) => s.openTurnDetail);
  const running = turn.status === "running";
  const stats = turn.actionStats;

  return (
    <div className="animate-fade-in space-y-3">
      {turn.userMessages.map((message, i) => (
        <div key={i} className="flex justify-end">
          <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-accent px-3.5 py-2.5 text-sm leading-6 whitespace-pre-wrap break-words text-white shadow-sm">
            {message}
          </div>
        </div>
      ))}

      <div className="flex gap-2.5">
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-purple-500 text-white shadow-sm">
          <Bot size={15} />
        </div>
        <div className="min-w-0 flex-1 space-y-2">
          {running && <LiveStatus turn={turn} />}

          {turn.assistantText && (
            <div className="rounded-2xl rounded-tl-sm border border-line bg-bg-elev px-4 py-3 shadow-sm">
              <Markdown>{turn.assistantText}</Markdown>
            </div>
          )}

          {turn.status === "failed" && (
            <div className="rounded-xl border border-danger/30 bg-danger-soft px-3.5 py-2.5 text-[13px] text-danger">
              <div className="flex items-start gap-2">
                <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                <span className="break-words">
                  {turn.failureMessage || "Turn failed"}
                </span>
              </div>
              {(turn.failure?.module ||
                turn.failure?.kind ||
                turn.failure?.reason) && (
                <div className="mt-1.5 pl-[23px] font-mono text-[11px] text-danger/80">
                  {[
                    turn.failure.module,
                    turn.failure.kind,
                    turn.failure.reason,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
              )}
              {turn.failure?.feedback && turn.failure.feedback.length > 0 && (
                <ul className="mt-1.5 list-disc space-y-0.5 pl-9 text-danger/90">
                  {turn.failure.feedback.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {!running && (
            <div className="flex flex-wrap items-center gap-2 px-1">
              <TurnStatusBadge status={turn.status} />
              {turn.recovered && (
                <span
                  className="inline-flex items-center gap-1 text-[11px] text-fg-faint"
                  title="Restored from backend history after reconnect"
                >
                  <History size={11} />
                  restored
                </span>
              )}
              <span className="text-[11px] text-fg-faint">
                {formatDuration(turn.startedAt, turn.endedAt)}
              </span>
              <span className="text-[11px] text-fg-faint">·</span>
              <span className="text-[11px] text-fg-muted">{turn.summary}</span>
              {stats.total > 0 && (
                <>
                  <span className="text-[11px] text-fg-faint">·</span>
                  <span className="text-[11px] text-fg-faint">
                    {stats.success} ok
                    {stats.failed > 0 ? ` · ${stats.failed} failed` : ""}
                    {stats.timeout > 0 ? ` · ${stats.timeout} timeout` : ""}
                  </span>
                </>
              )}
              {turn.usage.calls > 0 && (
                <>
                  <span className="text-[11px] text-fg-faint">·</span>
                  <span className="text-[11px] text-fg-faint">
                    {turn.usage.calls} calls ·{" "}
                    {formatTokens(turn.usage.promptTokens)} →{" "}
                    {formatTokens(turn.usage.completionTokens)}
                    {turn.modelName ? ` · ${turn.modelName}` : ""}
                  </span>
                </>
              )}
              <Button
                variant="ghost"
                size="xs"
                className="ml-auto"
                onClick={() => openTurnDetail(turn.turnId)}
              >
                <PanelRightOpen size={12} />
                Details
              </Button>
            </div>
          )}

          {running && (
            <div className="flex px-1">
              <Button
                variant="ghost"
                size="xs"
                className="ml-auto"
                onClick={() => openTurnDetail(turn.turnId)}
              >
                <PanelRightOpen size={12} />
                Details
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
