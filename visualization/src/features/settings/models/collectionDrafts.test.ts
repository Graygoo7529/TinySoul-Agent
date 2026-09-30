/**
 * Models & Services projection tests (plan §16): the projected collection view
 * over saved fields + local drafts (draft-created objects visible to reference
 * pickers, subtree deletes, shared-atom single entries), reference finders and
 * the credential derivation that keeps masked values display-only.
 */

import { beforeEach, describe, expect, it } from "vitest";

import type { Configuration, JsonObject, JsonValue } from "../../../api/v2/types";
import type { ConfigCatalog } from "../../../api/v2/types";
import { draftKey } from "../draft/model";
import { draftOperations, useConfigDraftStore } from "../draft/store";
import {
  deriveCredentials,
  modelReferences,
  moveItem,
  objectDeletable,
  objectIdError,
  projectAtomEntries,
  projectCollection,
  projectedFields,
  providerCredentialStates,
  providerReferences,
  serviceModelReferences,
  serviceProviderReferences,
  taskChainUsage,
  useConsumers,
} from "./collectionDrafts";

const MAIN = "project:tinysoul.toml";
const PROVIDERS = "project:configs/llm/providers.toml";
const MODELS_CUSTOM = "project:configs/llm/models/custom.toml";
const MODELS_BUILTIN = "project:configs/llm.models/kimi.toml";
const TASKS = "project:configs/llm/tasks.toml";
const SERVICES = "project:configs/infra/model_services.toml";

function makeCatalog(): ConfigCatalog {
  const field = (
    path: string,
    valueKind: string,
    extra: Record<string, unknown> = {},
  ) => ({
    path,
    surface: "models",
    group: "g",
    title: path.split(".").pop() ?? path,
    description: "",
    value_kind: valueKind,
    importance: "primary",
    ...extra,
  });
  return {
    surfaces: [],
    field_groups: [
      { id: "providers.connection", surface: "providers", title: "Connection", description: "" },
    ],
    collections: [
      {
        id: "llm.providers",
        surface: "providers",
        root: "llm.providers",
        title: "Provider",
        description: "",
        create_source: PROVIDERS,
        create_template: {},
        allow_create: true,
        delete_policy: "all",
      },
      {
        id: "llm.models",
        surface: "models",
        root: "llm.models",
        title: "Model",
        description: "",
        create_source: MODELS_CUSTOM,
        create_template: {},
        allow_create: true,
        delete_policy: "create_source_only",
      },
      {
        id: "llm.tasks",
        surface: "task_chains",
        root: "llm.tasks",
        title: "Task Chain",
        description: "",
        create_source: TASKS,
        create_template: {},
        allow_create: true,
        delete_policy: "all",
      },
    ],
    fields: [
      field("llm.providers.*.api_key_envs", "string_list", {
        credential_reference: true,
        group: "providers.connection",
      }),
      field("llm.models.*.providers", "object_list"),
      field("llm.models.*.adapter_options.thinking", "object"),
      field("llm.models.*.adapter_options.reasoning_effort", "string"),
      field("llm.tasks.*.models", "reference_list"),
      field("infra.model_services.providers", "object_list"),
      field("infra.model_services.providers.*.api_key_env", "string", {
        credential_reference: true,
        group: "providers.connection",
      }),
    ],
    document_fields: [],
    rules: { llm: { adapters: [] } },
  } as unknown as ConfigCatalog;
}

function makeSaved(
  fields: Record<string, { value: JsonValue; source: string }>,
  extraSources: { id: string; kind?: string; values: Record<string, JsonValue> }[] = [],
  runtime?: JsonObject,
): Configuration {
  const sourceIds = new Set<string>();
  for (const field of Object.values(fields)) sourceIds.add(field.source);
  const sources = [...sourceIds].map((id) => ({
    id,
    kind: "project_toml",
    path: id,
    exists: true,
    writable: true,
    values: Object.fromEntries(
      Object.entries(fields)
        .filter(([, field]) => field.source === id)
        .map(([key, field]) => [key, field.value]),
    ),
  }));
  for (const extra of extraSources) {
    sources.push({
      id: extra.id,
      kind: extra.kind ?? "dotenv",
      path: extra.id,
      exists: true,
      writable: true,
      values: extra.values,
    });
  }
  return {
    view: "saved",
    generation_id: "gen_saved",
    activity: { state: "idle", can_write: true, can_reload: true, reason: "" },
    pending_reload: false,
    sources,
    fields: Object.fromEntries(
      Object.entries(fields).map(([key, field]) => [
        key,
        { value: field.value, source: field.source, writable: true },
      ]),
    ),
    ...(runtime !== undefined ? { runtime } : {}),
  };
}

