// @vitest-environment jsdom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import type { JsonValue } from "../../../api/v2/types";
import { NetworkPolicyEditor } from "./NetworkPolicyEditor";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

describe("network policy editing", () => {
  it("replaces an override atomically when switching to direct or inherit", async () => {
    function Harness() {
      const [value, setValue] = useState<Record<string, JsonValue>>({
        mode: "override", http_proxy: "http://proxy:8000", no_proxy: "localhost",
      });
      return <><NetworkPolicyEditor value={value} parentLabel="系统默认" onChange={setValue} />
        <output data-testid="policy">{JSON.stringify(value)}</output></>;
    }
    const container = document.createElement("div");
    const root = createRoot(container);
    try {
      await act(async () => root.render(<Harness />));
      const select = container.querySelector("select")!;
      await act(async () => {
        select.value = "direct";
        select.dispatchEvent(new Event("change", { bubbles: true }));
      });
      expect(container.querySelector("output")!.textContent).toBe('{"mode":"direct"}');
      expect(container.querySelector("input")).toBeNull();
      await act(async () => {
        select.value = "inherit";
        select.dispatchEvent(new Event("change", { bubbles: true }));
      });
      expect(container.querySelector("output")!.textContent).toBe('{"mode":"inherit"}');
      expect(container.textContent).toContain("继承：系统默认");
    } finally {
      await act(async () => root.unmount());
    }
  });
});
