// @vitest-environment jsdom
/**
 * Local store facade, browser-mode contract: reads and writes round-trip
 * through the hydrated cache and WebView storage, legacy plain keys read
 * through until rewritten, and test resets leave no residue. Tauri-mode
 * commands are covered by the Rust unit tests in src-tauri.
 */
import { beforeEach, describe, expect, it } from "vitest";

import {
  initLocalStore,
  listLocal,
  localStoreState,
  readLocal,
  removeLocal,
  resetLocalStoreForTests,
  writeLocal,
} from "./localStore";

beforeEach(() => {
  resetLocalStoreForTests();
  localStorage.clear();
});

describe("localStore browser mode", () => {
  it("round-trips values through cache and storage", async () => {
    await initLocalStore();
    await writeLocal("alpha", "one");
    expect(readLocal("alpha")).toBe("one");
    expect(localStorage.getItem("tinysoul-local:alpha")).toBe("one");
    await removeLocal("alpha");
    expect(readLocal("alpha")).toBeNull();
  });

  it("reads legacy plain keys through until rewritten", async () => {
    localStorage.setItem("legacy-key", "old");
    await initLocalStore();
    expect(readLocal("legacy-key")).toBe("old");
    await writeLocal("legacy-key", "new");
    expect(readLocal("legacy-key")).toBe("new");
  });

  it("lists saved keys and reports browser state", async () => {
    await initLocalStore();
    await writeLocal("beta", "b");
    const keys = await listLocal();
    expect(keys).toContain("beta");
    expect(localStoreState().mode).toBe("browser");
  });

  it("test reset clears the cache", async () => {
    await initLocalStore();
    await writeLocal("gamma", "g");
    resetLocalStoreForTests();
    localStorage.clear();
    expect(readLocal("gamma")).toBeNull();
  });
});
