/**
 * API-09: read-only views of the currently installed Context of one Turn.
 * The segment body uses `messages[{message_index,message}]` (not items);
 * inspect returns the shared DisclosurePage. A closed Context answers
 * 409 context.unavailable — stop live continuation reads for that Turn.
 */

import type {
  BackgroundPage,
  ContextMessagesPage,
  ContextOverview,
  DisclosurePage,
} from "../types";
import type { RequestOptions, V2Transport } from "../transport";
import type { ContinuationParams } from "./paging";

export class ContextClient {
  constructor(private readonly transport: V2Transport) {}

  background(requestId: string, params?: ContinuationParams, options?: RequestOptions): Promise<BackgroundPage> {
    return this.transport.get<BackgroundPage>(`/requests/${encodeURIComponent(requestId)}/context/background`,
      { ...options, query: { ...params } });
  }

  /** GET /v2/requests/{id}/context — installed segments and resolved refs. */
  overview(requestId: string, options?: RequestOptions): Promise<ContextOverview> {
    return this.transport.get<ContextOverview>(
      `/requests/${encodeURIComponent(requestId)}/context`,
      options,
    );
  }

  /** GET /v2/requests/{id}/context/segments/{segment_id} — installed body. */
  segment(
    requestId: string,
    segmentId: string,
    params?: ContinuationParams,
    options?: RequestOptions,
  ): Promise<ContextMessagesPage> {
    return this.transport.get<ContextMessagesPage>(
      `/requests/${encodeURIComponent(requestId)}/context/segments/${encodeURIComponent(segmentId)}`,
      { ...options, query: { ...params } },
    );
  }

  /**
   * GET /v2/requests/{id}/context/inspect — user-side reading only; never
   * appends Action results or lifts the model-side display protection.
   */
  inspect(
    requestId: string,
    params: { ref: string; query?: string; continuation?: string },
    options?: RequestOptions,
  ): Promise<DisclosurePage> {
    return this.transport.get<DisclosurePage>(
      `/requests/${encodeURIComponent(requestId)}/context/inspect`,
      { ...options, query: { ...params } },
    );
  }
}
