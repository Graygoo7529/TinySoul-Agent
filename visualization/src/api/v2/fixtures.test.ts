/**
 * Structural smoke checks for the copied contract fixtures. These are
 * deliberately lightweight runtime checks (no JSON-schema dependency): each
 * family asserts the fields the frontend actually consumes.
 */

import { describe, expect, it } from "vitest";

import capabilities from "../../../test/fixtures/contracts/capabilities.json";
import configApply from "../../../test/fixtures/contracts/config-apply.json";
import configViews from "../../../test/fixtures/contracts/config-views.json";
import contextMessages from "../../../test/fixtures/contracts/context-messages.json";
import contextOverview from "../../../test/fixtures/contracts/context-overview.json";
import contextTracePage from "../../../test/fixtures/contracts/context-trace-page.json";
import emptyPage from "../../../test/fixtures/contracts/empty-page.json";
import homeDiffMemoryRedirect from "../../../test/fixtures/contracts/home-diff-memory-redirect.json";
import homeEffective from "../../../test/fixtures/contracts/home-effective.json";
import homeFragment from "../../../test/fixtures/contracts/home-fragment.json";
import homeFragmentEnd from "../../../test/fixtures/contracts/home-fragment-end.json";
import interactions from "../../../test/fixtures/contracts/interactions.json";
import jobDetail from "../../../test/fixtures/contracts/job-detail.json";
import jobOutput from "../../../test/fixtures/contracts/job-output.json";
import memoryDocument from "../../../test/fixtures/contracts/memory-document.json";
import memoryFragment from "../../../test/fixtures/contracts/memory-fragment.json";
import modelObservation from "../../../test/fixtures/contracts/model-observation.json";
import preset from "../../../test/fixtures/contracts/preset.json";
import questionReply from "../../../test/fixtures/contracts/question-reply.json";
import runtimeStatus from "../../../test/fixtures/contracts/runtime-status.json";
import searchEvidence from "../../../test/fixtures/contracts/search-evidence.json";
import turnFinished from "../../../test/fixtures/contracts/turn-finished.json";
import turnReceipts from "../../../test/fixtures/contracts/turn-receipts.json";
import turnWaiting from "../../../test/fixtures/contracts/turn-waiting.json";

import type { PageEnvelope } from "./common";
import type { Configuration, ConfigMutationResult, Preset } from "./config";
import type { ContextMessagesPage, ContextOverview } from "./context";
import type { ObservationEvent } from "./events";
import type { HomeContentPage, HomeDiffPage } from "./home";
import type { JobDetail, JobOutputPage } from "./job";
import type { MemoryDocumentPage } from "./memory";
import type { ResourceResolve } from "./resources";
import type { AcpDirectory, McpServersPage, RuntimeStatus } from "./runtime";
import type { SearchPage } from "./search";
import type {
  CommandReceipt,
  InteractionPage,
  TurnSnapshot,
} from "./turn";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function checkPageEnvelope(value: unknown): PageEnvelope {
  expect(isRecord(value)).toBe(true);
  const page = value as Record<string, unknown>;
  expect(Array.isArray(page.items)).toBe(true);
  if ("next_continuation" in page) {
    expect(
      page.next_continuation === null ||
        typeof page.next_continuation === "string",
    ).toBe(true);
  }
  return value as PageEnvelope;
}

function checkTurnSnapshot(value: unknown): TurnSnapshot {
  expect(isRecord(value)).toBe(true);
  const turn = value as Record<string, unknown>;
  expect(typeof turn.turn_id).toBe("string");
  expect(typeof turn.kind).toBe("string");
  expect(typeof turn.state).toBe("string");
  expect(typeof turn.cancel_requested).toBe("boolean");
  expect(Array.isArray(turn.jobs)).toBe(true);
  for (const key of ["wait_reason", "question", "budget_request", "result"]) {
    expect(key in turn).toBe(true);
  }
  return value as TurnSnapshot;
}

