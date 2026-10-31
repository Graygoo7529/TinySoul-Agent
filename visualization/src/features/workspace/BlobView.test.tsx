// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { ImageLightbox } from "./BlobView";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function renderLightbox(overrides: { onClose?: Mock; onDownload?: Mock } = {}) {
  const onClose = overrides.onClose ?? vi.fn();
  const onDownload = overrides.onDownload ?? vi.fn();
  act(() => {
    root.render(
      <ImageLightbox
        url="blob:test"
        name="温度趋势.png"
        detail="PNG 图片 · 84.2 KB"
        onDownload={onDownload}
        onClose={onClose}
      />,
    );
  });
  return { onClose, onDownload };
}

function viewArea(): HTMLDivElement {
  const view = container.querySelector(".cursor-grab, .cursor-grabbing");
  if (view === null) throw new Error("view area not rendered");
  return view as HTMLDivElement;
}

function press(
  target: Element,
  points: { x: number; y: number }[],
): void {
  const [first, ...rest] = points;
  target.dispatchEvent(
    new MouseEvent("pointerdown", { bubbles: true, clientX: first!.x, clientY: first!.y }),
  );
  for (const point of rest) {
    target.dispatchEvent(
      new MouseEvent("pointermove", { bubbles: true, clientX: point.x, clientY: point.y }),
    );
  }
  const last = points[points.length - 1]!;
  target.dispatchEvent(
    new MouseEvent("pointerup", { bubbles: true, clientX: last.x, clientY: last.y }),
  );
}

function wheel(deltaY: number): void {
  viewArea().dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY }));
}

describe("ImageLightbox", () => {
  it("renders the name, detail and fit zoom, and closes on Escape", () => {
    const { onClose } = renderLightbox();
    expect(container.textContent).toContain("温度趋势.png");
    expect(container.textContent).toContain("PNG 图片 · 84.2 KB");
    expect(container.textContent).toContain("100%");
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("zooms by wheel in 25% steps and clamps at 0.25x–4x", () => {
    renderLightbox();
    act(() => wheel(-100));
    expect(container.textContent).toContain("125%");
    act(() => {
      for (let i = 0; i < 12; i += 1) wheel(-100);
    });
    expect(container.textContent).toContain("400%");
    act(() => {
      for (let i = 0; i < 30; i += 1) wheel(100);
    });
    expect(container.textContent).toContain("25%");
  });

  it("closes on a background click but not on a drag or an image press", () => {
    const { onClose } = renderLightbox();
    // A press without movement on the backdrop closes.
    act(() => {
      press(viewArea(), [{ x: 100, y: 100 }]);
    });
    expect(onClose).toHaveBeenCalledTimes(1);

    onClose.mockClear();
    // A drag is not a click-away.
    act(() => {
      press(viewArea(), [
        { x: 100, y: 100 },
        { x: 160, y: 140 },
      ]);
    });
    expect(onClose).not.toHaveBeenCalled();

    // A press starting on the image is never a click-away.
    const img = container.querySelector("img")!;
    act(() => {
      press(img, [{ x: 200, y: 120 }]);
    });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("resets zoom and pan via the button and double-click", () => {
    renderLightbox();
    act(() => wheel(-100));
    act(() => {
      press(viewArea(), [
        { x: 0, y: 0 },
        { x: 80, y: 60 },
      ]);
    });
    const img = container.querySelector("img")!;
    expect(img.style.transform).not.toContain("scale(1)");
    act(() => {
      (container.querySelector('button[aria-label="复位到 100%"]') as HTMLButtonElement).click();
    });
    expect(container.textContent).toContain("100%");
    expect(img.style.transform).toContain("scale(1)");
    act(() => wheel(-100));
    act(() => {
      viewArea().dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
    });
    expect(container.textContent).toContain("100%");
  });

  it("downloads through the same blob route and closes via the button", () => {
    const onDownload = vi.fn();
    const onClose = vi.fn();
    renderLightbox({ onDownload, onClose });
    act(() => {
      (container.querySelector('button[aria-label="下载"]') as HTMLButtonElement).click();
    });
    expect(onDownload).toHaveBeenCalledTimes(1);
    act(() => {
      (container.querySelector('button[aria-label="关闭"]') as HTMLButtonElement).click();
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
