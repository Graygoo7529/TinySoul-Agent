/**
 * Resource reference classification (plan §21.2).
 *
 * A reference is routable only when it strictly matches one of the owner
 * protocols (workspace:/home:/memory:/session:/turn:trace…), is a web URL, or
 * is a relative reference (no protocol before the fragment) that an origin
 * owner can resolve. Arbitrary colon text ("note: important", "C:\\…") never
 * becomes a link. The checks mirror the owner link rules closely enough to
 * reject malformed text; the backend resolve (API-18) stays authoritative.
 */

import type { HomeView } from "../../api/v2/types";

/** Reading context a reference is interpreted against. */
export interface ResourceOrigin {
  /** Owner link of the document being read; required by relative references. */
  link?: string;
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
  if (body === "" || /\s/.test(body)) return false;
  for (const space of ["skills_domain:", "skills_action:"]) {
    if (body.startsWith(space)) return body.length > space.length;
  }
  const at = body.indexOf("@");
  if (at >= 0) {
    const space = body.slice(0, at);
    const name = body.slice(at + 1);
    return (space === "agent" || space === "skills") && name !== "";
  }
  const slash = body.indexOf("/");
  if (slash > 0) {
    const space = body.slice(0, slash);
    return (
      (space === "agent" || space === "skills") && slash < body.length - 1
    );
  }
  return false;
}

const SESSION_REF =
  /^session:(map|topics|annotations|history|history\/\d+|turn\/[\w-]+|node\/[\w-]+|edge\/[\w-]+)$/;

function isTraceReference(resource: string): boolean {
  if (resource.startsWith("turn:trace@")) {
    return resource.length > "turn:trace@".length;
  }
  if (resource.startsWith("turn:trace/")) {
    const parts = resource.split("/");
    return parts.length === 3 && parts[1] !== "" && parts[2] !== "";
  }
  return false;
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
  if (resource.startsWith("turn:trace@") || resource.startsWith("turn:trace/")) {
    return isTraceReference(resource) ? "trace" : "other";
  }
  if (!resource.includes(":")) return "relative";
  return "other";
}

/** `true` when the reference can become a link control. */
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
  return { startLine, endLine: Math.max(startLine, endLine) };
}

/** The turn identity of a trace reference; null for non-trace references. */
export function traceTurnId(reference: string): string | null {
  const { resource } = splitFragment(reference);
  if (resource.startsWith("turn:trace@")) {
    const id = resource.slice("turn:trace@".length);
    return id === "" ? null : id;
  }
  if (resource.startsWith("turn:trace/")) {
    const parts = resource.split("/");
    return parts.length === 3 && parts[1] !== "" ? parts[1] : null;
  }
  return null;
}
