/**
 * Shared calm easing for chat-surface motion — entrances, the steps roll,
 * height glides. Mirrors the long-standing cubic-bezier used by the CSS
 * grow-in so JS-driven and CSS-driven motion read as one language.
 */
export const EASE_CALM: [number, number, number, number] = [0.22, 0.9, 0.3, 1];

/** Turn-completion fold: the live status body rolls up into its header
    line; the answer starts streaming once the fold completes. */
export const LIVE_FOLD_MS = 550;
