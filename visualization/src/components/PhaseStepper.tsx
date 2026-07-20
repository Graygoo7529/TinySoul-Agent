import type { PhaseStep } from "../hooks/useDerivedChat";

interface PhaseStepperProps {
  phases: PhaseStep[];
}

export function PhaseStepper({ phases }: PhaseStepperProps) {
  const allPhases: Array<{ phase: PhaseStep["phase"]; label: string }> = [
    { phase: "phase1", label: "Context" },
    { phase: "phase2", label: "Plan" },
    { phase: "phase3", label: "Act" },
  ];

  return (
    <div className="phase-stepper">
      {allPhases.map(({ phase, label }) => {
        const step = phases.find((p) => p.phase === phase);
        const status = step?.status || "idle";
        return (
          <div key={phase} className={`phase-step ${status}`}>
            <div className="phase-name">{label}</div>
            <div className="phase-status">
              {status === "running" && "Running…"}
              {status === "completed" && "Done"}
              {status === "idle" && "Waiting"}
            </div>
          </div>
        );
      })}
    </div>
  );
}
