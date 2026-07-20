import type { PhaseStep } from "../hooks/useDerivedChat";

interface PhaseStepperProps {
  phases: PhaseStep[];
}

export function PhaseStepper({ phases }: PhaseStepperProps) {
  const allPhases: Array<{
    phase: PhaseStep["phase"];
    label: string;
    short: string;
  }> = [
    { phase: "phase1", label: "Context & Domains", short: "Context" },
    { phase: "phase2", label: "Plan Actions", short: "Plan" },
    { phase: "phase3", label: "Execute", short: "Act" },
  ];

  return (
    <div className="phase-stepper">
      {allPhases.map(({ phase, label, short }) => {
        const step = phases.find((p) => p.phase === phase);
        const status = step?.status || "idle";
        return (
          <div key={phase} className={`phase-step ${status}`} title={label}>
            <div className="phase-name">{short}</div>
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
