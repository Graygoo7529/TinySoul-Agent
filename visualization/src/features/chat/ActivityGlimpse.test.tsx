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
  act(() => root.render(glimpseBody(result({ actionId: "execution.run", payload: { exit_code: 0, stdout: "one\ntwo\nthree\nfour\n" } }))));
  expect(host.textContent).toContain("three\nfour");
  expect(host.textContent).not.toContain("one\ntwo");
  act(() => host.querySelector("button")!.click());
  expect(host.textContent).toContain("one\ntwo\nthree\nfour");
});

it("shows actual search previews and bounds the live inset to three hits", () => {
  act(() => root.render(glimpseBody(result({ actionId: "home.search", payload: {
    items: [1, 2, 3, 4].map((i) => ({ ...searchExample.items[0], ref: `home:top/skills/${i}`, title: `Skill ${i}` })),
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

it("keeps the result preview grounded in the returned write facts", () => {
  act(() => root.render(glimpseBody(result({
    actionId: "workspace.edit",
    params: { edits: [{ old_text: "old", new_text: "new" }] },
    payload: { changed: true, written: 42, ref: "workspace:notes.md", summary: "Saved" },
  }))));
  expect(host.textContent).toContain("changed");
  expect(host.textContent).toContain("42 written");
  expect(host.textContent).toContain("workspace:notes.md");
  expect(host.textContent).not.toContain("+ new");
});

it("labels Memory character counts and Home resource sizes with their actual units", () => {
  act(() => root.render(glimpseBody(result({
    actionId: "memory.memorize",
    payload: { ref: "memory:current", changed: true, chars: 126 },
  }))));
  expect(host.textContent).toContain("126 chars");
  expect(host.textContent).not.toContain("126 bytes");

  act(() => root.render(glimpseBody(result({
    actionId: "home.resource.write",
    payload: { ref: "home:resource/agent/resources/guide.md", size: 240 },
  }))));
  expect(host.textContent).toContain("240 chars");
  expect(host.textContent).not.toContain("240 bytes");
});

it("summarizes analysis reports and descriptions from their actual fields", () => {
  act(() => root.render(glimpseBody(result({
    actionId: "workspace.analyze",
    payload: { answer: "# 容量恢复分析\n\n先检查 Context，再决定是否重建。\n\n## 细节" },
  }))));
  expect(host.textContent).toMatch(/分析报告 · \d+ 字符/);
  expect(host.textContent).toContain("容量恢复分析");
  expect(host.textContent).toContain("先检查 Context，再决定是否重建。");
  expect(host.textContent).not.toContain("# 容量恢复分析");

  act(() => root.render(glimpseBody(result({
    actionId: "workspace.describe",
    payload: { description: "记录 Context 段组合与容量恢复边界。" },
  }))));
  expect(host.textContent).toMatch(/资源描述 · \d+ 字符/);
  expect(host.textContent).toContain("记录 Context 段组合与容量恢复边界。");

  act(() => root.render(glimpseBody(result({
    actionId: "workspace.compose",
    payload: { summary: "已有文件摘要", description: "不能被当成生成正文的元数据" },
  }))));
  expect(host.textContent).toContain("已有文件摘要");
  expect(host.textContent).not.toContain("不能被当成生成正文的元数据");
  expect(host.textContent).not.toContain("资源描述");
});

it("uses the first content line when an analysis report has no heading", () => {
  act(() => root.render(glimpseBody(result({
    actionId: "workspace.analyze",
    payload: { answer: "\n- 第一条结论\n- 第二条结论" },
  }))));
  expect(host.textContent).toContain("第一条结论");
  expect(host.textContent).not.toContain("- 第一条结论");
});

it("keeps web gists focused on primary content and adds only discovery states", () => {
  act(() => root.render(glimpseBody(result({
    actionId: "web.search_by_kimi",
    payload: {
      answer: "不应重复插入 gist 的搜索回答",
      result_count: 2,
      results: [
        { title: "Context design", url: "https://example.com/context", snippet: "Context slots and recovery" },
        { title: "Disclosure", url: "https://example.com/disclosure", snippet: "Bounded pages" },
      ],
    },
  }))));
  expect(host.textContent).toContain("Context design");
  expect(host.textContent).toContain("Context slots and recovery");
  expect(host.textContent).not.toContain("不应重复插入 gist 的搜索回答");
  expect(host.textContent).not.toContain("2 个来源");

  act(() => root.render(glimpseBody(result({
    actionId: "web.fetch_with_defuddle",
    payload: { title: "Recovery guide", excerpt: "Bounded content is reclaimed.", content_chars: 18420, extractor: "defuddle" },
  }))));
  expect(host.textContent).toContain("Recovery guide");
  expect(host.textContent).toContain("Bounded content is reclaimed.");
  expect(host.textContent).not.toContain("18,420");
  expect(host.textContent).not.toContain("defuddle");

  act(() => root.render(glimpseBody(result({
    actionId: "web.discover_pages",
    payload: {
      page_count: 4, visited_count: 2, failed_count: 1, candidate_count: 1,
      pages: [
        { title: "Getting started", state: "visited", url: "https://example.com/start" },
        { title: "Advanced setup", state: "failed", failure_reason: "request timeout", url: "https://example.com/advanced" },
        { anchor_text: "API reference", state: "candidate", url: "https://example.com/api" },
        { title: "第四页不进入有界 gist", state: "candidate", url: "https://example.com/fourth" },
      ],
    },
  }))));
  expect(host.textContent).toContain("已访问");
  expect(host.textContent).toContain("失败");
  expect(host.textContent).toContain("候选");
  expect(host.textContent).toContain("request timeout");
  expect(host.textContent).toContain("API reference");
  expect(host.textContent).not.toContain("4 页");
  expect(host.textContent).not.toContain("2 已访问");
  expect(host.textContent).not.toContain("第四页不进入有界 gist");
});
