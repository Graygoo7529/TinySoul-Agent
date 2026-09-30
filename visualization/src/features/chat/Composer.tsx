/**
 * The v2 composer (plan §5.1).
 *
 * The visible intent — new turn / append / queued — is derived from the
 * formal runtime status and the active turn snapshot at send time
 * (resolveComposerIntent), and the same intent drives the placeholder, the
 * hint text and the compact intent chip, so what the user reads is what the
 * submit does. With an empty draft and a cancellable active turn the send
 * position becomes the stop button.
 *
 * The draft lives in useComposerDraft so compose-mode question blocks can
 * place picked text into it; filling the draft never sends. The run-preset
 * quick entry is only a mount point here — the preset workflow wires it.
 */

import { useState } from "react";
import { ArrowUp, CornerDownRight, Send, Square } from "lucide-react";
import { useConnectionStore } from "../../store/connectionStore";
import { useTurnStore } from "../../store/turnStore";
import { canCancelActiveTurn, resolveComposerIntent } from "./interactions";
import { cancelActiveTurn, sendUserMessage } from "./turnController";
import { useComposerDraft } from "./composerDraft";

export function Composer() {
  const epoch = useConnectionStore((s) => s.epoch);
  const phase = useConnectionStore((s) => s.phase);
  const status = useConnectionStore((s) => s.status);
  const snapshot = useTurnStore((s) => s.snapshot);
  const text = useComposerDraft((s) => s.draft);
  const setText = useComposerDraft((s) => s.setDraft);
  const [sending, setSending] = useState(false);

  const connected = phase === "connected";
  const intent = resolveComposerIntent(status, snapshot, connected);
  const cancellable = canCancelActiveTurn(status, snapshot);
  const canSend =
    intent.kind !== "unavailable" && text.trim().length > 0 && !sending;

  const send = async () => {
    if (!canSend) return;
    setSending(true);
    try {
      const sent = await sendUserMessage(epoch, text);
      if (sent) setText("");
    } finally {
      setSending(false);
    }
  };

  const placeholder =
    intent.kind === "unavailable"
      ? intent.reason === "not-ready"
        ? "The backend is starting…"
        : "Connect to a running TinySoul backend first"
      : intent.kind === "append"
        ? "Append to the current turn…"
        : intent.queued
          ? "Queue a new turn…"
          : "Message TinySoul…";

  const hint =
    intent.kind === "append"
      ? "Enter to send · Shift+Enter for newline · sent as input to the current turn"
      : intent.kind === "new-turn" && intent.queued
        ? "Enter to send · Shift+Enter for newline · queued as the next turn"
        : "Enter to send · Shift+Enter for newline";

  const intentChip =
    intent.kind === "append" ? (
      <span
        className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[10px] font-medium text-accent"
        title="This message is appended to the current turn"
      >
        <CornerDownRight size={10} />
        Append to current turn
      </span>
    ) : intent.kind === "new-turn" && intent.queued ? (
      <span
        className="inline-flex items-center gap-1 rounded-full bg-hover px-2 py-0.5 text-[10px] font-medium text-fg-muted"
        title="This message starts a new turn, queued behind the current work"
      >
        <ArrowUp size={10} />
        New turn · queued
      </span>
    ) : null;

  return (
    <div className="border-t border-line bg-bg px-4 pt-3 pb-4">
      <div className="mx-auto max-w-3xl">
        <div className="composer-box rounded-xl border border-line-strong bg-bg-elev shadow-card transition-[border-color,box-shadow] focus-within:border-accent focus-within:shadow-(--focus-ring)">
          <div className="flex items-start px-3.5 pt-3 pb-1">
            <span
              className="composer-prompt mr-2 leading-6 select-none"
              aria-hidden="true"
            >
              ›
            </span>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void send();
                }
              }}
              placeholder={placeholder}
              disabled={intent.kind === "unavailable"}
              rows={Math.min(8, Math.max(1, text.split("\n").length))}
              className="composer-input block w-full flex-1 resize-none bg-transparent text-sm leading-6 outline-none placeholder:text-fg-faint disabled:cursor-not-allowed"
            />
          </div>
          <div className="flex items-center justify-between gap-2 px-2.5 pb-2">
            <div className="flex min-w-0 items-center gap-2 px-1 text-[11px] text-fg-faint">
              {intentChip}
              <span className="min-w-0 truncate">{hint}</span>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              {/* F2-E mount point: the run-preset quick entry renders here. */}
              <div data-slot="preset-entry" />
              {cancellable && !text.trim() ? (
                <button
                  onClick={() => void cancelActiveTurn(epoch)}
                  title="Stop the current turn"
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-danger text-white shadow-sm transition-colors hover:bg-danger/90"
                >
                  <Square size={13} />
                </button>
              ) : (
                <button
                  onClick={() => void send()}
                  disabled={!canSend}
                  title="Send"
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-accent-grad text-white shadow-brand transition-colors hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
                >
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
