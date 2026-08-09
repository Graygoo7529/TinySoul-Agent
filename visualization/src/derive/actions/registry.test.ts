import { describe, expect, it } from "vitest";

import type { ActionResultView } from "../model";
import { defaultTargetOf } from "./common";
import { actionVerb, descriptorFor, resultSummaryFor } from "./registry";

function result(
  status: string,
  payload?: Record<string, unknown>,
): ActionResultView {
  return { status, stage: "execute", payload };
}

describe("descriptorFor", () => {
  it("resolves verbs and families for known actions", () => {
    expect(descriptorFor("workspace.patch")).toMatchObject({
      verb: "Editing",
      family: "patch",
    });
    expect(descriptorFor("workspace.create").family).toBe("generate");
    expect(descriptorFor("execution.patch_script").family).toBe("patch");
    expect(descriptorFor("execution.create_script").family).toBe("generate");
    expect(descriptorFor("execution.promote_script").family).toBe("generate");
    expect(descriptorFor("execution.run_cmd").family).toBe("command");
    expect(descriptorFor("execution.run_bash_command").family).toBe("command");
    expect(descriptorFor("execution.run_powershell").family).toBe("command");
    expect(descriptorFor("execution.run_python_script").family).toBe("process");
    expect(descriptorFor("execution.wait").family).toBe("process");
    expect(descriptorFor("execution.apply").family).toBe("process");
    expect(descriptorFor("web.search_by_kimi").family).toBe("search");
    expect(descriptorFor("workspace.search_text").family).toBe("search");
    expect(descriptorFor("home.top.search").family).toBe("search");
    expect(descriptorFor("core.memory.inspect").family).toBe("search");
    expect(descriptorFor("web.fetch_with_defuddle").family).toBe("fetch");
    expect(descriptorFor("web.discover_pages").family).toBe("fetch");
    expect(descriptorFor("core.memory.recall").family).toBe("memory-read");
    expect(descriptorFor("core.memory.memorize").family).toBe("memory-write");
    expect(descriptorFor("workspace.read").family).toBe("read");
    expect(descriptorFor("home.resource.read").family).toBe("read");
    expect(descriptorFor("core.answer").family).toBe("answer");
    expect(descriptorFor("core.reason").family).toBe("reason");
    expect(descriptorFor("core.context.inspect").family).toBe("inspect");
    expect(descriptorFor("core.session.inspect").family).toBe("inspect");
    expect(descriptorFor("workspace.scan").family).toBe("scan");
    expect(descriptorFor("workspace.trash.list").family).toBe("scan");
    expect(descriptorFor("workspace.delete").family).toBe("delete");
    expect(descriptorFor("workspace.restore").family).toBe("delete");
    expect(descriptorFor("home.top.patch").family).toBe("patch");
    expect(descriptorFor("home.prompt_mount.patch").family).toBe("patch");
  });

  it("falls back to a generic descriptor for unknown actions", () => {
    const descriptor = descriptorFor("unknown.thing");
    expect(descriptor.verb).toBe("Executing");
    expect(descriptor.family).toBe("generic");
    expect(actionVerb("unknown.thing")).toBe("Executing");
    expect(descriptor.summarizeCall({}).headline).toBe("执行");
  });
});

describe("summarizeCall", () => {
  it("builds Chinese verb-phrase headlines with targets", () => {
    expect(
      descriptorFor("workspace.patch").summarizeCall({ target_link: "workspace:report/draft.md" }),
    ).toEqual({
      headline: "编辑 workspace:report/draft.md",
      target: { file: "workspace:report/draft.md" },
      chips: undefined,
    });
    expect(
      descriptorFor("core.memory.recall").summarizeCall({ memory_link: "memory:fact/f-1" })
        .headline,
    ).toBe("召回 memory:fact/f-1");
    expect(descriptorFor("core.memory.memorize").summarizeCall({}).headline).toBe(
      "更新活动记忆",
    );
  });

  it("puts short facts into chips", () => {
    expect(
      descriptorFor("workspace.read").summarizeCall({
        link: "workspace:a.md",
        start_line: 120,
        end_line: 180,
      }).chips,
    ).toEqual(["120-180 行"]);
    expect(
      descriptorFor("execution.run_bash_command").summarizeCall({ command: "ls" }).chips,
    ).toEqual(["bash"]);
    expect(
      descriptorFor("execution.run_powershell").summarizeCall({ command: "dir" }).chips,
    ).toEqual(["powershell"]);
    expect(
      descriptorFor("core.memory.memorize").summarizeCall({
        operations: [{ kind: "append" }, { kind: "remove" }],
      }).chips,
    ).toEqual(["2 项操作"]);
  });

  it("quotes search queries and resolves fetch hosts", () => {
    expect(
      descriptorFor("web.search_by_kimi").summarizeCall({ query: "Vite 代理" }).headline,
    ).toBe("检索 “Vite 代理”");
    const fetchCall = descriptorFor("web.fetch_with_defuddle").summarizeCall({
      url: "https://example.com/docs/page",
      target_link: "workspace:page.md",
    });
    expect(fetchCall.headline).toBe("访问 example.com");
    expect(fetchCall.target).toEqual({
      url: "https://example.com/docs/page",
      host: "example.com",
    });
  });
});

