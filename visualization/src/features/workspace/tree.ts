/**
 * Directory tree derivation for the Workspace page (plan §10/P06).
 *
 * The manifest is the committed index: the tree is a pure projection of its
 * records — explicit directory records plus the parent segments implied by
 * every resource path. Directories sort before files, then alphabetically.
 * Filtering keeps the ancestors of every hit so a match stays in context.
 * Path validation mirrors the owner ref rules; the backend stays
 * authoritative.
 *
 * The shared presentation mapping lives here too: fileKindIcon gives one
 * muted type icon per manifest record (tree rows), and TAG_TONES keeps the
 * tree and the FilePanel header reading the same tag the same way.
 */

import { Braces, File, FileCode, FileText, Image, type LucideIcon } from "lucide-react";

import type { WorkspaceResourceRecord } from "../../api/v2/types";
import type { BadgeTone } from "../../components/ui/Badge";

/** Tag → badge tone, shared by the tree rows and the FilePanel header. */
export const TAG_TONES: Record<string, BadgeTone> = {
  pinned: "accent",
  tmp: "yellow",
  important: "teal",
};

const MARKDOWN_SUFFIXES = new Set([".md", ".markdown"]);
const CODE_SUFFIXES = new Set([
  ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
  ".py", ".rs", ".go", ".java", ".c", ".h", ".cpp", ".hpp", ".cs",
  ".rb", ".php", ".sh", ".ps1", ".css", ".scss", ".html", ".vue", ".sql",
]);
const DATA_SUFFIXES = new Set([".json", ".jsonc", ".toml", ".yaml", ".yml"]);

/**
 * The muted type icon for one manifest record: recognized suffixes get their
 * shape with a soft existing token, images follow media_type, and anything
 * unrecognized stays a plain gray File — never a guessed type.
 */
export function fileKindIcon(record: WorkspaceResourceRecord): {
  Icon: LucideIcon;
  className: string;
} {
  if (record.media_type.startsWith("image/")) {
    return { Icon: Image, className: "text-domain-home opacity-75" };
  }
  const suffix = record.suffix.toLowerCase();
  if (MARKDOWN_SUFFIXES.has(suffix)) {
    return { Icon: FileText, className: "text-info opacity-75" };
  }
  if (CODE_SUFFIXES.has(suffix)) {
    return { Icon: FileCode, className: "text-success opacity-75" };
  }
  if (DATA_SUFFIXES.has(suffix)) {
    return { Icon: Braces, className: "text-warning opacity-75" };
  }
  return { Icon: File, className: "text-fg-faint" };
}

const MEDIA_TYPE_LABELS: Record<string, string> = {
  "text/markdown": "Markdown",
  "text/plain": "纯文本",
  "text/x-python": "Python",
  "application/json": "JSON",
  "application/toml": "TOML",
  "application/yaml": "YAML",
  "text/csv": "CSV",
  "text/tab-separated-values": "TSV",
  "text/html": "HTML",
  "text/css": "CSS",
  "text/javascript": "JavaScript",
  "text/typescript": "TypeScript",
  "application/xml": "XML",
  "application/sql": "SQL",
  "text/x-shellscript": "Shell",
  "text/x-powershell": "PowerShell",
  "text/x-msdos-batch": "Batch",
  "image/png": "PNG 图片",
  "image/jpeg": "JPEG 图片",
  "image/gif": "GIF 图片",
  "image/webp": "WebP 图片",
  "application/pdf": "PDF",
  "application/msword": "Word 文档",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word 文档",
  "application/vnd.ms-powerpoint": "PowerPoint",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
  "application/vnd.ms-excel": "Excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
  "inode/directory": "目录",
  "application/octet-stream": "二进制",
};

/**
 * Readable label for a manifest media type, mirroring the backend's own
 * classification vocabulary. Unknown values pass through unchanged; an empty
 * media type renders nothing.
 */
export function mediaTypeLabel(mediaType: string): string | null {
  if (mediaType === "") return null;
  return MEDIA_TYPE_LABELS[mediaType] ?? mediaType;
}

export interface DirectoryStats {
  /** Direct child files. */
  files: number;
  /** Direct child directories. */
  subdirs: number;
  /** Total bytes of the direct child files. */
  totalBytes: number;
}

/**
 * Direct-child statistics of one directory, aggregated from the already
 * loaded manifest — the same scope as expanding the tree node one level.
 */
export function directoryStats(
  records: WorkspaceResourceRecord[],
  dirPath: string,
): DirectoryStats {
  const prefix = `${dirPath}/`;
  let files = 0;
  let subdirs = 0;
  let totalBytes = 0;
  for (const record of records) {
    if (!record.relative_path.startsWith(prefix)) continue;
    const rest = record.relative_path.slice(prefix.length);
    if (rest.includes("/")) continue;
    if (record.kind === "directory") {
      subdirs += 1;
    } else {
      files += 1;
      totalBytes += record.size;
    }
  }
  return { files, subdirs, totalBytes };
}

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

/** Client-side workspace path check (mirrors the owner ref rules). */
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
