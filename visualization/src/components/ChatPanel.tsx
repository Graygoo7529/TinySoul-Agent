import { Eye } from "lucide-react";

import { useAppStore } from "../store/appStore";
import { MessageList } from "./MessageList";
import { Composer } from "./Composer";
import { TopLinkPanel } from "./TopLinkPanel";
import { ModelInspector } from "./ModelInspector";

const MODES = [
  { key: "normal", label: "Normal" },
  { key: "verbose", label: "Verbose" },
  { key: "model", label: "Model" },
] as const;

export function ChatPanel() {
  const { observationMode, setObservationMode } = useAppStore();

  return (
    <div className="chat-layout">
      <div className="chat-main">
        <div className="panel h-full">
          <div className="panel-header">
            <span className="flex items-center gap-2">
              <Eye size={14} />
              Conversation
            </span>
            <div className="tabs">
              {MODES.map((mode) => (
                <button
                  key={mode.key}
                  className={`tab ${observationMode === mode.key ? "active" : ""}`}
                  onClick={() => setObservationMode(mode.key)}
                >
                  <span className={`badge badge-${mode.key}`}>{mode.label}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="panel-body">
            <MessageList />
          </div>
          <div className="panel-header" style={{ borderTop: "1px solid var(--border)", borderBottom: "none" }}>
            <Composer />
          </div>
        </div>
      </div>
      <div className="chat-sidebar">
        <TopLinkPanel />
        {observationMode === "model" && <ModelInspector />}
      </div>
    </div>
  );
}
