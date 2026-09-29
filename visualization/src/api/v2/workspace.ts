/**
 * Workspace read/mutation envelopes (API-12).
 * Workspace has no exported contract schema; fields follow
 * docs/endpoint/workspace.md and the owner serialization in
 * tinysoul/plugins/workspace/ (manifest to_json, browse_text).
 */

import type { ContentFragment, ContinuationPage, ResourceLocator } from "./common";

export type WorkspaceTag = "pinned" | "tmp" | "library" | (string & {});

/** Manifest resource record (WorkspaceManifest record to_json). */
export interface WorkspaceResourceRecord {
  link: string;
  relative_path: string;
  kind: string;
  media_type: string;
  suffix: string;
  summary: string;
  size: number;
  mtime_ns: number;
  description: string;
  tags: WorkspaceTag[];
  [key: string]: unknown;
}

/** GET /v2/workspace/manifest (manifest schema v4). */
export interface WorkspaceManifest {
  schema_version: number;
  day: string;
  resources: WorkspaceResourceRecord[];
  [key: string]: unknown;
}

/**
 * GET /v2/workspace/resource text page. This family does NOT use the
 * items/content_fragment envelope: the body is `text` plus
 * complete/editable/truncated and next_continuation. `full=true` reads the
 * complete editable text and rejects over-limit resources.
 */
export interface WorkspaceTextPage extends ContinuationPage {
  link: string;
  locator: ResourceLocator;
  day: string;
  text: string;
  size: number;
  media_type: string;
  editable: boolean;
  truncated: boolean;
  complete: boolean;
  [key: string]: unknown;
}

/**
 * GET /v2/workspace/blob is a streamed binary response (200/206 with
 * Content-Range), not a JSON envelope; clients read it as Blob/Response.
 */

/** Successful workspace mutation: record plus full manifest. */
export interface WorkspaceMutationResult {
  record: WorkspaceResourceRecord;
  manifest: WorkspaceManifest;
  [key: string]: unknown;
}

/** POST /v2/workspace/edit entry (WorkspaceEdit request schema). */
export interface WorkspaceTextEdit {
  old_text: string;
  new_text: string;
}

/**
 * Trash entry (WorkspaceTrashItem.to_json plus its `ref`).
 * `descendants` are the records removed together with a directory.
 */
export interface WorkspaceTrashItem {
  ref: string;
  trash_id: string;
  original: WorkspaceResourceRecord;
  descendants: WorkspaceResourceRecord[];
  trashed_at: number;
  day: string;
  [key: string]: unknown;
}

/**
 * POST /v2/workspace/trash result. Unlike the other mutations the trashed
 * resource is returned under `trash`, not `record`
 * (EndpointWorkspaceEngine.trash_resource).
 */
export interface WorkspaceTrashResult {
  trash: WorkspaceTrashItem;
  manifest: WorkspaceManifest;
  [key: string]: unknown;
}

/** GET /v2/workspace/trash page (base carries the page's day). */
export interface WorkspaceTrashPage extends ContinuationPage {
  day: string;
  items: WorkspaceTrashItem[];
  content_fragment?: ContentFragment | null;
  [key: string]: unknown;
}
