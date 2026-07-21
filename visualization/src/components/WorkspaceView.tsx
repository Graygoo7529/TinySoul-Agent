import { useEffect, useMemo, useState } from "react";
import {
  FolderOpen,
  FilePlus,
  RefreshCw,
  Trash2,
  RotateCcw,
  Search,
  X,
} from "lucide-react";

import { useAppStore } from "../store/appStore";
import { useWorkspace } from "../hooks/useWorkspace";
import { WorkspaceTree } from "./WorkspaceTree";
import { MarkdownEditor } from "./MarkdownEditor";
import { BinaryPreview } from "./BinaryPreview";
import { formatSize } from "../utils/format";
import type { TrashItem, WorkspaceResourceRecord } from "../types";

const TEXT_KINDS = new Set(["text", "markdown", "script"]);

export function WorkspaceView() {
  const store = useAppStore();
  const {
    workspace,
    workspaceLoading,
    workspaceError,
    workspaceConflict,
    openResource,
  } = store;
  const {
    refresh,
    readText,
    saveText,
    createResource,
    deleteResource,
    listTrash,
    restoreResource,
  } = useWorkspace();

  const [showNewDialog, setShowNewDialog] = useState(false);
  const [newLink, setNewLink] = useState("workspace:");
  const [newContent, setNewContent] = useState("");
  const [trashItems, setTrashItems] = useState<TrashItem[]>([]);
  const [activeTab, setActiveTab] = useState<"files" | "trash">("files");
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (store.connection.status === "connected") {
      void refresh();
    }
  }, [store.connection.status]);

  useEffect(() => {
    if (activeTab === "trash") {
      void listTrash().then(setTrashItems);
    }
  }, [activeTab, workspace?.revision]);

  const activeRecord = useMemo(() => {
    if (!openResource || !workspace) return null;
    return (
      workspace.resources.find((r) => r.link === openResource.link) || null
    );
  }, [openResource, workspace]);

  const dirtyLinks = useMemo(
    () =>
      openResource?.dirty ? new Set([openResource.link]) : new Set<string>(),
    [openResource],
  );

  const onSave = async () => {
    if (!openResource) return;
    await saveText(
      openResource.link,
      openResource.draft,
      true,
      openResource.read.digest,
    );
  };

  const onCreate = async () => {
    if (!newLink.trim() || !newLink.startsWith("workspace:")) return;
    await createResource(newLink, newContent, "day");
    setShowNewDialog(false);
    setNewLink("workspace:");
    setNewContent("");
  };

  const onResolveConflict = (action: "overwrite" | "discard") => {
    if (!openResource) return;
    if (action === "overwrite") {
      void saveText(
        openResource.link,
        openResource.draft,
        true,
        openResource.read.digest,
      );
    } else {
      store.updateResourceDraft(openResource.read.text);
      store.setWorkspaceConflict(false);
    }
  };

  const summary = workspace
    ? {
        total: workspace.resources.length,
        size: workspace.resources.reduce((acc, r) => acc + r.size, 0),
      }
    : null;

  return (
    <div className="workspace-view">
      <div className="workspace-sidebar">
        <div className="panel h-full">
          <div className="panel-header">
            <span className="flex items-center gap-2">
              <FolderOpen size={14} />
              Workspace
            </span>
            <div className="flex gap-2">
              <button
                className="btn btn-sm btn-ghost"
                onClick={() => void refresh()}
                disabled={workspaceLoading}
              >
                <RefreshCw
                  size={12}
                  className={workspaceLoading ? "animate-spin" : ""}
                />
              </button>
              <button
                className="btn btn-sm btn-primary"
                onClick={() => setShowNewDialog(true)}
              >
                <FilePlus size={12} />
              </button>
            </div>
          </div>
          <div className="panel-body" style={{ padding: 0 }}>
            {summary && (
              <div className="workspace-summary">
                <span className="badge badge-subtle">
                  {summary.total} files
                </span>
                <span className="badge badge-subtle">
                  {formatSize(summary.size)}
                </span>
              </div>
            )}
            <div className="workspace-search">
              <Search size={12} className="workspace-search-icon" />
              <input
                className="workspace-search-input"
                placeholder="Filter by path…"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
              {filter && (
                <button
                  className="workspace-search-clear"
                  onClick={() => setFilter("")}
                >
                  <X size={12} />
                </button>
              )}
            </div>
            <div className="tabs p-3">
              <button
                className={`tab ${activeTab === "files" ? "active" : ""}`}
                onClick={() => setActiveTab("files")}
              >
                Files
              </button>
              <button
                className={`tab ${activeTab === "trash" ? "active" : ""}`}
                onClick={() => setActiveTab("trash")}
              >
                Trash
              </button>
            </div>
            <div className="resource-list">
              {workspaceError && (
                <div className="text-danger text-xs p-2">{workspaceError}</div>
              )}
              {activeTab === "files" && workspace && (
                <WorkspaceTree
                  resources={workspace.resources}
                  activeLink={openResource?.link}
                  dirtyLinks={dirtyLinks}
                  filter={filter}
                  onOpen={(resource) => void readText(resource.link)}
                  onDelete={(resource) =>
                    void deleteResource(resource.link, resource.digest || "")
                  }
                />
              )}
              {activeTab === "files" && !workspace && !workspaceError && (
                <div className="text-muted text-xs p-2">
                  Workspace is empty.
                </div>
              )}
              {activeTab === "trash" && trashItems.length === 0 && (
                <div className="text-muted text-xs p-2">Trash is empty.</div>
              )}
              {activeTab === "trash" &&
                trashItems.map((item) => (
                  <TrashItemRow
                    key={item.ref}
                    item={item}
                    onRestore={() =>
                      void restoreResource(item.ref).then(
                        () => void listTrash().then(setTrashItems),
                      )
                    }
                  />
                ))}
            </div>
          </div>
        </div>
      </div>

      <div className="workspace-main">
        {openResource && activeRecord && isTextLike(activeRecord) ? (
          <MarkdownEditor
            resource={activeRecord}
            open={openResource}
            onSave={() => void onSave()}
            conflict={workspaceConflict}
            onResolveConflict={onResolveConflict}
          />
        ) : openResource && activeRecord ? (
          <BinaryPreview resource={activeRecord} />
        ) : (
          <div className="panel h-full">
            <div className="panel-header">
              <span className="flex items-center gap-2">
                <FolderOpen size={14} />
                Select a resource
              </span>
            </div>
            <div className="panel-body" style={{ padding: 0 }}>
              <div className="empty-state">
                <div className="empty-state-icon">
                  <FolderOpen size={48} />
                </div>
                <div>Select a resource from the sidebar to view or edit.</div>
              </div>
            </div>
          </div>
        )}
      </div>

      {showNewDialog && (
        <div
          className="modal-overlay"
          onClick={(e) =>
            e.target === e.currentTarget && setShowNewDialog(false)
          }
        >
          <div className="modal">
            <div className="modal-header">New Workspace Resource</div>
            <div className="modal-body flex flex-col gap-3">
              <label className="text-sm">
                Link
                <input
                  className="input mt-1"
                  value={newLink}
                  onChange={(e) => setNewLink(e.target.value)}
                  placeholder="workspace:notes/demo.md"
                />
              </label>
              <label className="text-sm">
                Initial content
                <textarea
                  className="textarea mt-1"
                  rows={8}
                  value={newContent}
                  onChange={(e) => setNewContent(e.target.value)}
                />
              </label>
            </div>
            <div className="modal-footer">
              <button className="btn" onClick={() => setShowNewDialog(false)}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={() => void onCreate()}
                disabled={!newLink.startsWith("workspace:")}
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function isTextLike(resource: WorkspaceResourceRecord): boolean {
  if (TEXT_KINDS.has(resource.kind)) return true;
  if (resource.media_type.startsWith("text/")) return true;
  if (resource.suffix === "md" || resource.suffix === "txt") return true;
  return false;
}

function TrashItemRow({
  item,
  onRestore,
}: {
  item: TrashItem;
  onRestore: () => void;
}) {
  return (
    <div className="resource-item">
      <span className="resource-icon">
        <Trash2 size={16} />
      </span>
      <div className="resource-info">
        <div className="resource-link" title={item.link}>
          {item.link}
        </div>
        <div className="resource-summary">
          {formatSize(item.size)} · {item.kind}
        </div>
      </div>
      <div className="resource-actions" style={{ opacity: 1 }}>
        <button
          className="btn btn-sm btn-ghost btn-icon"
          onClick={onRestore}
          title="Restore"
        >
          <RotateCcw size={12} />
        </button>
      </div>
    </div>
  );
}
