import { t } from "../../../i18n";
/**
 * Home settings (config-coverage §5.3): actual Home and the cross-day runtime
 * overlay roots, read/write limits, search bounds and the embedding use.
 */

import { ArrowRight } from "lucide-react";
import { Badge } from "../../../components/ui/Badge";
import { SectionCard } from "../../../components/ui/Card";
import { activeValue, savedValue } from "../draft/model";
import { useConfigDraftStore } from "../draft/store";
import { useSettingsUiStore } from "../uiStore";
import { FieldSection, SettingsPageBody, EmbeddingUseControl, valuePreview } from "./controls";

export function HomePage() {
  return (
    <SettingsPageBody>
      <div className="rounded-lg border border-line bg-bg-elev px-3.5 py-2.5 text-[12px] leading-5 text-fg-muted">{t("settings.text.6e14438775f9")}</div>
      <SkillCatalogRow />
      <FieldSection
        title={t("settings.text.2e06127d045a")}
        description={t("settings.text.36f489d6f75e")}
        paths={[
          "home.root",
          "home.runtime_root",
          "home.max_read_chars",
          "home.max_write_chars",
        ]}
        overrides={{
          "home.max_read_chars": { min: 1 },
          "home.max_write_chars": { min: 1 },
        }}
      />
      <FieldSection
        title={t("settings.text.bce06414177f")}
        description={t("settings.text.a3f34ae5d0ae")}
        paths={[
          "home.search.scan_limit",
          "home.search.max_resource_chars",
          "home.search.max_embedding_cache_chars",
          "home.search.embedding_use",
        ]}
        overrides={{
          "home.search.scan_limit": { min: 1 },
          "home.search.max_resource_chars": { min: 1 },
          "home.search.max_embedding_cache_chars": { min: 1 },
          "home.search.embedding_use": {
            render: (api) => <EmbeddingUseControl api={api} />,
          },
        }}
      />
    </SettingsPageBody>
  );
}

function SkillCatalogRow() {
  const saved = useConfigDraftStore((s) => s.saved);
  const active = useConfigDraftStore((s) => s.active);
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  return (
    <SectionCard title={t("settings.text.1652da7b1999")} description={t("settings.text.780960a0facd")}>
      <div className="flex items-center gap-3">
        <span className="font-mono text-[12px] text-fg">home.max_skill_catalog_chars</span>
        <Badge tone="gray">由 Context 管理</Badge>
        <span className="ml-auto flex items-center gap-3">
          <span className="font-mono text-[12px] text-fg-muted">saved {valuePreview(savedValue(saved, "home.max_skill_catalog_chars"))}{" · "}running {valuePreview(activeValue(active, "home.max_skill_catalog_chars"))}</span>
          <button type="button" className="flex items-center gap-1 text-[12px] font-medium text-accent hover:underline" onClick={() => navigateTo("context", "home.max_skill_catalog_chars")}>
            {t("settings.text.7bc633796227")}<ArrowRight size={12} />
          </button>
        </span>
      </div>
    </SectionCard>
  );
}
