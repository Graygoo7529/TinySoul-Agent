import { useState } from "react";
import {
  Activity,
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  FileJson,
  FolderTree,
  History,
  Info,
  RefreshCw,
} from "lucide-react";

import { useSessionExplorer } from "../hooks/useSessionExplorer";
import { useAppStore } from "../store/appStore";
import type { SessionActions, SessionHistoryItem, SessionTrace } from "../types";
import { JsonTree } from "./JsonTree";

type DetailTab = "overview" | "actions" | "trace";

export function SessionView() {
  const { client } = useAppStore();
  const explorer = useSessionExplorer(client);
  const { state, historyLevel, history, actions, trace } = explorer;
  const [tab, setTab] = useState<DetailTab>("overview");

  const openNode = (item: SessionHistoryItem) => {
    if (item.kind === "summary") {
      explorer.openSummary(item);
      return;
    }
    explorer.selectTurn(item);
    setTab("overview");
  };

  const loadTraceIndex = (index: number) => {
    setTab("trace");
    explorer.loadTraceIndex(index);
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
              onClick={explorer.refresh}
              disabled={historyLevel.trail.loading}
              title="Refresh history"
            >
              <RefreshCw
                size={12}
                className={historyLevel.trail.loading ? "animate-spin" : ""}
              />
            </button>
          </div>

          <div className="session-path">
            {state.historyPath.length > 1 && (
              <button
                className="btn btn-sm btn-ghost"
                onClick={explorer.historyBack}
                title="Back to parent"
              >
                <ArrowLeft size={13} />
              </button>
            )}
            <FolderTree size={13} />
            <span className="session-breadcrumbs">
              {state.historyPath.map((level, index) => (
                <span key={level.ref ?? "root"} className="session-breadcrumb">
                  {index > 0 && <ChevronRight size={11} />}
                  <span>{level.label}</span>
                </span>
              ))}
            </span>
          </div>

          <div className="panel-body resource-list">
            {historyLevel.trail.error && (
              <div className="text-danger text-xs p-2">
                {historyLevel.trail.error}
              </div>
            )}
            {historyLevel.trail.loading && !history && (
              <div className="text-muted text-xs p-2">Loading...</div>
            )}
            {history?.items.length === 0 && (
              <div className="text-muted text-xs p-2">No history at this level.</div>
            )}
            {history?.items.map((item) => (
              <button
                key={item.ref}
                className={`resource-item session-node ${state.selected?.ref === item.ref ? "active" : ""}`}
                onClick={() => openNode(item)}
                disabled={historyLevel.trail.loading}
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

          {history && (
            <div className="session-pagination">
              <PageControls
                page={historyLevel.trail.current + 1}
                loading={historyLevel.trail.loading}
                canPrevious={explorer.historyCanPrevious}
                canNext={explorer.historyCanNext}
                onPrevious={explorer.historyPrevious}
                onNext={explorer.historyNext}
              />
            </div>
          )}
        </div>
      </div>

      <div className="workspace-main">
        <div className="panel h-full">
          <div className="panel-header session-detail-header">
            <span className="flex items-center gap-2">
              <History size={14} />
              {state.selected ? shortRef(state.selected.ref) : "Turn detail"}
            </span>
            {state.selected && (
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
            {!state.selected && (
              <div className="empty-state">
                <History size={48} className="empty-state-icon" />
                <div>Select a Turn from the history tree.</div>
              </div>
            )}
            {state.selected && tab === "overview" && (
              <JsonTree value={state.selected.preview} />
            )}
            {state.selected && tab === "actions" && (
              <AsyncPageState
                loading={state.detail?.actions.loading ?? false}
                error={state.detail?.actions.error ?? ""}
                hasPage={actions !== null}
              >
                {actions && (
                  <ActionHistory
                    actions={actions}
                    onTraceIndex={loadTraceIndex}
                    page={(state.detail?.actions.current ?? 0) + 1}
                    loading={state.detail?.actions.loading ?? false}
                    canPrevious={explorer.actionsCanPrevious}
                    canNext={explorer.actionsCanNext}
                    onPrevious={explorer.actionsPrevious}
                    onNext={explorer.actionsNext}
                  />
                )}
              </AsyncPageState>
            )}
            {state.selected && tab === "trace" && (
              <AsyncPageState
                loading={state.detail?.trace.loading ?? false}
                error={state.detail?.trace.error ?? ""}
                hasPage={trace !== null}
              >
                {trace && (
                  <TracePage
                    trace={trace}
                    page={(state.detail?.trace.current ?? 0) + 1}
                    loading={state.detail?.trace.loading ?? false}
                    canPrevious={explorer.traceCanPrevious}
                    canNext={explorer.traceCanNext}
                    onPrevious={explorer.tracePrevious}
                    onNext={explorer.traceNext}
                  />
                )}
              </AsyncPageState>
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
  page,
  loading,
  canPrevious,
  canNext,
  onPrevious,
  onNext,
}: {
  actions: SessionActions;
  onTraceIndex: (index: number) => void;
  page: number;
  loading: boolean;
  canPrevious: boolean;
  canNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
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
      <PageControls
        page={page}
        loading={loading}
        canPrevious={canPrevious}
        canNext={canNext}
        onPrevious={onPrevious}
        onNext={onNext}
      />
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
  onTraceIndex: (index: number) => void;
}) {
  return (
    <button
      className="btn btn-sm btn-ghost"
      onClick={() => index != null && onTraceIndex(index)}
      disabled={index == null}
      title={`${label} trace entry`}
    >
      <FileJson size={11} /> {label} {index ?? "-"}
    </button>
  );
}

function TracePage({
  trace,
  page,
  loading,
  canPrevious,
  canNext,
  onPrevious,
  onNext,
}: {
  trace: SessionTrace;
  page: number;
  loading: boolean;
  canPrevious: boolean;
  canNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
}) {
  return (
    <div className="session-trace-view">
      <JsonTree value={trace} />
      <PageControls
        page={page}
        loading={loading}
        canPrevious={canPrevious}
        canNext={canNext}
        onPrevious={onPrevious}
        onNext={onNext}
      />
    </div>
  );
}

function AsyncPageState({
  loading,
  error,
  hasPage,
  children,
}: {
  loading: boolean;
  error: string;
  hasPage: boolean;
  children: React.ReactNode;
}) {
  return (
    <>
      {error && <div className="text-danger text-xs p-2">{error}</div>}
      {loading && !hasPage && (
        <div className="text-muted text-xs p-2">Loading...</div>
      )}
      {children}
    </>
  );
}

function PageControls({
  page,
  loading,
  canPrevious,
  canNext,
  onPrevious,
  onNext,
}: {
  page: number;
  loading: boolean;
  canPrevious: boolean;
  canNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
}) {
  return (
    <div className="session-page-controls">
      <button
        className="btn btn-sm btn-ghost"
        onClick={onPrevious}
        disabled={loading || !canPrevious}
        title="Previous page"
      >
        <ChevronLeft size={13} />
      </button>
      <span>Page {page}</span>
      <button
        className="btn btn-sm btn-ghost"
        onClick={onNext}
        disabled={loading || !canNext}
        title="Next page"
      >
        <ChevronRight size={13} />
      </button>
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
