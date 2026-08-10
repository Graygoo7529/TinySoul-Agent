import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type Key,
  type ReactNode,
} from "react";
import { useReducedMotion } from "motion/react";

/**
 * Exit-layer fade duration (the `xfade-out` animation in index.css); the
 * layer is retired shortly after it finishes.
 */
const EXIT_MS = 240;

/**
 * Crossfade swap primitive. When `id` changes, the outgoing content fades
 * out on an absolute layer while the incoming content fades in, and the
 * wrapper's height glides from the old content height to the new one
 * instead of jumping. Same-id content updates refresh silently (no fade),
 * and any resulting height change glides too (e.g. an expand toggle).
 * Under reduced motion everything swaps instantly.
 */
export function Crossfade({
  id,
  className,
  children,
}: {
  /** Identity of the content; a change triggers the crossfade swap. */
  id: Key;
  className?: string;
  children: ReactNode;
}) {
  const reduced = useReducedMotion();
  const latest = useRef(children);
  latest.current = children;

  const [current, setCurrent] = useState<{ id: Key; node: ReactNode }>({ id, node: children });
  const [exiting, setExiting] = useState<{ id: Key; node: ReactNode } | null>(null);
  const currentRef = useRef(current);
  currentRef.current = current;

  const boxRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const prevHeight = useRef<number | null>(null);
  const releaseTimer = useRef<number | undefined>(undefined);

  // Swap on id change: park the outgoing render on the exit layer, mount
  // the new one. Same id: refresh the content silently in place.
  useEffect(() => {
    if (currentRef.current.id === id) {
      if (currentRef.current.node !== latest.current) {
        setCurrent({ id, node: latest.current });
      }
      return;
    }
    if (reduced) {
      setExiting(null);
      setCurrent({ id, node: latest.current });
      return;
    }
    setExiting(currentRef.current);
    setCurrent({ id, node: latest.current });
  }, [id, children, reduced]);

  // Retire the exit layer once its fade has played.
  useEffect(() => {
    if (!exiting) return;
    const timer = window.setTimeout(() => setExiting(null), EXIT_MS + 80);
    return () => window.clearTimeout(timer);
  }, [exiting]);

  // Height glide: whenever the natural content height changes between
  // commits (a swap, or an in-place expand), transition the wrapper's
  // explicit height, then release back to auto so later reflows stay
  // natural. The content node is measured — not the wrapper — so an
  // in-flight glide never retriggers itself.
  useLayoutEffect(() => {
    const box = boxRef.current;
    const content = contentRef.current;
    if (!box || !content) return;
    const from = prevHeight.current;
    const to = content.offsetHeight;
    if (!reduced && from !== null && Math.abs(from - to) > 1) {
      box.style.transition = "none";
      box.style.height = `${from}px`;
      void box.offsetHeight; // commit the start height before animating
      box.style.transition = "";
      box.style.height = `${to}px`;
      window.clearTimeout(releaseTimer.current);
      releaseTimer.current = window.setTimeout(() => {
        box.style.height = "";
      }, 350);
    }
    prevHeight.current = to;
  });

  useEffect(
    () => () => {
      window.clearTimeout(releaseTimer.current);
    },
    [],
  );

  return (
    <div ref={boxRef} className={className ? `xfade ${className}` : "xfade"}>
      <div
        key={current.id}
        ref={contentRef}
        className={exiting ? "animate-xfade-in" : undefined}
      >
        {current.node}
      </div>
      {exiting && (
        <div className="xfade-exit animate-xfade-out" aria-hidden="true">
          {exiting.node}
        </div>
      )}
    </div>
  );
}
