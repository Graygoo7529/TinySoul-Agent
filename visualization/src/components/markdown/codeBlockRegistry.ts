import type { ComponentType } from "react";

/**
 * CodeBlockRegistry (plan §21.1): explicit registration of rich fence
 * renderers, keyed by a stable language alias. Each entry declares an
 * optional `parse` (fence-body validation; a null result or a thrown value
 * falls back to the plain code block), a `render` component for the parsed
 * content and an optional custom `fallback`. Unknown fences never reach the
 * registry and keep the default code rendering — arbitrary Markdown code is
 * never treated as executable script.
 */

/** The theme renderers compile against (light/dark page theme). */
export type CodeBlockTheme = "light" | "dark";

/**
 * Where the Markdown is being read. Only the live/history distinction has a
 * consumer today (question fence interaction mode); resource-routing fields
 * (day, turn, locators) join this structure with the ResourceRouter work.
 */
export interface MarkdownOrigin {
  /** "history" marks read-only committed conversations. */
  view?: "live" | "history";
}

/** Props every registered block renderer receives. */
export interface CodeBlockRenderProps<T = unknown> {
  /** The parse result; the raw source when the entry declares no `parse`. */
  parsed: T;
  /** The raw fence body. */
  source: string;
  /** The alias the fence matched (already lower-cased). */
  language: string;
  theme: CodeBlockTheme;
  origin: MarkdownOrigin;
}

/** Props for the parse-failure/plain fallback. */
export interface CodeBlockFallbackProps {
  source: string;
  language: string;
}

export interface CodeBlockRegistration<T = unknown> {
  /**
   * Validate/interpret the fence body. Returning null (or throwing) keeps
   * the source visible through the fallback instead of manufacturing a
   * broken rich block.
   */
  parse?: (source: string) => T | null;
  /** The rich renderer. Hooks are safe: it is mounted as a real component. */
  render: ComponentType<CodeBlockRenderProps<T>>;
  /** Parse-failure presentation; defaults to a plain code block. */
  fallback?: ComponentType<CodeBlockFallbackProps>;
}

/** The registry stores entries of heterogeneous parse types behind one
    erased shape; the registration call is the (typed) write boundary. */
type StoredRegistration = {
  parse?: (source: string) => unknown;
  render: ComponentType<CodeBlockRenderProps<unknown>>;
  fallback?: ComponentType<CodeBlockFallbackProps>;
};

const registrations = new Map<string, StoredRegistration>();

/**
 * Register a renderer for one or more language aliases (case-insensitive).
 * Re-registering an alias replaces the entry; assembly code registers each
 * alias once at startup, tests re-register their own doubles.
 */
export function registerCodeBlock<T>(
  aliases: string | readonly string[],
  registration: CodeBlockRegistration<T>,
): void {
  const stored = registration as unknown as StoredRegistration;
  const list = typeof aliases === "string" ? [aliases] : aliases;
  for (const alias of list) {
    registrations.set(alias.toLowerCase(), stored);
  }
}

/** The entry for a fence language, or null when the fence stays plain code. */
export function resolveCodeBlock(
  language: string | null | undefined,
): CodeBlockRegistration | null {
  if (!language) return null;
  return registrations.get(language.toLowerCase()) ?? null;
}
