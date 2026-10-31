/**
 * Non-text workspace resources (plan §10/P06).
 *
 * Images embed through the authenticated blob client (Object URL). Every
 * other binary kind — documents, audio, video, unknown — shows its manifest
 * metadata plus a real download; the page never fakes playback of media it
 * cannot embed.
 *
 * Clicking the embedded image opens a fullscreen viewer (the same overlay
 * language as Modal: dark backdrop, Esc, click-away): wheel zooms 0.25x–4x
 * anchored at the cursor, pointer drag pans, double-click or the reset button
 * returns to fit, and download reuses the same blob route. The Object URL
 * lifecycle never changes.
 */

import { useCallback, useEffect, useRef, useState, type ReactElement } from "react";
import { AlertTriangle, Download, File as FileIcon, Loader2, RotateCcw, X } from "lucide-react";

import type { WorkspaceResourceRecord } from "../../api/v2/types";
import { Button, IconButton } from "../../components/ui/Button";
import { useWorkspaceBlobUrl } from "../resources/blobUrl";
import { formatSize } from "../../utils/format";
import { downloadWorkspaceBlob } from "./download";
import { mediaTypeLabel } from "./tree";

export function BlobView({
  ref,
  day,
  record,
}: {
  /** Fragment-free `workspace:` ref. */
  ref: string;
  /** Archive binding; null reads the active day. */
  day: string | null;
  record: WorkspaceResourceRecord;
}): ReactElement {
  if (record.media_type.startsWith("image/")) {
    return <ImageBlob ref={ref} day={day} record={record} />;
  }
  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-md space-y-4 rounded-xl border border-line bg-bg-elev px-5 py-5">
        <div className="flex items-center gap-3">
          <FileIcon size={22} className="shrink-0 text-fg-faint" />
          <div className="min-w-0">
            <div className="truncate text-sm font-medium" title={record.relative_path}>
              {record.relative_path}
            </div>
            <div className="text-[11px] text-fg-faint">{record.kind}</div>
          </div>
        </div>
        <dl className="space-y-1.5 text-[12px]">
          <MetadataRow label="Media type" value={record.media_type} />
          <MetadataRow label="Size" value={formatSize(record.size)} />
        </dl>
        <div className="text-[11px] leading-4 text-fg-faint">
          This file type is not embedded in the page. Download it to open with
          a local application.
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void downloadWorkspaceBlob(ref, day, fileName(record))}
        >
          <Download size={13} />
          Download
        </Button>
      </div>
    </div>
  );
}

function ImageBlob({
  ref,
  day,
  record,
}: {
  ref: string;
  day: string | null;
  record: WorkspaceResourceRecord;
}): ReactElement {
  const blob = useWorkspaceBlobUrl(ref, day);
  const [viewerOpen, setViewerOpen] = useState(false);
  if (blob.error !== null) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="flex max-w-md items-center gap-2 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-[12px] text-warning">
          <AlertTriangle size={13} className="shrink-0" />
          The image could not be read: {blob.error}
        </div>
      </div>
    );
  }
  if (blob.url === null) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-fg-faint">
        <Loader2 size={16} className="animate-spin-slow" />
      </div>
    );
  }
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-line px-4 py-1.5 text-[11px] text-fg-faint">
        <span title={record.media_type}>{mediaTypeLabel(record.media_type)}</span>
        <span>·</span>
        <span>{formatSize(record.size)}</span>
        <span className="flex-1" />
        <Button
          variant="ghost"
          size="xs"
          onClick={() => void downloadWorkspaceBlob(ref, day, fileName(record))}
        >
          <Download size={12} />
          Download
        </Button>
      </div>
      <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-4">
        <img
          src={blob.url}
          alt={record.relative_path}
          title="点击放大查看"
          onClick={() => setViewerOpen(true)}
          className="max-h-full max-w-full cursor-zoom-in object-contain hover:outline-2 hover:outline-accent/60 hover:outline-solid hover:outline-offset-2"
        />
      </div>
      {viewerOpen && (
        <ImageLightbox
          url={blob.url}
          name={fileName(record)}
          detail={`${mediaTypeLabel(record.media_type) ?? record.media_type} · ${formatSize(record.size)}`}
          onDownload={() => void downloadWorkspaceBlob(ref, day, fileName(record))}
          onClose={() => setViewerOpen(false)}
        />
      )}
    </div>
  );
}

const LIGHTBOX_MIN_ZOOM = 0.25;
const LIGHTBOX_MAX_ZOOM = 4;
const LIGHTBOX_ZOOM_STEP = 1.25;
/** Below this pointer travel a press is a click, not a drag. */
const LIGHTBOX_CLICK_SLOP = 4;

/**
 * Fullscreen image viewer sharing Modal's overlay language (dark backdrop,
 * Esc, click-away). Wheel zooms 0.25x–4x anchored at the cursor, pointer drag
 * pans, double-click or reset returns to fit.
 */
