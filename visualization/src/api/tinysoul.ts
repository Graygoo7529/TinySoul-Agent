/**
 * HTTP client for the TinySoul local Endpoint.
 *
 * All mutations use the active-day lease and revision/digest CAS checks
 * provided by the backend; the frontend never touches the local filesystem
 * directly.
 */

import type {
  BackendError,
  BackendStatus,
  CommandReceipt,
  ConnectionInfo,
  ControlRequest,
  EndpointEvent,
  InputRequest,
  MaintenanceDecision,
  MaintenanceDecisionRequest,
  MaintenanceRequest,
  MaintenanceStatus,
  SessionHistory,
  SessionCursor,
  SessionRecall,
  TrashItem,
  WorkspaceBlobHeaders,
  WorkspaceManifest,
  WorkspaceResourceRecord,
  WorkspaceRestoreRequest,
  WorkspaceTextRead,
  WorkspaceTrashRequest,
  WorkspaceWriteRequest,
  WorkspaceWriteResponse,
} from "../types";

export interface EventPage {
  events: EndpointEvent[];
  next_sequence: number;
  gap: boolean;
}

export class TinySoulClient {
  private baseUrl: string;
  private token: string;

  constructor(info: ConnectionInfo) {
    this.baseUrl = `http://${info.host}:${info.port}`;
    this.token = info.token;
  }

  setConnection(info: ConnectionInfo) {
    this.baseUrl = `http://${info.host}:${info.port}`;
    this.token = info.token;
  }

  private headers(): Record<string, string> {
    return {
      Authorization: `Bearer ${this.token}`,
      "Content-Type": "application/json",
    };
  }

