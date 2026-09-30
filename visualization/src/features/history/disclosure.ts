/**
 * Session map / inspect DisclosurePage reading (plan §7, API-08).
 *
 * A Session DisclosurePage carries four item families in `items` (owner
 * order, see kernel DisclosurePage.render): owner content (annotations,
 * session turn headers, fact details), navigation hints
 * `{kind:"child", ref, title, clue}`, fact/interpretation relations
 * `{kind:"relation", source, target, relation, basis}` and evidence sources
 * `{kind:"source", ref}`. This module narrows the dynamic page items into the
 * view models the history panels render; unparseable items are dropped, never
 * guessed.
 *
 * Interpretations (thread/note nodes and relation edges, `basis:
 * "interpretation"`) and immutable facts stay visually distinct; retracted
 * annotations keep their owner status.
 */

import type { JsonObject, JsonValue } from "../../api/v2/json";

/** A navigation hint (`{kind:"child"}`) — opens its ref's own page. */
export interface DisclosureChild {
  ref: string;
  title: string;
  clue: string;
}

/** A relation row (`{kind:"relation"}`); basis is "fact" or an annotation. */
export interface DisclosureRelation {
  source: string;
  target: string;
  relation: string;
  basis: string;
}

export interface ParsedDisclosureItems {
  /** Owner content items in page order (annotations, headers, facts). */
  content: JsonObject[];
  children: DisclosureChild[];
  relations: DisclosureRelation[];
  /** Evidence refs the page declares (`{kind:"source"}`). */
  sources: string[];
}

export function parseDisclosureItems(items: JsonValue[]): ParsedDisclosureItems {
  const content: JsonObject[] = [];
  const children: DisclosureChild[] = [];
  const relations: DisclosureRelation[] = [];
  const sources: string[] = [];
  for (const item of items) {
    if (!isRecord(item)) continue;
    if (item.kind === "child") {
      if (typeof item.ref === "string" && typeof item.title === "string") {
        children.push({
          ref: item.ref,
          title: item.title,
          clue: typeof item.clue === "string" ? item.clue : "",
        });
      }
      continue;
    }
    if (item.kind === "relation") {
      if (
        typeof item.source === "string" &&
        typeof item.target === "string" &&
        typeof item.relation === "string"
      ) {
        relations.push({
          source: item.source,
          target: item.target,
          relation: item.relation,
          basis: typeof item.basis === "string" ? item.basis : "fact",
        });
      }
      continue;
    }
    if (item.kind === "source") {
      if (typeof item.ref === "string") sources.push(item.ref);
      continue;
    }
    content.push(item);
  }
  return { content, children, relations, sources };
}

// ---------------------------------------------------------------------------
// Interpretations (semantic annotations)
// ---------------------------------------------------------------------------

/** A thread/note node (`basis:"interpretation"` with a title). */
export interface AnnotationNodeView {
  family: "node";
  ref: string;
  /** Owner kind: "thread" | "note". */
  kind: string;
  title: string;
  body: string;
  status: string;
  sourceRefs: string[];
}

/** A relation edge between nodes/facts (`basis:"interpretation"`, no title). */
export interface AnnotationEdgeView {
  family: "edge";
  ref: string;
  source: string;
  target: string;
  relation: string;
  body: string;
  status: string;
  sourceRefs: string[];
}

export type AnnotationView = AnnotationNodeView | AnnotationEdgeView;

/**
 * Narrow one content item to an annotation view. Nodes carry
 * `kind: thread|note` and a title; edges carry source/target/relation and no
 * `kind` field (SemanticEdge.to_json). Anything else returns null.
 */
export function parseAnnotation(item: JsonObject): AnnotationView | null {
  if (item.basis !== "interpretation" || typeof item.ref !== "string") {
    return null;
  }
  const body = typeof item.body === "string" ? item.body : "";
  const status = typeof item.status === "string" ? item.status : "active";
  const sourceRefs = Array.isArray(item.source_refs)
    ? item.source_refs.filter((ref): ref is string => typeof ref === "string")
    : [];
  if (
    typeof item.source === "string" &&
    typeof item.target === "string" &&
    typeof item.relation === "string"
  ) {
    return {
      family: "edge",
      ref: item.ref,
      source: item.source,
      target: item.target,
      relation: item.relation,
      body,
      status,
      sourceRefs,
    };
  }
  if (typeof item.title === "string") {
    return {
      family: "node",
      ref: item.ref,
      kind: typeof item.kind === "string" ? item.kind : "note",
      title: item.title,
      body,
      status,
      sourceRefs,
    };
  }
  return null;
}

/**
 * Annotation list hints carry `"{status}: {body excerpt}"` as their clue.
 * Split the known status prefix for display; the authoritative status lives
 * on the annotation's own page.
 */
export function splitAnnotationClue(clue: string): {
  status: string | null;
  text: string;
} {
  const match = /^(active|retracted): ([\s\S]*)$/.exec(clue);
  if (match === null) return { status: null, text: clue };
  return { status: match[1] ?? null, text: match[2] ?? "" };
}

// ---------------------------------------------------------------------------
// Ref identities
// ---------------------------------------------------------------------------

/** `session:turn/<id>` → `<id>`; null for any other ref. */
export function sessionTurnId(ref: string): string | null {
  const match = /^session:turn\/([a-z0-9_-]+)$/.exec(ref);
  return match?.[1] ?? null;
}

/** True for interpretation refs (semantic nodes/edges). */
export function isAnnotationRef(ref: string): boolean {
  return ref.startsWith("session:node/") || ref.startsWith("session:edge/");
}

/** Compact display form of a Session ref; the full ref stays in tooltips. */
export function shortRef(ref: string): string {
  const node = /^session:(node|edge)\/([a-z0-9_-]+)$/.exec(ref);
  if (node !== null) return `${node[1]} ${node[2]!.slice(0, 8)}`;
  if (ref.startsWith("session:turn/")) return ref.slice("session:turn/".length);
  return ref;
}

function isRecord(value: JsonValue): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
