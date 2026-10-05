/**
 * Chunked owner-content rendering (Home content/diff, Memory documents).
 *
 * Owner pages deliver a document as paged {ref, text} chunks (each a line
 * range of the same document). Every chunk renders through the shared
 * Markdown renderer with the reading origin so links/images route through
 * the ResourceRouter; a `#L…` fragment locates the chunk whose own ref
 * fragment covers it, scrolls it into view and marks it — opening a chunk
 * never reloads or reinstalls anything on the model side.
 */

import { useEffect, useMemo, useRef, type ReactElement } from "react";

import { Markdown } from "../../components/markdown/Markdown";
import type { MarkdownOrigin } from "../../components/markdown/codeBlockRegistry";
import type { JsonValue } from "../../api/v2/json";
import { parseLineFragment, splitFragment } from "./reference";

export interface ContentChunk {
  ref: string;
  text: string;
}

/**
 * Decode one {ref, text} chunk from an untyped page.json item; null when the
 * shape is not a content chunk. Typed owner pages (Home content/diff, Memory
 * document) carry the shape already; plain envelopes (Memory active) convert
 * at the boundary.
 */
export function decodeContentChunk(value: JsonValue): ContentChunk | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  if (typeof record.ref !== "string" || typeof record.text !== "string") {
    return null;
  }
  return { ref: record.ref, text: record.text };
}

/** True when the target fragment intersects the chunk's own line range. */
function fragmentHits(chunkRef: string, target: { startLine: number; endLine: number }): boolean {
  const own = parseLineFragment(splitFragment(chunkRef).fragment);
  if (own === null) return false;
  return own.startLine <= target.endLine && target.startLine <= own.endLine;
}

export function ChunkedMarkdown({
  items,
  fragment,
  origin,
}: {
  items: ContentChunk[];
  /** Raw `#…` fragment (without the leading #) to locate, if any. */
  fragment: string | null;
  origin: MarkdownOrigin;
}): ReactElement {
  const target = useMemo(() => parseLineFragment(fragment), [fragment]);
  const hitIndex = useMemo(() => {
    if (target === null) return -1;
    return items.findIndex((item) => fragmentHits(item.ref, target));
  }, [items, target]);
  const groups = useMemo(() => {
    const result: Array<{ base: string; items: ContentChunk[]; start: number; end: number }> = [];
    items.forEach((item, index) => {
      const base = splitFragment(item.ref).resource;
      const previous = result[result.length - 1];
      if (previous?.base === base && previous.end === index - 1) {
        previous.items.push(item);
        previous.end = index;
      } else {
        result.push({ base, items: [item], start: index, end: index });
      }
    });
    return result;
  }, [items]);
  const hitGroupIndex = useMemo(() => groups.findIndex((group) =>
    hitIndex >= group.start && hitIndex <= group.end), [groups, hitIndex]);
  const locatedRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    locatedRef.current?.scrollIntoView({ block: "center" });
  }, [hitGroupIndex, items.length]);

  return (
    <div className="space-y-1">
      {groups.map((group, groupIndex) => {
        const located = groupIndex === hitGroupIndex;
        return (
          <div
            key={`${group.base}:${group.start}`}
            ref={located ? locatedRef : undefined}
            data-chunk-ref={group.items[0].ref}
            data-chunk-refs={group.items.map((item) => item.ref).join(" ")}
            className={
              located
                ? "rounded-lg bg-accent-soft/50 px-3 py-1 ring-1 ring-accent/40"
                : "px-3 py-1"
            }
          >
            {group.items.slice(1).map((item, offset) => {
              const itemIndex = group.start + offset + 1;
              return <div key={item.ref} data-chunk-ref={item.ref}
                className={itemIndex === hitIndex ? "sr-only ring-1 ring-accent" : "sr-only"}
                aria-hidden="true">{item.text}</div>;
            })}
            <Markdown origin={origin}>{group.items.map((item) => item.text).join("")}</Markdown>
          </div>
        );
      })}
    </div>
  );
}
