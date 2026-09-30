/**
 * Workspace page sidebar (plan §10/P06): the day selector (active writable,
 * archived read-only), the manifest-driven directory tree with tags, filter
 * and drafts, the Files/Trash tabs and drag-in upload (the blob write route
 * exists, so dropping files is a real capability). Search reads the active
 * Workspace only — opening it from an archived day switches back with an
 * explicit note.
 */

import {
  useMemo,
  useState,
  type DragEvent,
  type ReactElement,
} from "react";
import {
  ChevronDown,
  ChevronRight,
  File as FileIcon,
  FilePlus2,
  Folder as FolderIcon,
  FolderPlus,
  Loader2,
  RotateCcw,
  Search,
  Trash2,
  Upload,
} from "lucide-react";

import type { DayEntry } from "../../api/v2/session";
import type {
  WorkspaceManifest,
  WorkspaceTrashItem,
  WorkspaceTrashPage,
} from "../../api/v2/types";
import { nextContinuation } from "../../api/v2/pagination";
import { EmptyState } from "../../components/ui/EmptyState";
import { Badge } from "../../components/ui/Badge";
import { Button, IconButton } from "../../components/ui/Button";
import { Tabs } from "../../components/ui/Tabs";
import { useAppStore } from "../../store/appStore";
import { useConnectionStore } from "../../store/connectionStore";
import { formatDateTime, formatSize } from "../../utils/format";
import { usePagedSequence } from "../history/usePagedSequence";
import { PathInputModal } from "./modals";
import type { WorkspaceMutations } from "./mutations";
import { useWorkspacePage } from "./store";
import {
  buildWorkspaceTree,
  filterWorkspaceTree,
  type WorkspaceTreeNode,
} from "./tree";

