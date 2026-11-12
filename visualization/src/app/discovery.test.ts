// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";

import {
  clearStoredBrowserTarget,
  loadStoredBrowserTarget,
  storeBrowserTarget,
} from "./discovery";
import { resetLocalStoreForTests } from "./localStore/localStore";

const STORAGE_KEY = "tinysoul-web-connection";

beforeEach(() => {
  resetLocalStoreForTests();
  localStorage.clear();
});

describe("browser target persistence", () => {
  it("round-trips address + token", () => {
    storeBrowserTarget({ address: "127.0.0.1:1430", token: "tok-1" });
    expect(loadStoredBrowserTarget()).toEqual({
      address: "127.0.0.1:1430",
      token: "tok-1",
    });
  });

  it("persists only address + token", () => {
    storeBrowserTarget({
      address: "https://example.test:9443",
      token: "tok-2",
    });
    expect(loadStoredBrowserTarget()).toEqual({
      address: "https://example.test:9443",
      token: "tok-2",
    });
  });

  it("clears the stored target", () => {
    storeBrowserTarget({ address: "127.0.0.1:1430", token: "tok-1" });
    clearStoredBrowserTarget();
    expect(loadStoredBrowserTarget()).toBeNull();
  });

  it("returns null when nothing is stored", () => {
    expect(loadStoredBrowserTarget()).toBeNull();
  });
});

describe("obsolete connection shapes", () => {
  it("does not interpret the old host/port shape", () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ host: "192.168.1.10", port: 1430, token: "legacy" }),
    );
    expect(loadStoredBrowserTarget()).toBeNull();
  });
});

describe("invalid stored values", () => {
  it("returns null for malformed JSON", () => {
    localStorage.setItem(STORAGE_KEY, "{not json");
    expect(loadStoredBrowserTarget()).toBeNull();
  });

  it("returns null when the token is missing", () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ address: "127.0.0.1:1430" }),
    );
    expect(loadStoredBrowserTarget()).toBeNull();
  });

  it("returns null for a blank v2 address", () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ address: "  ", token: "tok" }),
    );
    expect(loadStoredBrowserTarget()).toBeNull();
  });

  it("returns null for a target without an address", () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ token: "tok" }),
    );
    expect(loadStoredBrowserTarget()).toBeNull();
  });

  it("returns null for unrelated shapes", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ hello: "world" }));
    expect(loadStoredBrowserTarget()).toBeNull();
  });
});
