/**
 * Backend connection discovery.
 *
 * Inside Tauri the Rust `discover_backend` command reads the App-published
 * instance lease for the configured project root. In a plain browser (web
 * development without the Tauri shell) the same information can be passed as
 * `?host=&port=&token=` query parameters, which are then persisted to
 * localStorage so the URL can be shared/bookmarked once.
 */

import { invoke } from "@tauri-apps/api/core";
import type { ConnectionInfo } from "../types";

const STORAGE_KEY = "tinysoul-web-connection";

export function isTauriShell(): boolean {
  return (
    typeof window !== "undefined" &&
    ("__TAURI_INTERNALS__" in window || "__TAURI__" in window)
  );
}

export async function resolveConnectionInfo(
  projectRoot: string,
): Promise<ConnectionInfo | null> {
  if (isTauriShell()) {
    return (await invoke("discover_backend", {
      projectRoot,
    })) as ConnectionInfo | null;
  }
  return webConnectionInfo();
}

function webConnectionInfo(): ConnectionInfo | null {
  const params = new URLSearchParams(window.location.search);
  const host = params.get("host");
  const port = params.get("port");
  const token = params.get("token");
  if (host && port && token) {
    const info: ConnectionInfo = {
      host,
      port: Number(port),
      token,
      protocol_version: 1,
      instance_id: "",
      project_identity: "",
      project_root: "",
    };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(info));
    } catch {
      // storage may be unavailable; the query params still work
    }
    return info;
  }
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return JSON.parse(stored) as ConnectionInfo;
  } catch {
    // ignore
  }
  return null;
}
