/**
 * Resource reference classification (plan §21.2).
 *
 * A reference is routable only when it strictly matches one of the owner
 * protocols (workspace:/home:/memory:/session:/turn:trace…), is a web URL, or
 * is a relative reference (no protocol before the fragment) that an origin
 * owner can resolve. Arbitrary colon text ("note: important", "C:\\…") never
 * becomes a ref. The checks mirror the owner ref rules closely enough to
 * reject malformed text; the backend resolve (API-18) stays authoritative.
 */

import type { HomeView } from "../../api/v2/types";

/** Reading context a reference is interpreted against. */
export interface ResourceOrigin {
  /** Owner ref of the document being read; required by relative references. */
  ref?: string;
  /** Day the content belongs to (history/archive reads). */
  day?: string;
  /** Turn the content belongs to (trace/dynamic bindings). */
  turnId?: string;
  /** Home view for Home content (default effective). */
  homeView?: HomeView;
}

export type ReferenceKind =
  | "external"
  | "workspace"
  | "home"
  | "memory"
  | "memory-dynamic"
  | "session"
  | "trace"
  | "relative"
  | "other";

export const DYNAMIC_MEMORY_REFERENCES = [
  "memory:current",
  "memory:latest",
  "memory:target",
] as const;

/** Split `reference` into its resource part and `#fragment` (null if none). */
export function splitFragment(reference: string): {
  resource: string;
  fragment: string | null;
} {
  const at = reference.indexOf("#");
  if (at < 0) return { resource: reference, fragment: null };
  return {
    resource: reference.slice(0, at),
    fragment: reference.slice(at + 1),
  };
}

function isWorkspacePath(path: string): boolean {
  if (path === "" || path.includes("\\") || path.startsWith("/")) return false;
  if (path.includes("\0")) return false;
  for (const part of path.split("/")) {
    if (part === "" || part === "." || part === ".." || part.includes(":")) {
      return false;
    }
  }
  return true;
}

const MEMORY_KINDS = ["daily", "entity", "concept", "fact", "note"] as const;

function isMemoryReference(resource: string): boolean {
  for (const kind of MEMORY_KINDS) {
    const prefix = `memory:${kind}/`;
    if (!resource.startsWith(prefix)) continue;
    const cite = resource.slice(prefix.length);
    // A cite is one name segment (optionally the physical *.md form); it never
    // contains whitespace or another colon.
    if (cite === "" || /[\s:/]/.test(cite)) return false;
    return true;
  }
  return false;
}

function isHomeReference(resource: string): boolean {
  const body = resource.slice("home:".length);
  if (/\s/.test(body)) return false;
  const [category, space, ...path] = body.split("/");
  if (!path.length || !isWorkspacePath(path.join("/"))) return false;
  if (category === "top" || category === "resource") return space === "agent" || space === "skills";
  return category === "mount" && ((space === "domain" && path.length === 1) || (space === "action" && path.length === 2));
}

const SESSION_REF = /^session:(map|topics|annotations|unclassified|history(?:\/\d+)?|(?:turn|node|edge)\/\d{4}-\d{2}-\d{2}\/[1-9]\d*)$/;

function isTraceReference(resource: string): boolean {
  return /^turn:trace\/\d{4}-\d{2}-\d{2}\/[1-9]\d*$/.test(resource);
}

/** Classify one reference string; the fragment never affects the kind. */
export function classifyReference(reference: string): ReferenceKind {
  const { resource } = splitFragment(reference);
  if (/^https?:\/\//i.test(resource)) return "external";
  if (resource.startsWith("workspace:")) {
    return isWorkspacePath(resource.slice("workspace:".length))
      ? "workspace"
      : "other";
  }
  if (
    (DYNAMIC_MEMORY_REFERENCES as readonly string[]).includes(resource)
  ) {
    return "memory-dynamic";
  }
  if (resource.startsWith("memory:")) {
    return isMemoryReference(resource) ? "memory" : "other";
  }
  if (resource.startsWith("home:")) {
    return isHomeReference(resource) ? "home" : "other";
  }
  if (resource.startsWith("session:")) {
    return SESSION_REF.test(resource) ? "session" : "other";
  }
  if (resource.startsWith("turn:trace/")) {
    return isTraceReference(resource) ? "trace" : "other";
  }
  if (!resource.includes(":")) return "relative";
  return "other";
}

/** `true` when the reference can become a ref control. */
export function isRoutableReference(reference: string): boolean {
  return classifyReference(reference) !== "other";
}

/** A `#L12` / `#L12-L15` line fragment; null for any other fragment text. */
export function parseLineFragment(
  fragment: string | null,
): { startLine: number; endLine: number } | null {
  if (fragment === null) return null;
  const match = /^L(\d+)(?:-L(\d+))?$/.exec(fragment);
  if (match === null) return null;
  const startLine = Number.parseInt(match[1]!, 10);
  const endLine = match[2] !== undefined ? Number.parseInt(match[2], 10) : startLine;
  if (!Number.isFinite(startLine) || startLine < 1) return null;
  return endLine >= startLine ? { startLine, endLine } : null;
}

/** The turn identity of a trace reference; null for non-trace references. */
export function traceTurnId(reference: string): string | null {
  const { resource } = splitFragment(reference);
  return isTraceReference(resource) ? resource.slice("turn:trace/".length) : null;
}