describe("contract fixtures: turn family", () => {
  it("turn-waiting exposes question and budget_request", () => {
    const turn = checkTurnSnapshot(turnWaiting);
    expect(turn.state).toBe("waiting");
    expect(turn.question?.question_id).toBe("action_result_1");
    expect(turn.question?.options[0]?.id).toBe("a");
    expect(turn.budget_request?.request_id).toBe("budget_1");
    expect(turn.jobs[0]?.job_id).toBe("job_1");
  });

  it("turn-finished carries a terminal result", () => {
    const turn = checkTurnSnapshot(turnFinished);
    expect(turn.state).toBe("finished");
    expect(turn.result?.status).toBe("answered");
    expect(turn.wait_reason).toBeNull();
  });

  it("turn-receipts match the command receipt shape", () => {
    const receipt = (turnReceipts as { create: unknown }).create;
    expect(isRecord(receipt)).toBe(true);
    const typed = receipt as CommandReceipt;
    expect(typed.accepted).toBe(true);
    expect(typed.turn_id).toBe("contract-turn");
  });

  it("interactions page keeps items/pending_items/queued split", () => {
    const page = checkPageEnvelope(interactions) as InteractionPage;
    expect(page.turn_id).toBe("contract-turn");
    expect(page.day).toBe("2026-09-29");
    expect(Array.isArray(page.pending_items)).toBe(true);
    expect(page.items[0]?.role).toBe("user.input");
    expect(page.items[0]?.delivery).toBe("visible");
    expect(typeof page.next_continuation).toBe("string");
  });

  it("question-reply links question and answer by question_id", () => {
    const { question, reply } = questionReply as {
      question: InteractionPage["items"][number];
      reply: InteractionPage["items"][number];
    };
    expect(question.role).toBe("agent.question");
    expect(reply.role).toBe("user.reply");
    expect(reply.question_id).toBe(question.question_id);
  });
});

describe("contract fixtures: context family", () => {
  it("context-overview lists segments with slot/shape and resolved refs", () => {
    const overview = contextOverview as ContextOverview;
    expect(overview.generation_id).toBe("generation_1");
    expect(overview.segments.length).toBeGreaterThan(0);
    for (const segment of overview.segments) {
      expect(typeof segment.id).toBe("string");
      expect(typeof segment.owner).toBe("string");
      expect(typeof segment.slot).toBe("string");
      expect(typeof segment.shape).toBe("string");
      expect(Array.isArray(segment.root_refs)).toBe(true);
    }
    expect(overview.resolved_references["memory:current"]?.link).toBe(
      "memory:current",
    );
  });

  it("context-messages uses messages[{message_index,message}], not items", () => {
    const page = contextMessages as ContextMessagesPage;
    expect(page.segment_id).toBe("inputs");
    expect(Array.isArray(page.messages)).toBe(true);
    expect(typeof page.messages[0]?.message_index).toBe("number");
    expect("items" in page).toBe(false);
  });

  it("context-trace-page is a disclosure page with kind/ref items", () => {
    const page = checkPageEnvelope(contextTracePage);
    expect(page.kind).toBe("context_trace");
    const first = page.items[0] as Record<string, unknown>;
    expect(first.kind).toBe("child");
    expect(typeof first.ref).toBe("string");
  });
});

describe("contract fixtures: resource pages", () => {
  it("home-effective is a content page with locator metadata", () => {
    const page = checkPageEnvelope(homeEffective) as HomeContentPage;
    expect(page.metadata?.locator.link).toBe("home:agent@contract");
    expect(Array.isArray(page.metadata?.direct_refs)).toBe(true);
  });

  it("home fragments carry canonical_json chunks", () => {
    for (const fixture of [homeFragment, homeFragmentEnd]) {
      const page = checkPageEnvelope(fixture);
      expect(page.content_fragment?.encoding).toBe("canonical_json");
      expect(typeof page.content_fragment?.text).toBe("string");
    }
    // First page continues, last page has no token.
    expect(typeof homeFragment.next_continuation).toBe("string");
    expect("next_continuation" in homeFragmentEnd).toBe(false);
  });

  it("memory-document metadata carries kind and resolution chain", () => {
    const page = checkPageEnvelope(memoryDocument) as MemoryDocumentPage;
    expect(page.metadata?.kind).toBe("entity");
    expect(page.metadata?.resolution_chain).toEqual(["memory:entity/project"]);
  });

  it("memory-fragment is a resource-resolve response (no dedicated example)", () => {
    const resolved = memoryFragment as ResourceResolve;
    expect(resolved.kind).toBe("memory");
    expect(resolved.locator.link).toBe("memory:current#notes");
    expect(resolved.locator.day).toBe("2026-09-29");
    expect(resolved.capabilities).toContain("read");
  });

  it("home-diff exposes baseline_diverged; memory redirect keeps chain", () => {
    const bundle = homeDiffMemoryRedirect as {
      home_diff: HomeDiffPage;
      memory_redirect: MemoryDocumentPage;
    };
    expect(bundle.home_diff.metadata?.baseline_diverged).toBe(false);
    expect(bundle.memory_redirect.metadata?.status).toBe("merged");
    expect(bundle.memory_redirect.metadata?.resolution_chain).toHaveLength(2);
    expect(bundle.memory_redirect.metadata?.direct_refs).toContain(
      "memory:entity/project",
    );
  });

  it("empty-page is a valid page with no items", () => {
    const page = checkPageEnvelope(emptyPage);
    expect(page.items).toEqual([]);
  });
});

