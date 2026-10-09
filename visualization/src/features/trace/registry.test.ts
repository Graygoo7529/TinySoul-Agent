import { describe, expect, it } from "vitest";

import {
  ACTION_FAMILY,
  actionFamily,
  domainTextClass,
  isKnownAction,
} from "./registry";
import { FAMILY_VIEWS } from "./resultViews";

/**
 * The canonical Action Catalog at registration time
 * (tinysoul/assets/common/configs/action/catalog/* /actions/*.toml `name`).
 * This snapshot pins the coverage matrix in
 * visualization/docs/design/action-renderers.md: an added/removed backend
 * action fails here until the registry and the matrix are updated together.
 */
const CANONICAL_ACTION_IDS = [
  // core
  "core.answer",
  "core.ask",
  "core.reason",
  "core.wait",
  "core.job.status",
  "core.job.wait",
  "core.job.stop",
  "core.session.organize",
  "core.context.inspect",
  "core.context.search",
  // execution
  "execution.start",
  "execution.run_shell",
  "execution.run_script",
  "execution.stdin",
  "execution.collect",
  // expand (MCP)
  "expand.call",
  "expand.describe_servers",
  "expand.describe_tools",
  "expand.search",
  // home
  "home.search",
  "home.inspect",
  "home.diff",
  "home.review",
  "home.top.write",
  "home.top.patch",
  "home.top.delete",
  "home.resource.write",
  "home.resource.patch",
  "home.resource.delete",
  "home.prompt_mount.write",
  "home.prompt_mount.patch",
  // memory
  "memory.search",
  "memory.inspect",
  "memory.memorize",
  "memory.write",
  "memory.write_daily",
  // subagent (ACP)
  "subagent.agents",
  "subagent.connect",
  "subagent.delegate",
  "subagent.respond",
  "subagent.collect",
  "subagent.disconnect",
  // web
  "web.search_by_kimi",
  "web.fetch_with_trafilatura",
  "web.fetch_with_defuddle",
  "web.discover_pages",
  // workspace
  "workspace.search",
  "workspace.read",
  "workspace.list",
  "workspace.trash_list",
  "workspace.analyze",
  "workspace.describe",
  "workspace.compose",
  "workspace.convert_with_pypdf",
  "workspace.convert_with_markitdown",
  "workspace.write",
  "workspace.append",
  "workspace.edit",
  "workspace.inspect",
  "workspace.mkdir",
  "workspace.move",
  "workspace.delete",
  "workspace.tag",
  "workspace.restore",
];

describe("ACTION_FAMILY registration", () => {
  it("covers exactly the canonical catalog — no missing, no stale entries", () => {
    expect(Object.keys(ACTION_FAMILY).sort()).toEqual(
      [...CANONICAL_ACTION_IDS].sort(),
    );
    expect(CANONICAL_ACTION_IDS).toHaveLength(64);
  });

  it("maps every canonical ID to a family with a real view", () => {
    for (const id of CANONICAL_ACTION_IDS) {
      const family = actionFamily(id);
      expect(family, id).not.toBe("generic");
      expect(FAMILY_VIEWS[family], id).toBeTypeOf("function");
      expect(isKnownAction(id)).toBe(true);
    }
  });

  it("keeps the plan-mandated family assignments", () => {
    // §9.1 explicit checks: web fetch/search stay distinct from internal
    // Search; analysis/compose/convert are the analysis family; job control
    // is its own family; organize is not an edit; reflection writes are
    // reflection-write.
    expect(actionFamily("web.search_by_kimi")).toBe("web");
    expect(actionFamily("web.fetch_with_trafilatura")).toBe("web");
    expect(actionFamily("web.discover_pages")).toBe("web");
    expect(actionFamily("workspace.search")).toBe("search");
    expect(actionFamily("core.context.search")).toBe("search");
    expect(actionFamily("workspace.analyze")).toBe("analysis");
    expect(actionFamily("workspace.compose")).toBe("analysis");
    expect(actionFamily("workspace.convert_with_pypdf")).toBe("analysis");
    expect(actionFamily("core.wait")).toBe("job-control");
    expect(actionFamily("core.job.stop")).toBe("job-control");
    expect(actionFamily("core.session.organize")).toBe("session-organize");
    expect(actionFamily("home.diff")).toBe("reflection-write");
    expect(actionFamily("home.review")).toBe("reflection-write");
    expect(actionFamily("memory.write")).toBe("reflection-write");
    expect(actionFamily("memory.write_daily")).toBe("reflection-write");
    expect(actionFamily("memory.memorize")).toBe("write");
    expect(actionFamily("expand.search")).toBe("mcp");
    expect(actionFamily("subagent.delegate")).toBe("acp");
  });

  it("routes unknown actions to the generic structured view", () => {
    expect(actionFamily("core.plan")).toBe("generic");
    expect(actionFamily("future.new_action")).toBe("generic");
    expect(isKnownAction("core.plan")).toBe(false);
    expect(FAMILY_VIEWS.generic).toBeTypeOf("function");
  });
});

describe("domainTextClass", () => {
  it("uses the existing domain tokens; unlisted domains fall back", () => {
    expect(domainTextClass("core")).toBe("text-domain-core");
    expect(domainTextClass("workspace")).toBe("text-domain-workspace");
    expect(domainTextClass("memory")).toBe("text-domain-memory");
    // subagent/expand have no token in the stylesheet; they reuse maintenance.
    expect(domainTextClass("subagent")).toBe("text-domain-maintenance");
    expect(domainTextClass("expand")).toBe("text-domain-maintenance");
    expect(domainTextClass("unknown")).toBe("text-fg-muted");
  });
});
