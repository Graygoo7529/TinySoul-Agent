import { useEffect, useRef, useState } from "react";

const TICK_MS = 24;

/**
 * Simulated streaming typewriter: reveals `target` progressively over a
 * fixed time budget (longer texts reveal more characters per tick, so the
 * cadence always feels like a steady stream). `startDelayMs` holds the
 * first tick back so an outgoing erase animation can finish first. When
 * `active` is false (reduced motion, user-expanded view) the full text
 * shows immediately. A new target restarts the reveal from empty.
 */
export function useTypewriter(
  target: string,
  {
    durationMs = 760,
    startDelayMs = 0,
    active = true,
  }: { durationMs?: number; startDelayMs?: number; active?: boolean } = {},
): { shown: string; typing: boolean } {
  const [count, setCount] = useState(() => (active ? 0 : target.length));
  const prevTarget = useRef(target);

  useEffect(() => {
    if (!active) {
      prevTarget.current = target;
      setCount(target.length);
      return;
    }
    if (prevTarget.current !== target) {
      prevTarget.current = target;
      setCount(0);
    }
    if (target.length === 0) return;
    const perTick = Math.max(1, Math.ceil(target.length / (durationMs / TICK_MS)));
    let interval: number | undefined;
    const start = window.setTimeout(() => {
      interval = window.setInterval(() => {
        setCount((current) => {
          const next = current + perTick;
          if (next < target.length) return next;
          window.clearInterval(interval);
          return target.length;
        });
      }, TICK_MS);
    }, startDelayMs);
    return () => {
      window.clearTimeout(start);
      window.clearInterval(interval);
    };
  }, [target, active, durationMs, startDelayMs]);

  return { shown: target.slice(0, count), typing: count < target.length };
}
