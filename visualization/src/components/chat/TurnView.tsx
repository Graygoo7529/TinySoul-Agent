import { AlertTriangle, Bot, PanelRightOpen } from "lucide-react";
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
            <div className="flex items-start gap-2 rounded-xl border border-danger/30 bg-danger-soft px-3.5 py-2.5 text-[13px] text-danger">
              <AlertTriangle size={15} className="mt-0.5 shrink-0" />
              <span className="break-words">{turn.failureMessage || "Turn failed"}</span>
            </div>
          )}

          {!running && (
            <div className="flex flex-wrap items-center gap-2 px-1">
              <TurnStatusBadge status={turn.status} />
              <span className="text-[11px] text-fg-faint">
                {formatDuration(turn.startedAt, turn.endedAt)}
              </span>
              <span className="text-[11px] text-fg-faint">·</span>
              <span className="text-[11px] text-fg-muted">{turn.summary}</span>
              {turn.usage.calls > 0 && (
                <>
                  <span className="text-[11px] text-fg-faint">·</span>
                  <span className="text-[11px] text-fg-faint">
                    {turn.usage.calls} calls · {formatTokens(turn.usage.promptTokens)} →{" "}
                    {formatTokens(turn.usage.completionTokens)} tokens
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
