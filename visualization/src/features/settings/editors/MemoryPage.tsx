import { useI18n } from "../../../i18n";
/**
 * Memory settings (config-coverage §5.4): the persistent Markdown store's
 * limits per document kind, inspect/search bounds and the embedding use.
 */

import { EmbeddingUseControl, FieldSection, SettingsPageBody } from "./draftCompositeControls";

export function MemoryPage() {
  const { t } = useI18n();
  return (
    <SettingsPageBody>
      <FieldSection
        title={t("settings.locationActiveMemory")}
        description={t("settings.thePersistentMemoryRootAndTheActiveMemoryMd")}
        paths={["memory.root", "memory.max_active_chars"]}
        overrides={{
          "memory.max_active_chars": { min: 1 },
        }}
      />
      <FieldSection
        title={t("settings.persistentDocuments")}
        description={t("settings.sizeLimitsOfTheFivePersistentMarkdownKindsAnd")}
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
        title={t("settings.inspectSearch")}
        description={t("settings.singlePageInspectBoundsAndTheLogicalEmbeddingUse")}
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
