/**
 * Shared calm easing for chat-surface motion — entrances, the steps roll,
 * height glides. Mirrors the long-standing cubic-bezier used by the CSS
 * grow-in so JS-driven and CSS-driven motion read as one language.
 */
export const EASE_CALM: [number, number, number, number] = [0.22, 0.9, 0.3, 1];

/** Turn-completion fold: the live status body rolls up into its header
    line; the answer starts streaming once the fold completes. */
export const LIVE_FOLD_MS = 700;
/** Settling pause between turn completion and the fold — the position
    itself is never adjusted on completion. */
export const FOLD_DELAY_MS = 600;
/** The answer stream starts once the fold has finished plus a short beat. */
export const ANSWER_STREAM_DELAY_MS = FOLD_DELAY_MS + LIVE_FOLD_MS + 280;
/** Settle wipe: once the stream ends, the terminal layer wipes away
    top-to-bottom behind a scanline (0.7s) plus a short fade tail; the
    .answer-settling class is kept for this whole window. */
export const SETTLE_WIPE_MS = 900;
