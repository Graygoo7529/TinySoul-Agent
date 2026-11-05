import { t, useI18n } from "../../../i18n";
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
import { valuePreview } from "./draftControls";
import { FieldSection, SettingsPageBody } from "./draftCompositeControls";

export function SessionPage() {
  useI18n();
  return (
    <SettingsPageBody>
      <BackgroundBudgetRow />
      <FieldSection
        title={t("settings.page.session.title")}
        description={t("settings.dailySessionFactsAndTheSemanticMap")}
        paths={["session.root", "session.max_inspect_chars"]}
        overrides={{
          "session.max_inspect_chars": { min: 1 },
        }}
      />
    </SettingsPageBody>
  );
}

function BackgroundBudgetRow() {
  const { t } = useI18n();
  const saved = useConfigDraftStore((s) => s.saved);
  const active = useConfigDraftStore((s) => s.active);
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  return (
    <SectionCard title={t("settings.backgroundBudget")} description={t("settings.theContextPageOwnsTheSharedSessionBackgroundProjection")}>
      <div className="flex items-center gap-3">
        <span className="text-[13px] font-medium text-fg">session.max_background_chars</span>
        <Badge tone="gray">{t("settings.managedByContext")}</Badge>
        <span className="ml-auto flex items-center gap-3">
          <span className="font-mono text-[12px] text-fg-muted">{t("settings.savedBadge")}{valuePreview(savedValue(saved, "session.max_background_chars"))}{" · "}{t("common.running")}{valuePreview(activeValue(active, "session.max_background_chars"))}</span>
          <button type="button" className="flex items-center gap-1 text-[12px] font-medium text-accent hover:underline" onClick={() => navigateTo("context", "session.max_background_chars")}>
            {t("settings.editInContext")}<ArrowRight size={12} />
          </button>
        </span>
      </div>
    </SectionCard>
  );
}
