/** Workspace resource, binary and trash client. */

import type {
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
import type { EndpointHttpTransport } from "./transport";

export class EndpointWorkspaceClient {
  constructor(private readonly transport: EndpointHttpTransport) {}

  manifest(): Promise<WorkspaceManifest> {
    return this.transport.request<WorkspaceManifest>(
      "GET",
      "/v1/workspace/manifest",
    );
  }

  readText(link: string): Promise<WorkspaceTextRead> {
    return this.transport.request<WorkspaceTextRead>(
      "GET",
      "/v1/workspace/resource",
      { query: { link } },
    );
  }

  async readBlob(
    link: string,
  ): Promise<{ blob: Blob; headers: WorkspaceBlobHeaders }> {
    const response = await this.transport.readBlob("/v1/workspace/blob", { link });
    return {
      blob: await response.blob(),
      headers: {
        link: response.headers.get("X-TinySoul-Link") || link,
        digest: response.headers.get("X-TinySoul-Digest") || "",
        size: parseInt(response.headers.get("X-TinySoul-Size") || "0", 10),
      },
    };
  }

  writeText(request: WorkspaceWriteRequest): Promise<WorkspaceWriteResponse> {
    return this.transport.request<WorkspaceWriteResponse>(
      "PUT",
      "/v1/workspace/resource",
      { body: request },
    );
  }

  writeBlob(
    link: string,
    data: Blob,
    options: {
      overwrite?: boolean;
      expectedDigest?: string;
      expectedRevision: number;
      retention?: WorkspaceResourceRecord["retention"];
    },
  ): Promise<WorkspaceWriteResponse> {
    return this.transport.writeBlob<WorkspaceWriteResponse>(
      "/v1/workspace/blob",
      data,
      {
        link,
        expected_revision: options.expectedRevision,
        overwrite: options.overwrite ? "true" : undefined,
        expected_digest: options.expectedDigest,
        retention: options.retention,
      },
    );
  }

  listTrash(): Promise<{ items: TrashItem[] }> {
    return this.transport.request<{ items: TrashItem[] }>(
      "GET",
      "/v1/workspace/trash",
    );
  }

  trash(request: WorkspaceTrashRequest): Promise<{ manifest: WorkspaceManifest }> {
    return this.transport.request<{ manifest: WorkspaceManifest }>(
      "POST",
      "/v1/workspace/trash",
      { body: request },
    );
  }

  restore(
    request: WorkspaceRestoreRequest,
  ): Promise<{ manifest: WorkspaceManifest }> {
    return this.transport.request<{ manifest: WorkspaceManifest }>(
      "POST",
      "/v1/workspace/restore",
      { body: request },
    );
  }
}
