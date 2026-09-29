import { useEffect, useRef, useState, type RefObject } from "react";

/**
 * Delays expensive diagram rendering until the block actually enters the
 * viewport (or the caller asks for eager rendering). jsdom has no
 * IntersectionObserver; there the block is treated as visible immediately.
 */
export function useInViewport<T extends HTMLElement>(
  eager: boolean,
): [RefObject<T | null>, boolean] {
  const ref = useRef<T | null>(null);
  const [visible, setVisible] = useState(
    eager || typeof IntersectionObserver === "undefined",
  );

  useEffect(() => {
    if (visible || typeof IntersectionObserver === "undefined") return;
    const element = ref.current;
    if (!element) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setVisible(true);
        observer.disconnect();
      }
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [visible]);

  return [ref, visible];
}
