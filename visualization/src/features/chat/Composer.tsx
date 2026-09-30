/**
 * The v2 composer (plan §5.1).
 *
 * The visible intent — new turn / append / queued — is derived from the
 * formal runtime status and the active turn snapshot (resolveComposerIntent).
 * While an appendable turn is active the intent chip is a menu: the default
 * is "append to this turn", but the user may explicitly pick "queue as next
 * turn"; the choice is pinned at submit time, so a state change mid-flight
 * never redirects the message to another target. The same intent drives the
 * placeholder, the hint text and the chip, so what the user reads is what
 * the submit does. With an empty draft and a cancellable active turn the
 * send position becomes the stop button.
 *
 * The draft lives in useComposerDraft so compose-mode question blocks can
 * place picked text into it; filling the draft never sends. The run-preset
 * quick entry (PresetEntry) renders at the data-slot="preset-entry" position.
 */

import { useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  Check,
  ChevronUp,
  CornerDownRight,
  Send,
  Square,
} from "lucide-react";
import { useConnectionStore } from "../../store/connectionStore";
import { useTurnStore } from "../../store/turnStore";
import {
  applyIntentChoice,
  canCancelActiveTurn,
  resolveComposerIntent,
  type ComposerIntent,
  type ComposerIntentChoice,
} from "./interactions";
import { cancelActiveTurn, sendUserMessage } from "./turnController";
import { useComposerDraft } from "./composerDraft";
import { PresetEntry } from "./PresetEntry";

