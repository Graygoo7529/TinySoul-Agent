/**
 * Memory settings (config-coverage §5.4): the persistent Markdown store's
 * limits per document kind, inspect/search bounds and the embedding use.
 */

import { EmbeddingUseControl, FieldSection, SettingsPageBody } from "./controls";

export function MemoryPage() {
  return (
    <SettingsPageBody>
      <FieldSection
        title="Location & Active Memory"
        description="The persistent memory root and the active Memory.md size."
        paths={["memory.root", "memory.max_active_chars"]}
        overrides={{
          "memory.max_active_chars": { min: 1 },
        }}
      />
      <FieldSection
        title="Persistent Documents"
        description="Size limits of the five persistent Markdown kinds and the redirect chain."
        paths={[
          "memory.documents.daily_max_chars",
          "memory.documents.entity_max_chars",
          "memory.documents.concept_max_chars",
          "memory.documents.fact_max_chars",
          "memory.documents.note_max_chars",
          "memory.documents.redirect_max_hops",
        ]}
        overrides={{
          "memory.documents.daily_max_chars": { min: 1 },
          "memory.documents.entity_max_chars": { min: 1 },
          "memory.documents.concept_max_chars": { min: 1 },
          "memory.documents.fact_max_chars": { min: 1 },
          "memory.documents.note_max_chars": { min: 1 },
          "memory.documents.redirect_max_hops": { min: 0 },
        }}
      />
      <FieldSection
        title="Inspect & Search"
        description="Single-page inspect bounds and the logical embedding use shared by Memory search."
        paths={[
          "memory.inspect.page_max_chars",
          "memory.search.embedding_cache_max_chars",
          "memory.search.embedding_use",
        ]}
        overrides={{
          "memory.inspect.page_max_chars": { min: 1 },
          "memory.search.embedding_cache_max_chars": { min: 1 },
          "memory.search.embedding_use": {
            render: (api) => <EmbeddingUseControl api={api} />,
          },
        }}
      />
    </SettingsPageBody>
  );
}
