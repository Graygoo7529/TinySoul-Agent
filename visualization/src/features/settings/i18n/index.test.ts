import { describe, expect, it } from "vitest";
import { decodeCatalog } from "../draft/catalog";
import { searchConfig } from "../pages";
import { localizeField, translatedField } from ".";

const catalog = decodeCatalog({ fields: [{
  path: "llm.models.*.adapter_options.reasoning_effort",
  surface: "models", group: "models.adapter_options",
  title: "Reasoning Effort", description: "Reasoning preference.", value_kind: "enum",
  choices: [{ value: "high", label: "High" }],
}] });

describe("settings presentation localization", () => {
  it("localizes catalog metadata after wildcard matching without changing values or the catalog", () => {
    const field = translatedField(catalog, "llm.models.my-model.adapter_options.reasoning_effort");
    expect(field?.title).toBe("推理强度");
    expect(field?.choices).toEqual([{ value: "high", label: "高" }]);
    expect(field?.path).toBe(catalog.fields[0].path);
    expect(catalog.fields[0].title).toBe("Reasoning Effort");
    expect(localizeField({ ...catalog.fields[0], path: "new.owner.field" }).title).toBe("Reasoning Effort");
  });

  it("routes both Chinese and source-language searches to the same stable field", () => {
    const localized = searchConfig(catalog, "推理强度");
    expect(localized).toHaveLength(1);
    expect(localized[0].page).toBe("llm-models");
    expect(searchConfig(catalog, "reasoning_effort")[0].id).toBe(localized[0].id);
    expect(searchConfig(catalog, "Reasoning Effort")[0].id).toBe(localized[0].id);
  });
});
