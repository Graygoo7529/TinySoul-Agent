import { describe, expect, it } from "vitest";

import type { ContextOverview, SegmentView } from "../../api/v2/types";
import overviewFixture from "../../../test/fixtures/contracts/context-overview.json";
import {
  canInspect,
  canQuery,
  classifyRef,
  groupBySlot,
  partitionHeapRefs,
  segmentStatusLine,
  shapeLabel,
  slotLabel,
  usageLine,
} from "./segments";

const overview = overviewFixture as ContextOverview;

function segment(id: string): SegmentView {
  const found = overview.segments.find((entry) => entry.id === id);
  if (found === undefined) throw new Error(`fixture segment ${id} missing`);
  return found;
}

describe("groupBySlot", () => {
  it("groups the fixture segments into Background/Trace/Working in order", () => {
    const groups = groupBySlot(overview.segments);
    expect(groups.map((group) => group.slot)).toEqual([
      "background",
      "trace",
      "working",
    ]);
    expect(groups.map((group) => group.label)).toEqual([
      "Background",
      "Trace",
      "Working",
    ]);
    expect(groups[0]!.segments.map((entry) => entry.id)).toEqual([
      "identity",
      "session",
      "inputs",
      "journal",
      "home",
      "memory",
    ]);
    expect(groups[1]!.segments.map((entry) => entry.id)).toEqual(["trace"]);
    expect(groups[2]!.segments.map((entry) => entry.id)).toEqual([
      "plan",
      "workspace",
      "jobs",
      "connections",
    ]);
  });

  it("keeps unknown slots after the known three, labeled by the raw slot", () => {
    const custom: SegmentView = {
      ...segment("plan"),
      id: "custom",
      slot: "taskprompt",
    };
    const groups = groupBySlot([...overview.segments, custom]);
    expect(groups[groups.length - 1]).toMatchObject({
      slot: "taskprompt",
      label: "taskprompt",
    });
  });
});

describe("partitionHeapRefs", () => {
  it("splits installed from available without duplication", () => {
    const partition = partitionHeapRefs(segment("home"));
    expect(partition.installed).toHaveLength(7);
    expect(partition.available).toEqual([
      "home:agent@contract",
      "home:agent@long-contract",
      "home:skills@tinysoul-docs",
    ]);
    expect(partition.protectedRefs).toHaveLength(7);
  });
});

describe("classifyRef", () => {
  it("routes by owner prefix", () => {
    expect(classifyRef("home:agent@AGENT")).toBe("home");
    expect(classifyRef("memory:current")).toBe("memory");
    expect(classifyRef("session:map")).toBe("session");
    expect(classifyRef("turn:trace@contract-turn")).toBe("trace");
    expect(classifyRef("workspace:job.py")).toBe("workspace");
    expect(classifyRef("https://example.com")).toBe("web");
    expect(classifyRef("something-else")).toBe("other");
  });
});

describe("capabilities", () => {
  it("reads inspect/query from the descriptor, not the name", () => {
    expect(canInspect(segment("trace"))).toBe(true);
    expect(canQuery(segment("trace"))).toBe(true);
    expect(canInspect(segment("session"))).toBe(true);
    // The heap segments declare select/reclaim only: no inspect route.
    expect(canInspect(segment("home"))).toBe(false);
    expect(canQuery(segment("home"))).toBe(false);
    expect(canInspect(segment("identity"))).toBe(false);
  });
});

describe("usageLine", () => {
  it("reports characters, never tokens", () => {
    expect(usageLine(segment("home"))).toBe("11,317 chars");
    expect(usageLine(segment("identity"))).toBe("17 chars");
  });

  it("adds image bytes when present", () => {
    expect(usageLine({ ...segment("identity"), image_bytes: 2048 })).toBe(
      "17 chars · 2.0 KB of images",
    );
  });
});

describe("segmentStatusLine", () => {
  it("summarizes heap segments by installed/available counts", () => {
    expect(segmentStatusLine(segment("home"))).toBe("7 installed · 3 available");
  });

  it("summarizes stack/map segments by root refs", () => {
    expect(segmentStatusLine(segment("trace"))).toBe("1 root ref");
    expect(segmentStatusLine(segment("session"))).toBe("1 root ref");
  });

  it("marks segments without content as empty", () => {
    expect(segmentStatusLine(segment("journal"))).toBe("empty");
    expect(segmentStatusLine(segment("inputs"))).toBeNull();
  });
});

describe("labels", () => {
  it("labels known slots and shapes, passing unknown values through", () => {
    expect(slotLabel("background")).toBe("Background");
    expect(slotLabel("elsewhere")).toBe("elsewhere");
    expect(shapeLabel("state")).toBe("State");
    expect(shapeLabel("heap")).toBe("Heap");
    expect(shapeLabel("stack")).toBe("Stack");
    expect(shapeLabel("map")).toBe("Map");
    expect(shapeLabel("future")).toBe("future");
  });
});
