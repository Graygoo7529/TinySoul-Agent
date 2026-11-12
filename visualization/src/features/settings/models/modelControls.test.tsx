// @vitest-environment jsdom
/**
 * OrderableRow drag contract: only the grip starts a reorder drag, the drop
 * indicator is an insertion edge (before/after) on the target row, stale
 * edges clear when the drag ends anywhere, and foreign drags are rejected.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrderableRow } from "./modelControls";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const MIME = "application/x-tinysoul-reorder";

function dragEvent(
  type: string,
  init: { data?: Record<string, string>; types?: string[]; clientY?: number } = {},
): Event {
  const store = new Map(Object.entries(init.data ?? {}));
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.assign(event, {
    clientY: init.clientY ?? 0,
    dataTransfer: {
      get types() {
        return [...store.keys(), ...(init.types ?? [])];
      },
      getData: (mime: string) => store.get(mime) ?? "",
      setData: (mime: string, value: string) => void store.set(mime, value),
      effectAllowed: "",
      dropEffect: "",
    },
  });
  return event;
}

describe("OrderableRow drag", () => {
  let host: HTMLDivElement;
  let root: Root;
  let onDrop: ReturnType<typeof vi.fn<(source: number) => void>>;

  beforeEach(async () => {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    onDrop = vi.fn<(source: number) => void>();
    await act(async () => {
      root.render(
        <OrderableRow
          index={1}
          count={3}
          disabled={false}
          onMove={() => undefined}
          onDrop={onDrop}
          onRemove={null}
          ariaLabel="Row 2"
        >
          <span>content</span>
        </OrderableRow>,
      );
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
  });

  const row = () => host.querySelector<HTMLDivElement>(".settings-orderable-row")!;
  const grip = () => host.querySelector<HTMLElement>("[role=\"button\"]")!;

  it("keeps the row undraggable until the grip is held", async () => {
    expect(row().getAttribute("draggable")).toBe("false");
    await act(async () => {
      grip().dispatchEvent(new Event("pointerdown", { bubbles: true }));
    });
    expect(row().getAttribute("draggable")).toBe("true");
  });

  it("marks the drag with the reorder MIME and not text/plain", async () => {
    await act(async () => {
      grip().dispatchEvent(new Event("pointerdown", { bubbles: true }));
    });
    const event = dragEvent("dragstart");
    await act(async () => void row().dispatchEvent(event));
    const dt = (event as unknown as { dataTransfer: { types: string[] } }).dataTransfer;
    expect(dt.types).toContain(MIME);
    expect(dt.types).not.toContain("text/plain");
  });

  it("shows an insertion edge matching the pointer half of the row", async () => {
    // jsdom rects are zero-height, so clientY below the midpoint (0) reads as
    // "after" and above it as "before".
    await act(async () => void row().dispatchEvent(dragEvent("dragover", { types: [MIME], clientY: 10 })));
    expect(row().className).toContain("insert-after");
    await act(async () => void row().dispatchEvent(dragEvent("dragover", { types: [MIME], clientY: -10 })));
    expect(row().className).toContain("insert-before");
  });

  it("ignores foreign drags entirely", async () => {
    const event = dragEvent("dragover", { types: ["text/plain"], data: { "text/plain": "0" }, clientY: 10 });
    await act(async () => void row().dispatchEvent(event));
    expect(event.defaultPrevented).toBe(false);
    expect(row().className).not.toContain("insert-");
  });

  it("clears the insertion edge when the drag ends outside any row", async () => {
    await act(async () => void row().dispatchEvent(dragEvent("dragover", { types: [MIME], clientY: 10 })));
    expect(row().className).toContain("insert-after");
    await act(async () => void document.dispatchEvent(dragEvent("dragend")));
    expect(row().className).not.toContain("insert-");
  });

  it("commits the dropped source index and clears the edge", async () => {
    await act(async () => void row().dispatchEvent(dragEvent("dragover", { types: [MIME], clientY: 10 })));
    await act(async () => void row().dispatchEvent(dragEvent("drop", { types: [MIME], data: { [MIME]: "0" } })));
    expect(onDrop).toHaveBeenCalledWith(0);
    expect(row().className).not.toContain("insert-");
  });
});
