import { describe, expect, it } from "vitest";

import type { ConfigCatalog, ConfigStatus } from "../../types";
import {
  configObjects,
  deriveCredentials,
  descriptorForPath,
  groupSurfaceFields,
  pathMatches,
  subtreeDeleteMutations,
  surfaceFields,
  validObjectId,
} from "./model";

describe("settings catalog projection", () => {
  it("matches wildcard descriptors without guessing page ownership", () => {
    expect(pathMatches("llm.models.*.provider", "llm.models.primary.provider")).toBe(true);
    expect(pathMatches("llm.models.*.provider", "llm.models.primary.provider.id")).toBe(false);
    expect(descriptorForPath(catalog(), "llm.models.primary.provider")?.surface).toBe("models");
  });

  it("uses catalog titles and importance for effective fields", () => {
    const fields = surfaceFields(status(), catalog(), "models");
    expect(fields).toHaveLength(2);
    expect(fields.map((field) => field.descriptor.title)).toEqual([
      "Provider",
      "Provider Model ID",
    ]);
    expect(groupSurfaceFields(fields, catalog())[0].fields).toHaveLength(2);
  });

  it("derives collection objects from the shared status facts", () => {
    const objects = configObjects(status(), catalog(), "llm.models");
    expect(objects).toHaveLength(1);
    expect(objects[0].id).toBe("primary");
    expect(objects[0].value).toEqual({ provider: "openai", provider_model: "gpt-5" });
  });

  it("uses credential_reference descriptors instead of suffix conventions", () => {
    const result = deriveCredentials(status(), catalog());
    expect(result.credentials).toEqual([
      {
        name: "OPENAI_API_KEY",
        value: "secret",
        present: true,
        configured: true,
        declaredBy: ["llm.providers.openai.api_key_envs"],
      },
    ]);
  });

  it("accepts stable object IDs without dotted mutation ambiguity", () => {
    expect(validObjectId("gpt_5_6")).toBe(true);
    expect(validObjectId("gpt.5")).toBe(false);
    expect(validObjectId(" model ")).toBe(false);
  });

  it("deletes an object subtree from every contributing project source", () => {
    const current = status();
    current.sources.push({
      id: "project:configs/llm/models/overlay.toml",
      kind: "project_toml",
      path: "configs/llm/models/overlay.toml",
      exists: true,
      writable: true,
      values: { "llm.models.primary.provider_model": "gpt-5-mini" },
    });
    expect(subtreeDeleteMutations(current, "llm.models.primary")).toEqual([
      { source_id: "project:configs/llm/models/custom.toml", path: "llm.models.primary", op: "delete" },
      { source_id: "project:configs/llm/models/overlay.toml", path: "llm.models.primary", op: "delete" },
    ]);
  });
});

function catalog(): ConfigCatalog {
  return {
    surfaces: [
      { id: "models", title: "Models", description: "Configured models." },
      { id: "providers", title: "Providers", description: "Configured providers." },
    ],
    collections: [
      {
        id: "llm.models",
        surface: "models",
        root: "llm.models",
        title: "Model",
        description: "A model.",
        identity: { title: "Model ID", description: "Stable model identifier." },
        create_source: "project:configs/llm/models/custom.toml",
        create_template: {},
        allow_create: true,
        allow_delete: true,
      },
    ],
    fields: [
      {
        path: "llm.models.*.provider",
        surface: "models",
        group: "models.binding",
        title: "Provider",
        description: "Provider used by this model.",
        value_kind: "reference",
        importance: "primary",
        credential_reference: false,
      },
      {
        path: "llm.models.*.provider_model",
        surface: "models",
        group: "models.binding",
        title: "Provider Model ID",
        description: "Provider model identifier.",
        value_kind: "string",
        importance: "primary",
        credential_reference: false,
      },
      {
        path: "llm.providers.*.api_key_envs",
        surface: "providers",
        group: "providers.credentials",
        title: "Credential Names",
        description: "Credential references.",
        value_kind: "string_list",
        importance: "primary",
        credential_reference: true,
      },
    ],
    field_groups: [
      { id: "models.binding", surface: "models", title: "Binding", description: "Model binding." },
      { id: "providers.credentials", surface: "providers", title: "Credentials", description: "Credential references." },
    ],
  };
}

function status(): ConfigStatus {
  return {
    activity: { state: "idle", can_write: true, reason: "" },
    sources: [
      {
        id: "project:configs/llm/models/custom.toml",
        kind: "project_toml",
        path: "configs/llm/models/custom.toml",
        exists: true,
        writable: true,
        values: {
          "llm.models.primary.provider": "openai",
          "llm.models.primary.provider_model": "gpt-5",
          "llm.providers.openai.api_key_envs": ["OPENAI_API_KEY"],
        },
      },
      {
        id: "dotenv",
        kind: "dotenv",
        path: ".env",
        exists: true,
        writable: true,
        values: { OPENAI_API_KEY: "secret" },
      },
    ],
    fields: {
      "llm.models.primary.provider": {
        value: "openai",
        source: "project:configs/llm/models/custom.toml",
        writable: true,
      },
      "llm.models.primary.provider_model": {
        value: "gpt-5",
        source: "project:configs/llm/models/custom.toml",
        writable: true,
      },
      "llm.providers.openai.api_key_envs": {
        value: ["OPENAI_API_KEY"],
        source: "project:configs/llm/models/custom.toml",
        writable: true,
      },
    },
    runtime: { generation_id: "g1", activity: "idle", activation: "stable" },
    process_shell: {
      writable: false,
      reason: "process_owned",
      endpoint: { host: "127.0.0.1", port: 1, instance_id: "i" },
    },
  };
}
