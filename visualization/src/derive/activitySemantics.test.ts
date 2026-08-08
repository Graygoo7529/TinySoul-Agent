import { describe, expect, it } from "vitest";

import {
  actionTargetOf,
  actionVerb,
  firstLine,
  isDomainSkillLabel,
  resultSummaryOf,
  skillTitleOf,
  targetLabel,
} from "./activitySemantics";

describe("actionVerb", () => {
  it("maps well-known actions to semantic verbs", () => {
    expect(actionVerb("workspace.patch")).toBe("Editing");
    expect(actionVerb("workspace.create")).toBe("Creating");
    expect(actionVerb("execution.run_bash_command")).toBe("Running");
    expect(actionVerb("execution.run_python_script")).toBe("Running script");
    expect(actionVerb("web.search_by_kimi")).toBe("Searching");
    expect(actionVerb("web.fetch_with_trafilatura")).toBe("Fetching");
    expect(actionVerb("core.memory.memorize")).toBe("Memorizing");
    expect(actionVerb("core.memory.inspect")).toBe("Inspecting memory");
    expect(actionVerb("core.memory.recall")).toBe("Recalling");
    expect(actionVerb("core.session.inspect")).toBe("Inspecting session");
    expect(actionVerb("core.answer")).toBe("Composing answer");
  });

  it("falls back to Executing for unknown actions", () => {
    expect(actionVerb("unknown.thing")).toBe("Executing");
  });
});

describe("actionTargetOf", () => {
  it("extracts the edited file from link-like params", () => {
    expect(
      actionTargetOf("workspace.patch", { target_link: "workspace:README.md" }),
    ).toEqual({ file: "workspace:README.md" });
    expect(actionTargetOf("workspace.read", { link: "workspace:a.md" })).toEqual({
      file: "workspace:a.md",
    });
    expect(
      actionTargetOf("core.memory.recall", { memory_link: "memory:entity/tinysoul" }),
    ).toEqual({ file: "memory:entity/tinysoul" });
  });

  it("extracts shell commands", () => {
    expect(actionTargetOf("execution.run_cmd", { command: "npm test" })).toEqual({
      command: "npm test",
    });
  });

  it("extracts search queries with optional scope", () => {
    expect(actionTargetOf("web.search_by_kimi", { query: "kimi code" })).toEqual({
      query: "kimi code",
    });
    expect(
      actionTargetOf("workspace.search_text", { query: "TODO", scope: "workspace:docs" }),
    ).toEqual({ query: "TODO", subject: "workspace:docs" });
  });

  it("extracts urls and resolves the host", () => {
    expect(
      actionTargetOf("web.fetch_with_trafilatura", {
        url: "https://example.com/docs/page",
        target_link: "workspace:page.md",
      }),
    ).toEqual({ url: "https://example.com/docs/page", host: "example.com" });
    expect(
      actionTargetOf("web.discover_pages", { start_url: "https://kimi.moonshot.cn" }),
    ).toEqual({ url: "https://kimi.moonshot.cn", host: "kimi.moonshot.cn" });
  });

  it("summarizes memory memorize operations", () => {
    expect(
      actionTargetOf("core.memory.memorize", {
        expected_digest: "abc",
        operations: [{ kind: "append", text: "x" }, { kind: "replace", old_text: "a", new_text: "b" }],
      }),
    ).toEqual({ subject: "2 ops: append, replace" });
  });

  it("returns undefined when nothing is recognizable", () => {
    expect(actionTargetOf("workspace.scan", {})).toBeUndefined();
  });
});

describe("targetLabel", () => {
  it("prefers command, then query, then host, then file", () => {
    expect(targetLabel({ command: "npm run build" })).toBe("npm run build");
    expect(targetLabel({ query: "kimi" })).toBe("“kimi”");
    expect(targetLabel({ url: "https://a.com/x", host: "a.com" })).toBe("a.com");
    expect(targetLabel({ file: "workspace:a.md" })).toBe("workspace:a.md");
    expect(targetLabel(undefined)).toBeUndefined();
  });
});

describe("resultSummaryOf", () => {
  it("summarizes terminal results", () => {
    expect(
      resultSummaryOf({
        status: "success",
        stage: "executor",
        payload: { exit_code: 0, duration_seconds: 1.234, stdout: "ok" },
      }),
    ).toBe("exit 0 · 1.2s");
  });

  it("summarizes search result counts and revisions", () => {
    expect(
      resultSummaryOf({ status: "success", stage: "executor", payload: { results: [1, 2, 3] } }),
    ).toBe("3 results");
    expect(
      resultSummaryOf({
        status: "success",
        stage: "executor",
        payload: { link: "workspace:a.md", revision: 3 },
      }),
    ).toBe("rev 3");
  });

  it("returns undefined for empty payloads", () => {
    expect(resultSummaryOf({ status: "success", stage: "executor" })).toBeUndefined();
    expect(resultSummaryOf({ status: "success", stage: "executor", payload: {} })).toBeUndefined();
  });
});

describe("skillTitleOf", () => {
  it("prefers the first markdown heading inside the skill body", () => {
    expect(
      skillTitleOf("# Domain Skill\n# Workspace Editing\nSome guidance text."),
    ).toBe("Workspace Editing");
  });

  it("falls back to the first non-empty body line", () => {
    expect(skillTitleOf("# Domain Skill\n\nedit files carefully")).toBe(
      "edit files carefully",
    );
  });

  it("handles a missing body", () => {
    expect(skillTitleOf("# Domain Skill")).toBe("domain skill");
  });
});

describe("isDomainSkillLabel / firstLine", () => {
  it("recognizes mounted domain skill labels", () => {
    expect(isDomainSkillLabel("task_prompt:guide:domain_skill:1")).toBe(true);
    expect(isDomainSkillLabel("task_prompt:guide:phase2")).toBe(false);
    expect(isDomainSkillLabel(undefined)).toBe(false);
  });

  it("extracts a whitespace-collapsed first line", () => {
    expect(firstLine("\n\n  The user  wants\nmore text", 140)).toBe("The user wants");
    expect(firstLine("x".repeat(200), 10)).toHaveLength(10);
    expect(firstLine("x".repeat(200), 10)?.endsWith("…")).toBe(true);
  });
});