describe("contract fixtures: search family", () => {
  it("search-evidence carries items, coverage, page and result_ref", () => {
    const page = searchEvidence as SearchPage;
    expect(page.result_ref).toBe("search-result:id-2");
    expect(page.source).toBe("refs");
    const item = page.items[0];
    expect(item?.content_coverage).toBe("full");
    expect(item?.evidence[0]?.matches[0]).toMatchObject({
      kind: "model",
      start: 0,
      end: 19,
    });
    expect(page.coverage.source_complete).toBe(true);
    expect(page.page.total).toBe(1);
    // Top-level continuation is the cursor; absent here means single page.
    expect(page.continuation).toBeUndefined();
  });
});

describe("contract fixtures: job family", () => {
  it("job-detail exposes state, pending_inputs and result_links", () => {
    const detail = jobDetail as JobDetail;
    expect(detail.job_id).toBe("job_1");
    expect(detail.state).toBe("running");
    expect(Array.isArray(detail.pending_inputs)).toBe(true);
    expect(detail.result_links.length).toBeGreaterThan(0);
    expect(detail.details?.stdout_bytes).toBe(7);
  });

  it("job-output items carry channel/text and a polling token", () => {
    const page = jobOutput as JobOutputPage;
    expect(page.items.map((item) => item.channel)).toEqual([
      "stdout",
      "stderr",
    ]);
    expect(typeof page.next_continuation).toBe("string");
    expect(typeof page.truncated).toBe("boolean");
    expect(page.result_locators.length).toBe(3);
  });
});

describe("contract fixtures: configuration family", () => {
  it("config-views provides saved and active configurations", () => {
    const views = configViews as { saved: unknown; active: unknown };
    for (const view of [views.saved, views.active]) {
      const config = view as Configuration;
      expect(["saved", "active"]).toContain(config.view);
      expect(Array.isArray(config.sources)).toBe(true);
      expect(typeof config.pending_reload).toBe("boolean");
      expect(typeof config.activity.can_reload).toBe("boolean");
      const field = config.fields["execution.enabled"];
      expect(field?.writable).toBe(true);
      expect(typeof field?.source).toBe("string");
    }
  });

  it("config-apply reports an active mutation", () => {
    const result = configApply as ConfigMutationResult;
    expect(result.state).toBe("active");
    expect(result.pending_reload).toBe(false);
    expect(result.changed_fields).toContain("execution.enabled");
  });

  it("preset carries summary fields and a snapshot", () => {
    const record = preset as Preset;
    expect(record.id).toBe("id-1");
    expect(record.included_scopes).toContain("models");
    expect(typeof record.active_match).toBe("boolean");
    expect(typeof record.saved_match).toBe("boolean");
    expect(Array.isArray(record.validation_issues)).toBe(true);
    expect(isRecord(record.snapshot)).toBe(true);
  });
});

describe("contract fixtures: runtime, capabilities and events", () => {
  it("runtime-status is protocol v2 with sources and journal", () => {
    const status = runtimeStatus as RuntimeStatus;
    expect(status.protocol_version).toBe(2);
    expect(status.ready).toBe(true);
    expect(typeof status.latest_event_sequence).toBe("number");
    expect(status.runtime.sources[0]?.source).toBe("workspace.fswatch");
    expect(status.event_journal.enabled).toBe(false);
  });

  it("capabilities holds the ACP directory and MCP server page", () => {
    const bundle = capabilities as { acp: unknown; mcp: unknown };
    const acp = bundle.acp as AcpDirectory;
    expect(Array.isArray(acp.targets)).toBe(true);
    expect(Array.isArray(acp.connections)).toBe(true);
    const mcp = bundle.mcp as McpServersPage;
    expect(Array.isArray(mcp.items)).toBe(true);
  });

  it("model-observation is an event envelope, not a page", () => {
    const event = modelObservation as ObservationEvent;
    expect(typeof event.sequence).toBe("number");
    expect(event.name).toBe("retrieval.model.invoked");
    expect(event.level).toBe("verbose");
    expect(event.payload.search_id).toBe("id-3");
  });
});
