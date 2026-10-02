// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { glimpseBody } from "./ActivityGlimpse";
import type { ActionGlimpseData } from "./presentation";
import searchExample from "../../../test/fixtures/contracts/search-evidence.json";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.append(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); });
const result = (patch: Partial<ActionGlimpseData>): ActionGlimpseData => ({ actionId: "workspace.read", domain: "workspace", stage: "result", result: { status: "success" }, ...patch });

it("keeps terminal output compact and reveals the earlier lines on request", () => {
  act(() => root.render(glimpseBody(result({ actionId: "execution.run_shell", payload: { exit_code: 0, stdout: "one\ntwo\nthree\nfour\n" } }))));
  expect(host.textContent).toContain("three\nfour");
  expect(host.textContent).not.toContain("one\ntwo");
  act(() => host.querySelector("button")!.click());
  expect(host.textContent).toContain("one\ntwo\nthree\nfour");
});

it("shows actual search previews and bounds the live inset to three hits", () => {
  act(() => root.render(glimpseBody(result({ actionId: "home.search", payload: {
    items: [1, 2, 3, 4].map((i) => ({ ...searchExample.items[0], ref: `home:skills@${i}`, title: `Skill ${i}` })),
  } }))));
  expect(host.textContent).toContain("Workspace guidance");
  expect(host.textContent).toContain("Skill 3");
  expect(host.textContent).not.toContain("Skill 4");
});

it("adapts ordered v2 edits to the original diff rows and retains failure feedback", () => {
  act(() => root.render(glimpseBody(result({ actionId: "workspace.edit", stage: "plan", params: { edits: [{ old_text: "old", new_text: "new" }] } }))));
  expect(host.textContent).toContain("− old");
  expect(host.textContent).toContain("+ new");
  act(() => root.render(glimpseBody(result({ result: { status: "failure" }, failure: { feedback: "Resource missing" } }))));
  expect(host.textContent).toBe("Resource missing");
  expect(glimpseBody(result({ actionId: "core.answer", payload: { text: "Already shown in chat" } }))).toBeNull();
});
