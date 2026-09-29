/**
 * API-09: read-only views of the currently installed Context of one Turn.
 * The segment body uses `messages[{message_index,message}]` (not items);
 * inspect returns the shared DisclosurePage. A closed Context answers
 * 409 context.unavailable — stop live continuation reads for that Turn.
 */

import type {
  ContextMessagesPage,
  ContextOverview,
  DisclosurePage,
} from "../types";
import type { RequestOptions, V2Transport } from "../transport";
import type { ContinuationParams } from "./paging";

export class ContextClient {
  constructor(private readonly transport: V2Transport) {}

  /** GET /v2/turns/{id}/context — installed segments and resolved refs. */
  overview(turnId: string, options?: RequestOptions): Promise<ContextOverview> {
    return this.transport.get<ContextOverview>(
      `/turns/${encodeURIComponent(turnId)}/context`,
      options,
    );
  }

  /** GET /v2/turns/{id}/context/segments/{segment_id} — installed body. */
  segment(
    turnId: string,
    segmentId: string,
    params?: ContinuationParams,
    options?: RequestOptions,
  ): Promise<ContextMessagesPage> {
    return this.transport.get<ContextMessagesPage>(
      `/turns/${encodeURIComponent(turnId)}/context/segments/${encodeURIComponent(segmentId)}`,
      { ...options, query: { ...params } },
    );
  }

  /**
   * GET /v2/turns/{id}/context/inspect — user-side reading only; never
   * appends Action results or lifts the model-side display protection.
   */
  inspect(
    turnId: string,
    params: { ref: string; query?: string; continuation?: string },
    options?: RequestOptions,
  ): Promise<DisclosurePage> {
    return this.transport.get<DisclosurePage>(
      `/turns/${encodeURIComponent(turnId)}/context/inspect`,
      { ...options, query: { ...params } },
    );
  }
}
