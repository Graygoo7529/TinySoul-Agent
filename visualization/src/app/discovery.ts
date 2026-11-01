/** Client-local connection target storage and Tauri capability detection. */

export interface ConnectTarget {
  /** Client-reachable address: `IP:Port` or an explicit http(s) URL. */
  address: string;
  token: string;
}

export function isTauriShell(): boolean {
  return (
    typeof window !== "undefined" &&
    ("__TAURI_INTERNALS__" in window || "__TAURI__" in window)
  );
}

const STORAGE_KEY = "tinysoul-web-connection";

interface StoredConnection {
  address?: unknown;
  token?: unknown;
}

/** Read the persisted connection target. */
export function loadStoredBrowserTarget(): ConnectTarget | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as StoredConnection;
    if (typeof value.address === "string" && value.address.trim() &&
        typeof value.token === "string" && value.token.trim()) {
      return { address: value.address, token: value.token };
    }
    return null;
  } catch {
    return null;
  }
}

export function storeBrowserTarget(target: ConnectTarget): void {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ address: target.address, token: target.token }),
    );
  } catch {
    // storage may be unavailable; the session connection still works
  }
}

export function clearStoredBrowserTarget(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
