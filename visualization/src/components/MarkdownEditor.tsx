/**
 * Markdown split editor with live preview.
 *
 * The source of truth remains the plain-text workspace resource. The preview is
 * rendered locally and never sent to the backend; saving submits the full source.
 */

import { useEffect, useMemo, useRef } from "react";
import { marked } from "marked";
import { Save, RotateCcw, Eye, FileCode, AlertTriangle } from "lucide-react";

import { useAppStore, type OpenResource } from "../store/appStore";
import type { WorkspaceResourceRecord } from "../types";
import { formatSize, shorten } from "../utils/format";

interface MarkdownEditorProps {
  resource: WorkspaceResourceRecord;
  open: OpenResource;
  onSave: () => void;
  conflict: boolean;
  onResolveConflict: (action: "overwrite" | "discard") => void;
}

export function MarkdownEditor({
  resource,
  open,
  onSave,
  conflict,
  onResolveConflict,
}: MarkdownEditorProps) {
  const updateDraft = useAppStore((state) => state.updateResourceDraft);
  const previewRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const syncSourceRef = useRef(true);

  const html = useMemo(() => {
    try {
      return marked.parse(open.draft, { async: false }) as string;
    } catch {
      return open.draft;
    }
  }, [open.draft]);

  const wordCount = useMemo(
    () => open.draft.trim().split(/\s+/).filter(Boolean).length,
    [open.draft],
  );

  // Keep textarea and preview scrolling loosely in sync when syncSource is on.
  const onScroll = (source: "textarea" | "preview") => {
    if (!syncSourceRef.current) return;
    const ta = textareaRef.current;
    const pv = previewRef.current;
    if (!ta || !pv) return;
    const taRatio = ta.scrollTop / (ta.scrollHeight - ta.clientHeight || 1);
    if (source === "textarea") {
      pv.scrollTop = taRatio * (pv.scrollHeight - pv.clientHeight || 1);
    }
  };

  useEffect(() => {
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = "auto";
      ta.style.height = `${ta.scrollHeight}px`;
    }
  }, [open.draft]);

  return (
    <div className="markdown-editor">
      <div className="panel-header">
        <span className="flex items-center gap-2">
          <FileCode size={14} />
          {open.link}
        </span>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted">
            {wordCount} words · {formatSize(open.read.size)} · rev{" "}
            {resource.retention}
          </span>
          <span className="text-xs text-tertiary" title={open.read.digest}>
            {shorten(open.read.digest)}
          </span>
          {open.dirty && <span className="badge badge-accent">modified</span>}
          <button
            className="btn btn-sm btn-ghost btn-icon"
            title="Discard changes"
            onClick={() => onResolveConflict("discard")}
            disabled={!open.dirty && !conflict}
          >
            <RotateCcw size={12} />
          </button>
          <button
            className="btn btn-sm btn-primary"
            onClick={onSave}
            disabled={!open.dirty || conflict}
          >
            <Save size={12} />
            Save
          </button>
        </div>
      </div>

      <div className="markdown-editor-body">
        {conflict && (
          <div className="conflict-banner">
            <AlertTriangle size={14} />
            <span className="flex-1">
              This resource changed on disk. Your draft is preserved. Choose to
              overwrite with your version or reload the server version.
            </span>
            <button
              className="btn btn-sm btn-primary"
              onClick={() => onResolveConflict("overwrite")}
            >
              Overwrite
            </button>
            <button
              className="btn btn-sm"
              onClick={() => onResolveConflict("discard")}
            >
              Reload
            </button>
          </div>
        )}

        <div className="markdown-panes">
          <div className="markdown-source">
            <div className="markdown-pane-header">
              <FileCode size={12} />
              Source
            </div>
            <textarea
              ref={textareaRef}
              className="textarea"
              value={open.draft}
              onChange={(e) => updateDraft(e.target.value)}
              onScroll={() => onScroll("textarea")}
              spellCheck={false}
            />
          </div>
          <div className="markdown-preview">
            <div className="markdown-pane-header">
              <Eye size={12} />
              Preview
            </div>
            <div
              ref={previewRef}
              className="markdown-preview-content"
              dangerouslySetInnerHTML={{ __html: html }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