const store = () => useConfigDraftStore.getState();

function install(
  saved: Configuration,
  active?: Configuration,
): void {
  store().applySnapshots({
    saved,
    active: active ?? { ...saved, view: "active", generation_id: "gen_active" },
    catalogRaw: makeCatalog(),
    presets: [],
  });
}

beforeEach(() => {
  store().reset();
});

// ---------------------------------------------------------------------------
// projectedFields
// ---------------------------------------------------------------------------

describe("projectedFields", () => {
  it("overlays whole-object creates by flattening, stopping at catalog object boundaries", () => {
    install(
      makeSaved({
        "llm.models.kimi-k2.adapter": { value: "kimi", source: MODELS_BUILTIN },
        "llm.models.kimi-k2.providers": {
          value: [{ provider: "kimi", provider_model: "k2" }],
          source: MODELS_BUILTIN,
        },
      }),
    );
    store().setValue(MODELS_CUSTOM, "llm.models.my-model", {
      adapter: "openai",
      providers: [{ provider: "openai", provider_model: "my-model" }],
      adapter_options: { thinking: { type: "enabled" }, reasoning_effort: "high" },
    });

    const fields = projectedFields(store());
    // Leaf values flatten…
    expect(fields.get("llm.models.my-model.adapter")).toBe("openai");
    expect(fields.get("llm.models.my-model.adapter_options.reasoning_effort")).toBe("high");
    // …but catalog object / object_list boundaries stay atomic.
    expect(fields.get("llm.models.my-model.providers")).toEqual([
      { provider: "openai", provider_model: "my-model" },
    ]);
    expect(fields.get("llm.models.my-model.adapter_options.thinking")).toEqual({
      type: "enabled",
    });
    expect(fields.get("llm.models.my-model.adapter_options.thinking.type")).toBeUndefined();
    // Saved objects stay untouched.
    expect(fields.get("llm.models.kimi-k2.adapter")).toBe("kimi");
  });

  it("a set replaces the subtree; a delete removes only the keys the draft source owns", () => {
    install(
      makeSaved({
        "llm.models.m.adapter": { value: "kimi", source: MODELS_BUILTIN },
        "llm.models.m.family": { value: "kimi", source: MODELS_BUILTIN },
        "llm.models.m.context_window_tokens": { value: 262144, source: MODELS_CUSTOM },
      }),
    );
    // A set below the object replaces exactly that subtree. `adapter_options`
    // is not a catalog object boundary, so the object flattens to leaf keys.
    store().setValue(MODELS_BUILTIN, "llm.models.m.adapter_options", { protocol: "k3" });
    let fields = projectedFields(store());
    expect(fields.get("llm.models.m.adapter_options.protocol")).toBe("k3");

    // Delete at the object root removes only keys owned by that source.
    store().deleteValue(MODELS_BUILTIN, "llm.models.m");
    fields = projectedFields(store());
    expect(fields.get("llm.models.m.adapter")).toBeUndefined();
    expect(fields.get("llm.models.m.family")).toBeUndefined();
    // The custom source's override survives the builtin-source delete.
    expect(fields.get("llm.models.m.context_window_tokens")).toBe(262144);
  });
});

// ---------------------------------------------------------------------------
// projectCollection
// ---------------------------------------------------------------------------

