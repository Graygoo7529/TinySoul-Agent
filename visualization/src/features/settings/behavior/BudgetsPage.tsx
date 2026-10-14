import { settingsText } from "../i18n";
/**
 * Budgets settings page (config-coverage §3.4): turn and reflection cycle
 * limits. Every field edits one writable atomic
 * value through the shared draft controls; bounded numbers render the
 * SliderField (range + exact input + unit + restore default) and clearing a
 * number withdraws the override and restores the owner default. Apply stays
 * authoritative for the exact constraint boundaries (e.g. compression ratios
 * are open intervals).
 */

import { FieldSection, SettingsPageBody } from "../editors/controls";

export function BudgetsPage() {
  return (
    <SettingsPageBody>
      <FieldSection
        title={settingsText("Turn Cycles")}
        description={settingsText("Complete Agent Cycles allowed in one turn of each kind. A turn that exhausts its budget ends as exhausted instead of answering.")}
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
    </SettingsPageBody>
  );
}
