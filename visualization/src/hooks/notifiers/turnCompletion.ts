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
    if (!last || !lastStatus) return;
    if (prevId !== lastTurnId || prevStatus !== "running" || lastStatus === "running") {
      return;
    }
    // "Watching" = on the chat tab and parked at the follow target. The
    // completion choreography already plays in place there — no notice.
    const { activeTab, chatPinnedToBottom } = useAppStore.getState();
    if (activeTab === "chat" && chatPinnedToBottom) return;
    const toast = completionToast(last);
    if (!toast) return;
    const turnId = last.turnId;
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

/** Toast for a finished turn. Maintenance turns announce with their task
    label; a user-requested stop stays silent — the user already knows. */
function completionToast(
  turn: ChatTurn,
): { kind: ToastItem["kind"]; text: string } | null {
  const label = turn.maintenance
    ? turn.maintenance.kind === "home"
      ? "Home 维护"
      : "Memory 维护"
    : null;
  switch (turn.status) {
    case "answered":
      return { kind: "success", text: "新回答已完成" };
    case "completed":
      return { kind: "success", text: label ? `${label}完成` : "轮次已完成" };
    case "failed":
      return { kind: "error", text: label ? `${label}失败` : "轮次失败" };
    case "exhausted":
      return { kind: "info", text: label ? `${label}已达上限` : "轮次已达上限" };
    default:
      return null;
  }
}
