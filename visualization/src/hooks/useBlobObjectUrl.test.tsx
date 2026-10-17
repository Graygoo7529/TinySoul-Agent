// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { deferred } from "../app/testing";
import { useBlobObjectUrl } from "./useBlobObjectUrl";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

it("discards late blobs and releases displayed URLs on resource change and unmount", async () => {
  const create = vi.fn(() => "blob:preview");
  const revoke = vi.fn();
  vi.stubGlobal("URL", class extends URL { static createObjectURL = create; static revokeObjectURL = revoke; });
  const container = document.createElement("div");
  const root = createRoot(container);
  const late = deferred<Response>();
  let signal: AbortSignal | undefined;
  const first = (value: AbortSignal) => { signal = value; return late.promise; };
  const next = () => Promise.resolve(new Response("image", { headers: { "Content-Type": "image/png" } }));
  function Preview({ read }: { read: (signal: AbortSignal) => Promise<Response> }) {
    const blob = useBlobObjectUrl(read);
    return <span>{blob.url ?? "loading"}</span>;
  }
  try {
    await act(async () => root.render(<Preview read={first} />));
    await act(async () => root.render(<Preview read={next} />));
    expect(signal?.aborted).toBe(true);
    expect(container.textContent).toBe("blob:preview");
    await act(async () => late.resolve(new Response("obsolete")));
    expect(create).toHaveBeenCalledTimes(1);
    await act(async () => root.unmount());
    expect(revoke).toHaveBeenCalledWith("blob:preview");
  } finally {
    vi.unstubAllGlobals();
  }
});
