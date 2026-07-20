import { useEffect, useState } from "react";
import { History, RefreshCw, ChevronRight } from "lucide-react";

import { useAppStore } from "../store/appStore";
import type { SessionHistoryItem, SessionRecall } from "../types";
import { formatTime } from "../utils/format";

export function SessionView() {
  const { client } = useAppStore();
  const [items, setItems] = useState<SessionHistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [recall, setRecall] = useState<SessionRecall | null>(null);

  const load = async () => {
    if (!client) return;
    setLoading(true);
    try {
      const history = await client.sessionHistory();
      setItems(history.items);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (client) void load();
  }, [client]);

  const onRecall = async (ref: string) => {
    if (!client) return;
    try {
      const data = await client.sessionRecall(ref, 0, 4000);
      setRecall(data);
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="session-view">
      <div className="workspace-sidebar">
        <div className="panel h-full">
          <div className="panel-header">
            <span className="flex items-center gap-2">
              <History size={14} />
              Today&apos;s Turns
            </span>
            <button className="btn btn-sm btn-ghost" onClick={() => void load()} disabled={loading}>
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
            </button>
          </div>
          <div className="panel-body resource-list">
            {items.length === 0 && <div className="text-muted text-xs">No turns recorded yet.</div>}
            {items.map((item) => (
              <div key={item.ref} className="resource-item" onClick={() => void onRecall(item.ref)}>
                <div className="resource-info">
                  <div className="resource-link">{item.turn_id.slice(-8)}</div>
                  <div className="resource-summary">
                    {formatTime(item.started_at)} · {item.status} · {item.summary || "No summary"}
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
          </div>
          <div className="panel-body" style={{ padding: 0 }}>
            {recall ? (
              <textarea
                className="textarea"
                style={{ height: "100%", border: "none", borderRadius: 0, background: "var(--bg)" }}
                value={recall.text}
                readOnly
              />
            ) : (
              <div className="empty-state">
                <div className="empty-state-icon">
                  <History size={48} />
                </div>
                <div>Select a turn to recall its canonical trace.</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
