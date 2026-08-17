import { useEffect, useRef } from "react";
import { AlertTriangle, Bot, History, PanelRightOpen } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import type { ChatTurn } from "../../derive/model";
import { useAppStore } from "../../store/appStore";
import { formatDuration, formatTokens } from "../../utils/format";
import { EASE_CALM, ANSWER_STREAM_DELAY_MS, FOLD_DELAY_MS, LIVE_FOLD_MS } from "../../utils/motion";
import { useTypewriter } from "../../hooks/useTypewriter";
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
  // Stream the answer only when the turn completes while this view is
  // mounted; answers from restored history render instantly.
  const streamAnswer = useRef(turn.status === "running" && !turn.assistantText).current;
  // The latest finished turn keeps its LiveStatus as a settled card — the
  // final activity trail stays visible until the next user turn starts,
  // then it naturally folds away (the new turn mounts its own live card).
  const showSettled = !running && isLatest === true && turn.activity.length > 0;
  const stats = turn.actionStats;

  return (
    <div data-turn-root={turn.turnId} className="animate-fade-in space-y-4">
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
          {/* one card instance across the run/finish boundary: completing
              the turn folds the live trail up into the settled bar */}
          {(running || showSettled) && (
            <LiveStatus turn={turn} mode={running ? "live" : "settled"} />
          )}

          {turn.assistantText && (
            <AnswerCard turnId={turn.turnId} text={turn.assistantText} stream={streamAnswer} />
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

/**
 * The final answer card. When the turn completes while this view is
 * mounted, the card materializes just as the live status finishes folding
 * away, then the text streams in at a fixed cadence (~220 chars/s, capped
 * at 7s for long answers) under a soft streaming glow. Answers from
 * restored history render instantly. While streaming, the chat view keeps
 * the turn top-anchored (answerStreamingTurnId).
 */
function AnswerCard({ turnId, text, stream }: { turnId: string; text: string; stream: boolean }) {
  const reduced = useReducedMotion();
  const setAnswerStreaming = useAppStore((s) => s.setAnswerStreaming);
  const streaming = stream && !reduced;
  const { shown, typing } = useTypewriter(text, {
    // fixed cadence ≈220 chars/s; very long answers finish within 7s. The
    // stream starts only after the fold has finished plus a short beat.
    durationMs: Math.min(text.length * 4.5, 7000),
    startDelayMs: streaming ? ANSWER_STREAM_DELAY_MS : 0,
    active: streaming,
  });

  useEffect(() => {
    if (!(streaming && typing)) return;
    setAnswerStreaming(turnId);
    return () => setAnswerStreaming(null);
  }, [streaming, typing, turnId, setAnswerStreaming]);

  return (
    <motion.div
      className={`answer-card rounded-2xl rounded-tl-sm border px-4 py-3 ${
        typing ? "answer-streaming" : ""
      }`}
      initial={reduced ? false : { opacity: 0, y: 8, filter: "blur(3px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      transition={{
        duration: 0.5,
        ease: EASE_CALM,
        delay: streaming ? (FOLD_DELAY_MS + LIVE_FOLD_MS - 120) / 1000 : 0,
      }}
    >
      <Markdown>{typing ? `${shown}▍` : shown}</Markdown>
    </motion.div>
  );
}
