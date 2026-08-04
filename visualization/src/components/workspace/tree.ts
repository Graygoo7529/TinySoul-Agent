/**
 * Directory tree derived from the Workspace Manifest. The backend does not
 * expose explicit directory entities, so the tree is built from resource
 * `relative_path` values on the frontend.
 */

import type { WorkspaceResourceRecord } from "../../types";

export interface WorkspaceTreeNode {
  type: "directory" | "file";
  name: string;
  path: string;
  link?: string;
  resource?: WorkspaceResourceRecord;
  children: WorkspaceTreeNode[];
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

  const sorted = [...resources].sort((a, b) =>
    a.relative_path.localeCompare(b.relative_path),
  );

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
        child = { type: isFile ? "file" : "directory", name, path, children: [] };
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

export function filterTree(
  node: WorkspaceTreeNode,
  query: string,
): WorkspaceTreeNode | null {
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
