import { describe, expect, it } from "vitest";

import type { ConfigStatus } from "../../types";
import {
  configFieldsForPage,
  deriveCredentials,
  groupConfigFields,
  settingsPageForPath,
} from "./model";

describe("settings configuration projection", () => {
  it("maps owned TOML paths to stable settings pages", () => {
    expect(settingsPageForPath("llm.models.primary.model")).toBe("models");
    expect(settingsPageForPath("infra.embedding.model")).toBe("embedding");
    expect(settingsPageForPath("capabilities.web.search.enabled")).toBe("capabilities");
    expect(settingsPageForPath("loop.user.cycle_limit")).toBe("behavior");
    expect(settingsPageForPath("config.profile")).toBe("system");
  });

  it("keeps the TOML source value while exposing endpoint write semantics", () => {
    const status = configStatus();
    const fields = configFieldsForPage(status, "models");
    expect(fields).toHaveLength(3);
    expect(fields.find((field) => field.path === "llm.models.primary.model")).toMatchObject({
      path: "llm.models.primary.model",
      storedValue: "gpt-5.5",
      effectiveValue: "gpt-5.5",
      writable: true,
      overridden: false,
    });
    expect(fields.find((field) => field.path === "llm.providers.openai.api_style")).toMatchObject({
      path: "llm.providers.openai.api_style",
      storedValue: "responses",
      effectiveValue: "chat",
      writable: false,
      overridden: true,
    });
  });

  it("groups model fields by concrete model or provider", () => {
    const groups = groupConfigFields(
      configFieldsForPage(configStatus(), "models"),
      "models",
    );
    expect(groups.map((group) => group.title)).toEqual([
      "Model: Primary",
      "Provider: Openai",
    ]);
  });

  it("keeps module root fields together and separates real subdomains", () => {
    const fields = [
      settingField("memory.enabled"),
      settingField("memory.base_dir"),
      settingField("memory.documents.max_chars"),
    ];

    expect(groupConfigFields(fields, "memory").map((group) => group.title)).toEqual([
      "General",
      "Documents",
    ]);
  });

  it("combines declared API key names with existing dotenv values", () => {
    const { source, credentials } = deriveCredentials(configStatus());
    expect(source?.id).toBe("dotenv");
    expect(credentials).toEqual([
      {
        name: "EXTRA_TOKEN",
        value: "extra",
        present: true,
        configured: true,
        declaredBy: [],
      },
      {
        name: "OPENAI_API_KEY",
        value: "secret",
        present: true,
        configured: true,
        declaredBy: ["llm.providers.openai.api_key_env"],
      },
    ]);
  });

  it("distinguishes declared, empty, and absent dotenv values", () => {
    const status = configStatus();
    const dotenv = status.sources.find((source) => source.kind === "dotenv");
    dotenv!.values.OPENAI_API_KEY = "";
    delete dotenv!.values.EXTRA_TOKEN;
    status.sources[0].values["llm.providers.other.api_key_env"] = "ABSENT_API_KEY";

    const { credentials } = deriveCredentials(status);
    expect(credentials.find((item) => item.name === "OPENAI_API_KEY")).toMatchObject({
      present: true,
      configured: false,
    });
    expect(credentials.find((item) => item.name === "ABSENT_API_KEY")).toMatchObject({
      present: false,
      configured: false,
    });
  });
});

function settingField(path: string) {
  return {
    path,
    label: path,
    sourceId: "project:config/memory.toml",
    sourcePath: "config/memory.toml",
    storedValue: true,
    effectiveValue: true,
    effectiveSource: "project:config/memory.toml",
    writable: true,
    overridden: false,
  };
}

function configStatus(): ConfigStatus {
  return {
    activity: { state: "idle", can_write: true, reason: "" },
    sources: [
      {
        id: "project:config/llm/models.toml",
        kind: "project_toml",
        path: "config/llm/models.toml",
        exists: true,
        writable: true,
        values: {
          "llm.models.primary.model": "gpt-5.5",
          "llm.providers.openai.api_style": "responses",
          "llm.providers.openai.api_key_env": "OPENAI_API_KEY",
          "infra.embedding.enabled": true,
        },
      },
      {
        id: "dotenv",
        kind: "dotenv",
        path: ".env",
        exists: true,
        writable: true,
        values: {
          OPENAI_API_KEY: "secret",
          EXTRA_TOKEN: "extra",
        },
      },
      {
        id: "environment",
        kind: "environment",
        path: "process environment",
        exists: true,
        writable: false,
        values: { "llm.providers.openai.api_style": "chat" },
      },
    ],
    fields: {
      "llm.models.primary.model": {
        value: "gpt-5.5",
        source: "project:config/llm/models.toml",
        writable: true,
      },
      "llm.providers.openai.api_style": {
        value: "chat",
        source: "environment",
        writable: false,
      },
    },
    runtime: {
      generation_id: "generation-1",
      activity: "idle",
      activation: "active",
    },
    process_shell: {
      writable: false,
      reason: "process_owned",
      endpoint: { host: "127.0.0.1", port: 8000, instance_id: "instance-1" },
    },
  };
}
