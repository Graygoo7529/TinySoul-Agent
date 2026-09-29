/**
 * API-04: Reflection availability and maintenance requests.
 * Availability pages continue with `?before=<next_before>` (the route has no
 * limit parameter); a request accepts one Reflection Turn on the shared root
 * queue and returns the same receipt as POST /v2/turns.
 */

import type {
  ReflectionRequestBody,
  ReflectionStatusResponse,
  TurnCreateReceipt,
} from "../types";
import type { RequestOptions, V2Transport } from "../transport";

export class ReflectionClient {
  constructor(private readonly transport: V2Transport) {}

  /** GET /v2/reflection?before= — owner-derived availability projection. */
  availability(
    params?: { before?: string },
    options?: RequestOptions,
  ): Promise<ReflectionStatusResponse> {
    return this.transport.get<ReflectionStatusResponse>("/reflection", {
      ...options,
      query: { ...params },
    });
  }

  /**
   * POST /v2/reflection — one explicit maintenance grant. kind=memory
   * requires target_day (enforced by the body type); kind=home ignores it.
   */
  request(
    body: ReflectionRequestBody,
    options?: RequestOptions,
  ): Promise<TurnCreateReceipt> {
    return this.transport.post<TurnCreateReceipt>("/reflection", {
      ...options,
      body,
    });
  }
}
