import { describe, expect, it } from "vitest";

import {
  apiErrorFromBody,
  configErrorKey,
  hasApiCode,
  isConfigActivationUnavailable,
  isContextUnavailable,
  isCapacityRejection,
  isContinuationInvalid,
  isSearchViewExpired,
  isTinySoulApiError,
  TinySoulApiError,
} from "./errors";

describe("TinySoulApiError", () => {
  it("parses the error envelope and preserves structured details", () => {
    const error = apiErrorFromBody(422, {
      error: {
        code: "config.invalid",
        message: "provider primary has no credential",
        details: { key: "llm.providers.primary.api_key_envs" },
      },
    });
    expect(error.status).toBe(422);
    expect(error.code).toBe("config.invalid");
    expect(error.details).toEqual({
      key: "llm.providers.primary.api_key_envs",
    });
  });

  it("falls back to endpoint.unknown for non-envelope bodies", () => {
    const error = apiErrorFromBody(502, "<html>bad gateway</html>");
    expect(error.code).toBe("endpoint.unknown");
    expect(error.message).toBe("HTTP 502");
    expect(error.details).toEqual({});
  });
});

describe("error classification", () => {
  const make = (code: string, details = {}) =>
    new TinySoulApiError(409, code, "human text", details);

  it("branches on code, not message", () => {
    expect(isContinuationInvalid(make("invalid_continuation"))).toBe(true);
    expect(isContinuationInvalid(make("continuation_mismatch"))).toBe(true);
    expect(isContinuationInvalid(make("continuation_content_changed"))).toBe(
      true,
    );
    expect(isContinuationInvalid(make("continuation_out_of_range"))).toBe(
      true,
    );
    expect(isContinuationInvalid(make("context.unavailable"))).toBe(false);
    expect(isContinuationInvalid(new Error("continuation"))).toBe(false);
  });

  it("recognizes capacity, activation, context and search codes", () => {
    expect(isCapacityRejection(make("agent.queue_full"))).toBe(true);
    expect(isCapacityRejection(make("turn.inbox_full"))).toBe(true);
    expect(isCapacityRejection(make("turn.command_rejected"))).toBe(false);
    expect(
      isConfigActivationUnavailable(make("config.activation_unavailable")),
    ).toBe(true);
    expect(isContextUnavailable(make("context.unavailable"))).toBe(true);
    expect(isSearchViewExpired(make("search.view_expired"))).toBe(true);
    expect(isSearchViewExpired(make("search.scope_required"))).toBe(false);
  });

  it("hasApiCode matches only TinySoulApiError codes", () => {
    expect(hasApiCode(make("agent.not_ready"), "agent.not_ready")).toBe(true);
    expect(hasApiCode(new Error("x"), "agent.not_ready")).toBe(false);
    expect(isTinySoulApiError(new Error("x"))).toBe(false);
  });

  it("configErrorKey uses structured details only, never message text", () => {
    expect(
      configErrorKey(
        new TinySoulApiError(422, "config.invalid", "bad", {
          key: "llm.models.primary",
        }),
      ),
    ).toBe("llm.models.primary");
    // Generic request.invalid has no field location even if the message
    // mentions one; callers must show a form-level error.
    expect(
      configErrorKey(
        new TinySoulApiError(
          422,
          "request.invalid",
          "field llm.models.primary is wrong",
        ),
      ),
    ).toBeNull();
    expect(configErrorKey(new TinySoulApiError(422, "config.invalid", "x")))
      .toBeNull();
  });
});
