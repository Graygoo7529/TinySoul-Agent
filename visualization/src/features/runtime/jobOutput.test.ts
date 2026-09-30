// @vitest-environment node
import { describe, expect, it } from "vitest";

import type { JobOutputPage } from "../../api/v2/types";
import {
  channelTexts,
  INITIAL_JOB_OUTPUT,
  JobOutputReader,
  type JobOutputState,
} from "./jobOutput";

function page(
  overrides: Partial<JobOutputPage> = {},
): JobOutputPage {
  return {
    job_id: "job_1",
    items: [],
    next_continuation: "c1",
    truncated: false,
    result_locators: [],
    ...overrides,
  };
}

function makeReader(pages: JobOutputPage[]) {
  const calls: (string | undefined)[] = [];
  const states: JobOutputState[] = [];
  const queue = [...pages];
  const reader = new JobOutputReader(
    async (continuation) => {
      calls.push(continuation);
      const next = queue.shift();
      if (next === undefined) throw new Error("no page queued");
      return next;
    },
    (state) => states.push(state),
  );
  return { calls, states, reader };
}

describe("JobOutputReader", () => {
  it("keeps the polling position of a running job's empty page", async () => {
    const { calls, reader } = makeReader([
      page({ next_continuation: "c2" }),
      page({ items: [{ channel: "stdout", text: "late\n" }], next_continuation: "c3" }),
    ]);
    expect(await reader.poll(false)).toBe("idle");
    expect(reader.snapshot.items).toEqual([]);
    expect(reader.snapshot.exhausted).toBe(false);
    // The token is kept: the next tick continues from it and still delivers.
    expect(await reader.poll(false)).toBe("progress");
    expect(calls).toEqual([undefined, "c2"]);
    expect(reader.snapshot.items).toEqual([
      { channel: "stdout", text: "late\n" },
    ]);
    expect(reader.snapshot.exhausted).toBe(false);
  });

  it("drains a terminal job's remaining output before reporting exhausted", async () => {
    const { reader } = makeReader([
      page({
        items: [{ channel: "stdout", text: "tail\n" }],
        next_continuation: "c2",
        truncated: true,
      }),
      page({
        items: [{ channel: "stdout", text: "end\n" }],
        next_continuation: "c3",
      }),
      page({ next_continuation: "c3" }),
    ]);
    // First tick: truncated page chains within the tick, so progress is made
    // and exhaustion is not claimed yet.
    expect(await reader.poll(true)).toBe("progress");
    expect(reader.snapshot.exhausted).toBe(false);
    // Second tick makes no progress: terminal + drained ⇒ exhausted.
    expect(await reader.poll(true)).toBe("idle");
    expect(reader.snapshot.exhausted).toBe(true);
    expect(channelTexts(reader.snapshot.items)).toEqual([
      ["stdout", "tail\nend\n"],
    ]);
  });

  it("stalls on a truncated page that makes no progress and surfaces locators", async () => {
    const locators = [{ link: "workspace:jobs/job_1/logs/stdout.log" }];
    const { reader } = makeReader([
      page({ next_continuation: "c1", truncated: true, result_locators: locators }),
    ]);
    expect(await reader.poll(false)).toBe("stalled");
    expect(reader.snapshot.stalled).toBe(true);
    expect(reader.snapshot.locators).toEqual(locators);
    // Stalled is not exhausted: the read limit says nothing about the job.
    expect(reader.snapshot.exhausted).toBe(false);
  });

  it("caps the pages one tick chains even while truncated pages deliver", async () => {
    const pages = Array.from({ length: 20 }, (_, index) =>
      page({
        items: [{ channel: "stdout", text: `p${index}\n` }],
        next_continuation: `c${index + 1}`,
        truncated: true,
      }),
    );
    const { calls, reader } = makeReader(pages);
    expect(await reader.poll(false)).toBe("progress");
    expect(calls.length).toBeLessThanOrEqual(8);
    expect(reader.snapshot.truncated).toBe(true);
  });

  it("records a bounded read error and rethrows", async () => {
    const reader = new JobOutputReader(
      async () => {
        throw new Error("connection lost");
      },
      () => {},
    );
    await expect(reader.poll(false)).rejects.toThrow("connection lost");
    expect(reader.snapshot.error).toBe("connection lost");
    expect(reader.snapshot.reading).toBe(false);
  });

  it("concatenates channels separately without inventing a cross-stream order", () => {
    const items = [
      { channel: "stdout", text: "a" },
      { channel: "stderr", text: "x" },
      { channel: "stdout", text: "b" },
    ];
    expect(channelTexts(items)).toEqual([
      ["stdout", "ab"],
      ["stderr", "x"],
    ]);
  });

  it("starts from a clean initial state", () => {
    expect(INITIAL_JOB_OUTPUT).toEqual({
      items: [],
      locators: [],
      reading: false,
      truncated: false,
      stalled: false,
      exhausted: false,
      error: null,
    });
  });
});
