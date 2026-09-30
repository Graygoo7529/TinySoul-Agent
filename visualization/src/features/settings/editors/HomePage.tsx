/**
 * Home settings (config-coverage §5.3): actual Home and the cross-day runtime
 * overlay roots, read/write limits, search bounds and the embedding use.
 */

import { FieldSection, SettingsPageBody, EmbeddingUseControl } from "./controls";

export function HomePage() {
  return (
    <SettingsPageBody>
      <div className="rounded-lg border border-line bg-bg-elev px-3.5 py-2.5 text-[12px] leading-5 text-fg-muted">
        Home holds the identity rules, preferences and guidance. Regular turns
        write a cross-day runtime overlay (the effective Home); only a Home
        Reflection can accept changes back into the actual Home.
      </div>
      <FieldSection
        title="Location & Limits"
        description="The actual Home root and the cross-day runtime overlay root."
        paths={[
          "home.root",
          "home.runtime_root",
          "home.max_read_chars",
          "home.max_write_chars",
          "home.skill_catalog_max_chars",
        ]}
        overrides={{
          "home.max_read_chars": { min: 1 },
          "home.max_write_chars": { min: 1 },
          "home.skill_catalog_max_chars": { min: 1 },
        }}
      />
      <FieldSection
        title="Search"
        description="Discovery bounds and the logical embedding use shared by Home search."
        paths={[
          "home.search.scan_limit",
          "home.search.resource_max_chars",
          "home.search.embedding_cache_max_chars",
          "home.search.embedding_use",
        ]}
        overrides={{
          "home.search.scan_limit": { min: 1 },
          "home.search.resource_max_chars": { min: 1 },
          "home.search.embedding_cache_max_chars": { min: 1 },
          "home.search.embedding_use": {
            render: (api) => <EmbeddingUseControl api={api} />,
          },
        }}
      />
    </SettingsPageBody>
  );
}