  private async request<T>(
    method: string,
    path: string,
    options: { body?: unknown; query?: Record<string, string | number | undefined> } = {},
  ): Promise<T> {
    const query = options.query
      ? "?" +
        Object.entries(options.query)
          .filter(([, v]) => v !== undefined)
          .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
          .join("&")
      : "";
    const url = `${this.baseUrl}${path}${query}`;
    const init: RequestInit = {
      method,
      headers: this.headers(),
    };
    if (options.body !== undefined) {
      init.body = JSON.stringify(options.body);
    }

    const response = await fetch(url, init);
    if (!response.ok) {
      const data = (await response.json().catch(() => ({}))) as BackendError;
      throw new TinySoulApiError(
        response.status,
        data.error?.code || "endpoint.unknown",
        data.error?.message || `HTTP ${response.status}`,
        data.error?.details,
      );
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }

  async health(): Promise<{ ok: boolean }> {
    return fetch(`${this.baseUrl}/v1/health`).then((r) => r.json() as Promise<{ ok: boolean }>);
  }

  async status(): Promise<BackendStatus> {
    return this.request<BackendStatus>("GET", "/v1/status");
  }

  async submitInput(request: InputRequest): Promise<CommandReceipt> {
    return this.request<CommandReceipt>("POST", "/v1/input", { body: request });
  }

  async submitControl(request: ControlRequest): Promise<CommandReceipt> {
    return this.request<CommandReceipt>("POST", "/v1/control", {
      body: request,
    });
  }

  async replayEvents(after: number, mode: string, limit = 200): Promise<EventPage> {
    return this.request<EventPage>("GET", "/v1/events", {
      query: { after, mode, limit },
    });
  }

  async sessionHistory(): Promise<SessionHistory> {
    return this.request<SessionHistory>("GET", "/v1/session/history");
  }

  async sessionRecall(
    ref: string,
    cursor: SessionCursor = { entry_index: 0, char_offset: 0 },
    maxChars?: number,
  ): Promise<SessionRecall> {
    return this.request<SessionRecall>("GET", "/v1/session/recall", {
      query: {
        ref,
        max_chars: maxChars,
        cursor_entry_index: cursor.entry_index,
        cursor_char_offset: cursor.char_offset,
        cursor_entry_digest: cursor.entry_digest,
      },
    });
  }

  async workspaceManifest(): Promise<WorkspaceManifest> {
    return this.request<WorkspaceManifest>("GET", "/v1/workspace/manifest");
  }

  async readWorkspaceText(link: string): Promise<WorkspaceTextRead> {
    return this.request<WorkspaceTextRead>("GET", "/v1/workspace/resource", { query: { link } });
  }

  async readWorkspaceBlob(link: string): Promise<{ blob: Blob; headers: WorkspaceBlobHeaders }> {
    const response = await fetch(
      `${this.baseUrl}/v1/workspace/blob?link=${encodeURIComponent(link)}`,
      {
        headers: { Authorization: `Bearer ${this.token}` },
      },
    );
    if (!response.ok) {
      const data = (await response.json().catch(() => ({}))) as BackendError;
      throw new TinySoulApiError(
        response.status,
        data.error?.code || "endpoint.unknown",
        data.error?.message || `HTTP ${response.status}`,
        data.error?.details,
      );
    }
    return {
      blob: await response.blob(),
      headers: {
        link: response.headers.get("X-TinySoul-Link") || link,
        digest: response.headers.get("X-TinySoul-Digest") || "",
        size: parseInt(response.headers.get("X-TinySoul-Size") || "0", 10),
      },
    };
  }

  async writeWorkspaceResource(request: WorkspaceWriteRequest): Promise<WorkspaceWriteResponse> {
    return this.request<WorkspaceWriteResponse>("PUT", "/v1/workspace/resource", { body: request });
  }

  async writeWorkspaceBlob(
    link: string,
    data: Blob,
    options: {
      overwrite?: boolean;
      expectedDigest?: string;
      expectedRevision: number;
      retention?: WorkspaceResourceRecord["retention"];
    },
  ): Promise<WorkspaceWriteResponse> {
    const query: Record<string, string | number | undefined> = {
      link,
      expected_revision: options.expectedRevision,
    };
    if (options.overwrite) query.overwrite = "true";
    if (options.expectedDigest) query.expected_digest = options.expectedDigest;
    if (options.retention) query.retention = options.retention;

    const queryString = Object.entries(query)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join("&");
    const response = await fetch(`${this.baseUrl}/v1/workspace/blob?${queryString}`, {
      method: "PUT",
      headers: { Authorization: `Bearer ${this.token}` },
      body: data,
    });
    if (!response.ok) {
      const data = (await response.json().catch(() => ({}))) as BackendError;
      throw new TinySoulApiError(
        response.status,
        data.error?.code || "endpoint.unknown",
        data.error?.message || `HTTP ${response.status}`,
        data.error?.details,
      );
    }
    return (await response.json()) as WorkspaceWriteResponse;
  }

  async listTrash(): Promise<{ items: TrashItem[] }> {
    return this.request<{ items: TrashItem[] }>("GET", "/v1/workspace/trash");
  }

  async trashResource(request: WorkspaceTrashRequest): Promise<{ manifest: WorkspaceManifest }> {
    return this.request<{ manifest: WorkspaceManifest }>("POST", "/v1/workspace/trash", {
      body: request,
    });
  }

  async restoreResource(request: WorkspaceRestoreRequest): Promise<{ manifest: WorkspaceManifest }> {
    return this.request<{ manifest: WorkspaceManifest }>("POST", "/v1/workspace/restore", {
      body: request,
    });
  }

  async maintenanceDecision(): Promise<MaintenanceDecision> {
    return this.request<MaintenanceDecision>("GET", "/v1/maintenance/decision");
  }

  async maintenanceStatus(): Promise<MaintenanceStatus> {
    return this.request<MaintenanceStatus>("GET", "/v1/maintenance");
  }

  async requestMaintenance(request: MaintenanceRequest): Promise<CommandReceipt> {
    return this.request<CommandReceipt>("POST", "/v1/maintenance", { body: request });
  }

  async resolveMaintenanceDecision(request: MaintenanceDecisionRequest): Promise<CommandReceipt> {
    return this.request<CommandReceipt>("POST", "/v1/maintenance/decision", {
      body: request,
    });
  }
}

export class TinySoulApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "TinySoulApiError";
  }
}
