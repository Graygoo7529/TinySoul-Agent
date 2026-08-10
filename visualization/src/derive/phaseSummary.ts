/**
 * Semantic one-line summaries for cycles and phases, used by the trace
 * drawer's collapsed rows: instead of explaining what a phase *is*, these
 * state what the phase *did* (domains selected, actions planned/executed).
 */

import type { ActionRecord, Cycle, PhaseStep } from "./model";
import { PHASE_META } from "./model";
import { targetLabel } from "./activitySemantics";
import { descriptorFor } from "./actions/registry";

export function selectedDomains(phase: PhaseStep): string[] {
  const op = phase.controlOps.find((o) => o.kind === "select_domains");
  return op?.kind === "select_domains" ? op.domains : [];
}

export function selectIntent(phase: PhaseStep): string | undefined {
  const op = phase.controlOps.find((o) => o.kind === "select_domains");
  return op?.kind === "select_domains" ? op.intent : undefined;
}

export function cycleDomains(cycle: Cycle): string[] {
  const phase1 = cycle.phases.find((p) => p.phase === "phase1");
  return phase1 ? selectedDomains(phase1) : [];
}

export interface CycleStats {
  actions: number;
  llmCalls: number;
  succeeded: number;
  failed: number;
}

export function cycleStats(cycle: Cycle): CycleStats {
  const seen = new Map<string, ActionRecord>();
  let llmCalls = 0;
  for (const phase of cycle.phases) {
    llmCalls += phase.tasks.length;
    for (const action of phase.actions) {
      const existing = seen.get(action.callId);
      if (!existing || (action.result && !existing.result)) {
        seen.set(action.callId, action);
      }
    }
  }
  let succeeded = 0;
  let failed = 0;
  for (const action of seen.values()) {
    if (action.result?.status === "success") succeeded++;
    else if (action.result) failed++;
  }
  return { actions: seen.size, llmCalls, succeeded, failed };
}

/** What the phase is doing / has done, in one direct sentence. */
export function phaseHeadline(phase: PhaseStep): string {
  const running = phase.status === "running";
  switch (phase.phase) {
    case "phase1": {
      const domains = selectedDomains(phase);
      if (domains.length > 0) {
        return `Selected ${domains.length} domain${domains.length > 1 ? "s" : ""}`;
      }
      return running ? PHASE_META.phase1.running : "Context maintenance";
    }
    case "phase2": {
      // Collapsed rows are narrow: the bare count stays readable, per-action
      // semantics live in the chips and the expanded cards.
      if (phase.actions.length > 0) {
        return `Planned ${phase.actions.length} action${phase.actions.length > 1 ? "s" : ""}`;
      }
      return running ? PHASE_META.phase2.running : "No actions planned";
    }
    case "phase3": {
      const total = phase.actions.length;
      if (total === 0) return running ? PHASE_META.phase3.running : "Nothing to execute";
      const pending = phase.actions.find((a) => !a.result);
      if (pending) {
        const descriptor = descriptorFor(pending.action);
        const target = descriptor.summarizeCall(pending.params).target;
        const label = `${descriptor.verb} ${targetLabel(target) ?? pending.action}`;
        return `${label} (${total - phase.actions.filter((a) => !a.result).length + 1}/${total})`;
      }
      const failed = phase.actions.filter((a) => a.result && a.result.status !== "success");
      if (failed.length > 0) {
        return `${total} action${total > 1 ? "s" : ""} executed · ${failed.length} failed`;
      }
      return `${total} action${total > 1 ? "s" : ""} executed successfully`;
    }
  }
}
