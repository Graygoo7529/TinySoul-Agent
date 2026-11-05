import { effectiveLocale } from "../i18n/locale";
import type { Locale } from "../i18n/types";

export function formatDateTime(ts: number, locale: Locale = effectiveLocale()): string {
  const d = new Date(ts * 1000);
  return d.toLocaleString(locale, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

/** Format a duration between two epoch-second timestamps (or a delta). */
export function formatDuration(from: number, to?: number): string {
  const seconds = Math.max(0, (to ?? nowSeconds()) - from);
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  if (minutes < 60) return `${minutes}m ${rest}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

/** Compact token count, e.g. 12.4k. */
export function formatTokens(value: number): string {
  const KIBI = 1024;
  const MEBI = 1024 * 1024;
  if (value < KIBI) return `${value}`;
  if (value < MEBI) return `${(value / KIBI).toFixed(1)}k`;
  return `${(value / MEBI).toFixed(2)}M`;
}

function nowSeconds(): number {
  return Date.now() / 1000;
}
