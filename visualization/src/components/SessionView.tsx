import { useEffect, useState } from "react";
import { ChevronRight, History, RefreshCw } from "lucide-react";

import { useAppStore } from "../store/appStore";
import type { SessionHistoryItem, SessionRecall } from "../types";

export function SessionView() {
  const { client } = useAppStore();
  const [items, setItems] = useState<SessionHistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [recall, setRecall] = useState<SessionRecall | null>(null);
  const [selectedRef, setSelectedRef] = useState<string | null>(null);
  const [error, setError] = useState("");

  const load = async () => {
    if (!client) return;
    setLoading(true);
    setError("");
    try {
      const history = await client.sessionHistory();
      setItems(history.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (client) void load();
  }, [client]);

  const onRecall = async (ref: string) => {
    if (!client) return;
    setError("");
    try {
      const data = await client.sessionRecall(ref, undefined, 4000, 20);
      setSelectedRef(ref);
      setRecall(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const onNextPage = async () => {
    if (!client || !selectedRef || !recall?.next_cursor) return;
    setError("");
    try {
      setRecall(
        await client.sessionRecall(selectedRef, recall.next_cursor, 4000, 20),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="session-view">
      <div className="workspace-sidebar">
        <div className="panel h-full">
          <div className="panel-header">
            <span className="flex items-center gap-2">
              <History size={14} />
              Today&apos;s History
            </span>
            <button
              className="btn btn-sm btn-ghost"
              onClick={() => void load()}
              disabled={loading}
              title="Refresh history"
            >
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
            </button>
          </div>
          <div className="panel-body resource-list">
            {items.length === 0 && (
              <div className="text-muted text-xs">No history recorded yet.</div>
            )}
            {error && <div className="text-danger text-xs p-2">{error}</div>}
            {items.map((item) => (
              <div
                key={item.ref}
                className="resource-item"
                onClick={() => void onRecall(item.ref)}
              >
                <div className="resource-info">
                  <div className="resource-link">{item.ref.split("/").slice(-1)[0]}</div>
                  <div className="resource-summary">
                    {item.kind} · {item.char_count.toLocaleString()} chars
                    {item.action_outcome_summary
                      ? ` · ${item.action_outcome_summary.success_count} ok · ${item.action_outcome_summary.failed_count + item.action_outcome_summary.timeout_count} failed`
                      : ""}
                  </div>
                </div>
                <ChevronRight size={14} className="text-tertiary" />
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="workspace-main">
        <div className="panel h-full">
          <div className="panel-header">
            <span className="flex items-center gap-2">
              <History size={14} />
              Recall
            </span>
            {recall?.next_cursor && (
              <button className="btn btn-sm btn-ghost" onClick={() => void onNextPage()}>
                Next page
                <ChevronRight size={12} />
              </button>
            )}
          </div>
          <div className="panel-body" style={{ padding: 0 }}>
            {recall ? (
              <div className="h-full flex flex-col">
                {!recall.background_state.included &&
                  recall.background_state.reason === "page_budget" && (
                    <div className="text-muted text-xs p-2">
                      Background omitted from this page (
                      {recall.background_state.char_count.toLocaleString()} chars).
                    </div>
                  )}
                <textarea
                  className="textarea"
                  style={{
                    flex: 1,
                    border: "none",
                    borderRadius: 0,
                    background: "var(--bg)",
                  }}
                  value={JSON.stringify(recall, null, 2)}
                  readOnly
                />
              </div>
            ) : (
              <div className="empty-state">
                <div className="empty-state-icon">
                  <History size={48} />
                </div>
                <div>Select a record to recall its canonical detail.</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
