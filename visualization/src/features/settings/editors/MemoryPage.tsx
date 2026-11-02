import { t } from "../../../i18n";
/**
 * Memory settings (config-coverage §5.4): the persistent Markdown store's
 * limits per document kind, inspect/search bounds and the embedding use.
 */

import { EmbeddingUseControl, FieldSection, SettingsPageBody } from "./controls";

export function MemoryPage() {
  return (
    <SettingsPageBody>
      <FieldSection
        title={t("settings.text.f3d653acf7a3")}
        description={t("settings.text.d19891b8e867")}
        paths={["memory.root", "memory.max_active_chars"]}
        overrides={{
          "memory.max_active_chars": { min: 1 },
        }}
      />
      <FieldSection
        title={t("settings.text.66ee876e308e")}
        description={t("settings.text.685b8bf13323")}
        paths={[
          "memory.documents.max_daily_chars",
          "memory.documents.max_entity_chars",
          "memory.documents.max_concept_chars",
          "memory.documents.max_fact_chars",
          "memory.documents.max_note_chars",
          "memory.documents.redirect_max_hops",
        ]}
        overrides={{
          "memory.documents.max_daily_chars": { min: 1 },
          "memory.documents.max_entity_chars": { min: 1 },
          "memory.documents.max_concept_chars": { min: 1 },
          "memory.documents.max_fact_chars": { min: 1 },
          "memory.documents.max_note_chars": { min: 1 },
          "memory.documents.redirect_max_hops": { min: 0 },
        }}
      />
      <FieldSection
        title={t("settings.text.505acce570b4")}
        description={t("settings.text.0cf440c10818")}
        paths={[
          "memory.inspect.max_page_chars",
          "memory.search.max_embedding_cache_chars",
          "memory.search.embedding_use",
        ]}
        overrides={{
          "memory.inspect.max_page_chars": { min: 1 },
          "memory.search.max_embedding_cache_chars": { min: 1 },
          "memory.search.embedding_use": {
            render: (api) => <EmbeddingUseControl api={api} />,
          },
        }}
      />
    </SettingsPageBody>
  );
}
