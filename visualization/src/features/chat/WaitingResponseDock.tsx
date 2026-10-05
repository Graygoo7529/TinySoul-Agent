import { useEffect, useState } from "react";
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
 */
export function WaitingResponseDock() {
  const [submitted, setSubmitted] = useState<{ targetId: string; question: TurnQuestion } | null>(null);
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

  if (targetId === null || question === null) return null;

  return (
    <div className="waiting-dock-root absolute inset-x-0 bottom-0 z-(--z-overlay) pointer-events-none" data-waiting-dock>
      <div className="waiting-dock-scrim pointer-events-none absolute inset-x-0 bottom-0 h-[min(70vh,34rem)]" aria-hidden="true" />
      <div
        className="waiting-response-dock pointer-events-auto relative mx-auto max-h-[min(72vh,38rem)] w-[min(720px,calc(100%-1.5rem))] overflow-y-auto rounded-2xl border border-accent/35 bg-bg-elev/95 p-3 shadow-pop backdrop-blur-md animate-slide-up"
        role="dialog"
        aria-label="Waiting for your reply"
        aria-live="polite"
      >
        <QuestionCard
          key={question.question_id}
          epoch={epoch}
          turnId={targetId}
          item={null}
          live={question}
          reply={null}
          commentAsBubble
          onSubmitted={(_draft: QuestionDraft) => setSubmitted({ targetId, question })}
        />
      </div>
    </div>
  );
}
