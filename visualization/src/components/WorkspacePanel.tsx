import { useEffect, useState } from "react";
import {
  FolderOpen,
  FilePlus,
  RefreshCw,
  Save,
  Trash2,
  FileText,
  Image as ImageIcon,
  RotateCcw,
} from "lucide-react";

import { useAppStore } from "../store/appStore";
import { useWorkspace } from "../hooks/useWorkspace";
import { formatSize, shorten } from "../utils/format";
import type { TrashItem, WorkspaceResourceRecord } from "../types";

const TEXT_KINDS = new Set(["text", "markdown", "script"]);

export function WorkspacePanel() {
  const store = useAppStore();
  const { workspace, workspaceLoading, workspaceError, openResource } = store;
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
  const [activeTreeTab, setActiveTreeTab] = useState<"resources" | "trash">(
    "resources",
  );

  useEffect(() => {
    if (store.connection.status === "connected") {
      void refresh();
    }
  }, [store.connection.status]);

  useEffect(() => {
    if (activeTreeTab === "trash") {
      void listTrash().then(setTrashItems);
    }
  }, [activeTreeTab, workspace?.revision]);

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

  const summary = workspace
    ? {
        total: workspace.resources.length,
        size: workspace.resources.reduce((acc, r) => acc + r.size, 0),
        byKind: workspace.resources.reduce(
          (acc, r) => {
            acc[r.kind] = (acc[r.kind] || 0) + 1;
            return acc;
          },
          {} as Record<string, number>,
        ),
      }
    : null;

  return (
    <div className="workspace-layout">
      <div className="workspace-tree">
        <div className="panel h-full">
          <div className="panel-header">
            <span className="flex items-center gap-2">
              <FolderOpen size={14} />
              Workspace
            </span>
            <div className="flex gap-2">
              <button
                className="btn btn-sm"
                onClick={() => void refresh()}
                disabled={workspaceLoading}
              >
                <RefreshCw
                  size={12}
                  className={workspaceLoading ? "spin" : ""}
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
          <div
            className="panel-body"
            style={{ padding: 0, display: "flex", flexDirection: "column" }}
          >
            {summary && (
              <div
                className="flex gap-2 p-3 border-b"
                style={{ borderColor: "var(--border)" }}
              >
                <div className="badge badge-normal">{summary.total} files</div>
                <div className="badge badge-normal">
                  {formatSize(summary.size)}
                </div>
                {Object.entries(summary.byKind).map(([kind, count]) => (
                  <div key={kind} className="badge badge-normal">
                    {kind} {count}
                  </div>
                ))}
              </div>
            )}
            <div className="tabs p-2">
              <button
                className={`tab ${activeTreeTab === "resources" ? "active" : ""}`}
                onClick={() => setActiveTreeTab("resources")}
              >
                Resources
              </button>
              <button
                className={`tab ${activeTreeTab === "trash" ? "active" : ""}`}
                onClick={() => setActiveTreeTab("trash")}
              >
                Trash
              </button>
            </div>
            <div
              className="resource-list p-2"
              style={{ flex: 1, overflowY: "auto" }}
            >
              {workspaceError && (
                <div className="text-danger text-xs">{workspaceError}</div>
              )}
              {activeTreeTab === "resources" &&
                workspace?.resources.length === 0 && (
                  <div className="text-muted text-xs">Workspace is empty.</div>
                )}
              {activeTreeTab === "resources" &&
                workspace?.resources.map((resource) => (
                  <ResourceItem
                    key={resource.link}
                    resource={resource}
                    active={openResource?.link === resource.link}
                    onOpen={() => void readText(resource.link)}
                    onDelete={() =>
                      void deleteResource(resource.link, resource.digest || "")
                    }
                  />
                ))}
              {activeTreeTab === "trash" && trashItems.length === 0 && (
                <div className="text-muted text-xs">Trash is empty.</div>
              )}
              {activeTreeTab === "trash" &&
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

      <div className="workspace-editor">
        <div className="panel h-full">
          <div className="panel-header">
            <span className="flex items-center gap-2">
              <FileText size={14} />
              {openResource ? openResource.link : "Select a resource"}
            </span>
            {openResource && (
              <div className="flex gap-2">
                <span className="text-xs text-muted">
                  {formatSize(openResource.read.size)} ·{" "}
                  {shorten(openResource.read.digest)}
                </span>
                <button
                  className="btn btn-sm btn-primary"
                  onClick={() => void onSave()}
                  disabled={!openResource.dirty}
                >
                  <Save size={12} />
                  Save
                </button>
              </div>
            )}
          </div>
          <div className="panel-body" style={{ padding: 0 }}>
            {openResource ? (
              <textarea
                className="textarea"
                style={{ height: "100%", border: "none", borderRadius: 0 }}
                value={openResource.draft}
                onChange={(e) => store.updateResourceDraft(e.target.value)}
                spellCheck={false}
              />
            ) : (
              <div className="empty-state">
                <div className="empty-state-icon">
                  <FolderOpen size={48} />
                </div>
                <div>Select a resource from the tree to view or edit.</div>
              </div>
            )}
          </div>
        </div>
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

interface ResourceItemProps {
  resource: WorkspaceResourceRecord;
  active: boolean;
  onOpen: () => void;
  onDelete: () => void;
}

function ResourceItem({
  resource,
  active,
  onOpen,
  onDelete,
}: ResourceItemProps) {
  const isText =
    TEXT_KINDS.has(resource.kind) || resource.media_type.startsWith("text/");
  return (
    <div className={`resource-item ${active ? "active" : ""}`} onClick={onOpen}>
      <span className="text-muted">
        {isText ? <FileText size={14} /> : <ImageIcon size={14} />}
      </span>
      <div className="resource-info">
        <div className="resource-link" title={resource.link}>
          {resource.link}
        </div>
        <div className="resource-summary" title={resource.summary}>
          {resource.summary || resource.description || resource.media_type}
        </div>
      </div>
      <div className="resource-actions">
        <button
          className="btn btn-sm btn-danger"
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          title="Move to trash"
        >
          <Trash2 size={12} />
        </button>
      </div>
    </div>
  );
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
      <span className="text-muted">
        <Trash2 size={14} />
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
        <button className="btn btn-sm" onClick={onRestore} title="Restore">
          <RotateCcw size={12} />
        </button>
      </div>
    </div>
  );
}
