import { useEffect, useState } from "react";

/**
 * Whether a single-line truncated element's content is wider than its
 * visible box (scrollWidth > clientWidth). Watches the element with a
 * ResizeObserver for layout changes and re-checks when `content` changes
 * (text swaps do not resize the fixed box, so the observer alone misses
 * them). Returns a callback ref so conditionally mounted targets re-arm
 * the observer when they reappear.
 */
export function useTruncated<T extends HTMLElement>(content: unknown) {
  const [node, setNode] = useState<T | null>(null);
  const [truncated, setTruncated] = useState(false);

  useEffect(() => {
    if (!node) return;
    const check = () => setTruncated(node.scrollWidth > node.clientWidth + 1);
    check();
    const observer = new ResizeObserver(check);
    observer.observe(node);
    return () => observer.disconnect();
  }, [node, content]);

  return { ref: setNode, truncated };
}
