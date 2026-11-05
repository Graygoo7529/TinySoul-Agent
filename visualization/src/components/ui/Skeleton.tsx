/**
 * Structured loading placeholders for list-shaped areas (directory trees and
 * catalogs). The shimmer reuses the existing `.animate-shimmer` sweep; the
 * global `.ui-reduced-motion` rule already flattens it to a static block, so
 * there is no separate degraded variant. The caller keeps its own sr-only
 * loading label — these blocks are purely visual.
 */

import type { CSSProperties, ReactElement } from "react";

/** One shimmer block. */
export function Skeleton({
  className = "",
  style,
}: {
  className?: string;
  style?: CSSProperties;
}): ReactElement {
  return (
    <div
      className={`animate-shimmer rounded-md ${className}`}
      style={style}
      aria-hidden="true"
    />
  );
}

const ROW_WIDTHS = ["86%", "72%", "94%", "64%", "80%"];

/** Icon-square + name-bar rows previewing a directory/catalog shape. */
export function SkeletonRows({ rows = 4 }: { rows?: number }): ReactElement {
  return (
    <div className="space-y-2.5 px-2 py-3" aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="flex items-center gap-2">
          <Skeleton className="h-2.5 w-2.5 shrink-0 rounded-sm" />
          <Skeleton
            className="h-2"
            style={{ width: ROW_WIDTHS[index % ROW_WIDTHS.length] }}
          />
        </div>
      ))}
    </div>
  );
}
