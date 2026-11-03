import { describe, expect, it } from "vitest";
import { decodeCatalog } from "../features/settings/draft/catalog";
import { searchConfig } from "../features/settings/pages";
import { localizeCollection, localizeDocument, localizeField, message, protocolText, resolveText, t, tStatus, translatedField } from ".";
import { collectionText, documentText, fieldText } from "./catalog/zh-CN";
import { commonMessages as zhCommon } from "./messages/zh-CN/common";
import { commonMessages as enCommon } from "./messages/en-US/common";
import { settingsMessages as zhSettings } from "./messages/zh-CN/settings";
import { settingsMessages as enSettings } from "./messages/en-US/settings";
import { protocolMessages as zhProtocol } from "./protocol/zh-CN";
import { protocolMessages as enProtocol } from "./protocol/en-US";
import { historyMessages as zhHistory } from "./messages/zh-CN/history";
import { historyMessages as enHistory } from "./messages/en-US/history";
import { contextMessages as zhContext } from "./messages/zh-CN/context";
import { contextMessages as enContext } from "./messages/en-US/context";
import { traceMessages as zhTrace } from "./messages/zh-CN/trace";
import { traceMessages as enTrace } from "./messages/en-US/trace";
import { presentationMessages as zhPresentation } from "./messages/zh-CN/presentation";
import { presentationMessages as enPresentation } from "./messages/en-US/presentation";
import { chatMessages as zhChat } from "./messages/zh-CN/chat";
import { chatMessages as enChat } from "./messages/en-US/chat";
import { homeMessages as zhHome } from "./messages/zh-CN/home";
import { homeMessages as enHome } from "./messages/en-US/home";
import { memoryMessages as zhMemory } from "./messages/zh-CN/memory";
import { memoryMessages as enMemory } from "./messages/en-US/memory";
import { workspaceMessages as zhWorkspace } from "./messages/zh-CN/workspace";
import { workspaceMessages as enWorkspace } from "./messages/en-US/workspace";
import { runtimeMessages as zhRuntime } from "./messages/zh-CN/runtime";
import { runtimeMessages as enRuntime } from "./messages/en-US/runtime";
import { resourcesMessages as zhResources } from "./messages/zh-CN/resources";
import { resourcesMessages as enResources } from "./messages/en-US/resources";

const catalog = decodeCatalog({ fields: [{
  path: "llm.models.*.reasoning_effort",
  surface: "models", group: "models.adapter_options",
  title: "Reasoning Effort", description: "Reasoning preference.", value_kind: "enum",
  choices: [{ value: "high", label: "High" }],
}] });

describe("settings presentation localization", () => {
  it("localizes catalog metadata after wildcard matching without changing values or the catalog", () => {
    const field = translatedField(catalog, "llm.models.my-model.reasoning_effort");
    expect(field?.title).toBe(fieldText[catalog.fields[0].path][0]);
    expect(field?.choices.map((choice) => choice.value)).toEqual(["high"]);
    expect(field?.choices[0].label).not.toBe(catalog.fields[0].choices[0].label);
    expect(field?.path).toBe(catalog.fields[0].path);
    expect(catalog.fields[0].title).toBe("Reasoning Effort");
    expect(localizeField({ ...catalog.fields[0], path: "new.owner.field" }).title).toBe("Reasoning Effort");
  });

  it("routes both Chinese and source-language searches to the same stable field", () => {
    const localized = searchConfig(catalog, fieldText[catalog.fields[0].path][0]);
    expect(localized).toHaveLength(1);
    expect(localized[0].page).toBe("llm-models");
    expect(searchConfig(catalog, "reasoning_effort")[0].id).toBe(localized[0].id);
    expect(searchConfig(catalog, "Reasoning Effort")[0].id).toBe(localized[0].id);
  });

  it("localizes stable collection identities and preserves unknown source metadata", () => {
    const collection = {
      id: "llm.models",
      surface: "models",
      root: "llm.models",
      title: "Models",
      description: "Model collection.",
      createSource: null,
      createTemplate: {},
      allowCreate: true,
      deletePolicy: "all",
    } as const;
    expect(localizeCollection(collection, "zh-CN").title).toBe(collectionText[collection.id][0]);
    const unknown = { ...collection, id: "future.models" };
    expect(localizeCollection(unknown, "zh-CN").title).toBe("Models");
    expect(localizeCollection(collection, "en-US").title).toBe("Models");
  });

  it("uses the complete document identity for action catalog metadata", () => {
    const field = {
      documentSet: "action.catalog",
      documentKind: "action",
      path: "semantic.use_when",
      surface: "action_catalog",
      group: "action.semantic",
      title: "Use when",
      description: "Source description.",
      valueKind: "string",
    } as const;
    expect(localizeDocument(field, "zh-CN").title).toBe(documentText["action.catalog:action:semantic.use_when"][0]);
    expect(localizeDocument({ ...field, documentSet: "future.catalog" }, "zh-CN").title).toBe("Use when");
  });

  it("keeps message ownership, locale keys and interpolation parameters aligned before merging", () => {
    const groups = [
      [zhCommon, enCommon], [zhSettings, enSettings], [zhHistory, enHistory],
      [zhContext, enContext], [zhTrace, enTrace], [zhPresentation, enPresentation],
      [zhChat, enChat], [zhHome, enHome], [zhMemory, enMemory],
      [zhWorkspace, enWorkspace], [zhRuntime, enRuntime], [zhResources, enResources],
      [zhProtocol, enProtocol],
    ] as const;
    const ids = new Set<string>();
    const parameters = (value: string) => [...new Set([...value.matchAll(/\{(\w+)\}/g)].map((match) => match[1]))].sort();
    for (const [zh, en] of groups) {
      expect(Object.keys(zh).sort()).toEqual(Object.keys(en).sort());
      for (const [id, value] of Object.entries(zh)) {
        expect(ids.has(id), `Message has more than one owner: ${id}`).toBe(false);
        ids.add(id);
        expect(parameters(value), id).toEqual(parameters((en as Record<string, string>)[id]));
      }
    }
  });

  it("projects known protocol codes and leaves unknown diagnostics as raw text", () => {
    expect(protocolText("presentation.invalid_config", "zh-CN")).toBe(zhProtocol["protocol.presentation.invalid_config"]);
    expect(protocolText("future.error", "en-US")).toBeUndefined();
    expect(resolveText("backend diagnostic", "zh-CN")).toBe("backend diagnostic");
    expect(tStatus("ready", "zh-CN")).toBe(zhProtocol["protocol.runtime.ready"]);
  });

  it("resolves stable feature messages in either language and preserves interpolation", () => {
    expect(t("history.locate", { query: "alpha" }, "en-US")).toBe("Locate: alpha");
    expect(resolveText(message("history.locate", { query: "alpha" }), "zh-CN")).toBe("定位：alpha");
  });
});

