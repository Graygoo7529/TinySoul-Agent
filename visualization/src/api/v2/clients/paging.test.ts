import { describe, expect, it } from "vitest";

import type { PageEnvelope } from "../common";
import type { JsonValue } from "../json";
import { drainPages } from "./paging";

function chunk(text: string, size: number): string[] {
  const parts: string[] = [];
  for (let i = 0; i < text.length; i += size) parts.push(text.slice(i, i + size));
  return parts;
}

describe("drainPages", () => {
  const longItem = { ref: "home:top/agent/x#1", text: "长正文 emoji 🎉".repeat(20) };
  const serialized = JSON.stringify(longItem);
  const [c1, ...restChunks] = chunk(serialized, 40);
  const c2 = restChunks.join("");

  it("follows tokens to the end and assembles fragments in page order", async () => {
    const pages: PageEnvelope[] = [
      {
        items: [{ ref: "a" }],
        content_fragment: { encoding: "canonical_json", text: c1 },
        next_continuation: "t1",
      },
      // Empty items do not end the sequence; the fragment completes here.
      { items: [], content_fragment: { encoding: "canonical_json", text: c2 }, next_continuation: "t2" },
      { items: [{ ref: "b" }] },
    ];
    const requested: (string | null)[] = [];
    const result = await drainPages(async (continuation) => {
      requested.push(continuation);
      const page = pages[continuation === null ? 0 : continuation === "t1" ? 1 : 2];
      if (!page) throw new Error("unexpected token");
      return page;
    });
    expect(requested).toEqual([null, "t1", "t2"]);
    expect(result.incomplete).toBe(false);
    expect(result.pages).toHaveLength(3);
    // The decoded fragment item lands right after its own page's items.
    expect(result.items).toEqual([{ ref: "a" }, longItem, { ref: "b" }]);
  });

  it("delivers a fragment item that completes on the final token-less page", async () => {
    const result = await drainPages(async (continuation) =>
      continuation === null
        ? {
            items: [],
            content_fragment: { encoding: "canonical_json", text: c1 },
            next_continuation: "t1",
          }
        : { items: [], content_fragment: { encoding: "canonical_json", text: c2 } },
    );
    expect(result.items).toEqual([longItem]);
    expect(result.incomplete).toBe(false);
  });

  it("stops at maxPages and marks the result incomplete", async () => {
    const result = await drainPages(
      async () => ({ items: [{ ref: "x" }], next_continuation: "next" }),
      { maxPages: 2 },
    );
    expect(result.pages).toHaveLength(2);
    expect(result.items).toHaveLength(2);
    expect(result.incomplete).toBe(true);
  });

  it("reads the messages collection and next_before tokens of other families", async () => {
    const messages = drainPages(
      async (continuation) => ({
        turn_id: "t",
        segment_id: "inputs",
        messages:
          continuation === null
            ? [{ message_index: 0 }]
            : [{ message_index: 1 }],
        next_continuation: continuation === null ? "m1" : null,
      }),
      {
        itemsOf: (page) => page.messages,
        decodeItem: (value) => value as { message_index: number },
      },
    );
    await expect(messages).resolves.toMatchObject({
      items: [{ message_index: 0 }, { message_index: 1 }],
      incomplete: false,
    });

    interface DayItem {
      day: string;
      active: boolean;
    }
    interface DayPage {
      items: DayItem[];
      next_before: string | null;
    }
    const days = await drainPages<DayItem, DayPage>(
      async (before) => ({
        items: [{ day: before === null ? "2026-09-29" : "2026-09-28", active: before === null }],
        next_before: before === null ? "2026-09-28" : null,
      }),
      { nextToken: (page) => page.next_before },
    );
    expect(days.items.map((item) => item.day)).toEqual([
      "2026-09-29",
      "2026-09-28",
    ]);
  });

  it("decodes typed items through decodeItem", async () => {
    const result = await drainPages<string>(async () => ({
      items: [],
      content_fragment: {
        encoding: "canonical_json",
        text: JSON.stringify({ text: "正文" }),
      },
    }), {
      decodeItem: (value) => (value as { text: string }).text,
    });
    expect(result.items).toEqual(["正文"]);
  });

  it("propagates read errors so callers restart without the old token", async () => {
    const failure = new Error("409 continuation_content_changed");
    await expect(
      drainPages(async (continuation) => {
        if (continuation !== null) throw failure;
        return { items: [] as JsonValue[], next_continuation: "t1" };
      }),
    ).rejects.toBe(failure);
  });
});
