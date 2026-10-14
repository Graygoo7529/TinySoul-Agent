import { settingsText } from "../i18n";
/**
 * Session settings (config-coverage §5.2): the daily session root and inspect
 * limits. The background budget is owned by Data & Knowledge → Context; this
 * page shows it read-only with a jump.
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
        description={settingsText("Daily session facts and the semantic map.")}
        paths={["session.root", "session.max_inspect_chars"]}
        overrides={{
          "session.max_inspect_chars": { min: 1 },
        }}
      />
    </SettingsPageBody>
  );
}

function BackgroundBudgetRow() {
  const saved = useConfigDraftStore((s) => s.saved);
  const active = useConfigDraftStore((s) => s.active);
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  return (
    <SectionCard title={settingsText("Background Budget")} description={settingsText("The Context page owns the shared Session background projection budget.")}>
      <div className="flex items-center gap-3">
        <span className="text-[13px] font-medium text-fg">session.max_background_chars</span>
        <Badge tone="gray">由 Context 管理</Badge>
        <span className="ml-auto flex items-center gap-3">
          <span className="font-mono text-[12px] text-fg-muted">saved {valuePreview(savedValue(saved, "session.max_background_chars"))}{" · "}running {valuePreview(activeValue(active, "session.max_background_chars"))}</span>
          <button type="button" className="flex items-center gap-1 text-[12px] font-medium text-accent hover:underline" onClick={() => navigateTo("context", "session.max_background_chars")}>
            {settingsText("Edit in Context")}<ArrowRight size={12} />
          </button>
        </span>
      </div>
    </SectionCard>
  );
}
