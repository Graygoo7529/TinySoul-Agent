import { useAppStore } from "../store/appStore";
import { useTurnGroups } from "../hooks/useBackend";
import { TurnCard } from "./TurnCard";

export function MessageList() {
  const { events, observationMode } = useAppStore();
  const turns = useTurnGroups(events);

  return (
    <div className="message-list">
      {turns.length === 0 && (
        <div className="empty-state">
          <div className="empty-state-icon">💬</div>
          <div>No conversation yet.</div>
          <div className="text-xs mt-1">Send a message to start a turn.</div>
        </div>
      )}
      {turns.map((turn) => (
        <TurnCard key={turn.turnId} turnId={turn.turnId} events={turn.events} mode={observationMode} />
      ))}
    </div>
  );
}
