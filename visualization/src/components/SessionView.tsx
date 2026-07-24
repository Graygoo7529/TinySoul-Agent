import { useEffect, useState } from "react";
import {
  Activity,
  ArrowLeft,
  ChevronRight,
  FileJson,
  FolderTree,
  History,
  Info,
  RefreshCw,
} from "lucide-react";

import { TinySoulApiError } from "../api/tinysoul";
import { useAppStore } from "../store/appStore";
import type {
  SessionActions,
  SessionCursor,
  SessionHistory,
  SessionHistoryItem,
  SessionTrace,
} from "../types";
import { JsonTree } from "./JsonTree";

type DetailTab = "overview" | "actions" | "trace";

interface HistoryLevel {
  ref: string;
  label: string;
}

const PAGE_CHARS = 8000;
const PAGE_ENTRIES = 20;

export function SessionView() {
  const { client } = useAppStore();
  const [history, setHistory] = useState<SessionHistory | null>(null);
  const [levels, setLevels] = useState<HistoryLevel[]>([]);
  const [selected, setSelected] = useState<SessionHistoryItem | null>(null);
  const [actions, setActions] = useState<SessionActions | null>(null);
  const [trace, setTrace] = useState<SessionTrace | null>(null);
  const [tab, setTab] = useState<DetailTab>("overview");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const currentRef = levels.length > 0 ? levels[levels.length - 1].ref : undefined;

  const loadHistory = async (ref?: string, cursor?: SessionCursor) => {
    if (!client) return;
    setLoading(true);
    setError("");
    try {
      let page: SessionHistory;
      try {
        page = await client.sessionHistory(
          ref,
          cursor,
          PAGE_CHARS,
          PAGE_ENTRIES,
        );
      } catch (err) {
        const rootContinuation =
          ref === undefined &&
          cursor !== undefined &&
          (cursor.entry_index > 0 || cursor.char_offset > 0);
        if (
          rootContinuation &&
          err instanceof TinySoulApiError &&
          err.code === "session.revision_changed"
        ) {
          setLevels([]);
          setSelected(null);
          setActions(null);
          setTrace(null);
          page = await client.sessionHistory(
            undefined,
            undefined,
            PAGE_CHARS,
            PAGE_ENTRIES,
          );
        } else {
          throw err;
        }
      }
      setHistory(page);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (client) void loadHistory();
  }, [client]);

  const refresh = () => {
    setLevels([]);
    setSelected(null);
    setActions(null);
    setTrace(null);
    void loadHistory();
  };

  const openNode = async (item: SessionHistoryItem) => {
    if (!client) return;
    if (item.kind === "summary") {
      setLevels((current) => [
        ...current,
        { ref: item.ref, label: shortRef(item.ref) },
      ]);
      setSelected(null);
      setActions(null);
      setTrace(null);
      await loadHistory(item.ref);
      return;
    }
    setSelected(item);
    setTab("overview");
    setLoading(true);
    setError("");
    try {
      const [actionPage, tracePage] = await Promise.all([
        client.sessionActions(item.ref, 0, PAGE_ENTRIES),
        client.sessionTrace(item.ref, undefined, PAGE_CHARS, PAGE_ENTRIES),
      ]);
      setActions(actionPage);
      setTrace(tracePage);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const goBack = async () => {
    const next = levels.slice(0, -1);
    setLevels(next);
    setSelected(null);
    setActions(null);
    setTrace(null);
    await loadHistory(next.length > 0 ? next[next.length - 1].ref : undefined);
  };

  const loadTraceIndex = async (index: number) => {
    if (!client || !selected) return;
    setLoading(true);
    setError("");
    try {
      setTrace(
        await client.sessionTrace(
          selected.ref,
          { entry_index: index, char_offset: 0 },
          PAGE_CHARS,
          1,
        ),
      );
      setTab("trace");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const nextActions = async () => {
    if (!client || !selected || actions?.next_cursor == null) return;
    setLoading(true);
    setError("");
    try {
      setActions(await client.sessionActions(
        selected.ref,
        actions.next_cursor,
        PAGE_ENTRIES,
      ));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const nextTrace = async () => {
    if (!client || !selected || !trace?.next_cursor) return;
    setLoading(true);
    setError("");
    try {
      setTrace(await client.sessionTrace(
        selected.ref,
        trace.next_cursor,
        PAGE_CHARS,
        PAGE_ENTRIES,
      ));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="session-view">
      <div className="workspace-sidebar">
        <div className="panel h-full">
          <div className="panel-header">
            <span className="flex items-center gap-2">
              <History size={14} />
              Session History
            </span>
            <button
              className="btn btn-sm btn-ghost"
              onClick={refresh}
              disabled={loading}
              title="Refresh history"
            >
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
            </button>
          </div>

          <div className="session-path">
            {levels.length > 0 && (
              <button
                className="btn btn-sm btn-ghost"
                onClick={() => void goBack()}
                title="Back to parent"
              >
                <ArrowLeft size={13} />
              </button>
            )}
            <FolderTree size={13} />
            <span>{levels.length > 0 ? levels[levels.length - 1].label : "Active head"}</span>
          </div>

          <div className="panel-body resource-list">
            {error && <div className="text-danger text-xs p-2">{error}</div>}
            {history?.items.length === 0 && (
              <div className="text-muted text-xs p-2">No history at this level.</div>
            )}
            {history?.items.map((item) => (
              <button
                key={item.ref}
                className={`resource-item session-node ${selected?.ref === item.ref ? "active" : ""}`}
                onClick={() => void openNode(item)}
              >
                <div className="resource-info">
                  <div className="resource-link">{shortRef(item.ref)}</div>
                  <div className="resource-summary">
                    {item.kind}
                    {item.kind === "summary" ? ` · ${item.child_count} children` : turnStats(item)}
                  </div>
                </div>
                <ChevronRight size={14} className="text-tertiary" />
              </button>
            ))}
          </div>

          {history?.next_cursor && (
            <div className="session-pagination">
              <button
                className="btn btn-sm btn-ghost"
                onClick={() => void loadHistory(currentRef, history.next_cursor ?? undefined)}
              >
                Next page <ChevronRight size={12} />
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="workspace-main">
        <div className="panel h-full">
          <div className="panel-header session-detail-header">
            <span className="flex items-center gap-2">
              <History size={14} />
              {selected ? shortRef(selected.ref) : "Turn detail"}
            </span>
            {selected && (
              <div className="tabs">
                <DetailTabButton active={tab === "overview"} onClick={() => setTab("overview")}>
                  <Info size={12} /> Overview
                </DetailTabButton>
                <DetailTabButton active={tab === "actions"} onClick={() => setTab("actions")}>
                  <Activity size={12} /> Actions
                </DetailTabButton>
                <DetailTabButton active={tab === "trace"} onClick={() => setTab("trace")}>
                  <FileJson size={12} /> Trace
                </DetailTabButton>
              </div>
            )}
          </div>

          <div className="panel-body session-detail-body">
            {!selected && (
              <div className="empty-state">
                <History size={48} className="empty-state-icon" />
                <div>Select a Turn from the history tree.</div>
              </div>
            )}
            {selected && tab === "overview" && <JsonTree value={selected.preview} />}
            {selected && tab === "actions" && actions && (
              <ActionHistory
                actions={actions}
                onTraceIndex={loadTraceIndex}
                onNext={nextActions}
              />
            )}
            {selected && tab === "trace" && trace && (
              <TracePage trace={trace} onNext={nextTrace} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function DetailTabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button className={`tab ${active ? "active" : ""}`} onClick={onClick}>
      {children}
    </button>
  );
}

function ActionHistory({
  actions,
  onTraceIndex,
  onNext,
}: {
  actions: SessionActions;
  onTraceIndex: (index: number) => Promise<void>;
  onNext: () => Promise<void>;
}) {
  const outcome = actions.summary.outcome;
  return (
    <div className="session-action-view">
      <div className="session-metrics">
        <Metric label="Calls" value={outcome.call_count} />
        <Metric label="Success" value={outcome.success_count} tone="success" />
        <Metric label="Failed" value={outcome.failed_count} tone="danger" />
        <Metric label="Timeout" value={outcome.timeout_count} tone="warning" />
      </div>
      <div className="session-action-list">
        {actions.details.map((detail) => {
          return (
            <div
              key={`${detail.occurrence}:${detail.call_id}`}
              className="session-action-row"
            >
              <span className="resource-link">{detail.action}</span>
              <span className={`badge ${statusBadge(detail.status)}`}>
                {detail.status ?? detail.pairing_issue ?? "pending"}
              </span>
              <span className="session-trace-links">
                <TraceIndexButton
                  label="Call"
                  index={detail.call_trace_index}
                  onTraceIndex={onTraceIndex}
                />
                <TraceIndexButton
                  label="Result"
                  index={detail.result_trace_index}
                  onTraceIndex={onTraceIndex}
                />
              </span>
            </div>
          );
        })}
      </div>
      {actions.next_cursor != null && (
        <button className="btn btn-sm btn-ghost" onClick={() => void onNext()}>
          Next page <ChevronRight size={12} />
        </button>
      )}
    </div>
  );
}

function TraceIndexButton({
  label,
  index,
  onTraceIndex,
}: {
  label: string;
  index: number | null;
  onTraceIndex: (index: number) => Promise<void>;
}) {
  return (
    <button
      className="btn btn-sm btn-ghost"
      onClick={() => index != null && void onTraceIndex(index)}
      disabled={index == null}
      title={`${label} trace entry`}
    >
      <FileJson size={11} /> {label} {index ?? "-"}
    </button>
  );
}

function TracePage({ trace, onNext }: { trace: SessionTrace; onNext: () => Promise<void> }) {
  return (
    <div className="session-trace-view">
      <JsonTree value={trace} />
      {trace.next_cursor && (
        <button className="btn btn-sm btn-ghost" onClick={() => void onNext()}>
          Next page <ChevronRight size={12} />
        </button>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  tone = "subtle",
}: {
  label: string;
  value: number;
  tone?: "subtle" | "success" | "danger" | "warning";
}) {
  return (
    <div className="session-metric">
      <span className={`badge badge-${tone}`}>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function shortRef(ref: string): string {
  return ref.split("/").slice(-1)[0] || ref;
}

function turnStats(item: SessionHistoryItem): string {
  const raw = item.preview.action_outcome_summary;
  if (!raw || typeof raw !== "object") return "";
  const outcome = raw as Record<string, unknown>;
  const success = typeof outcome.success_count === "number" ? outcome.success_count : 0;
  const failed = typeof outcome.failed_count === "number" ? outcome.failed_count : 0;
  const timeout = typeof outcome.timeout_count === "number" ? outcome.timeout_count : 0;
  return ` · ${success} ok · ${failed + timeout} failed`;
}

function statusBadge(status?: string): string {
  if (status === "success") return "badge-success";
  if (status === "failed") return "badge-danger";
  if (status === "timeout") return "badge-warning";
  return "badge-subtle";
}
