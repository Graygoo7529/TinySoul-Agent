import { t, useI18n } from "../../i18n";
import { useRef, useState, type ReactElement } from "react";
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
  useI18n();
  const [tab, setTab] = useState<ContextTab>(turnId === null ? "session" : "context");
  const [visited, setVisited] = useState(new Set<ContextTab>([turnId === null ? "session" : "context"]));
  const activeDay = useConnectionStore(selectActiveDay);
  const activeId = useConnectionStore(selectActiveTurnId);
  const displayedId = useTurnStore((s) => s.turnId);
  const displayedDay = useTurnStore((s) => s.day);
  const snapshot = useTurnStore((s) => s.snapshot);
  const turns = useTurnStore((s) => s.sessionTurns);
  const runtimeTurns = useTurnStore((s) => s.runtimeTurns);
  const [target] = useState(() => {
    const id = turnId ?? activeId ?? displayedId ?? turns?.[0]?.turn_id ?? null;
    const day = id === activeId ? activeDay : id === displayedId ? displayedDay : turns?.find((entry) => entry.turn_id === id)?.day;
    return { id, day: day ?? activeDay };
  });
  const { id: targetId, day: targetDay } = target;
  const retainedRoot = useRef(runtimeTurns.find((entry) => entry.turn_id === targetId));
  const root = runtimeTurns.find((entry) => entry.turn_id === targetId);
  if (root) retainedRoot.current = root;
  const kind = retainedRoot.current?.kind ?? "user";
  const mapDay = kind === "memory" ? retainedRoot.current?.reflection?.target_day ?? targetDay : targetDay;
  const committed = turns?.some((entry) => entry.turn_id === targetId) ?? false;
  const active = targetId !== null && targetId === activeId && !(snapshot?.turn_id === targetId && snapshot.state === "finished");
  const tabs: Array<{ id: ContextTab; label: string; icon: ReactElement }> = [
    { id: "context", label: t("context.tab.current"), icon: <Layers size={13} /> },
    { id: "session", label: t("context.tab.session"), icon: <Map size={13} /> },
    { id: "home", label: t("context.tab.loadedHome"), icon: <BookOpen size={13} /> },
    { id: "memory", label: t("context.tab.loadedMemory"), icon: <Brain size={13} /> },
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
      {tab === "context" && !targetId && <EmptyState title={t("context.noActiveContext")} description={t("context.lastBackgroundHint")} />}
      {visited.has("session") && (mapDay ?? activeDay) !== null && (
        <div hidden={tab !== "session"}>
          {kind === "memory" && <p className="mb-2 text-[11px] text-fg-faint">{t("context.reflectionSource")}{mapDay}</p>}
          <SessionMapPanel epoch={epoch} day={(mapDay ?? activeDay)!} /></div>
      )}
      {tab === "session" && activeDay === null && (
        <EmptyState title={t("context.activeDay")} description={t("context.sessionMapAvailableAgentEstablishesCalendarDay")} />
      )}
      {(visited.has("home") || visited.has("memory")) && <div hidden={tab !== "home" && tab !== "memory"}>
        {targetId && targetDay ? <BackgroundPanel key={targetId} epoch={epoch} turnId={targetId} day={targetDay} active={active} committed={committed} reflection={kind !== "user"} owner={tab === "memory" ? "memory" : "home"} />
          : <EmptyState title={t("context.noBackground")} />}
      </div>}
    </div>
  );
}
