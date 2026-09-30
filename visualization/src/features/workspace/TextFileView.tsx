/**
 * Text resource read and edit (plan §10/P06).
 *
 * Read mode pages the text (Show more follows the continuation token); a
 * `#L…` fragment switches to the line view, auto-reads pages until the target
 * line is covered, then highlights and scrolls to it. Editing is gated on
 * the full editable text: an incomplete paged read first goes through
 * `full=true` and an owner rejection stays a clear "too large to edit", never
 * a silent save of the first screen. Drafts live in the page store, survive
 * tab switches and external manifest changes, and Ctrl+S saves.
 */

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
} from "react";
import {
  AlertTriangle,
  Eye,
  Loader2,
  Pencil,
  RotateCcw,
  Save,
  X,
} from "lucide-react";

import type { WorkspaceResourceRecord } from "../../api/v2/types";
import { Markdown } from "../../components/markdown/Markdown";
import { Button } from "../../components/ui/Button";
import { Tabs } from "../../components/ui/Tabs";
import { useAppStore } from "../../store/appStore";
import { useConnectionStore } from "../../store/connectionStore";
import { parseLineFragment } from "../resources/reference";
import { useWorkspacePage, workspaceDraftKey } from "./store";
import type { WorkspaceMutations } from "./mutations";
import { useWorkspaceText } from "./useWorkspaceText";

type EditorView = "edit" | "split" | "preview";

