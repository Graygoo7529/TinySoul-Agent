import { useEffect, useState } from "react";

/**
 * Whether an element's content is taller than its visible box. Watches the
 * clipped container and its direct children with a ResizeObserver so the
 * flag tracks animated growth on either side of the clip boundary (the
 * steps viewport clamps its own box while the inner flow keeps growing).
 *
 * Returns a callback ref so conditionally mounted targets re-arm the
 * observer when they appear.
 */
export function useOverflowing<T extends HTMLElement>() {
  const [node, setNode] = useState<T | null>(null);
  const [overflowing, setOverflowing] = useState(false);

  useEffect(() => {
    if (!node) return;
    const check = () => setOverflowing(node.scrollHeight > node.clientHeight + 1);
    check();
    const observer = new ResizeObserver(check);
    observer.observe(node);
    for (const child of Array.from(node.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [node]);

  return { ref: setNode, overflowing };
}
