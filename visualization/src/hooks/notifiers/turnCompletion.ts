import { useEffect, useRef } from "react";
import { useAppStore, type ToastItem } from "../../store/appStore";
import type { ChatTurn, TurnStatus } from "../../derive/model";

/**
 * Turn-completion notifier: when the latest turn flips from running to a
 * terminal status while the user is not watching it (scrolled away in the
 * chat view, or on another tab entirely), a small toast announces the
 * outcome; its action switches back to the chat tab and requests a glide
 * to that turn. Turns already finished at mount (restored history) and
 * user-requested stops stay silent.
 */
export function useTurnCompletionNotifier(turns: ChatTurn[]) {
  const pushToast = useAppStore((s) => s.pushToast);
  const last = turns.length > 0 ? turns[turns.length - 1] : undefined;
  const lastTurnId = last?.turnId ?? null;
  const lastStatus = last?.status ?? null;
  const prev = useRef<{ id: string | null; status: TurnStatus | null }>({
    id: lastTurnId,
    status: lastStatus,
  });

  useEffect(() => {
    const { id: prevId, status: prevStatus } = prev.current;
    prev.current = { id: lastTurnId, status: lastStatus };
    if (!lastTurnId || !lastStatus) return;
    if (prevId !== lastTurnId || prevStatus !== "running" || lastStatus === "running") {
      return;
    }
    // "Watching" = on the chat tab and parked at the follow target. The
    // completion choreography already plays in place there — no notice.
    const { activeTab, chatPinnedToBottom } = useAppStore.getState();
    if (activeTab === "chat" && chatPinnedToBottom) return;
    const toast = completionToast(lastStatus);
    if (!toast) return;
    const turnId = lastTurnId;
    pushToast(toast.kind, toast.text, {
      label: "查看",
      onClick: () => {
        const store = useAppStore.getState();
        store.setActiveTab("chat");
        store.requestChatScrollTo(turnId);
      },
    });
  }, [lastTurnId, lastStatus, pushToast]);
}

/** Toast for a finished turn. A user-requested stop stays silent — the
    user already knows. */
function completionToast(
  status: TurnStatus,
): { kind: ToastItem["kind"]; text: string } | null {
  switch (status) {
    case "answered":
      return { kind: "success", text: "新回答已完成" };
    case "completed":
      return { kind: "success", text: "轮次已完成" };
    case "failed":
      return { kind: "error", text: "轮次失败" };
    case "exhausted":
      return { kind: "info", text: "轮次已达上限" };
    default:
      return null;
  }
}
