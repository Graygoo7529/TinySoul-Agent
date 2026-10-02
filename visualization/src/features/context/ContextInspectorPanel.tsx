import { useState, type ReactElement } from "react";
import { BookOpen, Brain, Layers, Map } from "lucide-react";

import { selectActiveDay, selectActiveTurnId, useConnectionStore } from "../../store/connectionStore";
import { useTurnStore } from "../../store/turnStore";
import { BackgroundPanel } from "./BackgroundPanel";
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
  const [visited, setVisited] = useState(new Set<ContextTab>([turnId === null ? "session" : "context"]));
  const activeDay = useConnectionStore(selectActiveDay);
  const activeId = useConnectionStore(selectActiveTurnId);
  const displayedId = useTurnStore((s) => s.turnId);
  const displayedDay = useTurnStore((s) => s.day);
  const snapshot = useTurnStore((s) => s.snapshot);
  const turns = useTurnStore((s) => s.sessionTurns);
  const [target] = useState(() => {
    const id = turnId ?? activeId ?? displayedId ?? turns?.[0]?.turn_id ?? null;
    const day = id === activeId ? activeDay : id === displayedId ? displayedDay : turns?.find((entry) => entry.turn_id === id)?.day;
    return { id, day: day ?? activeDay };
  });
  const { id: targetId, day: targetDay } = target;
  const committed = turns?.some((entry) => entry.turn_id === targetId) ?? false;
  const active = targetId !== null && targetId === activeId && !(snapshot?.turn_id === targetId && snapshot.state === "finished");
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
            onClick={() => { setVisited((current) => new Set(current).add(entry.id)); setTab(entry.id); }}
          >
            {entry.icon}
            {entry.label}
          </Button>
        ))}
      </div>
      {visited.has("context") && targetId && <div hidden={tab !== "context"}><ContextOverviewPanel key={targetId} epoch={epoch} turnId={targetId} /></div>}
      {tab === "context" && !targetId && <EmptyState title="当前没有运行中的语境" description="Home 和 Memory 子页保留最近会话已加载的正文。" />}
      {visited.has("session") && (targetDay ?? activeDay) !== null && (
        <div hidden={tab !== "session"}><SessionMapPanel epoch={epoch} day={(targetDay ?? activeDay)!} /></div>
      )}
      {tab === "session" && activeDay === null && (
        <EmptyState title="No active day" description="The Session map is available after the Agent establishes a calendar day." />
      )}
      {(visited.has("home") || visited.has("memory")) && <div hidden={tab !== "home" && tab !== "memory"}>
        {targetId && targetDay ? <BackgroundPanel key={targetId} epoch={epoch} turnId={targetId} day={targetDay} active={active} committed={committed} owner={tab === "memory" ? "memory" : "home"} />
          : <EmptyState title="暂无会话背景" />}
      </div>}
    </div>
  );
}
