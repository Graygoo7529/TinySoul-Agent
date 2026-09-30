/**
 * Session settings (config-coverage §5.2): the daily session root and inspect
 * limits. The background budget is owned by Behavior → Budgets (the longest
 * prefix routes it there); this page shows it read-only with a jump.
 */

import { ArrowRight } from "lucide-react";

import { Badge } from "../../../components/ui/Badge";
import { SectionCard } from "../../../components/ui/Card";
import { activeValue, savedValue } from "../draft/model";
import { useConfigDraftStore } from "../draft/store";
import { useSettingsUiStore } from "../uiStore";
import { FieldSection, SettingsPageBody, valuePreview } from "./controls";

export function SessionPage() {
  return (
    <SettingsPageBody>
      <BackgroundBudgetRow />
      <FieldSection
        title="Session"
        description="Daily session facts and the semantic map."
        paths={["session.root", "session.inspect_max_chars"]}
        overrides={{
          "session.inspect_max_chars": { min: 1 },
        }}
      />
    </SettingsPageBody>
  );
}

/** session.background_max_chars is owned by the Budgets page. */
function BackgroundBudgetRow() {
  const saved = useConfigDraftStore((s) => s.saved);
  const active = useConfigDraftStore((s) => s.active);
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);

  return (
    <SectionCard
      title="Background Budget"
      description="How much session background the Context may carry; edited under Behavior → Budgets together with the other budgets."
    >
      <div className="flex items-center gap-3">
        <span className="text-[13px] font-medium text-fg">
          session.background_max_chars
        </span>
        <Badge tone="gray">owned by Budgets</Badge>
        <span className="ml-auto flex items-center gap-3">
          <span className="font-mono text-[12px] text-fg-muted">
            saved {valuePreview(savedValue(saved, "session.background_max_chars"))}
            {" · "}running{" "}
            {valuePreview(activeValue(active, "session.background_max_chars"))}
          </span>
          <button
            type="button"
            className="flex items-center gap-1 text-[12px] font-medium text-accent hover:underline"
            onClick={() => navigateTo("budgets", "session.background_max_chars")}
          >
            Edit in Budgets <ArrowRight size={12} />
          </button>
        </span>
      </div>
    </SectionCard>
  );
}
