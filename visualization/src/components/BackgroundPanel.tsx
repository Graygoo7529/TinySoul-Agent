import { BookOpen, X } from "lucide-react";

import { useAppStore } from "../store/appStore";
import { useBackgroundContext } from "../hooks/useBackgroundContext";

interface BackgroundPanelProps {
  open: boolean;
  onClose: () => void;
}

export function BackgroundPanel({ open, onClose }: BackgroundPanelProps) {
  const { events } = useAppStore();
  const links = useBackgroundContext(events);

  if (!open) return null;

  return (
    <div
      className="background-panel"
      style={{
        width: 340,
        flexShrink: 0,
        borderLeft: "1px solid var(--border-subtle)",
        background: "var(--bg-elevated)",
        display: "flex",
        flexDirection: "column",
        animation: "fadeIn 0.2s ease-out",
      }}
    >
      <div className="panel-header">
        <span className="flex items-center gap-2">
          <BookOpen size={14} />
          Background Context
          <span className="badge badge-subtle">{links.length}</span>
        </span>
        <button className="btn btn-sm btn-ghost btn-icon" onClick={onClose}>
          <X size={14} />
        </button>
      </div>
      <div className="panel-body">
        {links.length === 0 && (
          <div className="text-muted text-xs">No top-level background links loaded.</div>
        )}
        <div className="flex flex-col gap-2">
          {links.map((entry) => (
            <BackgroundEntry key={entry.link} entry={entry} />
          ))}
        </div>
      </div>
    </div>
  );
}

function BackgroundEntry({ entry }: { entry: { link: string; source: string; owner: string; evictable: boolean; content: string } }) {
  return (
    <div
      className="p-3"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
      }}
    >
      <div className="font-mono text-xs mb-1" style={{ color: "var(--accent)" }}>
        {entry.link}
      </div>
      <div className="flex gap-1 mb-2">
        <span className="badge badge-subtle">{entry.source}</span>
        <span className="badge badge-subtle">{entry.owner}</span>
        {entry.evictable && <span className="badge badge-subtle">evictable</span>}
      </div>
      <div
        className="text-xs text-muted"
        style={{
          maxHeight: 120,
          overflowY: "auto",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          fontFamily: "var(--font-mono)",
        }}
      >
        {entry.content}
      </div>
    </div>
  );
}
