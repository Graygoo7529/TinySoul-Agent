/**
 * Selected-resource panel of the Workspace page (plan §10/P06).
 *
 * The header carries the manifest facts (path, kind, tags, size) and the
 * resource operations; the body dispatches on the committed record kind
 * (text, image, other binary, directory). External changes are detected by
 * comparing the refreshed manifest record against the baseline adopted when
 * the file was read or last saved: a clean view re-reads silently, an
 * unsaved draft is never overwritten — it gets an explicit
 * Reload / Keep editing choice.
 */

import {
  useEffect,
  useRef,
  useState,
  type ReactElement,
} from "react";
import {
  AlertTriangle,
  Copy,
  Download,
  FilePlus2,
  Folder as FolderIcon,
  FolderInput,
  MessageSquareQuote,
  Replace,
  Tags as TagsIcon,
  Trash2,
} from "lucide-react";

import type {
  WorkspaceResourceRecord,
  WorkspaceTag,
} from "../../api/v2/types";
import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Button, IconButton } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";
import { useAppStore } from "../../store/appStore";
import { formatSize } from "../../utils/format";
import { copyReference, quoteReference } from "../resources/router";
import { BlobView } from "./BlobView";
import { TextFileView } from "./TextFileView";
import { downloadWorkspaceBlob } from "./download";
import { AppendModal, PathInputModal, ReplaceModal, TagsModal } from "./modals";
import type { WorkspaceMutations } from "./mutations";
import { useWorkspacePage, workspaceDraftKey } from "./store";

type PanelModal = "move" | "tags" | "append" | "replace" | "trash" | null;

const TAG_TONES: Record<string, BadgeTone> = {
  pinned: "accent",
  tmp: "yellow",
  library: "teal",
};

