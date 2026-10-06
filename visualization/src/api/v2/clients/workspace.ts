/**
 * API-12: Workspace reads, edits and trash (docs/endpoint/workspace.md).
 * GETs accept an optional day for archive reads (read-only, never falling
 * back to today); every write route acts on the active Workspace only.
 * `full=true` reads the complete editable text — never submit a paged first
 * screen as the whole file. Blob reads are authenticated binary responses;
 * build Object URLs from the returned Blob, not from the endpoint URL.
 */

import type {
  WorkspaceManifest,
  WorkspaceMutationResult,
  WorkspaceTag,
  WorkspaceTextEdit,
  WorkspaceTextPage,
  WorkspaceTrashPage,
  WorkspaceTrashResult,
} from "../types";
import type { RequestOptions, V2Transport } from "../transport";
import type { ContinuationParams } from "./paging";

/**
 * HTTP Range for blob reads: `{start, end?}` (both inclusive, end omitted
 * means to the end of the file) or `{suffix}` (the last N bytes).
 */
export type ByteRange = { start: number; end?: number } | { suffix: number };

export function formatByteRange(range: ByteRange): string {
  if ("suffix" in range) return `bytes=-${range.suffix}`;
  return range.end !== undefined
    ? `bytes=${range.start}-${range.end}`
    : `bytes=${range.start}-`;
}

export class WorkspaceClient {
  constructor(private readonly transport: V2Transport) {}

  /** GET /v2/workspace/manifest — committed index (schema v4), no reconcile. */
  manifest(
    params?: { day?: string },
    options?: RequestOptions,
  ): Promise<WorkspaceManifest> {
    return this.transport.get<WorkspaceManifest>("/workspace/manifest", {
      ...options,
      query: { ...params },
    });
  }

  /** GET /v2/workspace/resource — paged text, or the full editable text. */
  resource(
    params: {
      ref: string;
      day?: string;
      full?: boolean;
    } & ContinuationParams,
    options?: RequestOptions,
  ): Promise<WorkspaceTextPage> {
    return this.transport.get<WorkspaceTextPage>("/workspace/resource", {
      ...options,
      query: { ...params },
    });
  }

  /**
   * GET /v2/workspace/blob — streamed bytes. Returns the raw Response
   * (200 or 206 with Content-Range); the caller manages Object URLs.
   */
  readBlob(
    params: { ref: string; day?: string; range?: ByteRange },
    options?: RequestOptions,
  ): Promise<Response> {
    return this.transport.readBlob("/workspace/blob", {
      ...options,
      query: { ref: params.ref, day: params.day },
      headers: params.range
        ? { Range: formatByteRange(params.range) }
        : undefined,
    });
  }

  /** PUT /v2/workspace/resource — atomic JSON/text write. */
  writeText(
    body: { ref: string; text: string; overwrite?: boolean },
    options?: RequestOptions,
  ): Promise<WorkspaceMutationResult> {
    return this.transport.put<WorkspaceMutationResult>("/workspace/resource", {
      ...options,
      body,
    });
  }

  /** PUT /v2/workspace/blob?ref=&overwrite= — bounded binary write. */
  writeBlob(
    params: { ref: string; overwrite?: boolean },
    data: Blob | ArrayBuffer | Uint8Array,
    options?: RequestOptions,
  ): Promise<WorkspaceMutationResult> {
    return this.transport.writeBlob<WorkspaceMutationResult>(
      "/workspace/blob",
      data,
      { ...options, query: { ...params } },
    );
  }

  /** POST /v2/workspace/directory — create a directory. */
  createDirectory(
    body: { ref: string },
    options?: RequestOptions,
  ): Promise<WorkspaceMutationResult> {
    return this.transport.post<WorkspaceMutationResult>(
      "/workspace/directory",
      { ...options, body },
    );
  }

  /** POST /v2/workspace/move — refuses when the target exists. */
  move(
    body: { source_ref: string; target_ref: string },
    options?: RequestOptions,
  ): Promise<WorkspaceMutationResult> {
    return this.transport.post<WorkspaceMutationResult>("/workspace/move", {
      ...options,
      body,
    });
  }

  /** PUT /v2/workspace/tags — replace the tag set; an empty list clears. */
  setTags(
    body: { ref: string; tags: WorkspaceTag[] },
    options?: RequestOptions,
  ): Promise<WorkspaceMutationResult> {
    return this.transport.put<WorkspaceMutationResult>("/workspace/tags", {
      ...options,
      body,
    });
  }

  /** POST /v2/workspace/edit — 1–64 unique old_text matches, one commit. */
  edit(
    body: { ref: string; edits: WorkspaceTextEdit[] },
    options?: RequestOptions,
  ): Promise<WorkspaceMutationResult> {
    return this.transport.post<WorkspaceMutationResult>("/workspace/edit", {
      ...options,
      body,
    });
  }

  /** POST /v2/workspace/append — append explicit text. */
  append(
    body: { ref: string; text: string },
    options?: RequestOptions,
  ): Promise<WorkspaceMutationResult> {
    return this.transport.post<WorkspaceMutationResult>("/workspace/append", {
      ...options,
      body,
    });
  }

  /** GET /v2/workspace/trash — bounded page; archived trash is read-only. */
  listTrash(
    params?: { day?: string; continuation?: string; limit?: number },
    options?: RequestOptions,
  ): Promise<WorkspaceTrashPage> {
    return this.transport.get<WorkspaceTrashPage>("/workspace/trash", {
      ...options,
      query: { ...params },
    });
  }

  /** POST /v2/workspace/trash — move an active resource into the trash. */
  trash(
    body: { ref: string },
    options?: RequestOptions,
  ): Promise<WorkspaceTrashResult> {
    return this.transport.post<WorkspaceTrashResult>("/workspace/trash", {
      ...options,
      body,
    });
  }

  /** POST /v2/workspace/restore — restore by trash_ref. */
  restore(
    body: { trash_ref: string },
    options?: RequestOptions,
  ): Promise<WorkspaceMutationResult> {
    return this.transport.post<WorkspaceMutationResult>("/workspace/restore", {
      ...options,
      body,
    });
  }
}
