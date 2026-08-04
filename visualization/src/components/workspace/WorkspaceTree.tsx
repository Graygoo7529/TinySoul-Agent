import { useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  FileCode,
  FileText,
  Folder,
  FolderOpen,
  Image as ImageIcon,
  Trash2,
} from "lucide-react";
import type { WorkspaceResourceRecord } from "../../types";
import { buildWorkspaceTree, filterTree, type WorkspaceTreeNode } from "./tree";

export function WorkspaceTree({
  resources,
  activeLink,
  dirty,
  filter = "",
  onOpen,
  onDelete,
}: {
  resources: WorkspaceResourceRecord[];
  activeLink?: string | null;
  dirty?: string | null;
  filter?: string;
  onOpen: (resource: WorkspaceResourceRecord) => void;
  onDelete: (resource: WorkspaceResourceRecord) => void;
}) {
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
    <TreeNode
      node={tree}
      depth={0}
      expanded={expanded}
      activeLink={activeLink}
      dirty={dirty}
      onToggle={toggle}
      onOpen={onOpen}
      onDelete={onDelete}
    />
  );
}

interface TreeNodeProps {
  node: WorkspaceTreeNode;
  depth: number;
  expanded: Set<string>;
  activeLink?: string | null;
  dirty?: string | null;
  onToggle: (path: string) => void;
  onOpen: (resource: WorkspaceResourceRecord) => void;
  onDelete: (resource: WorkspaceResourceRecord) => void;
}

function TreeNode({
  node,
  depth,
  expanded,
  activeLink,
  dirty,
  onToggle,
  onOpen,
  onDelete,
}: TreeNodeProps) {
  const paddingLeft = 8 + depth * 14;
  const isExpanded = expanded.has(node.path);
  const isActive = node.resource && activeLink === node.resource.link;
  const isDirty = node.resource && dirty === node.resource.link;

  const rowClass = `group flex w-full items-center gap-1.5 rounded-md py-1 pr-1.5 text-left text-[13px] transition-colors ${
    isActive ? "bg-accent-soft text-accent" : "text-fg hover:bg-hover"
  }`;

  if (node.type === "directory") {
    if (depth === 0) {
      // Render root children directly.
      return (
        <>
          {node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth}
              expanded={expanded}
              activeLink={activeLink}
              dirty={dirty}
              onToggle={onToggle}
              onOpen={onOpen}
              onDelete={onDelete}
            />
          ))}
        </>
      );
    }
    return (
      <div>
        <button className={rowClass} style={{ paddingLeft }} onClick={() => onToggle(node.path)}>
          {isExpanded ? (
            <ChevronDown size={13} className="shrink-0 text-fg-faint" />
          ) : (
            <ChevronRight size={13} className="shrink-0 text-fg-faint" />
          )}
          {isExpanded ? (
            <FolderOpen size={14} className="shrink-0 text-warning" />
          ) : (
            <Folder size={14} className="shrink-0 text-warning" />
          )}
          <span className="truncate">{node.name}</span>
        </button>
        {isExpanded &&
          node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              activeLink={activeLink}
              dirty={dirty}
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
    <div className={rowClass} style={{ paddingLeft }} onClick={() => onOpen(resource)}>
      <span className="w-[13px] shrink-0" />
      <FileIcon resource={resource} />
      <span className="min-w-0 flex-1 truncate">
        {node.name}
        {isDirty && <span className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-warning" />}
      </span>
      <button
        className="hidden shrink-0 rounded p-1 text-fg-faint group-hover:block hover:bg-danger-soft hover:text-danger"
        onClick={(e) => {
          e.stopPropagation();
          onDelete(resource);
        }}
        title="Move to trash"
      >
        <Trash2 size={12} />
      </button>
    </div>
  );
}

function FileIcon({ resource }: { resource: WorkspaceResourceRecord }) {
  if (resource.media_type === "text/markdown" || resource.suffix === ".md") {
    return <FileText size={14} className="shrink-0 text-accent" />;
  }
  if (resource.media_type.startsWith("text/")) {
    return <FileCode size={14} className="shrink-0 text-fg-muted" />;
  }
  if (resource.media_type.startsWith("image/")) {
    return <ImageIcon size={14} className="shrink-0 text-info" />;
  }
  return <FileText size={14} className="shrink-0 text-fg-muted" />;
}
