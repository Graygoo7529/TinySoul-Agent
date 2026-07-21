/**
 * Directory tree view derived from the Workspace Manifest.
 *
 * The backend does not expose explicit directory entities, so the tree is
 * built from resource `relative_path` values on the frontend.
 */

import { useMemo, useState } from "react";
import {
  ChevronRight,
  ChevronDown,
  Folder,
  FolderOpen,
  FileText,
  Image as ImageIcon,
  FileCode,
  Trash2,
} from "lucide-react";

import type { WorkspaceResourceRecord } from "../types";

export interface WorkspaceTreeNode {
  type: "directory" | "file";
  name: string;
  path: string;
  link?: string;
  resource?: WorkspaceResourceRecord;
  children: WorkspaceTreeNode[];
}

interface WorkspaceTreeProps {
  resources: WorkspaceResourceRecord[];
  activeLink?: string | null;
  dirtyLinks?: Set<string>;
  filter?: string;
  onOpen: (resource: WorkspaceResourceRecord) => void;
  onDelete: (resource: WorkspaceResourceRecord) => void;
}

export function buildWorkspaceTree(
  resources: WorkspaceResourceRecord[],
  rootName = "workspace",
): WorkspaceTreeNode {
  const root: WorkspaceTreeNode = {
    type: "directory",
    name: rootName,
    path: "",
    children: [],
  };

  const sorted = [...resources].sort((a, b) => a.relative_path.localeCompare(b.relative_path));

  for (const resource of sorted) {
    const parts = resource.relative_path.split("/").filter(Boolean);
    if (parts.length === 0) continue;
    let current = root;
    for (let i = 0; i < parts.length; i++) {
      const name = parts[i];
      const isFile = i === parts.length - 1;
      const path = parts.slice(0, i + 1).join("/");
      let child = current.children.find((c) => c.name === name);
      if (!child) {
        child = {
          type: isFile ? "file" : "directory",
          name,
          path,
          children: [],
        };
        current.children.push(child);
      }
      if (isFile) {
        child.type = "file";
        child.link = resource.link;
        child.resource = resource;
      } else {
        current = child;
      }
    }
  }

  // Sort directories first, then files alphabetically.
  sortTree(root);
  return root;
}

function sortTree(node: WorkspaceTreeNode) {
  node.children.sort((a, b) => {
    if (a.type === b.type) return a.name.localeCompare(b.name);
    return a.type === "directory" ? -1 : 1;
  });
  for (const child of node.children) {
    if (child.type === "directory") sortTree(child);
  }
}

function filterTree(node: WorkspaceTreeNode, query: string): WorkspaceTreeNode | null {
  if (!query.trim()) return node;
  const lower = query.toLowerCase();
  const matchesName = node.name.toLowerCase().includes(lower);
  const filteredChildren: WorkspaceTreeNode[] = [];
  for (const child of node.children) {
    const filtered = filterTree(child, query);
    if (filtered) filteredChildren.push(filtered);
  }
  if (matchesName) {
    return { ...node, children: filteredChildren.length ? filteredChildren : node.children };
  }
  if (filteredChildren.length) {
    return { ...node, children: filteredChildren };
  }
  return null;
}

export function WorkspaceTree({
  resources,
  activeLink,
  dirtyLinks,
  filter = "",
  onOpen,
  onDelete,
}: WorkspaceTreeProps) {
  const tree = useMemo(() => {
    const full = buildWorkspaceTree(resources);
    return filterTree(full, filter) || full;
  }, [resources, filter]);

  const [expanded, setExpanded] = useState<Set<string>>(new Set([""]));

  const toggle = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  return (
    <div className="workspace-tree">
      <TreeNode
        node={tree}
        depth={0}
        expanded={expanded}
        activeLink={activeLink}
        dirtyLinks={dirtyLinks}
        onToggle={toggle}
        onOpen={onOpen}
        onDelete={onDelete}
      />
    </div>
  );
}

interface TreeNodeProps {
  node: WorkspaceTreeNode;
  depth: number;
  expanded: Set<string>;
  activeLink?: string | null;
  dirtyLinks?: Set<string>;
  onToggle: (path: string) => void;
  onOpen: (resource: WorkspaceResourceRecord) => void;
  onDelete: (resource: WorkspaceResourceRecord) => void;
}

function TreeNode({
  node,
  depth,
  expanded,
  activeLink,
  dirtyLinks,
  onToggle,
  onOpen,
  onDelete,
}: TreeNodeProps) {
  const paddingLeft = 10 + depth * 14;
  const isExpanded = expanded.has(node.path);
  const isActive = node.resource && activeLink === node.resource.link;
  const isDirty = node.resource && dirtyLinks?.has(node.resource.link);

  if (node.type === "directory") {
    return (
      <div>
        <button
          className={`tree-row ${isActive ? "active" : ""}`}
          style={{ paddingLeft }}
          onClick={() => onToggle(node.path)}
        >
          <span className="tree-chevron">
            {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </span>
          <span className="tree-icon">
            {isExpanded ? <FolderOpen size={14} /> : <Folder size={14} />}
          </span>
          <span className="tree-label truncate">{node.name}</span>
        </button>
        {isExpanded &&
          node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              activeLink={activeLink}
              dirtyLinks={dirtyLinks}
              onToggle={onToggle}
              onOpen={onOpen}
              onDelete={onDelete}
            />
          ))}
      </div>
    );
  }

  const resource = node.resource!;
  return (
    <div
      className={`tree-row tree-file ${isActive ? "active" : ""}`}
      style={{ paddingLeft }}
      onClick={() => onOpen(resource)}
    >
      <span className="tree-chevron" />
      <span className="tree-icon">{fileIcon(resource)}</span>
      <span className="tree-label truncate">
        {node.name}
        {isDirty && <span className="tree-dirty" />}
      </span>
      <span className="tree-actions">
        <button
          className="btn btn-sm btn-danger btn-icon"
          onClick={(e) => {
            e.stopPropagation();
            onDelete(resource);
          }}
          title="Move to trash"
        >
          <Trash2 size={12} />
        </button>
      </span>
    </div>
  );
}

function fileIcon(resource: WorkspaceResourceRecord) {
  if (resource.kind === "markdown" || resource.media_type === "text/markdown") {
    return <FileText size={14} style={{ color: "var(--accent)" }} />;
  }
  if (resource.kind === "script" || resource.media_type.startsWith("text/")) {
    return <FileCode size={14} />;
  }
  if (resource.media_type.startsWith("image/")) {
    return <ImageIcon size={14} />;
  }
  return <FileText size={14} />;
}