export function FilePanel({
  viewDay,
  activeDay,
  record,
  fragment,
  mutations,
}: {
  /** The day the page displays; null = active. */
  viewDay: string | null;
  activeDay: string | null;
  record: WorkspaceResourceRecord;
  fragment: string | null;
  mutations: WorkspaceMutations;
}): ReactElement {
  const isActive = viewDay === null || viewDay === activeDay;
  const apiDay = isActive ? null : viewDay;
  const select = useWorkspacePage((s) => s.select);
  const draftKey = workspaceDraftKey(apiDay, record.ref);
  const dirty = useWorkspacePage((s) => s.drafts[draftKey] !== undefined);
  const setDraft = useWorkspacePage((s) => s.setDraft);

  const [modal, setModal] = useState<PanelModal>(null);
  const [externalChange, setExternalChange] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const baselineRef = useRef<{ mtime: number; size: number } | null>(null);

  // A new selection adopts the current record as its baseline.
  useEffect(() => {
    baselineRef.current = { mtime: record.mtime_ns, size: record.size };
    setExternalChange(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [record.ref, viewDay]);

  // Later manifest refreshes: a changed record is an external change. A
  // clean view re-reads; a dirty draft asks.
  useEffect(() => {
    const baseline = baselineRef.current;
    if (baseline === null) return;
    if (record.mtime_ns === baseline.mtime && record.size === baseline.size) {
      return;
    }
    if (dirty) {
      setExternalChange(true);
    } else {
      baselineRef.current = { mtime: record.mtime_ns, size: record.size };
      setReloadToken((token) => token + 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [record.mtime_ns, record.size, dirty]);

  const adoptRecord = (committed: WorkspaceResourceRecord): void => {
    baselineRef.current = { mtime: committed.mtime_ns, size: committed.size };
    setExternalChange(false);
    setReloadToken((token) => token + 1);
  };

  const closeModal = () => setModal(null);
  const isText = record.kind === "text";
  const fileName =
    record.relative_path.split("/").pop() ?? record.relative_path;

  const runMove = async (target: string): Promise<void> => {
    const moved = await mutations.move(record.ref, target);
    if (moved !== null) {
      closeModal();
      select(`workspace:${moved}`);
    }
  };
  const runTags = async (tags: WorkspaceTag[]): Promise<void> => {
    const committed = await mutations.setTags(record.ref, tags);
    if (committed !== null) closeModal();
  };
  const runAppend = async (text: string): Promise<void> => {
    const committed = await mutations.append(record.ref, text);
    if (committed !== null) {
      closeModal();
      adoptRecord(committed);
    }
  };
  const runReplace = async (oldText: string, newText: string): Promise<void> => {
    const committed = await mutations.replaceText(record.ref, oldText, newText);
    if (committed !== null) {
      closeModal();
      adoptRecord(committed);
    }
  };
  const runTrash = async (): Promise<void> => {
    const ok = await mutations.trash(record.ref);
    if (ok) {
      closeModal();
      select(null);
      useAppStore.getState().pushToast("success", "Moved to trash.", {
        label: "View trash",
        onClick: () => useWorkspacePage.getState().setPanel("trash"),
      });
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-start gap-2 border-b border-line px-4 py-2">
        <div className="min-w-0 flex-1">
          <div
            className="truncate text-[13px] font-medium"
            title={record.ref}
          >
            {record.relative_path}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-fg-faint">
            {!isActive && <Badge tone="yellow">Archived · read-only</Badge>}
            {record.tags.map((tag) => (
              <Badge key={tag} tone={TAG_TONES[tag] ?? "gray"}>
                {tag}
              </Badge>
            ))}
            <span>{record.kind}</span>
            <span>·</span>
            <span>{formatSize(record.size)}</span>
            <span>·</span>
            <span className="truncate">{record.media_type}</span>
            {dirty && <Badge tone="accent">edited</Badge>}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          {isActive && isText && (
            <>
              <IconButton
                label="Append text"
                onClick={() => setModal("append")}
              >
                <FilePlus2 size={15} />
              </IconButton>
              <IconButton
                label="Find and replace"
                onClick={() => setModal("replace")}
              >
                <Replace size={15} />
              </IconButton>
            </>
          )}
          {isActive && (
            <>
              <IconButton label="Move or rename" onClick={() => setModal("move")}>
                <FolderInput size={15} />
              </IconButton>
              <IconButton label="Tags" onClick={() => setModal("tags")}>
                <TagsIcon size={15} />
              </IconButton>
            </>
          )}
          {record.kind !== "directory" && (
            <IconButton
              label="Download"
              onClick={() =>
                void downloadWorkspaceBlob(record.ref, apiDay, fileName)
              }
            >
              <Download size={15} />
            </IconButton>
          )}
          <IconButton
            label="Copy reference"
            onClick={() => copyReference(record.ref)}
          >
            <Copy size={15} />
          </IconButton>
          <IconButton
            label="Quote in conversation"
            onClick={() =>
              quoteReference(record.ref, {
                ref: record.ref,
                day: apiDay ?? undefined,
              })
            }
          >
            <MessageSquareQuote size={15} />
          </IconButton>
          {isActive && (
            <IconButton label="Move to trash" onClick={() => setModal("trash")}>
              <Trash2 size={15} />
            </IconButton>
          )}
        </div>
      </div>

      {externalChange && (
        <div className="flex items-center gap-2 border-b border-line bg-warning-soft px-4 py-2 text-[12px] text-warning">
          <AlertTriangle size={12} className="shrink-0" />
          <span className="min-w-0 flex-1">
            This file changed on disk while you have unsaved edits.
          </span>
          <button
            type="button"
            className="shrink-0 font-medium hover:underline"
            onClick={() => {
              setDraft(draftKey, null);
              baselineRef.current = {
                mtime: record.mtime_ns,
                size: record.size,
              };
              setExternalChange(false);
              setReloadToken((token) => token + 1);
            }}
          >
            Reload
          </button>
          <button
            type="button"
            className="shrink-0 font-medium hover:underline"
            onClick={() => setExternalChange(false)}
          >
            Keep editing
          </button>
        </div>
      )}

      {record.kind === "directory" ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <div className="max-w-sm space-y-2 text-center">
            <FolderIcon size={26} className="mx-auto text-fg-faint" />
            <div className="text-sm font-medium text-fg-muted">
              {record.relative_path}
            </div>
            <div className="text-[12px] text-fg-faint">
              Directory — its files appear in the tree.
              {record.description !== "" && ` ${record.description}`}
            </div>
          </div>
        </div>
      ) : isText ? (
        <TextFileView
          ref={record.ref}
          day={apiDay}
          isActive={isActive}
          fragment={fragment}
          record={record}
          reloadToken={reloadToken}
          mutations={mutations}
          onSaved={adoptRecord}
          onConsumeFragment={() => select(record.ref)}
        />
      ) : (
        <BlobView ref={record.ref} day={apiDay} record={record} />
      )}

      {modal === "move" && (
        <PathInputModal
          title="Move or rename"
          label="Target path"
          initial={record.relative_path}
          submitLabel="Move"
          busy={mutations.busy}
          onSubmit={(path) => void runMove(path)}
          onClose={closeModal}
        />
      )}
      {modal === "tags" && (
        <TagsModal
          tags={record.tags}
          busy={mutations.busy}
          onSubmit={(tags) => void runTags(tags)}
          onClose={closeModal}
        />
      )}
      {modal === "append" && (
        <AppendModal
          busy={mutations.busy}
          onSubmit={(text) => void runAppend(text)}
          onClose={closeModal}
        />
      )}
      {modal === "replace" && (
        <ReplaceModal
          busy={mutations.busy}
          onSubmit={(oldText, newText) => void runReplace(oldText, newText)}
          onClose={closeModal}
        />
      )}
      {modal === "trash" && (
        <Modal title="Move to trash" onClose={closeModal} width="max-w-sm">
          <div className="space-y-3">
            <p className="text-[13px] text-fg-muted">
              Move{" "}
              <span className="font-mono text-[12px] text-fg">
                {record.relative_path}
              </span>{" "}
              to the trash? It stays restorable from the Trash tab — there is
              no permanent delete here.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={closeModal}>
                Cancel
              </Button>
              <Button
                variant="danger"
                loading={mutations.busy}
                onClick={() => void runTrash()}
              >
                Move to trash
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
