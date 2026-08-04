import type { Cycle } from "../../derive/model";
import { SectionCard } from "../ui/Card";
import { Badge } from "../ui/Badge";
import { PhaseCard } from "./PhaseCard";

export function CycleSection({ cycle }: { cycle: Cycle }) {
  return (
    <SectionCard
      title={`Cycle ${cycle.index}`}
      description={
        cycle.status === "completed" ? "Completed" : "Running"
      }
      actions={
        <Badge tone={cycle.status === "completed" ? "green" : "accent"}>
          {cycle.status}
        </Badge>
      }
    >
      <div className="space-y-3">
        {cycle.phases.map((phase) => (
          <PhaseCard key={phase.phase} phase={phase} />
        ))}
        {cycle.phases.length === 0 && (
          <div className="text-xs text-fg-faint">No phase activity observed.</div>
        )}
      </div>
    </SectionCard>
  );
}
