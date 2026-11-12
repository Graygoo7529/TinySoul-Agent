import { invoke, isTauri } from "@tauri-apps/api/core";
import { open as openDirectoryDialog } from "@tauri-apps/plugin-dialog";
import { openPath } from "@tauri-apps/plugin-opener";

/**
 * Frontend local store facade (plan: 本地数据目录). Device-local data lives
 * in a user-chosen directory on desktop (atomic writes via the Rust
 * local_store commands) and falls back to WebView localStorage elsewhere —
 * the browser case is surfaced honestly as "browser storage".
 *
 * Reads are synchronous from a hydrated cache so existing consumers (zustand
 * persist, connection discovery) keep their call shapes; writes update the
 * cache immediately and persist through a per-key save queue (serialized,
 * revision-coalesced — a directory switch never issues a late write).
 */

export interface LocalStoreState {
  /** "tauri" = a real directory is configured and active. */
  mode: "tauri" | "browser";
  /** The configured directory (tauri mode only). */
  dir: string | null;
}

/** Choosing a directory either copies current data over (fresh dir) or
 *  loads the data found there (reload required to apply everywhere). */
export type ChooseResult =
  | { kind: "copied"; dir: string; keys: number }
  | { kind: "loaded"; dir: string; keys: number }
  | { kind: "cancelled" };

const BROWSER_PREFIX = "tinysoul-local:";
const cache = new Map<string, string>();
const listeners = new Set<() => void>();

let state: LocalStoreState = { mode: "browser", dir: null };
let generation = 0;

function notify(): void {
  for (const listener of listeners) listener();
}

export function subscribeLocalStore(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Test-only: clear the module-level cache and state between suites. */
export function resetLocalStoreForTests(): void {
  cache.clear();
  queues.clear();
  state = { mode: "browser", dir: null };
  generation += 1;
}

/** Sync snapshot for render paths; pair with subscribeLocalStore. */
export function localStoreState(): LocalStoreState {
  return state;
}

function readBrowser(key: string): string | null {
  try {
    // Read-through migration: the legacy plain key still answers until the
    // value is rewritten under the store namespace.
    return localStorage.getItem(`${BROWSER_PREFIX}${key}`) ?? localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeBrowser(key: string, payload: string): void {
  try {
    localStorage.setItem(`${BROWSER_PREFIX}${key}`, payload);
  } catch {
    // storage may be unavailable; the cache still holds the value.
  }
}

function browserKeys(): string[] {
  try {
    const keys: string[] = [];
    for (let index = 0; index < localStorage.length; index += 1) {
      const name = localStorage.key(index);
      if (name?.startsWith(BROWSER_PREFIX)) keys.push(name.slice(BROWSER_PREFIX.length));
    }
    return keys;
  } catch {
    return [];
  }
}

/** Hydrate the cache once, before consumers read. Safe to call again. */
export async function initLocalStore(): Promise<LocalStoreState> {
  if (isTauri()) {
    try {
      const backend = await invoke<{ dir: string | null }>("local_store_state");
      state = backend.dir !== null ? { mode: "tauri", dir: backend.dir } : { mode: "browser", dir: null };
    } catch {
      state = { mode: "browser", dir: null };
    }
    if (state.mode === "tauri") {
      try {
        const keys = await invoke<string[]>("local_store_list");
        for (const key of keys) {
          const payload = await invoke<string | null>("local_store_read", { key });
          if (payload !== null) cache.set(key, payload);
        }
      } catch {
        // A directory that vanished keeps the browser fallback per key.
      }
    }
  }
  // Migrate legacy plain-localStorage keys into the store namespace (the
  // originals stay untouched).
  for (const key of ["tinysoul-ui-state", "tinysoul-web-connection"]) {
    if (cache.has(key)) continue;
    try {
      const legacy = localStorage.getItem(key);
      if (legacy !== null) {
        cache.set(key, legacy);
        writeBrowser(key, legacy);
      }
    } catch {
      // ignore
    }
  }
  for (const key of browserKeys()) {
    const payload = readBrowser(key);
    if (payload !== null && !cache.has(key)) cache.set(key, payload);
  }
  notify();
  return state;
}

/** Synchronous read: cache first, then browser storage (which also answers
 *  legacy plain keys until the value is rewritten). */
export function readLocal(key: string): string | null {
  const hit = cache.get(key);
  if (hit !== undefined) return hit;
  return readBrowser(key);
}

const queues = new Map<string, Promise<void>>();

/** Cache-first write; persists through the per-key save queue. */
export function writeLocal(key: string, payload: string): Promise<void> {
  cache.set(key, payload);
  writeBrowser(key, payload);
  const ticket = ++generation;
  const tail = queues.get(key) ?? Promise.resolve();
  const task = tail.catch(() => undefined).then(async () => {
    if (state.mode !== "tauri" || ticket !== generation) return;
    await invoke("local_store_write", { key, payload });
  });
  queues.set(key, task);
  return task;
}

export function removeLocal(key: string): Promise<void> {
  cache.delete(key);
  try {
    localStorage.removeItem(`${BROWSER_PREFIX}${key}`);
  } catch {
    // ignore
  }
  const tail = queues.get(key) ?? Promise.resolve();
  const task = tail.catch(() => undefined).then(async () => {
    if (state.mode !== "tauri") return;
    await invoke("local_store_remove", { key });
  });
  queues.set(key, task);
  return task;
}

/** Keys currently visible in the store (union of dir listing and cache). */
export async function listLocal(): Promise<string[]> {
  if (state.mode === "tauri") {
    try {
      return await invoke<string[]>("local_store_list");
    } catch {
      // fall through to cache view
    }
  }
  return [...cache.keys()].sort();
}

/** Choose (and migrate into) a data directory. See ChooseResult semantics. */
export async function chooseDataDir(): Promise<ChooseResult> {
  if (!isTauri()) return { kind: "cancelled" };
  const chosen = await openDirectoryDialog({
    directory: true,
    multiple: false,
    title: "选择本地数据目录",
  });
  if (typeof chosen !== "string") return { kind: "cancelled" };
  await invoke("local_store_set_dir", { dir: chosen });
  const existing = await invoke<string[]>("local_store_list");
  if (existing.length === 0) {
    const keys = [...new Set([...cache.keys(), ...browserKeys()])];
    for (const key of keys) {
      const payload = cache.get(key) ?? readBrowser(key);
      if (payload !== null) {
        await invoke("local_store_write", { key, payload });
      }
    }
    generation += 1;
    state = { mode: "tauri", dir: chosen };
    notify();
    return { kind: "copied", dir: chosen, keys: keys.length };
  }
  cache.clear();
  for (const key of existing) {
    const payload = await invoke<string | null>("local_store_read", { key });
    if (payload !== null) cache.set(key, payload);
  }
  generation += 1;
  state = { mode: "tauri", dir: chosen };
  notify();
  return { kind: "loaded", dir: chosen, keys: existing.length };
}

/** Open the configured directory in the OS file manager. */
export async function openDataDir(): Promise<void> {
  if (state.dir !== null) await openPath(state.dir);
}