describe("projectCollection", () => {
  const baseFields = {
    "llm.providers.kimi.enabled": { value: true, source: PROVIDERS },
    "llm.providers.kimi.base_url": { value: "https://api.moonshot.cn/v1", source: PROVIDERS },
    "llm.providers.openai.enabled": { value: true, source: PROVIDERS },
  };

  it("includes draft-created objects and folds per-field drafts into saved objects", () => {
    install(makeSaved(baseFields));
    store().setValue(PROVIDERS, "llm.providers.newone", {
      enabled: false,
      base_url: "https://example.com/v1",
    });
    store().setValue(PROVIDERS, "llm.providers.kimi.enabled", false);

    const objects = projectCollection(store(), "llm.providers");
    expect(objects.map((item) => item.id)).toEqual(["kimi", "newone", "openai"]);
    const kimi = objects.find((item) => item.id === "kimi");
    expect(kimi?.isNew).toBe(false);
    expect(kimi?.dirty).toBe(true);
    expect(kimi?.value.enabled).toBe(false);
    const created = objects.find((item) => item.id === "newone");
    expect(created?.isNew).toBe(true);
    expect(created?.value.base_url).toBe("https://example.com/v1");
  });

  it("hides saved objects whose subtree delete is staged, and drops draft-new objects on delete", () => {
    install(makeSaved(baseFields));
    store().setValue(PROVIDERS, "llm.providers.drafty", { enabled: true });

    let objects = projectCollection(store(), "llm.providers");
    expect(objects.some((item) => item.id === "drafty")).toBe(true);

    store().deleteValue(PROVIDERS, "llm.providers.drafty");
    objects = projectCollection(store(), "llm.providers");
    expect(objects.some((item) => item.id === "drafty")).toBe(false);

    store().deleteValue(PROVIDERS, "llm.providers.kimi");
    objects = projectCollection(store(), "llm.providers");
    expect(objects.map((item) => item.id)).toEqual(["openai"]);
  });

  it("collects owner sources across files for multi-source objects", () => {
    install(
      makeSaved({
        "llm.models.kimi-k2.adapter": { value: "kimi", source: MODELS_BUILTIN },
        "llm.models.kimi-k2.collapsed": { value: true, source: MODELS_CUSTOM },
      }),
    );
    const objects = projectCollection(store(), "llm.models");
    expect(objects).toHaveLength(1);
    expect(objects[0]?.ownerSources).toEqual([MODELS_BUILTIN, MODELS_CUSTOM].sort());
  });
});

// ---------------------------------------------------------------------------
// objectDeletable (collection delete policy)
// ---------------------------------------------------------------------------

