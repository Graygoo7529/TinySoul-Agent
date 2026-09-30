import { useEffect, useState } from "react";

/**
 * Whether an element's content is taller than its visible box, plus a
 * running-max latch of the content's height. Watches the clipped container
 * and its direct children with a ResizeObserver so both track animated
 * growth on either side of the clip boundary (the steps viewport clamps its
 * own box while the inner flow keeps growing).
 *
 * `contentMaxHeight` only ever grows while observed — callers use it as a
 * never-shrink floor for the container. Returns a callback ref so
 * conditionally mounted targets re-arm the observer when they appear.
 */
export function useOverflowing<T extends HTMLElement>() {
  const [node, setNode] = useState<T | null>(null);
  const [overflowing, setOverflowing] = useState(false);
  const [contentMaxHeight, setContentMaxHeight] = useState(0);

  useEffect(() => {
    if (!node) return;
    const check = () => {
      setOverflowing(node.scrollHeight > node.clientHeight + 1);
      const inner = node.firstElementChild as HTMLElement | null;
      if (inner) setContentMaxHeight((prev) => Math.max(prev, inner.offsetHeight));
    };
    check();
    const observer = new ResizeObserver(check);
    observer.observe(node);
    for (const child of Array.from(node.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [node]);

  return { ref: setNode, node, overflowing, contentMaxHeight };
}
