// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";

import {
  clearStoredBrowserTarget,
  loadStoredBrowserTarget,
  storeBrowserTarget,
} from "./discovery";

const STORAGE_KEY = "tinysoul-web-connection";

beforeEach(() => {
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

  it("persists only address + token, not lease identity", () => {
    storeBrowserTarget({
      address: "https://example.test:9443",
      token: "tok-2",
      instanceId: "instance_9",
      projectIdentity: "proj",
    });
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)).toEqual({
      address: "https://example.test:9443",
      token: "tok-2",
    });
  });

  it("clears the stored target", () => {
    storeBrowserTarget({ address: "127.0.0.1:1430", token: "tok-1" });
    clearStoredBrowserTarget();
    expect(loadStoredBrowserTarget()).toBeNull();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("returns null when nothing is stored", () => {
    expect(loadStoredBrowserTarget()).toBeNull();
  });
});

describe("v1 migration", () => {
  it("migrates the legacy host/port shape to an http URL", () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ host: "192.168.1.10", port: 1430, token: "legacy" }),
    );
    expect(loadStoredBrowserTarget()).toEqual({
      address: "http://192.168.1.10:1430",
      token: "legacy",
    });
  });

  it("prefers the v2 shape when both are present", () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        address: "https://new.example:443",
        token: "tok",
        host: "old-host",
        port: 1430,
      }),
    );
    expect(loadStoredBrowserTarget()).toEqual({
      address: "https://new.example:443",
      token: "tok",
    });
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

  it("returns null for a non-positive legacy port", () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ host: "h", port: 0, token: "tok" }),
    );
    expect(loadStoredBrowserTarget()).toBeNull();
  });

  it("returns null for unrelated shapes", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ hello: "world" }));
    expect(loadStoredBrowserTarget()).toBeNull();
  });
});
