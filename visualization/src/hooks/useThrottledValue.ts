import { useEffect, useRef, useState } from "react";

/**
 * Trailing-edge throttle for rapidly changing values.
 *
 * The derived activity feed can update several times per second while the
 * agent works; rendering every change makes the live status strobe. This
 * hook guarantees each rendered value stays visible for at least
 * `intervalMs` — rapid bursts coalesce into calm, readable steps. The most
 * recent value always flushes through on the trailing edge, so nothing is
 * ever lost.
 */
export function useThrottledValue<T>(value: T, intervalMs = 600): T {
  const [throttled, setThrottled] = useState(value);
  const pending = useRef(value);
  const lastFlush = useRef(0);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    pending.current = value;
    const elapsed = Date.now() - lastFlush.current;
    if (elapsed >= intervalMs) {
      lastFlush.current = Date.now();
      setThrottled(pending.current);
    } else if (timer.current === undefined) {
      timer.current = window.setTimeout(() => {
        timer.current = undefined;
        lastFlush.current = Date.now();
        setThrottled(pending.current);
      }, intervalMs - elapsed);
    }
  }, [value, intervalMs]);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  return throttled;
}
