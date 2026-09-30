/**
 * Directory tree derivation for the Workspace page (plan §10/P06).
 *
 * The manifest is the committed index: the tree is a pure projection of its
 * records — explicit directory records plus the parent segments implied by
 * every resource path. Directories sort before files, then alphabetically.
 * Filtering keeps the ancestors of every hit so a match stays in context.
 * Path validation mirrors the owner link rules; the backend stays
 * authoritative.
 */

import type { WorkspaceResourceRecord } from "../../api/v2/types";

export interface WorkspaceTreeNode {
  /** Workspace-relative POSIX path (the root itself is never a node). */
  path: string;
  name: string;
  kind: "directory" | "file";
  /** The manifest record of an explicit directory or of the file itself. */
  record: WorkspaceResourceRecord | null;
  children: WorkspaceTreeNode[];
}

export function buildWorkspaceTree(
  records: WorkspaceResourceRecord[],
): WorkspaceTreeNode[] {
  const root: WorkspaceTreeNode = {
    path: "",
    name: "",
    kind: "directory",
    record: null,
    children: [],
  };
  const directories = new Map<string, WorkspaceTreeNode>([["", root]]);

  const ensureDirectory = (path: string): WorkspaceTreeNode => {
    const existing = directories.get(path);
    if (existing !== undefined) return existing;
    const parentPath = parentOf(path);
    const parent = ensureDirectory(parentPath);
    const node: WorkspaceTreeNode = {
      path,
      name: path.slice(parentPath === "" ? 0 : parentPath.length + 1),
      kind: "directory",
      record: null,
      children: [],
    };
    parent.children.push(node);
    directories.set(path, node);
    return node;
  };

  for (const record of records) {
    const path = record.relative_path;
    if (path === "") continue;
    if (record.kind === "directory") {
      ensureDirectory(path).record = record;
      continue;
    }
    const parentPath = parentOf(path);
    const parent = ensureDirectory(parentPath);
    parent.children.push({
      path,
      name: path.slice(parentPath === "" ? 0 : parentPath.length + 1),
      kind: "file",
      record,
      children: [],
    });
  }

  const sortLevel = (nodes: WorkspaceTreeNode[]): void => {
    nodes.sort((a, b) =>
      a.kind !== b.kind
        ? a.kind === "directory"
          ? -1
          : 1
        : a.name.localeCompare(b.name),
    );
    for (const node of nodes) sortLevel(node.children);
  };
  sortLevel(root.children);
  return root.children;
}

function parentOf(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash < 0 ? "" : path.slice(0, slash);
}

/** Keep nodes whose name/path matches, plus every ancestor of a match. */
export function filterWorkspaceTree(
  nodes: WorkspaceTreeNode[],
  query: string,
): WorkspaceTreeNode[] {
  const needle = query.trim().toLowerCase();
  if (needle === "") return nodes;
  const visit = (node: WorkspaceTreeNode): WorkspaceTreeNode | null => {
    const children = node.children
      .map(visit)
      .filter((child): child is WorkspaceTreeNode => child !== null);
    const hit =
      node.name.toLowerCase().includes(needle) ||
      node.path.toLowerCase().includes(needle);
    if (hit || children.length > 0) return { ...node, children };
    return null;
  };
  return nodes
    .map(visit)
    .filter((node): node is WorkspaceTreeNode => node !== null);
}

/** Top-level directory paths, for the search scope choices. */
export function topLevelDirectories(
  records: WorkspaceResourceRecord[],
): string[] {
  const dirs = new Set<string>();
  for (const record of records) {
    const path = record.relative_path;
    if (path === "") continue;
    const slash = path.indexOf("/");
    if (slash > 0) dirs.add(path.slice(0, slash));
    else if (record.kind === "directory") dirs.add(path);
  }
  return [...dirs].sort((a, b) => a.localeCompare(b));
}

/** Client-side workspace path check (mirrors the owner link rules). */
export function isValidWorkspacePath(path: string): boolean {
  if (
    path === "" ||
    path.includes("\\") ||
    path.startsWith("/") ||
    path.includes("\0")
  ) {
    return false;
  }
  for (const part of path.split("/")) {
    if (part === "" || part === "." || part === ".." || part.includes(":")) {
      return false;
    }
  }
  return true;
}

/** Normalize a user-typed path: optional prefix and edge slashes stripped. */
export function normalizeWorkspacePath(input: string): string {
  let value = input.trim();
  if (value.startsWith("workspace:")) value = value.slice("workspace:".length);
  while (value.startsWith("/")) value = value.slice(1);
  while (value.endsWith("/")) value = value.slice(0, -1);
  return value;
}