describe("objectDeletable", () => {
  it("create_source_only restricts deletion to custom-owned objects", () => {
    install(
      makeSaved({
        "llm.models.kimi-k2.adapter": { value: "kimi", source: MODELS_BUILTIN },
        "llm.models.mine.adapter": { value: "openai", source: MODELS_CUSTOM },
      }),
    );
    const objects = projectCollection(store(), "llm.models");
    const builtin = objects.find((item) => item.id === "kimi-k2") ?? null;
    const custom = objects.find((item) => item.id === "mine") ?? null;
    expect(objectDeletable(builtin, "create_source_only", MODELS_CUSTOM)).toBe(false);
    expect(objectDeletable(custom, "create_source_only", MODELS_CUSTOM)).toBe(true);
    expect(objectDeletable(builtin, "all", MODELS_CUSTOM)).toBe(true);
    expect(objectDeletable(custom, "none", MODELS_CUSTOM)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Shared atom entries (projectAtomEntries)
// ---------------------------------------------------------------------------

describe("projectAtomEntries", () => {
  const savedUses = [
    { id: "emb-main", kind: "embedding", model_id: "m1" },
    { id: "jev-1", kind: "structured_decision", model_id: "m2" },
  ];

  it("reports new / modified / deleted entries against the saved atom", () => {
    install(
      makeSaved({
        "infra.model_services.uses": { value: savedUses, source: SERVICES },
      }),
    );
    store().setValue(SERVICES, "infra.model_services.uses", [
      { id: "emb-main", kind: "embedding", model_id: "m9" }, // modified
      { id: "emb-new", kind: "embedding", model_id: "m9" }, // new
    ]);

    const atom = projectAtomEntries(store(), "infra.model_services.uses");
    const byId = new Map(atom.entries.map((entry) => [entry.id, entry]));
    expect(byId.get("emb-main")?.status).toBe("modified");
    expect(byId.get("emb-new")?.status).toBe("new");
    expect(byId.get("jev-1")?.status).toBe("deleted");
    // The deleted entry keeps the saved value for a restore affordance.
    expect(byId.get("jev-1")?.value.model_id).toBe("m2");
    expect(atom.dirty).toBe(true);
  });

  it("two pages writing the same object_list atom keep one draft entry", () => {
    install(
      makeSaved({
        "infra.model_services.uses": { value: savedUses, source: SERVICES },
      }),
    );
    store().setValue(SERVICES, "infra.model_services.uses", [
      ...savedUses,
      { id: "emb-new", kind: "embedding", model_id: "m9" },
    ]);
    // A second writer (another page) edits the same atom from the projected value.
    const current = projectAtomEntries(store(), "infra.model_services.uses")
      .entries.filter((entry) => entry.status !== "deleted")
      .map((entry) => entry.value);
    store().setValue(SERVICES, "infra.model_services.uses", [
      ...current,
      { id: "jev-2", kind: "structured_decision", model_id: "m2" },
    ]);

    const operations = draftOperations(store());
    expect(operations).toHaveLength(1);
    expect(operations[0]).toEqual({
      op: "set",
      source_id: SERVICES,
      path: "infra.model_services.uses",
      value: [...savedUses.slice(0, 2), { id: "emb-new", kind: "embedding", model_id: "m9" }, { id: "jev-2", kind: "structured_decision", model_id: "m2" }].map(
        (entry) => entry,
      ),
    });
  });
});

// ---------------------------------------------------------------------------
// Reference finders
// ---------------------------------------------------------------------------

describe("reference finders", () => {
  it("providerReferences locates chain positions, including draft-created models", () => {
    install(
      makeSaved({
        "llm.models.kimi-k2.providers": {
          value: [{ provider: "kimi", provider_model: "k2" }],
          source: MODELS_BUILTIN,
        },
      }),
    );
    store().setValue(MODELS_CUSTOM, "llm.models.drafty", {
      providers: [
        { provider: "kimi", provider_model: "k2" },
        { provider: "openai", provider_model: "g" },
      ],
    });
    const models = projectCollection(store(), "llm.models");
    const references = providerReferences(models, "kimi");
    expect(references).toHaveLength(2);
    expect(references.map((item) => item.owner).sort()).toEqual(["drafty", "kimi-k2"]);
    expect(references.find((item) => item.owner === "kimi-k2")?.path).toBe(
      "llm.models.kimi-k2.providers",
    );
  });

  it("modelReferences locates task-chain positions", () => {
    install(
      makeSaved({
        "llm.tasks.default.models": { value: ["kimi-k2", "gpt-5"], source: TASKS },
        "llm.tasks.coding.models": { value: ["gpt-5"], source: TASKS },
      }),
    );
    const tasks = projectCollection(store(), "llm.tasks");
    const references = modelReferences(tasks, "gpt-5");
    expect(references).toHaveLength(2);
    expect(references.find((item) => item.owner === "default")?.detail).toBe(
      "position 2",
    );
  });

  it("taskChainUsage reads phase bindings and action consumers from the projection", () => {
    install(
      makeSaved({
        "loop.cycle.phase1_task_profile": { value: "default", source: MAIN },
        "action.models.bindings": {
          value: [
            { consumer: "core.answer.generate", target: { task_profile: "default" } },
            { consumer: "memory.search.select", target: { use: "jev-1" } },
          ],
          source: MAIN,
        },
      }),
    );
    const usage = taskChainUsage(store(), "default");
    expect(usage.phases).toEqual(["Phase1"]);
    expect(usage.consumers).toEqual(["core.answer.generate"]);

    const consumers = useConsumers(store(), "jev-1");
    expect(consumers.consumers).toEqual(["memory.search.select"]);
    expect(consumers.ownerRefs).toEqual([]);
  });

  it("service references follow provider bindings and use model_id", () => {
    const models = [
      { id: "m1", provider_bindings: [{ provider_id: "p1", model: "text-emb" }] },
    ];
    const uses = [{ id: "emb-main", model_id: "m1" }];
    expect(serviceProviderReferences(models, "p1")).toHaveLength(1);
    expect(serviceProviderReferences(models, "p2")).toHaveLength(0);
    expect(serviceModelReferences(uses, "m1")).toHaveLength(1);
    expect(serviceModelReferences(uses, "m2")).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Credentials
// ---------------------------------------------------------------------------

describe("deriveCredentials", () => {
  it("collects referenced names, dotenv contents and draft state without values", () => {
    install(
      makeSaved(
        {
          "llm.providers.kimi.api_key_envs": {
            value: ["KIMI_API_KEY"],
            source: PROVIDERS,
          },
          "infra.model_services.providers": {
            value: [{ id: "p1", api_key_env: "SERVICE_API_KEY" }],
            source: SERVICES,
          },
        },
        [
          {
            id: "dotenv",
            values: { KIMI_API_KEY: "<redacted>", UNUSED_KEY: "<redacted>" },
          },
        ],
      ),
    );
    store().setValue("dotenv", "SERVICE_API_KEY", "sk-service");

    const entries = deriveCredentials(store());
    const byName = new Map(entries.map((entry) => [entry.name, entry]));

    const kimi = byName.get("KIMI_API_KEY");
    expect(kimi?.inDotenv).toBe(true);
    expect(kimi?.draftState).toBe("none");
    expect(kimi?.references.map((site) => site.path)).toEqual([
      "llm.providers.kimi.api_key_envs",
    ]);
    expect(kimi?.references[0]?.kind).toBe("env");

    const service = byName.get("SERVICE_API_KEY");
    expect(service?.inDotenv).toBe(false);
    expect(service?.draftState).toBe("set");

    // Dotenv contents not referenced by any field still appear.
    expect(byName.get("UNUSED_KEY")?.references).toEqual([]);

    // A staged delete is reported.
    store().deleteValue("dotenv", "KIMI_API_KEY");
    const after = new Map(
      deriveCredentials(store()).map((entry) => [entry.name, entry]),
    );
    expect(after.get("KIMI_API_KEY")?.draftState).toBe("deleted");
  });
});

// ---------------------------------------------------------------------------
// Runtime credential projection
// ---------------------------------------------------------------------------

describe("providerCredentialStates", () => {
  it("decodes the read-only runtime projection without secrets", () => {
    install(
      makeSaved({}, [], {
        llm: {
          providers: [
            { id: "kimi", credential_state: "configured", api_key_envs: ["KIMI_API_KEY"] },
            { id: "openai", credential_state: "missing", api_key_envs: [] },
          ],
        },
      }),
    );
    const states = providerCredentialStates(store());
    expect(states.get("kimi")?.credentialState).toBe("configured");
    expect(states.get("openai")?.credentialState).toBe("missing");
  });
});

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

describe("helpers", () => {
  it("moveItem reorders without mutating the input", () => {
    const input = ["a", "b", "c"];
    expect(moveItem(input, 0, 2)).toEqual(["b", "c", "a"]);
    expect(input).toEqual(["a", "b", "c"]);
    expect(moveItem(input, 1, 1)).toBe(input);
    expect(moveItem(input, -1, 5)).toBe(input);
  });

  it("objectIdError enforces the collection identity rules", () => {
    expect(objectIdError("")).not.toBeNull();
    expect(objectIdError(" padded")).not.toBeNull();
    expect(objectIdError("has.dot")).not.toBeNull();
    expect(objectIdError("123")).not.toBeNull();
    expect(objectIdError("kimi-k2")).toBeNull();
  });

  it("delete drafts at collection roots become single subtree delete operations", () => {
    install(
      makeSaved({
        "llm.providers.kimi.enabled": { value: true, source: PROVIDERS },
        "llm.providers.kimi.base_url": { value: "https://x", source: PROVIDERS },
      }),
    );
    store().deleteValue(PROVIDERS, "llm.providers.kimi");
    expect(draftOperations(store())).toEqual([
      { op: "delete", source_id: PROVIDERS, path: "llm.providers.kimi" },
    ]);
    expect(
      store().drafts[draftKey({ sourceId: PROVIDERS, path: "llm.providers.kimi" })],
    ).toBeDefined();
  });
});
