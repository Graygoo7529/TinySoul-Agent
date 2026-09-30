/**
 * Bounded TikZ compile concurrency (plan §21.1). Every compiling block
 * carries its own iframe + TeX wasm worker, so visible blocks compile
 * through a queue with at most TIKZ_MAX_CONCURRENT slots; the rest wait and
 * show a queued state. A slot is released when the compile settles, when the
 * block unmounts, or when its queued request is withdrawn.
 */

export const TIKZ_MAX_CONCURRENT = 2;

export interface TikzSlot {
  release: () => void;
}

interface Waiter {
  grant: () => void;
  cancelled: boolean;
}

let active = 0;
const waiters: Waiter[] = [];

function makeSlot(): TikzSlot {
  let released = false;
  return {
    release: () => {
      if (released) return;
      released = true;
      // Hand the slot to the next waiter that is still interested;
      // withdrawn requests drop out of the queue.
      while (waiters.length > 0) {
        const next = waiters.shift()!;
        if (next.cancelled) continue;
        next.grant();
        return;
      }
      active -= 1;
    },
  };
}

/**
 * Request a compile slot. The promise resolves once the slot is held;
 * `cancel()` withdraws the request while it is still queued (a grant that
 * already happened is unaffected — the holder releases its slot instead).
 */
export function requestTikzSlot(): {
  promise: Promise<TikzSlot>;
  cancel: () => void;
} {
  let waiter: Waiter | null = null;
  const promise = new Promise<TikzSlot>((resolve) => {
    if (active < TIKZ_MAX_CONCURRENT) {
      active += 1;
      resolve(makeSlot());
      return;
    }
    // A queued grant transfers the freed slot — the count stays unchanged.
    waiter = { grant: () => resolve(makeSlot()), cancelled: false };
    waiters.push(waiter);
  });
  return {
    promise,
    cancel: () => {
      if (waiter !== null) waiter.cancelled = true;
    },
  };
}

/** Test hook: drop every held/queued slot so suites stay isolated. */
export function resetTikzSlots(): void {
  active = 0;
  waiters.length = 0;
}
