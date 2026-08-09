import { useEffect, useState } from "react";
import { FilePlus2, FolderTree, RotateCcw, Search, Trash2 } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { useWorkspace } from "../../hooks/useWorkspace";
import type { TrashItem, WorkspaceResourceRecord } from "../../types";
import { formatDateTime, formatSize } from "../../utils/format";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { Modal } from "../ui/Modal";
import { Tabs } from "../ui/Tabs";
import { WorkspaceTree } from "./WorkspaceTree";
import { ResourceEditor } from "./ResourceEditor";
import { BinaryPreview } from "./BinaryPreview";

export function WorkspaceView() {
  const workspace = useAppStore((s) => s.workspace);
  const workspaceLoading = useAppStore((s) => s.workspaceLoading);
  const workspaceError = useAppStore((s) => s.workspaceError);
  const openResource = useAppStore((s) => s.openResource);
  const closeResource = useAppStore((s) => s.closeResource);
  const pushToast = useAppStore((s) => s.pushToast);
  const { refresh, readText, deleteResource, listTrash, restoreResource } = useWorkspace();

  const [tab, setTab] = useState<"files" | "trash">("files");
  const [filter, setFilter] = useState("");
  const [trash, setTrash] = useState<TrashItem[]>([]);
  const [binary, setBinary] = useState<WorkspaceResourceRecord | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!workspace) void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (tab === "trash") void listTrash().then(setTrash);
  }, [tab, listTrash]);

  const open = (resource: WorkspaceResourceRecord) => {
    if (isTextLike(resource)) {
      setBinary(null);
      void readText(resource.link);
    } else {
      closeResource();
      setBinary(resource);
    }
  };

  const remove = async (resource: WorkspaceResourceRecord) => {
    await deleteResource(resource.link, resource.digest ?? "");
    pushToast("info", `Moved ${resource.link} to trash.`);
  };

  const resources = workspace?.resources ?? [];

  return (
    <div className="flex h-full min-h-0">
      {/* left panel */}
      <div className="flex w-[280px] shrink-0 flex-col border-r border-line bg-bg-elev">
        <div className="flex items-center gap-2 border-b border-line px-3 py-2.5">
          <Tabs
            items={[
              { value: "files", label: "Files", count: resources.length },
              { value: "trash", label: "Trash" },
            ]}
            value={tab}
            onChange={setTab}
          />
          <div className="ml-auto flex items-center gap-0.5">
            <button
              onClick={() => void refresh()}
              title="Refresh manifest"
              className="rounded-md p-1.5 text-fg-muted hover:bg-hover hover:text-fg"
            >
              <RotateCcw size={13} className={workspaceLoading ? "animate-spin-slow" : ""} />
            </button>
            <button
              onClick={() => setCreating(true)}
              title="New resource"
              className="rounded-md p-1.5 text-fg-muted hover:bg-hover hover:text-fg"
            >
              <FilePlus2 size={14} />
            </button>
          </div>
        </div>

        {tab === "files" && (
          <div className="border-b border-line px-3 py-2">
            <div className="relative">
              <Search size={12} className="absolute top-1/2 left-2.5 -translate-y-1/2 text-fg-faint" />
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter files…"
                className="h-7 w-full rounded-md border border-line bg-bg px-2 pl-7 text-[12px] outline-none focus:border-accent"
              />
            </div>
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {workspaceError && (
            <div className="m-1 rounded-lg bg-danger-soft px-2.5 py-2 text-[12px] text-danger">
              {workspaceError}
            </div>
          )}
          {tab === "files" ? (
            resources.length === 0 ? (
              <EmptyState
                icon={<FolderTree size={24} />}
                title="Workspace is empty"
                description="Resources the agent creates during turns appear here."
              />
            ) : (
              <WorkspaceTree
                resources={resources}
                activeLink={openResource?.link ?? binary?.link ?? null}
                dirty={openResource?.dirty ? openResource.link : null}
                filter={filter}
                onOpen={open}
                onDelete={(r) => void remove(r)}
              />
            )
          ) : (
            <TrashList
              items={trash}
              onRestore={(ref) =>
                void restoreResource(ref).then(() => listTrash().then(setTrash))
              }
            />
          )}
        </div>

        {workspace && (
          <div className="border-t border-line px-3 py-1.5 text-[10px] text-fg-faint">
            day {workspace.day} · revision {workspace.revision}
          </div>
        )}
      </div>

      {/* right panel */}
      <div className="min-w-0 flex-1 bg-bg">
        {openResource ? (
          <ResourceEditor />
        ) : binary ? (
          <BinaryPreview resource={binary} />
        ) : (
          <EmptyState
            icon={<FolderTree size={28} />}
            title="No resource selected"
            description="Pick a file from the tree to view or edit it. Markdown files get a live rendered preview."
          />
        )}
      </div>

      {creating && <NewResourceDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

function isTextLike(resource: WorkspaceResourceRecord): boolean {
  return (
    resource.kind === "text" ||
    resource.media_type.startsWith("text/") ||
    resource.media_type === "application/json" ||
    resource.media_type === "text/markdown"
  );
}

function TrashList({
  items,
  onRestore,
}: {
  items: TrashItem[];
  onRestore: (ref: string) => void;
}) {
  if (items.length === 0) {
    return <EmptyState icon={<Trash2 size={24} />} title="Trash is empty" />;
  }
  return (
    <div className="space-y-1">
      {items.map((item) => (
        <div
          key={item.ref}
          className="flex items-center gap-2 rounded-lg border border-line bg-bg px-2.5 py-2"
        >
          <Trash2 size={13} className="shrink-0 text-fg-faint" />
          <div className="min-w-0 flex-1">
            <div className="truncate font-mono text-[11px] text-fg">{item.link}</div>
            <div className="text-[10px] text-fg-faint">
              {formatSize(item.size)} · {formatDateTime(item.moved_at)}
            </div>
          </div>
          <Button size="xs" variant="outline" onClick={() => onRestore(item.ref)}>
            Restore
          </Button>
        </div>
      ))}
    </div>
  );
}

function NewResourceDialog({ onClose }: { onClose: () => void }) {
  const { createResource } = useWorkspace();
  const pushToast = useAppStore((s) => s.pushToast);
  const [link, setLink] = useState("workspace:");
  const [busy, setBusy] = useState(false);
  const valid = /^workspace:[^\s]+\.[^\s/]+$/.test(link);

  const create = async () => {
    if (!valid) return;
    setBusy(true);
    try {
      await createResource(link, "", "day");
      pushToast("success", `Created ${link}`);
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="New workspace resource" onClose={onClose}>
      <div className="space-y-3">
        <input
          value={link}
          onChange={(e) => setLink(e.target.value)}
          placeholder="workspace:notes/example.md"
          className="h-9 w-full rounded-lg border border-line bg-bg-elev px-3 font-mono text-[12px] outline-none focus-ring focus:border-accent"
        />
        {!valid && (
          <p className="text-[11px] text-fg-faint">
            Use a workspace: link with a file extension, e.g. workspace:doc/notes.md
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!valid} loading={busy} onClick={() => void create()}>
            Create
          </Button>
        </div>
      </div>
    </Modal>
  );
}