export function Composer() {
  const epoch = useConnectionStore((s) => s.epoch);
  const phase = useConnectionStore((s) => s.phase);
  const status = useConnectionStore((s) => s.status);
  const snapshot = useTurnStore((s) => s.snapshot);
  const historyView = useTurnStore((s) => s.historyView);
  const text = useComposerDraft((s) => s.draft);
  const setText = useComposerDraft((s) => s.setDraft);
  const [sending, setSending] = useState(false);
  const [choice, setChoice] = useState<ComposerIntentChoice | null>(null);

  const connected = phase === "connected";
  const derived = resolveComposerIntent(status, snapshot, connected);
  const intent = applyIntentChoice(derived, choice);
  const cancellable = canCancelActiveTurn(status, snapshot);
  // A committed conversation is read-only: the composer is not an input path
  // here, and the whole unit degrades instead of looking sendable.
  const readOnly = historyView;
  const canSend =
    !readOnly && intent.kind !== "unavailable" && text.trim().length > 0 && !sending;

  const send = async () => {
    if (!canSend) return;
    setSending(true);
    try {
      // The intent (and its target) is pinned at submit time; a state change
      // afterwards never re-aims this message at another turn (plan §5.1).
      const sent = await sendUserMessage(epoch, text, intent);
      if (sent) {
        setText("");
        setChoice(null);
      }
    } finally {
      setSending(false);
    }
  };

  const placeholder = readOnly
    ? "Read-only history — replies and edits are disabled"
    : intent.kind === "unavailable"
      ? intent.reason === "not-ready"
        ? "The backend is starting…"
        : "Connect to a running TinySoul backend first"
      : intent.kind === "append"
        ? "Append to the current turn…"
        : intent.queued
          ? "Queue a new turn…"
          : "Message TinySoul…";

  const hint = readOnly
    ? "Back to today to send a message"
    : intent.kind === "append"
      ? "Enter to send · Shift+Enter for newline · sent as input to the current turn"
      : intent.kind === "new-turn" && intent.queued
        ? "Enter to send · Shift+Enter for newline · queued as the next turn"
        : "Enter to send · Shift+Enter for newline";

  return (
    <div className="border-t border-line bg-bg px-4 pt-3 pb-4">
      <div className="mx-auto max-w-3xl">
        <div
          className={`composer-box rounded-xl border transition-[border-color,box-shadow] ${
            readOnly
              ? "border-line bg-bg opacity-60"
              : "border-line-strong bg-bg-elev shadow-card focus-within:border-accent focus-within:shadow-(--focus-ring)"
          }`}
        >
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
              disabled={readOnly || intent.kind === "unavailable"}
              rows={Math.min(8, Math.max(1, text.split("\n").length))}
              className="composer-input block w-full flex-1 resize-none bg-transparent text-sm leading-6 outline-none placeholder:text-fg-faint disabled:cursor-not-allowed"
            />
          </div>
          <div className="flex items-center justify-between gap-2 px-2.5 pb-2">
            <div className="flex min-w-0 items-center gap-2 px-1 text-[11px] text-fg-faint">
              {readOnly ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-hover px-2 py-0.5 text-[10px] font-medium text-fg-faint">
                  Read-only
                </span>
              ) : (
                <IntentChip intent={intent} derived={derived} choice={choice} onChoose={setChoice} />
              )}
              <span className="min-w-0 truncate">{hint}</span>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              {!readOnly && <PresetEntry />}
              {cancellable && !text.trim() && !readOnly ? (
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

/**
 * The compact intent chip (plan §5.1). While the formal state offers only
 * one possible intent the chip is a static label; with an appendable turn
 * active it opens a small menu with the explicit alternatives (append /
 * queue as next turn) — no full-width mode panel.
 */
function IntentChip({
  intent,
  derived,
  choice,
  onChoose,
}: {
  intent: ComposerIntent;
  derived: ComposerIntent;
  choice: ComposerIntentChoice | null;
  onChoose: (choice: ComposerIntentChoice) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);

  // Dismiss on Escape and on outside pointer-down.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    const onPointer = (event: MouseEvent) => {
      if (rootRef.current !== null && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onPointer);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onPointer);
    };
  }, [open]);

  const label =
    intent.kind === "append"
      ? "Append to current turn"
      : intent.kind === "new-turn" && intent.queued
        ? "New turn · queued"
        : intent.kind === "new-turn"
          ? "New turn"
          : null;
  if (label === null) return null;

  const icon =
    intent.kind === "append" ? <CornerDownRight size={10} /> : <ArrowUp size={10} />;
  const tone =
    intent.kind === "append"
      ? "bg-accent-soft text-accent"
      : intent.kind === "new-turn" && intent.queued
        ? "bg-hover text-fg-muted"
        : "bg-hover text-fg-faint";
  const title =
    intent.kind === "append"
      ? "This message is appended to the current turn"
      : intent.kind === "new-turn" && intent.queued
        ? "This message starts a new turn, queued behind the current work"
        : "This message starts a new turn";

  // Only an appendable turn offers a real choice; every other state has a
  // single possible intent and the chip stays a plain label.
  if (derived.kind !== "append") {
    return (
      <span
        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${tone}`}
        title={title}
      >
        {icon}
        {label}
      </span>
    );
  }

  const pick = (next: ComposerIntentChoice) => {
    onChoose(next);
    setOpen(false);
  };

  return (
    <span ref={rootRef} className="relative inline-flex">
      <button
        type="button"
        aria-expanded={open}
        title={`${title} — click to choose the send intent`}
        onClick={() => setOpen((value) => !value)}
        className={`inline-flex cursor-pointer items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${tone}`}
      >
        {icon}
        {label}
        <ChevronUp
          size={9}
          className={open ? "transition-transform" : "rotate-180 transition-transform"}
        />
      </button>
      {open && (
        <span className="absolute bottom-full left-0 z-(--z-drawer) mb-1.5 block w-52 rounded-xl border border-line bg-bg-elev p-1 shadow-pop">
          <IntentOption
            active={choice !== "queue"}
            label="Append to current turn"
            note="Sent as input to the running turn"
            onClick={() => pick("append")}
          />
          <IntentOption
            active={choice === "queue"}
            label="Queue as next turn"
            note="Starts a new turn after the current work"
            onClick={() => pick("queue")}
          />
        </span>
      )}
    </span>
  );
}

function IntentOption({
  active,
  label,
  note,
  onClick,
}: {
  active: boolean;
  label: string;
  note: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-hover"
    >
      <span className="min-w-0 flex-1">
        <span className="block text-[12px] font-medium text-fg">{label}</span>
        <span className="block text-[10.5px] text-fg-faint">{note}</span>
      </span>
      {active && <Check size={12} className="shrink-0 text-accent" />}
    </button>
  );
}
