/**
 * Direct input to the current User Turn. The target is fixed at submission;
 * missing runtime state never silently changes an append into a new Turn.
 */
import { useState } from "react";
import { Send, Square } from "lucide-react";
import { useConnectionStore } from "../../store/connectionStore";
import { useTurnStore } from "../../store/turnStore";
import { resolveComposerIntent } from "./interactions";
import { cancelActiveTurn, sendUserMessage } from "./turnController";
import { useComposerDraft } from "./composerDraft";
import { PresetEntry } from "./PresetEntry";

export function Composer() {
  const epoch = useConnectionStore((s) => s.epoch);
  const phase = useConnectionStore((s) => s.phase);
  const status = useConnectionStore((s) => s.status);
  const snapshot = useTurnStore((s) => s.snapshot);
  const submittedTurnId = useTurnStore((s) =>
    s.outgoing.find((echo) => echo.kind === "new-turn" && echo.state === "accepted")?.turnId ?? null);
  const historyView = useTurnStore((s) => s.historyView);
  const text = useComposerDraft((s) => s.draft);
  const setText = useComposerDraft((s) => s.setDraft);
  const [sending, setSending] = useState(false);
  const [stopping, setStopping] = useState(false);
  const connected = phase === "connected";
  const intent = resolveComposerIntent(status, snapshot, connected, submittedTurnId);
  const readOnly = historyView;
  const canSend = !readOnly && intent.kind !== "unavailable" && text.trim().length > 0 && !sending;

  const send = async () => {
    if (!canSend) return;
    setSending(true);
    const submitted = text;
    try {
      const sent = await sendUserMessage(epoch, submitted, intent);
      // Do not erase text typed while the request was in flight.
      if (sent && useComposerDraft.getState().draft === submitted) setText("");
    } finally {
      setSending(false);
    }
  };
  const stop = async () => {
    if (stopping) return;
    setStopping(true);
    try { await cancelActiveTurn(epoch); }
    finally { setStopping(false); }
  };

  const placeholder = readOnly ? "Read-only history — replies and edits are disabled"
    : intent.kind === "append" ? "Append to the current turn…"
    : intent.kind === "new-turn" ? "Message TinySoul…"
    : {
        "offline": "Connect to a running TinySoul backend first",
        "not-ready": "The backend is starting…",
        "syncing": "Connecting to the current turn…",
        "finishing": "The current turn is finishing…",
      }[intent.reason];
  const hint = readOnly ? "Back to today to send a message"
    : intent.kind === "unavailable" && intent.reason === "finishing" ? "Your draft is kept until the turn finishes"
    : intent.kind === "unavailable" && intent.reason === "syncing" ? "Your draft is kept while the turn synchronizes"
    : intent.kind === "append" ? "Enter to send · Shift+Enter for newline · sent as input to the current turn"
    : "Enter to send · Shift+Enter for newline";

  return (
    <div className="border-t border-line bg-bg px-4 pt-3 pb-4">
      <div className="mx-auto max-w-3xl">
        <div className={`composer-box rounded-xl border transition-[border-color,box-shadow] ${
          readOnly ? "border-line bg-bg opacity-60"
            : "border-line-strong bg-bg-elev shadow-card focus-within:border-accent focus-within:shadow-(--focus-ring)"
        }`}>
          <div className="flex items-start px-3.5 pt-3 pb-1">
            <span className="composer-prompt mr-2 leading-6 select-none" aria-hidden="true">›</span>
            <textarea value={text} onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void send();
                }
              }}
              placeholder={placeholder}
              disabled={readOnly || !connected}
              rows={Math.min(8, Math.max(1, text.split("\n").length))}
              className="composer-input block w-full flex-1 resize-none bg-transparent text-sm leading-6 outline-none placeholder:text-fg-faint disabled:cursor-not-allowed" />
          </div>
          <div className="flex items-center justify-between gap-2 px-2.5 pb-2">
            <div className="min-w-0 px-1 text-[11px] text-fg-faint">
              <span className="block truncate" title={hint}>{hint}</span>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              {!readOnly && <PresetEntry />}
              {intent.kind === "append" && !text.trim() && !readOnly ? (
                <button onClick={() => void stop()} disabled={stopping}
                  title={stopping ? "Stopping…" : "Stop the current turn"}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-danger text-white shadow-sm transition-colors hover:bg-danger/90 disabled:opacity-60">
                  <Square size={13} />
                </button>
              ) : (
                <button onClick={() => void send()} disabled={!canSend} title="Send"
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-accent-grad text-white shadow-brand transition-colors hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40">
                  <Send size={14} className={sending ? "animate-pulse-dot" : ""} />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
