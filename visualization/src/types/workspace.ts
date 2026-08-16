/** Workspace manifest, resource and CAS contracts. */

export interface WorkspaceResourceRecord {
  link: string;
  relative_path: string;
  kind: string;
  media_type: string;
  suffix?: string;
  summary: string;
  size: number;
  mtime_ns: number;
  digest?: string;
  description?: string;
  described_digest?: string;
  retention: "ephemeral" | "turn" | "day" | "persistent";
  owner_turn_id?: string;
}

export interface WorkspaceManifest {
  schema_version: number;
  day: string;
  revision: number;
  resources: WorkspaceResourceRecord[];
}

export interface WorkspaceTextRead {
  link: string;
  text: string;
  truncated: boolean;
  size: number;
  digest: string;
}

export interface WorkspaceBlobHeaders {
  link: string;
  digest: string;
  size: number;
}

export interface WorkspaceWriteResponse {
  record: WorkspaceResourceRecord;
  manifest: WorkspaceManifest;
}

export interface TrashItem {
  ref: string;
  link: string;
  relative_path: string;
  kind: string;
  media_type: string;
  size: number;
  digest?: string;
  moved_at: number;
}

export interface WorkspaceWriteRequest {
  link: string;
  text: string;
  overwrite: boolean;
  expected_digest: string;
  expected_revision: number;
  retention?: WorkspaceResourceRecord["retention"];
}

export interface WorkspaceTrashRequest {
  link: string;
  expected_digest: string;
  expected_revision: number;
}

export interface WorkspaceRestoreRequest {
  trash_ref: string;
  expected_revision: number;
}
