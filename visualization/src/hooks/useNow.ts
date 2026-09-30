/**
 * useNow — tick every N milliseconds to drive live clocks.
 *
 * Returns the current Date; components destructure to access .getTime() etc.
 * When `enabled` is false, stops ticking (settled cards don't need timers).
 */

import { useEffect, useState } from "react";

export function useNow(enabled: boolean, intervalMs: number): Date {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    if (!enabled) return;

    const timer = setInterval(() => {
      setNow(new Date());
    }, intervalMs);

    return () => clearInterval(timer);
  }, [enabled, intervalMs]);

  return now;
}