export function Sidebar({
  epoch,
  days,
  viewDay,
  activeDay,
  manifest,
  manifestLoading,
  mutations,
}: {
  epoch: number;
  /** Day directory first page; null while unavailable. */
  days: DayEntry[] | null;
  viewDay: string | null;
  activeDay: string | null;
  manifest: { day: string; records: WorkspaceManifest["resources"] } | null;
  manifestLoading: boolean;
  mutations: WorkspaceMutations;
}): ReactElement {
  const isActive = viewDay === null || viewDay === activeDay;
  const apiDay = isActive ? null : viewDay;
  const panel = useWorkspacePage((s) => s.panel);
  const setPanel = useWorkspacePage((s) => s.setPanel);
  const setDay = useWorkspacePage((s) => s.setDay);
  const setSearchOpen = useWorkspacePage((s) => s.setSearchOpen);
  const drafts = useWorkspacePage((s) => s.drafts);
  const [filter, setFilter] = useState("");
  const [createModal, setCreateModal] = useState<"file" | "folder" | null>(null);
  const [dropActive, setDropActive] = useState(false);

  const dirtyLinks = useMemo(() => {
    const prefix = `${apiDay ?? ""}|`;
    const links = new Set<string>();
    for (const key of Object.keys(drafts)) {
      if (key.startsWith(prefix)) links.add(key.slice(prefix.length));
    }
    return links;
  }, [drafts, apiDay]);

  const tree = useMemo(
    () => filterWorkspaceTree(buildWorkspaceTree(manifest?.records ?? []), filter),
    [manifest, filter],
  );

  const openSearch = () => {
    if (!isActive) {
      setDay(null);
      setSearchOpen(true);
      useAppStore
        .getState()
        .pushToast(
          "info",
          "Content search reads the active workspace — switched back to it.",
        );
      return;
    }
    setSearchOpen(true);
  };

  const onDrop = (event: DragEvent, targetDir: string): void => {
    event.preventDefault();
    event.stopPropagation();
    setDropActive(false);
    if (!isActive) return;
    const files = [...event.dataTransfer.files];
    if (files.length > 0) void mutations.upload(files, targetDir);
  };
  const onDragOver = (event: DragEvent): void => {
    if (!isActive) return;
    event.preventDefault();
    setDropActive(true);
  };

  return (
    <aside
      className={`flex h-full w-64 shrink-0 flex-col border-r border-line bg-bg-elev/40 ${
        dropActive ? "ring-2 ring-inset ring-accent" : ""
      }`}
      onDragOver={onDragOver}
      onDragLeave={() => setDropActive(false)}
      onDrop={(event) => onDrop(event, "")}
    >
      <div className="space-y-2 border-b border-line px-3 py-2.5">
        <div className="flex items-center gap-2">
          <select
            value={viewDay ?? ""}
            onChange={(event) =>
              setDay(event.target.value === "" ? null : event.target.value)
            }
            aria-label="Workspace day"
            className="h-7 min-w-0 flex-1 rounded-lg border border-line bg-bg-elev px-2 text-[12px] outline-none focus:border-accent"
          >
            {days === null && <option value="">Active workspace</option>}
            {days?.map((entry) => (
              <option key={entry.day} value={entry.active ? "" : entry.day}>
                {entry.active ? `Active · ${entry.day}` : `${entry.day} (archived)`}
              </option>
            ))}
            {days !== null &&
              viewDay !== null &&
              !days.some((entry) => entry.day === viewDay) && (
                <option value={viewDay}>{viewDay} (archived)</option>
              )}
          </select>
          <IconButton label="Search workspace" onClick={openSearch}>
            <Search size={15} />
          </IconButton>
        </div>
        <Tabs
          items={[
            { value: "files", label: "Files" },
            { value: "trash", label: "Trash" },
          ]}
          value={panel}
          onChange={setPanel}
        />
      </div>

      {panel === "files" ? (
        <>
          <div className="flex items-center gap-1.5 border-b border-line px-3 py-2">
            <input
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Filter…"
              aria-label="Filter files"
              className="h-6.5 min-w-0 flex-1 rounded-md border border-line bg-bg-elev px-2 text-[12px] outline-none focus:border-accent"
            />
            {isActive && (
              <>
                <IconButton
                  label="New file"
                  className="h-6.5 w-6.5"
                  onClick={() => setCreateModal("file")}
                >
                  <FilePlus2 size={13} />
                </IconButton>
                <IconButton
                  label="New folder"
                  className="h-6.5 w-6.5"
                  onClick={() => setCreateModal("folder")}
                >
                  <FolderPlus size={13} />
                </IconButton>
              </>
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-1.5 py-1.5">
            {manifestLoading ? (
              <div className="flex items-center gap-2 px-2 py-3 text-[12px] text-fg-faint">
                <Loader2 size={13} className="animate-spin-slow" />
                Reading the manifest…
              </div>
            ) : tree.length === 0 ? (
              <EmptyState
                title={filter === "" ? "No files yet" : "No matches"}
                description={
                  filter === "" && isActive
                    ? "Create a file or drop files here to upload."
                    : undefined
                }
              />
            ) : (
              <TreeLevel
                nodes={tree}
                depth={0}
                dirtyLinks={dirtyLinks}
                onDrop={onDrop}
                onDragOver={onDragOver}
              />
            )}
          </div>
          {isActive && (
            <div className="border-t border-line px-3 py-1.5 text-[10.5px] text-fg-faint">
              <Upload size={10} className="mr-1 inline" />
              Drop files to upload (existing names are refused)
            </div>
          )}
        </>
      ) : (
        <TrashPanel epoch={epoch} apiDay={apiDay} isActive={isActive} mutations={mutations} />
      )}

      {createModal === "file" && (
        <PathInputModal
          title="New file"
          label="Path (e.g. notes/todo.md)"
          submitLabel="Create file"
          busy={mutations.busy}
          onSubmit={(path) => {
            void mutations.createFile(path).then((created) => {
              if (created !== null) {
                setCreateModal(null);
                useWorkspacePage.getState().select(`workspace:${created}`);
              }
            });
          }}
          onClose={() => setCreateModal(null)}
        />
      )}
      {createModal === "folder" && (
        <PathInputModal
          title="New folder"
          label="Path (e.g. notes/assets)"
          submitLabel="Create folder"
          busy={mutations.busy}
          onSubmit={(path) => {
            void mutations.createDirectory(path).then((created) => {
              if (created !== null) setCreateModal(null);
            });
          }}
          onClose={() => setCreateModal(null)}
        />
      )}
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Tree
// ---------------------------------------------------------------------------

function TreeLevel({
  nodes,
  depth,
  dirtyLinks,
  onDrop,
  onDragOver,
}: {
  nodes: WorkspaceTreeNode[];
  depth: number;
  dirtyLinks: ReadonlySet<string>;
  onDrop: (event: DragEvent, targetDir: string) => void;
  onDragOver: (event: DragEvent) => void;
}): ReactElement {
  return (
    <div>
      {nodes.map((node) => (
        <TreeNodeRow
          key={node.path}
          node={node}
          depth={depth}
          dirtyLinks={dirtyLinks}
          onDrop={onDrop}
          onDragOver={onDragOver}
        />
      ))}
    </div>
  );
}

function TreeNodeRow({
  node,
  depth,
  dirtyLinks,
  onDrop,
  onDragOver,
}: {
  node: WorkspaceTreeNode;
  depth: number;
  dirtyLinks: ReadonlySet<string>;
  onDrop: (event: DragEvent, targetDir: string) => void;
  onDragOver: (event: DragEvent) => void;
}): ReactElement {
  const [collapsed, setCollapsed] = useState(false);
  const selectedLink = useWorkspacePage((s) => s.link);
  const select = useWorkspacePage((s) => s.select);
  const link = `workspace:${node.path}`;

  if (node.kind === "directory") {
    return (
      <div
        onDrop={(event) => onDrop(event, node.path)}
        onDragOver={(event) => {
          event.stopPropagation();
          onDragOver(event);
        }}
      >
        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          className="flex h-6.5 w-full items-center gap-1 rounded-md px-1 text-left text-[12.5px] text-fg-muted hover:bg-hover"
          style={{ paddingLeft: `${depth * 12 + 4}px` }}
          title={node.path}
        >
          {collapsed ? (
            <ChevronRight size={12} className="shrink-0 text-fg-faint" />
          ) : (
            <ChevronDown size={12} className="shrink-0 text-fg-faint" />
          )}
          <FolderIcon size={13} className="shrink-0 text-fg-faint" />
          <span className="min-w-0 flex-1 truncate">{node.name}</span>
          {node.record?.tags.map((tag) => (
            <Badge key={tag} tone="gray" className="px-1 text-[9.5px]">
              {tag}
            </Badge>
          ))}
        </button>
        {!collapsed && (
          <TreeLevel
            nodes={node.children}
            depth={depth + 1}
            dirtyLinks={dirtyLinks}
            onDrop={onDrop}
            onDragOver={onDragOver}
          />
        )}
      </div>
    );
  }

  const selected = selectedLink === link;
  return (
    <button
      type="button"
      onClick={() => select(link)}
      className={`flex h-6.5 w-full items-center gap-1 rounded-md px-1 text-left text-[12.5px] ${
        selected ? "bg-accent-soft text-accent" : "text-fg-muted hover:bg-hover"
      }`}
      style={{ paddingLeft: `${depth * 12 + 17}px` }}
      title={node.path}
    >
      <FileIcon size={13} className="shrink-0 text-fg-faint" />
      <span className="min-w-0 flex-1 truncate">{node.name}</span>
      {dirtyLinks.has(link) && (
        <span
          className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent"
          title="Unsaved edits"
        />
      )}
      {node.record?.tags.map((tag) => (
        <Badge key={tag} tone="gray" className="px-1 text-[9.5px]">
          {tag}
        </Badge>
      ))}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Trash
// ---------------------------------------------------------------------------

function TrashPanel({
  epoch,
  apiDay,
  isActive,
  mutations,
}: {
  epoch: number;
  apiDay: string | null;
  isActive: boolean;
  mutations: WorkspaceMutations;
}): ReactElement {
  const trash = usePagedSequence<WorkspaceTrashItem, WorkspaceTrashPage>(
    (token, signal) => {
      const clients = useConnectionStore.getState().clients;
      if (clients === null) {
        return Promise.reject(new Error("Not connected to a backend."));
      }
      return clients.workspace.listTrash(
        {
          day: apiDay ?? undefined,
          continuation: token ?? undefined,
          limit: 50,
        },
        { signal },
      );
    },
    nextContinuation,
    [epoch, apiDay],
  );

  if (trash.loading) {
    return (
      <div className="flex items-center gap-2 px-3 py-3 text-[12px] text-fg-faint">
        <Loader2 size={13} className="animate-spin-slow" />
        Reading the trash…
      </div>
    );
  }
  if (trash.items.length === 0) {
    return (
      <EmptyState
        icon={<Trash2 size={22} />}
        title="Trash is empty"
        description={
          trash.error !== null ? trash.error : "Trashed resources stay restorable here."
        }
        action={
          trash.error !== null ? (
            <Button variant="outline" size="xs" onClick={trash.reload}>
              <RotateCcw size={12} />
              Retry
            </Button>
          ) : undefined
        }
      />
    );
  }
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-1.5 py-1.5">
      {trash.items.map((item) => (
        <div
          key={item.ref}
          className="mb-1 rounded-lg border border-line bg-bg-elev px-2.5 py-2"
        >
          <div
            className="truncate text-[12px] font-medium text-fg-muted"
            title={item.original.relative_path}
          >
            {item.original.relative_path}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10.5px] text-fg-faint">
            <span>{formatSize(item.original.size)}</span>
            <span>·</span>
            <span>{formatDateTime(item.trashed_at)}</span>
            {item.descendants.length > 0 && (
              <Badge tone="gray" className="px-1 text-[9.5px]">
                +{item.descendants.length} inside
              </Badge>
            )}
            {item.day !== "" && <span>· {item.day}</span>}
          </div>
          {isActive && (
            <div className="mt-1.5">
              <Button
                variant="outline"
                size="xs"
                loading={mutations.busy}
                onClick={() => {
                  void mutations.restore(item.ref).then((ok) => {
                    if (ok) {
                      useAppStore.getState().pushToast(
                        "success",
                        `Restored ${item.original.relative_path}.`,
                      );
                      trash.reload();
                    }
                  });
                }}
              >
                <RotateCcw size={11} />
                Restore
              </Button>
            </div>
          )}
        </div>
      ))}
      {trash.next !== null && (
        <Button
          variant="outline"
          size="xs"
          className="w-full"
          loading={trash.loadingMore}
          onClick={trash.loadMore}
        >
          Show more
        </Button>
      )}
      {trash.error !== null && (
        <div className="px-2 py-1.5 text-[11px] text-danger">{trash.error}</div>
      )}
    </div>
  );
}
