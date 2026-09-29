import { describe, expect, it } from "vitest";

import homeFragment from "../../../test/fixtures/contracts/home-fragment.json";
import homeFragmentEnd from "../../../test/fixtures/contracts/home-fragment-end.json";
import jobOutput from "../../../test/fixtures/contracts/job-output.json";
import searchEvidence from "../../../test/fixtures/contracts/search-evidence.json";
import {
  CanonicalJsonFragmentDecoder,
  createPageAssembler,
  isFinalPage,
  jobOutputContinuation,
  nextContinuation,
  searchContinuation,
} from "./pagination";
import type { JobOutputPage } from "./job";
import type { SearchPage } from "./search";

function chunk(text: string, size: number): string[] {
  const parts: string[] = [];
  for (let i = 0; i < text.length; i += size) parts.push(text.slice(i, i + size));
  return parts;
}

describe("canonical_json fragment decoder", () => {
  const item = { ref: "workspace:report.md#L1-L3", text: "第一段正文。emoji 🎉" };
  const serialized = JSON.stringify(item);
  const third = Math.ceil(serialized.length / 3);
  const c1 = serialized.slice(0, third);
  const c2 = serialized.slice(third, third * 2);
  const c3 = serialized.slice(third * 2);

  it("delivers an item exactly once after multi-page assembly", () => {
    const assembler = createPageAssembler();
    expect(
      assembler.push({
        items: [],
        content_fragment: { encoding: "canonical_json", text: c1 },
        next_continuation: "c1",
      }),
    ).toEqual([]);
    expect(assembler.fragmentPending).toBe(true);
    expect(
      assembler.push({
        items: [],
        content_fragment: { encoding: "canonical_json", text: c2 },
        next_continuation: "c2",
      }),
    ).toEqual([]);
    // Final chunk arrives on a page without a next token; still delivered.
    const delivered = assembler.push({
      items: [],
      content_fragment: { encoding: "canonical_json", text: c3 },
    });
    expect(delivered).toEqual([item]);
    expect(assembler.fragmentPending).toBe(false);
  });

  it("does not wait for next_continuation to disappear before parsing", () => {
    const assembler = createPageAssembler();
    const twoPart = chunk(serialized, Math.ceil(serialized.length / 2));
    assembler.push({
      items: [],
      content_fragment: { encoding: "canonical_json", text: twoPart[0] },
      next_continuation: "c1",
    });
    // Completes on a page that still carries a continuation token.
    const delivered = assembler.push({
      items: [],
      content_fragment: { encoding: "canonical_json", text: twoPart[1] },
      next_continuation: "c2",
    });
    expect(delivered).toEqual([item]);
  });

  it("does not deliver while the item is incomplete", () => {
    const decoder = new CanonicalJsonFragmentDecoder();
    expect(
      decoder.feed({ encoding: "canonical_json", text: serialized.slice(0, 5) }),
    ).toBeUndefined();
    expect(decoder.pending).toBe(true);
    expect(decoder.bufferedChars).toBe(5);
  });

  it("keeps regular items ordered around a completed fragment item", () => {
    const assembler = createPageAssembler();
    const twoPart = chunk(serialized, Math.ceil(serialized.length / 2));
    assembler.push({
      items: [{ ref: "a" }],
      content_fragment: { encoding: "canonical_json", text: twoPart[0] },
    });
    const middle = assembler.push({
      items: [],
      content_fragment: { encoding: "canonical_json", text: twoPart[1] },
    });
    expect(middle).toEqual([item]);
    // Items may follow the long item on later pages.
    expect(assembler.push({ items: [{ ref: "b" }] })).toEqual([{ ref: "b" }]);
  });

  it("delivers the fragment item after the same page's regular items", () => {
    const assembler = createPageAssembler();
    const delivered = assembler.push({
      items: [{ ref: "first" }],
      content_fragment: { encoding: "canonical_json", text: serialized },
    });
    expect(delivered).toEqual([{ ref: "first" }, item]);
  });

  it("reset clears a partial buffer so sequences never mix", () => {
    const decoder = new CanonicalJsonFragmentDecoder();
    decoder.feed({ encoding: "canonical_json", text: serialized.slice(0, 10) });
    decoder.reset();
    expect(decoder.pending).toBe(false);
    expect(decoder.bufferedChars).toBe(0);
    expect(
      decoder.feed({ encoding: "canonical_json", text: serialized }),
    ).toEqual(item);
  });

  it("rejects unknown encodings and resets", () => {
    const decoder = new CanonicalJsonFragmentDecoder();
    decoder.feed({ encoding: "canonical_json", text: serialized.slice(0, 4) });
    expect(() =>
      decoder.feed({ encoding: "markdown_excerpt", text: "x" }),
    ).toThrow(/encoding/);
    expect(decoder.pending).toBe(false);
  });

  it("fixture first+last fragments are not adjacent pages", () => {
    // home-fragment / home-fragment-end are the first and final pages of one
    // long item; the backend contract test consumes the intermediate pages.
    // The fixtures cannot stand in for a real sequence: the first chunk ends
    // mid-word ("…Long content L") and the final chunk starts with "ent …",
    // so a naive first+last join decodes to corrupted text ("Lent") that no
    // genuine assembly of this item would contain.
    const assembler = createPageAssembler();
    assembler.push(homeFragment);
    const delivered = assembler.push(homeFragmentEnd);
    expect(homeFragment.content_fragment.text.endsWith("L")).toBe(true);
    expect(homeFragmentEnd.content_fragment.text.startsWith("ent ")).toBe(true);
    const decoded = delivered[0] as { text: string };
    expect(decoded.text).toContain("Lent");
  });
});

describe("continuation primitives", () => {
  it("empty items decide neither emptiness nor completion", () => {
    expect(isFinalPage({ next_continuation: "c1" })).toBe(false);
    expect(nextContinuation({ next_continuation: "c1" })).toBe("c1");
    expect(isFinalPage({})).toBe(true);
    expect(isFinalPage({ next_continuation: null })).toBe(true);
  });

  it("search cursor is the top-level continuation, not page.continuation", () => {
    const page = searchEvidence as SearchPage;
    expect(page.page.continuation).toBeNull();
    expect(searchContinuation(page)).toBeNull();
    expect(
      searchContinuation({ ...page, continuation: "search-token" }),
    ).toBe("search-token");
  });

  it("job output always carries a polling token, even on empty pages", () => {
    const page = jobOutput as JobOutputPage;
    expect(jobOutputContinuation(page)).toBe("continuation_2");
    expect(jobOutputContinuation({ ...page, items: [] })).toBe(
      "continuation_2",
    );
    expect(page.truncated).toBe(false);
  });
});
