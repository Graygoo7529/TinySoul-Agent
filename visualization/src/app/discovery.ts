/**
 * Connection target discovery for the v2 Endpoint (plan §4).
 *
 * Two sources, both yielding a client-reachable address plus token; the v2
 * handshake (api/v2/connection.ts) is always the authority on protocol and
 * identity:
 *
 * - Browser: a manual connect form persists `{address, token}` to
 *   localStorage. The legacy v1 shape `{host, port, token}` is migrated on
 *   read.
 * - Tauri: the Rust `discover_backend` command reads the App-published
 *   instance lease for the configured project root. The lease only supplies
 *   address + token + expected identity; its protocol_version field is not
 *   consulted (the /status handshake decides).
 */

import { invoke } from "@tauri-apps/api/core";

export interface ConnectTarget {
  /** Client-reachable address: `IP:Port` or an explicit http(s) URL. */
  address: string;
  token: string;
  /**
   * Expected instance identity for lease-discovered connections. When
   * present, the handshake verifies it and a mismatch rejects the (stale)
   * lease.
   */
  instanceId?: string;
  projectIdentity?: string;
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
  /** Legacy v1 shape. */
  host?: unknown;
  port?: unknown;
}

/** Read the persisted browser connection; migrates the v1 host/port shape. */
export function loadStoredBrowserTarget(): ConnectTarget | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as StoredConnection;
    if (
      typeof value.address === "string" &&
      value.address.trim() &&
      typeof value.token === "string" &&
      value.token
    ) {
      return { address: value.address, token: value.token };
    }
    if (
      typeof value.host === "string" &&
      value.host.trim() &&
      typeof value.port === "number" &&
      value.port > 0 &&
      typeof value.token === "string" &&
      value.token
    ) {
      return {
        address: `http://${value.host}:${value.port}`,
        token: value.token,
      };
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

/** The subset of the Rust BackendConnection the lease publishes. */
interface LeaseRecord {
  host: string;
  port: number;
  token: string;
  instance_id: string;
  project_identity: string;
}

/**
 * Tauri-only: read the instance lease the local App published for the
 * project root. Returns null when no instance is running for the project.
 */
export async function discoverLocalLease(
  projectRoot: string,
): Promise<ConnectTarget | null> {
  const record = (await invoke("discover_backend", {
    projectRoot,
  })) as LeaseRecord | null;
  if (!record) return null;
  return {
    address: `http://${record.host}:${record.port}`,
    token: record.token,
    instanceId: record.instance_id,
    projectIdentity: record.project_identity,
  };
}
