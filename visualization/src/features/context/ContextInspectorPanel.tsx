import { useState, type ReactElement } from "react";
import { BookOpen, Brain, Layers, Map } from "lucide-react";

import { selectActiveDay, useConnectionStore } from "../../store/connectionStore";
import { EmptyState } from "../../components/ui/EmptyState";
import { Button } from "../../components/ui/Button";
import { SessionMapPanel } from "../history/SessionMapPanel";
import { ContextOverviewPanel } from "./OverviewPanel";

type ContextTab = "context" | "session" | "home" | "memory";

/** Unified top-right Context inspector. Each tab keeps its owner semantics. */
export function ContextInspectorPanel({
  epoch,
  turnId,
}: {
  epoch: number;
  turnId: string | null;
}): ReactElement {
  const [tab, setTab] = useState<ContextTab>(turnId === null ? "session" : "context");
  const activeDay = useConnectionStore(selectActiveDay);
  const tabs: Array<{ id: ContextTab; label: string; icon: ReactElement }> = [
    { id: "context", label: "当前 Context", icon: <Layers size={13} /> },
    { id: "session", label: "Session map", icon: <Map size={13} /> },
    { id: "home", label: "已加载 Home", icon: <BookOpen size={13} /> },
    { id: "memory", label: "已加载 Memory", icon: <Brain size={13} /> },
  ];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-1 rounded-lg border border-line bg-bg-sunken p-1">
        {tabs.map((entry) => (
          <Button
            key={entry.id}
            variant={tab === entry.id ? "secondary" : "ghost"}
            size="xs"
            className="justify-start"
            onClick={() => setTab(entry.id)}
          >
            {entry.icon}
            {entry.label}
          </Button>
        ))}
      </div>
      {tab !== "session" && turnId === null && <EmptyState title="当前没有运行中的语境" description="开始一轮对话后，可查看已加载的语境内容。" />}
      {tab === "context" && turnId !== null && <ContextOverviewPanel epoch={epoch} turnId={turnId} />}
      {tab === "session" && activeDay !== null && (
        <SessionMapPanel epoch={epoch} day={activeDay} />
      )}
      {tab === "session" && activeDay === null && (
        <EmptyState title="No active day" description="The Session map is available after the Agent establishes a calendar day." />
      )}
      {tab === "home" && turnId !== null && (
        <ContextOverviewPanel key="home" epoch={epoch} turnId={turnId} resourceOwner="home" />
      )}
      {tab === "memory" && turnId !== null && (
        <ContextOverviewPanel key="memory" epoch={epoch} turnId={turnId} resourceOwner="memory" />
      )}
    </div>
  );
}
