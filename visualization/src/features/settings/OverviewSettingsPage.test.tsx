import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConfigCatalog, ConfigStatus } from "../../types";
import { OverviewSettingsPage } from "./OverviewSettingsPage";

describe("OverviewSettingsPage", () => {
  it("collapses configuration source details by default", () => {
    const html = renderToStaticMarkup(
      <OverviewSettingsPage status={status()} catalog={catalog()} />,
    );

    expect(html).toContain("Configuration sources");
    expect(html).toContain("2 sources");
    expect(html).toContain("1 found");
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain("configs/llm/providers.toml");
  });
});

function catalog(): ConfigCatalog {
  return { surfaces: [], field_groups: [], collections: [], fields: [], document_fields: [] };
}

function status(): ConfigStatus {
  return {
    activity: { state: "idle", can_write: true, reason: "" },
    sources: [
      {
        id: "project:configs/llm/providers.toml",
        kind: "project_toml",
        path: "configs/llm/providers.toml",
        exists: true,
        writable: true,
        values: {},
      },
      {
        id: "dotenv",
        kind: "dotenv",
        path: ".env",
        exists: false,
        writable: true,
        values: {},
      },
    ],
    fields: {},
    runtime: { generation_id: "generation", activity: "idle", activation: "stable" },
    process_shell: {
      writable: false,
      reason: "process_owned",
      endpoint: { host: "127.0.0.1", port: 8080, instance_id: "instance" },
    },
  };
}
