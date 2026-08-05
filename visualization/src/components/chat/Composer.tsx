import { useMemo, useState } from "react";
import { Send, Square } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { randomId } from "../../utils/randomId";

export function Composer({ hasRunningTurn }: { hasRunningTurn?: boolean }) {
  const client = useAppStore((s) => s.client);
  const statusTurnActive = useAppStore((s) => s.status?.turn_active ?? false);
  // The derived event stream is fresher than the 2s status poll; trust either.
  const turnActive = hasRunningTurn || statusTurnActive;
  const connected = useAppStore((s) => s.connection.status === "connected");
  const recordLocalInput = useAppStore((s) => s.recordLocalInput);
  const pushToast = useAppStore((s) => s.pushToast);
  const stopPending = useAppStore((s) => s.stopPending);
  const setStopPending = useAppStore((s) => s.setStopPending);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);

  const canSend = useMemo(
    () => connected && !!client && text.trim().length > 0 && !sending,
    [connected, client, text, sending],
  );

  const send = async () => {
    const value = text.trim();
    if (!client || !value) return;
    setSending(true);
    const commandId = randomId();
    try {
      // Echo locally first: the accepted event is authoritative but may
      // arrive on the WebSocket a moment later.
      recordLocalInput(commandId, value);
      const receipt = await client.submitInput({
        text: value,
        command_id: commandId,
        metadata: { client_message_id: commandId },
      });
      if (!receipt.accepted) {
        pushToast("error", "The backend rejected the input.");
      }
      setText("");
    } catch (error) {
      pushToast(
        "error",
        `Failed to send: ${error instanceof Error ? error.message : String(error)}`,
      );
    } finally {
      setSending(false);
    }
  };

  const stop = async () => {
    if (!client || stopPending) return;
    setStopPending(true);
    try {
      const receipt = await client.submitControl({
        kind: "stop_turn",
        command_id: randomId(),
      });
      if (!receipt.accepted) {
        setStopPending(false);
        pushToast("error", "The backend rejected the stop request.");
      }
    } catch (error) {
      setStopPending(false);
      pushToast(
        "error",
        `Failed to stop the turn: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  };

  return (
    <div className="border-t border-line bg-bg px-4 pt-3 pb-4">
      <div className="mx-auto max-w-3xl">
        <div className="rounded-xl border border-line-strong bg-bg-elev shadow-sm transition-colors focus-within:border-accent">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder={
              connected
                ? turnActive
                  ? "Append to the current turn…"
                  : "Message TinySoul…"
                : "Connect to a running TinySoul backend first"
            }
            disabled={!connected}
            rows={Math.min(8, Math.max(1, text.split("\n").length))}
            className="block w-full resize-none bg-transparent px-3.5 pt-3 pb-1 text-sm leading-6 outline-none placeholder:text-fg-faint disabled:cursor-not-allowed"
          />
          <div className="flex items-center justify-between px-2.5 pb-2">
            <div className="px-1 text-[11px] text-fg-faint">
              Enter to send · Shift+Enter for newline
              {turnActive && " · sent while running becomes appended input"}
            </div>
            {/*
             * The send position adapts: while a turn runs and there is no
             * pending text it becomes the stop button, so the primary action
             * is always "interrupt the agent"; with pending text it stays a
             * send button (appended input).
             */}
            {turnActive && !text.trim() ? (
              <button
                onClick={() => void stop()}
                disabled={stopPending}
                title={stopPending ? "Stopping…" : "Stop the current turn"}
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-danger text-white shadow-sm transition-colors hover:bg-danger/90 disabled:opacity-60"
              >
                <Square size={13} />
              </button>
            ) : (
              <SendButton canSend={canSend} sending={sending} onClick={() => void send()} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function SendButton({
  canSend,
  sending,
  onClick,
}: {
  canSend: boolean;
  sending: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={!canSend}
      title="Send"
      className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-white shadow-sm transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-40"
    >
      <Send size={14} className={sending ? "animate-pulse-dot" : ""} />
    </button>
  );
}
