/**
 * Endpoint v2 error envelope and classification.
 * Shape: schemas/error.json ({error: {code, message, details}}). Branch on
 * `code`, preserve structured `details`, never parse human-facing `message`
 * (implementation plan §3.4).
 *
 * Note: src/api/transport.ts still carries the v1 TinySoulApiError used by
 * the existing clients; F1 rewires transport to this implementation.
 */

import type { JsonObject, JsonValue } from "./json";

/** schemas/error.json */
export interface ApiErrorBody {
  code: string;
  message: string;
  details: JsonObject;
  [key: string]: unknown;
}

export interface ApiErrorEnvelope {
  error: ApiErrorBody;
  [key: string]: unknown;
}

export class TinySoulApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details: JsonObject = {},
  ) {
    super(message);
    this.name = "TinySoulApiError";
  }
}

export function isTinySoulApiError(error: unknown): error is TinySoulApiError {
  return error instanceof TinySoulApiError;
}

/** Build from an HTTP status and an already-decoded response body. */
export function apiErrorFromBody(status: number, body: unknown): TinySoulApiError {
  const error = isRecord(body) && isRecord(body.error) ? body.error : null;
  const code = typeof error?.code === "string" ? error.code : "endpoint.unknown";
  const message =
    typeof error?.message === "string" ? error.message : `HTTP ${status}`;
  const details = isRecord(error?.details) ? (error.details as JsonObject) : {};
  return new TinySoulApiError(status, code, message, details);
}

export function apiErrorCode(error: unknown): string | null {
  return isTinySoulApiError(error) ? error.code : null;
}

export function hasApiCode(error: unknown, ...codes: string[]): boolean {
  const code = apiErrorCode(error);
  return code !== null && codes.includes(code);
}

/** Structured detail access; returns undefined when absent. */
export function apiErrorDetail(
  error: unknown,
  key: string,
): JsonValue | undefined {
  return isTinySoulApiError(error) ? error.details[key] : undefined;
}

/**
 * Continuation tokens become invalid when the bound content changed or the
 * generation/day moved on (docs/endpoint/inspection.md). The reader must end
 * the current sequence and restart without a token.
 */
export const CONTINUATION_INVALID_CODES = [
  "invalid_continuation",
  "continuation_mismatch",
  "continuation_content_changed",
  "continuation_out_of_range",
] as const;

export function isContinuationInvalid(error: unknown): boolean {
  return hasApiCode(error, ...CONTINUATION_INVALID_CODES);
}

/** New turn / inbox capacity rejections; the draft stays with the user. */
export function isCapacityRejection(error: unknown): boolean {
  return hasApiCode(error, "agent.queue_full", "turn.inbox_full");
}

/** 409 config.activation_unavailable: keep the draft, activation later. */
export function isConfigActivationUnavailable(error: unknown): boolean {
  return hasApiCode(error, "config.activation_unavailable");
}

/** Live Context is closed; stop continuation reads for this Turn. */
export function isContextUnavailable(error: unknown): boolean {
  return hasApiCode(error, "context.unavailable");
}

/** Frozen Search view is gone; offer an explicit re-search, not a retry. */
export function isSearchViewExpired(error: unknown): boolean {
  return hasApiCode(error, "search.view_expired");
}

/**
 * Field/config locator from structured details only. `config.invalid`
 * carries details.key when the failing config key is known; a generic
 * `request.invalid` has no field location and must surface as a form-level
 * error. Returns null otherwise — never derived from `message`.
 */
export function configErrorKey(error: unknown): string | null {
  if (!hasApiCode(error, "config.invalid")) return null;
  const key = apiErrorDetail(error, "key");
  return typeof key === "string" ? key : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
