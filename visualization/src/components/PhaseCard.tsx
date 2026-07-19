import type { EndpointEvent } from "../types";

interface PhaseCardProps {
  phase: "phase1" | "phase2" | "phase3";
  events: EndpointEvent[];
}

export function PhaseCard({ phase, events }: PhaseCardProps) {
  const started = events.find((e) => e.name === "loop.phase.started" && e.payload?.phase === phase);
  const completed = events.find(
    (e) => e.name === "loop.phase.completed" && e.payload?.phase === phase,
  );
  const state = completed ? "completed" : started ? "active" : "idle";

  return (
    <div className={`phase-card ${state}`}>
      <div className="phase-title">{phase}</div>
      <div className="phase-status">
        {state === "completed" && "Completed"}
        {state === "active" && "Running…"}
        {state === "idle" && "Waiting"}
      </div>
    </div>
  );
}
