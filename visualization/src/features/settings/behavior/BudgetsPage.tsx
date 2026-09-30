/**
 * Budgets settings page (config-coverage §3.4): turn cycle limits and the
 * Context/Session character budgets. Every field edits one writable atomic
 * value through the shared draft controls; bounded numbers render the
 * SliderField (range + exact input + unit + restore default) and clearing a
 * number withdraws the override and restores the owner default. Apply stays
 * authoritative for the exact constraint boundaries (e.g. compression ratios
 * are open intervals).
 */

import { FieldSection, SettingsPageBody } from "../editors/controls";

const MEBIBYTE = 1024 * 1024;

export function BudgetsPage() {
  return (
    <SettingsPageBody>
      <FieldSection
        title="Turn Cycles"
        description="Complete Agent Cycles allowed in one turn of each kind. A turn that exhausts its budget ends as exhausted instead of answering."
        paths={[
          "loop.user.max_cycles",
          "reflection.home.max_cycles",
          "reflection.memory.max_cycles",
        ]}
        overrides={{
          "loop.user.max_cycles": { min: 1, slider: { min: 1, max: 64 } },
          "reflection.home.max_cycles": { min: 1, slider: { min: 1, max: 64 } },
          "reflection.memory.max_cycles": { min: 1, slider: { min: 1, max: 64 } },
        }}
      />
      <FieldSection
        title="Context & Session Budgets"
        description="Character and byte budgets of the constructed model context and the session background it carries."
        paths={[
          "context.budget_max_image_bytes",
          "session.background_max_chars",
          "context.compression_trigger_ratio",
          "context.compression_target_ratio",
        ]}
        overrides={{
          "context.budget_max_image_bytes": {
            min: 1,
            slider: { min: MEBIBYTE, max: 64 * MEBIBYTE, step: MEBIBYTE },
          },
          "session.background_max_chars": {
            min: 512,
            slider: { min: 1024, max: 128 * 1024, step: 1024 },
          },
          "context.compression_trigger_ratio": {
            min: 0,
            max: 1,
            slider: { min: 0, max: 1, step: 0.01 },
          },
          "context.compression_target_ratio": {
            min: 0,
            max: 1,
            slider: { min: 0, max: 1, step: 0.01 },
          },
        }}
      />
      <FieldSection
        title="TurnTrace"
        description="Heap chunking and progressive inspection of the current turn's trace. These shape how long-running turns keep their history readable."
        paths={[
          "context.trace_chunk_max_chars",
          "context.trace_branch_factor",
          "context.trace_min_hot_entries",
          "context.trace_inspect_max_chars",
        ]}
        overrides={{
          "context.trace_chunk_max_chars": {
            min: 1,
            slider: { min: 1024, max: 64 * 1024, step: 1024 },
          },
          "context.trace_branch_factor": { min: 2, slider: { min: 2, max: 16 } },
          "context.trace_min_hot_entries": { min: 0, slider: { min: 0, max: 32 } },
          "context.trace_inspect_max_chars": {
            min: 1024,
            slider: { min: 1024, max: 64 * 1024, step: 1024 },
          },
        }}
      />
    </SettingsPageBody>
  );
}