export function ImageLightbox({
  url,
  name,
  detail,
  onDownload,
  onClose,
}: {
  /** Object URL from the same blob read as the inline preview. */
  url: string;
  name: string;
  /** e.g. "PNG 图片 · 84.2 KB". */
  detail: string;
  onDownload: () => void;
  onClose: () => void;
}): ReactElement {
  // zoom and pan live in one state so batched wheel events compose.
  const [view, setView] = useState({ zoom: 1, x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const viewRef = useRef<HTMLDivElement | null>(null);
  const dragStart = useRef<{ px: number; py: number; ox: number; oy: number; onImage: boolean } | null>(null);

  const reset = useCallback(() => {
    setView({ zoom: 1, x: 0, y: 0 });
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const applyWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    const el = viewRef.current;
    if (el === null) return;
    const rect = el.getBoundingClientRect();
    const cx = event.clientX - rect.left - rect.width / 2;
    const cy = event.clientY - rect.top - rect.height / 2;
    setView((prev) => {
      const next = Math.min(
        LIGHTBOX_MAX_ZOOM,
        Math.max(LIGHTBOX_MIN_ZOOM, prev.zoom * (event.deltaY < 0 ? LIGHTBOX_ZOOM_STEP : 1 / LIGHTBOX_ZOOM_STEP)),
      );
      if (next === prev.zoom) return prev;
      // Keep the image point under the cursor stationary across the zoom.
      return {
        zoom: next,
        x: cx - ((cx - prev.x) / prev.zoom) * next,
        y: cy - ((cy - prev.y) / prev.zoom) * next,
      };
    });
  };

  return (
    <div
      className="animate-fade-in fixed inset-0 z-(--z-drawer) flex flex-col bg-black/70 backdrop-blur-[2px]"
      role="dialog"
      aria-label={`查看图片 ${name}`}
    >
      <div className="flex items-center gap-2 border-b border-line/60 px-4 py-2 text-[11px] text-white/60">
        <span className="truncate text-[12.5px] font-medium text-white/90" title={name}>
          {name}
        </span>
        <span className="shrink-0">{detail}</span>
        <span className="flex-1" />
        <span className="w-11 shrink-0 text-center font-mono text-[10px] tabular-nums">
          {Math.round(view.zoom * 100)}%
        </span>
        <IconButton label="复位到 100%" className="h-7 w-7 text-white/70 hover:bg-white/10 hover:text-white" onClick={reset}>
          <RotateCcw size={13} />
        </IconButton>
        <IconButton label="下载" className="h-7 w-7 text-white/70 hover:bg-white/10 hover:text-white" onClick={onDownload}>
          <Download size={13} />
        </IconButton>
        <IconButton label="关闭" className="h-7 w-7 text-white/70 hover:bg-white/10 hover:text-white" onClick={onClose}>
          <X size={14} />
        </IconButton>
      </div>

      <div
        ref={viewRef}
        className={`relative min-h-0 flex-1 touch-none overflow-hidden ${dragging ? "cursor-grabbing" : "cursor-grab"}`}
        onWheel={applyWheel}
        onDoubleClick={reset}
        onPointerDown={(event) => {
          // jsdom lacks pointer capture; in browsers it keeps drags alive
          // beyond the viewport edge.
          event.currentTarget.setPointerCapture?.(event.pointerId);
          dragStart.current = {
            px: event.clientX,
            py: event.clientY,
            ox: view.x,
            oy: view.y,
            onImage: event.target !== event.currentTarget,
          };
          setDragging(true);
        }}
        onPointerMove={(event) => {
          const start = dragStart.current;
          if (start === null) return;
          setView((prev) => ({
            ...prev,
            x: start.ox + event.clientX - start.px,
            y: start.oy + event.clientY - start.py,
          }));
        }}
        onPointerUp={(event) => {
          const start = dragStart.current;
          if (start === null) return;
          dragStart.current = null;
          setDragging(false);
          event.currentTarget.releasePointerCapture?.(event.pointerId);
          const moved = Math.hypot(event.clientX - start.px, event.clientY - start.py);
          if (!start.onImage && moved < LIGHTBOX_CLICK_SLOP) onClose();
        }}
        onPointerCancel={() => {
          dragStart.current = null;
          setDragging(false);
        }}
      >
        <img
          src={url}
          alt={name}
          draggable={false}
          className="absolute top-1/2 left-1/2 max-h-[85%] max-w-[90%] object-contain select-none"
          style={{
            transform: `translate(calc(-50% + ${view.x}px), calc(-50% + ${view.y}px)) scale(${view.zoom})`,
          }}
        />
      </div>

      <div className="flex items-center justify-center gap-4 border-t border-line/60 py-1.5 text-[10px] text-white/45">
        <span>滚轮缩放</span>
        <span>拖拽平移</span>
        <span>双击复位</span>
        <span>Esc 关闭</span>
      </div>
    </div>
  );
}

function MetadataRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <dt className="w-20 shrink-0 text-fg-faint">{label}</dt>
      <dd className="min-w-0 flex-1 break-words text-fg-muted">{value}</dd>
    </div>
  );
}

function fileName(record: WorkspaceResourceRecord): string {
  const path = record.relative_path;
  const slash = path.lastIndexOf("/");
  return slash < 0 ? path : path.slice(slash + 1);
}