export function TextFileView({
  link,
  day,
  isActive,
  fragment,
  record,
  reloadToken,
  mutations,
  onSaved,
  onConsumeFragment,
}: {
  /** Fragment-free `workspace:` link. */
  link: string;
  /** Archive binding; null reads/writes the active day. */
  day: string | null;
  isActive: boolean;
  fragment: string | null;
  record: WorkspaceResourceRecord;
  /** Bumped by the owner panel to restart the paged read. */
  reloadToken: number;
  mutations: WorkspaceMutations;
  /** The committed record after a successful save (baseline update). */
  onSaved: (record: WorkspaceResourceRecord) => void;
  /** The fragment was honoured; clear it from the page selection. */
  onConsumeFragment: () => void;
}): ReactElement {
  const [retry, setRetry] = useState(0);
  const text = useWorkspaceText(link, day, reloadToken + retry);
  const draftKey = workspaceDraftKey(day, link);
  const draft = useWorkspacePage((s) => s.drafts[draftKey]);
  const setDraft = useWorkspacePage((s) => s.setDraft);
  const editing = draft !== undefined;

  const isMarkdown =
    record.media_type === "text/markdown" ||
    record.suffix === ".md" ||
    record.suffix === ".markdown";
  const [sourceView, setSourceView] = useState(false);
  const [editorView, setEditorView] = useState<EditorView>("split");
  const targetLines = useMemo(() => parseLineFragment(fragment), [fragment]);
  const lines = useMemo(() => text.text.split("\n"), [text.text]);

  // A line fragment pulls pages until its target is covered (or the read
  // ends); the highlight only points at lines actually read.
  useEffect(() => {
    if (targetLines === null) return;
    if (text.next === null || text.complete) return;
    if (lines.length >= targetLines.endLine) return;
    if (text.loading || text.loadingMore || text.error !== null) return;
    text.loadMore();
  }, [targetLines, text.next, text.complete, text.loading, text.loadingMore, text.error, lines.length, text.loadMore]);

  const scrolledRef = useRef<string | null>(null);
  useEffect(() => {
    if (targetLines === null) return;
    const key = `${day ?? ""}|${link}#${fragment ?? ""}`;
    if (scrolledRef.current === key) return;
    if (lines.length < targetLines.startLine) return;
    const element = document.getElementById(`ws-line-${targetLines.startLine}`);
    if (element !== null) {
      element.scrollIntoView({ block: "center" });
      scrolledRef.current = key;
    }
  }, [targetLines, lines.length, day, link, fragment]);

  const startEdit = async (): Promise<void> => {
    if (!isActive || !text.editable) return;
    if (text.complete) {
      setDraft(draftKey, text.text);
      return;
    }
    // The paged screen is not the whole file: gate on the full editable read.
    const clients = useConnectionStore.getState().clients;
    if (clients === null) return;
    try {
      const page = await clients.workspace.resource({
        link,
        day: day ?? undefined,
        full: true,
      });
      setDraft(draftKey, page.text);
    } catch (error) {
      useAppStore
        .getState()
        .pushToast(
          "error",
          `This file cannot be edited in the page (full read rejected): ${
            error instanceof Error ? error.message : String(error)
          }`,
        );
    }
  };

  const save = async (): Promise<void> => {
    if (draft === undefined) return;
    const record = await mutations.saveText(link, draft);
    if (record !== null) {
      setDraft(draftKey, null);
      onSaved(record);
    }
  };

  const showLines = !editing && (sourceView || !isMarkdown || targetLines !== null);
  const markdownOrigin = useMemo(
    () => ({ link, day: day ?? undefined }),
    [link, day],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b border-line px-4 py-1.5">
        {editing ? (
          <>
            {isMarkdown && (
              <Tabs<EditorView>
                items={[
                  { value: "edit", label: "Edit" },
                  { value: "split", label: "Split" },
                  { value: "preview", label: "Preview" },
                ]}
                value={editorView}
                onChange={setEditorView}
              />
            )}
            <span className="flex-1" />
            <Button
              variant="ghost"
              size="xs"
              onClick={() => setDraft(draftKey, null)}
            >
              <X size={12} />
              Discard
            </Button>
            <Button
              variant="primary"
              size="xs"
              loading={mutations.busy}
              onClick={() => void save()}
            >
              <Save size={12} />
              Save
            </Button>
          </>
        ) : (
          <>
            {isMarkdown && targetLines === null && (
              <Button
                variant="ghost"
                size="xs"
                className={sourceView ? "bg-hover text-fg" : ""}
                onClick={() => setSourceView((value) => !value)}
              >
                <Eye size={12} />
                {sourceView ? "Rendered" : "Source"}
              </Button>
            )}
            {targetLines !== null && (
              <span className="flex items-center gap-2 text-[11px] text-accent">
                Lines {targetLines.startLine}
                {targetLines.endLine !== targetLines.startLine &&
                  `–${targetLines.endLine}`}
                {isMarkdown && (
                  <button
                    type="button"
                    className="hover:underline"
                    onClick={() => {
                      setSourceView(false);
                      onConsumeFragment();
                    }}
                  >
                    Show rendered
                  </button>
                )}
              </span>
            )}
            {text.truncated && (
              <span className="text-[11px] text-fg-faint">truncated page</span>
            )}
            <span className="flex-1" />
            {isActive && text.editable && (
              <Button variant="outline" size="xs" onClick={() => void startEdit()}>
                <Pencil size={12} />
                Edit
              </Button>
            )}
          </>
        )}
      </div>

      {text.error !== null && (
        <div className="flex items-center gap-2 border-b border-line bg-danger-soft px-4 py-2 text-[12px] text-danger">
          <AlertTriangle size={12} className="shrink-0" />
          <span className="min-w-0 flex-1">{text.error}</span>
          <Button variant="ghost" size="xs" onClick={() => setRetry((n) => n + 1)}>
            <RotateCcw size={12} />
            Retry
          </Button>
        </div>
      )}

      {text.loading ? (
        <div className="flex flex-1 items-center justify-center text-fg-faint">
          <Loader2 size={16} className="animate-spin-slow" />
        </div>
      ) : editing ? (
        <div className="flex min-h-0 flex-1">
          {(!isMarkdown || editorView !== "preview") && (
            <textarea
              value={draft}
              onChange={(event) => setDraft(draftKey, event.target.value)}
              onKeyDown={(event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === "s") {
                  event.preventDefault();
                  void save();
                }
              }}
              spellCheck={false}
              aria-label="File editor"
              className="min-h-0 min-w-0 flex-1 resize-none bg-bg px-4 py-3 font-mono text-[12.5px] leading-5 text-fg outline-none"
            />
          )}
          {isMarkdown && editorView !== "edit" && (
            <div className="min-h-0 min-w-0 flex-1 overflow-y-auto border-l border-line px-4 py-3">
              <Markdown origin={markdownOrigin}>{draft}</Markdown>
            </div>
          )}
        </div>
      ) : showLines ? (
        <div className="min-h-0 flex-1 overflow-auto px-2 py-2">
          <LineView
            lines={lines}
            highlight={
              targetLines ?? { startLine: 0, endLine: 0 }
            }
          />
          {text.complete && text.text === "" && (
            <div className="px-3 py-2 text-[12px] text-fg-faint">Empty file.</div>
          )}
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <Markdown origin={markdownOrigin}>{text.text}</Markdown>
        </div>
      )}

      {!editing && !text.loading && text.next !== null && (
        <div className="border-t border-line px-4 py-2">
          <Button
            variant="outline"
            size="xs"
            loading={text.loadingMore}
            onClick={text.loadMore}
          >
            Show more
          </Button>
        </div>
      )}
    </div>
  );
}

function LineView({
  lines,
  highlight,
}: {
  lines: string[];
  highlight: { startLine: number; endLine: number };
}): ReactElement {
  return (
    <div className="font-mono text-[12px] leading-5">
      {lines.map((line, index) => {
        const number = index + 1;
        const hit =
          number >= highlight.startLine && number <= highlight.endLine;
        return (
          <div
            key={number}
            id={`ws-line-${number}`}
            className={`flex rounded-sm ${hit ? "bg-accent-soft/70" : ""}`}
          >
            <span className="w-10 shrink-0 select-none pr-3 text-right text-fg-faint">
              {number}
            </span>
            <span className="min-w-0 whitespace-pre-wrap break-words text-fg">
              {line === "" ? " " : line}
            </span>
          </div>
        );
      })}
    </div>
  );
}
