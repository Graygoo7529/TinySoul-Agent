import { useEffect, useState } from "react";
import { ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import type { TurnQuestion } from "../../api/v2/types";
import { useConnectionStore, selectActiveTurnId } from "../../store/connectionStore";
import { useTurnStore } from "../../store/turnStore";
import { QuestionCard } from "./QuestionCard";
import { useLiveWaitingQuestion } from "./ConversationRows";
import type { QuestionDraft } from "./questionContent";

const EMPTY_ITEMS: ReturnType<typeof useTurnStore.getState>["items"] = [];

/**
 * The single active question surface. It lives at the ChatView layout edge so
 * a long activity stream cannot push the reply controls below the viewport.
 * The question and submit path remain owned by QuestionCard/turnController.
 *
 * Features:
 * - Covers Composer when active (user replies through the dock)
 * - Blurs background content (ConversationView) for focus
 * - Collapsible: user can minimize to scroll conversation history
 * - Spring animation for natural feel
 */
export function WaitingResponseDock() {
  const [submitted, setSubmitted] = useState<{ targetId: string; question: TurnQuestion } | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  const epoch = useConnectionStore((state) => state.epoch);
  const activeTurnId = useConnectionStore(selectActiveTurnId);
  const displayedTurnId = useTurnStore((state) => state.turnId);
  const targetId = activeTurnId ?? displayedTurnId;
  const liveQuestion = useLiveWaitingQuestion(targetId);
  const items = useTurnStore((state) => targetId !== null && targetId !== state.turnId
    ? state.runtimeProjections[targetId]?.items ?? EMPTY_ITEMS
    : state.items);
  const hasFormalReply = submitted !== null && items.some((item) =>
    item.role === "user.reply" && item.question_id === submitted.question.question_id,
  );
  const question = liveQuestion ?? (submitted?.targetId === targetId && !hasFormalReply ? submitted.question : null);

  useEffect(() => {
    if (hasFormalReply) setSubmitted(null);
    else if (submitted !== null && liveQuestion !== null && submitted.question.question_id !== liveQuestion.question_id) setSubmitted(null);
    else if (submitted !== null && targetId !== submitted.targetId && liveQuestion === null) setSubmitted(null);
  }, [hasFormalReply, liveQuestion, submitted, targetId]);

  // Reset collapsed state when question changes
  useEffect(() => {
    if (question !== null) {
      setCollapsed(false);
    }
  }, [question?.question_id]);

  if (targetId === null || question === null) return null;

  return (
    <div
      className="waiting-dock-root fixed inset-x-0 bottom-0 z-[var(--z-overlay)] pointer-events-none"
      data-waiting-dock
    >
      {/* Background blur scrim - only when expanded */}
      <AnimatePresence>
        {!collapsed && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
            className="waiting-dock-scrim absolute inset-x-0 bottom-0 h-[min(80vh,42rem)]"
            aria-hidden="true"
          />
        )}
      </AnimatePresence>

      {/* Dock card */}
      <motion.div
        layout
        initial={{ y: 100, opacity: 0, scale: 0.95 }}
        animate={{
          y: 0,
          opacity: 1,
          scale: 1
        }}
        exit={{ y: 100, opacity: 0, scale: 0.95 }}
        transition={{
          type: "spring",
          damping: 25,
          stiffness: 300,
          mass: 0.8
        }}
        className={`
          waiting-response-dock pointer-events-auto relative mx-auto mb-3
          w-[min(720px,calc(100%-1.5rem))] rounded-2xl border border-accent/35
          bg-bg-elev/95 shadow-pop
          ${collapsed ? "" : "max-h-[min(72vh,38rem)]"}
        `}
        role="dialog"
        aria-label="Waiting for your reply"
        aria-live="polite"
        aria-expanded={!collapsed}
      >
        {/* Top decorative glow line */}
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-accent/50 to-transparent" />

        {/* Top control bar */}
        <div className="sticky top-0 z-10 border-b border-accent/20 bg-bg-elev/98 backdrop-blur-md rounded-t-2xl">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-hover/50 rounded-t-2xl"
            aria-label={collapsed ? "Expand question" : "Collapse question"}
          >
            {/* Indicator */}
            <div className="flex items-center gap-2 text-accent">
              <Loader2 size={14} className="animate-spin-slow" />
              <span className="text-[12px] font-medium">
                {collapsed ? "Agent is waiting for your reply" : "Question"}
              </span>
            </div>

            {/* Collapse/Expand control */}
            <div className="ml-auto flex items-center gap-2">
              {collapsed && (
                <span className="text-[11px] text-fg-faint">
                  {question.options.length} {question.options.length === 1 ? "option" : "options"}
                </span>
              )}
              {collapsed ? (
                <ChevronUp size={14} className="text-fg-faint" />
              ) : (
                <ChevronDown size={14} className="text-fg-faint" />
              )}
            </div>
          </button>
        </div>

        {/* Question content - only when expanded */}
        <AnimatePresence mode="wait">
          {!collapsed && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-y-auto"
              style={{ maxHeight: "calc(72vh - 3rem)" }}
            >
              <div className="p-4">
                <QuestionCard
                  key={question.question_id}
                  epoch={epoch}
                  turnId={targetId}
                  item={null}
                  live={question}
                  reply={null}
                  onSubmitted={(_draft: QuestionDraft) => {
                    setSubmitted({ targetId, question });
                    // Auto-collapse after submit
                    setTimeout(() => setCollapsed(true), 500);
                  }}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}