describe("defaultTargetOf (default extraction order)", () => {
  it("extracts the edited file from link-like params", () => {
    expect(defaultTargetOf("workspace.patch", { target_link: "workspace:README.md" })).toEqual({
      file: "workspace:README.md",
    });
    expect(defaultTargetOf("workspace.read", { link: "workspace:a.md" })).toEqual({
      file: "workspace:a.md",
    });
    expect(defaultTargetOf("core.memory.recall", { memory_link: "memory:entity/tinysoul" })).toEqual(
      { file: "memory:entity/tinysoul" },
    );
  });

  it("extracts shell commands", () => {
    expect(defaultTargetOf("execution.run_cmd", { command: "npm test" })).toEqual({
      command: "npm test",
    });
  });

  it("extracts search queries with optional scope", () => {
    expect(defaultTargetOf("web.search_by_kimi", { query: "kimi code" })).toEqual({
      query: "kimi code",
    });
    expect(
      defaultTargetOf("workspace.search_text", { query: "TODO", scope: "workspace:docs" }),
    ).toEqual({ query: "TODO", subject: "workspace:docs" });
  });

  it("extracts urls and resolves the host", () => {
    expect(
      defaultTargetOf("web.fetch_with_trafilatura", {
        url: "https://example.com/docs/page",
        target_link: "workspace:page.md",
      }),
    ).toEqual({ url: "https://example.com/docs/page", host: "example.com" });
    expect(defaultTargetOf("web.discover_pages", { start_url: "https://kimi.moonshot.cn" })).toEqual(
      { url: "https://kimi.moonshot.cn", host: "kimi.moonshot.cn" },
    );
  });

  it("summarizes memory memorize operations", () => {
    expect(
      defaultTargetOf("core.memory.memorize", {
        expected_digest: "abc",
        operations: [{ kind: "append", text: "x" }, { kind: "replace", old_text: "a", new_text: "b" }],
      }),
    ).toEqual({ subject: "2 ops: append, replace" });
  });

  it("returns undefined when nothing is recognizable", () => {
    expect(defaultTargetOf("workspace.scan", {})).toBeUndefined();
  });
});

describe("summarizeResult", () => {
  it("summarizes terminal results with exit code and elapsed time", () => {
    expect(
      resultSummaryFor(
        "execution.run_bash_command",
        result("success", { exit_code: 0, elapsed_seconds: 4.23 }),
      ),
    ).toEqual({ headline: "exit 0 · 4.2s", tone: "success", chips: undefined });
  });

  it("summarizes web search counts with the first title as chip", () => {
    expect(
      resultSummaryFor(
        "web.search_by_kimi",
        result("success", {
          result_count: 5,
          results: [{ title: "Kimi Code docs", url: "https://a.com" }],
        }),
      ),
    ).toEqual({ headline: "5 条结果", tone: "success", chips: ["Kimi Code docs"] });
  });

  it("summarizes read line counts and workspace scan counts", () => {
    expect(
      resultSummaryFor("workspace.read", result("success", { actual: { start: 1, end: 61 }, truncated: true })),
    ).toEqual({ headline: "61 行", tone: "success", chips: ["截断"] });
    expect(resultSummaryFor("workspace.scan", result("success", { count: 12 })).headline).toBe(
      "12 个资源",
    );
  });

  it("keeps the default summary for revisions and links", () => {
    expect(
      resultSummaryFor("workspace.patch", result("success", { link: "workspace:a.md", revision: 3 })),
    ).toEqual({ headline: "rev 3", tone: "success", chips: undefined });
    expect(
      resultSummaryFor("workspace.create", result("success", { link: "workspace:a.md" })).headline,
    ).toBe("workspace:a.md");
  });

  it("maps tone from status and mutes empty payloads", () => {
    expect(resultSummaryFor("workspace.patch", result("failed", { link: "x" })).tone).toBe(
      "danger",
    );
    expect(resultSummaryFor("workspace.patch", result("timeout", { link: "x" })).tone).toBe(
      "warning",
    );
    expect(resultSummaryFor("workspace.patch", result("success")).tone).toBe("muted");
    expect(resultSummaryFor("workspace.patch", result("success", {})).tone).toBe("muted");
  });
});
