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
export function TurnView({ turn, isLatest }: { turn: ChatTurn; isLatest?: boolean }) {
  const openTurnTrace = useAppStore((s) => s.openTurnTrace);
  const running = turn.status === "running";
  // The latest finished turn keeps its LiveStatus as a settled card — the
  // final activity trail stays visible until the next user turn starts,
  // then it naturally folds away (the new turn mounts its own live card).
  const showSettled = !running && isLatest === true && turn.activity.length > 0;
  const stats = turn.actionStats;

  return (
    <div className="animate-fade-in space-y-4">
      {turn.userMessages.map((message, i) => (
        <div key={i} className="flex justify-end">
          <div className="bubble-user max-w-[85%] rounded-2xl rounded-tr-sm px-3.5 py-2.5 text-sm leading-6 whitespace-pre-wrap break-words">
            {message}
          </div>
        </div>
      ))}

      <div className="flex gap-2.5">
        <div className="bg-accent-grad mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-white shadow-brand">
          <Bot size={15} />
        </div>
        <div className="min-w-0 flex-1 space-y-2">
          {running && <LiveStatus turn={turn} />}
          {showSettled && <LiveStatus turn={turn} mode="settled" />}

          {turn.assistantText && (
            <div className="animate-answer-in answer-card shadow-card rounded-2xl rounded-tl-sm border border-line bg-bg-elev px-4 py-3">
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
                onClick={() => openTurnTrace(turn.turnId)}
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
                onClick={() => openTurnTrace(turn.turnId)}
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
