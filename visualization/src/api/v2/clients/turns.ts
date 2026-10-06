/**
 * API-02/03: structured Turns.
 * create() always targets a new User Turn (kind=user); Reflection scenarios
 * are submitted through clients/reflection.ts. Receipts are acceptance facts,
 * not execution results — GET /v2/requests/{id} is the state source.
 */

import type {
  InboxReceipt,
  InteractionPage,
  TurnCancelReceipt,
  TurnCreateBody,
  TurnCreateReceipt,
  TurnGrantBody,
  TurnGrantReceipt,
  TurnInputBody,
  TurnReplyBody,
  TurnSnapshot,
  TurnDirectory,
} from "../types";
import type { RequestOptions, V2Transport } from "../transport";
import type { ListPageParams } from "./paging";

export class TurnsClient {
  constructor(private readonly transport: V2Transport) {}

  list(options?: RequestOptions): Promise<TurnDirectory> {
    return this.transport.get<TurnDirectory>("/requests", options);
  }

  /** POST /v2/requests — queue a new User Turn (202 acceptance fact). */
  create(
    body: TurnCreateBody,
    options?: RequestOptions,
  ): Promise<TurnCreateReceipt> {
    return this.transport.post<TurnCreateReceipt>("/requests", {
      ...options,
      body,
    });
  }

  /** GET /v2/requests/{id} — TurnSnapshot: state, question, budget, result. */
  get(requestId: string, options?: RequestOptions): Promise<TurnSnapshot> {
    return this.transport.get<TurnSnapshot>(
      `/requests/${encodeURIComponent(requestId)}`,
      options,
    );
  }

  /** POST /v2/requests/{id}/input — append text to an open Inbox. */
  appendInput(
    requestId: string,
    body: TurnInputBody,
    options?: RequestOptions,
  ): Promise<InboxReceipt> {
    return this.transport.post<InboxReceipt>(
      `/requests/${encodeURIComponent(requestId)}/input`,
      { ...options, body },
    );
  }

  /** POST /v2/requests/{id}/reply — answer the current question by id. */
  reply(
    requestId: string,
    body: TurnReplyBody,
    options?: RequestOptions,
  ): Promise<InboxReceipt> {
    return this.transport.post<InboxReceipt>(
      `/requests/${encodeURIComponent(requestId)}/reply`,
      { ...options, body },
    );
  }

  /** POST /v2/requests/{id}/grant — grant budget cycles; never a reply. */
  grant(
    requestId: string,
    body: TurnGrantBody,
    options?: RequestOptions,
  ): Promise<TurnGrantReceipt> {
    return this.transport.post<TurnGrantReceipt>(
      `/requests/${encodeURIComponent(requestId)}/grant`,
      { ...options, body },
    );
  }

  /** POST /v2/requests/{id}/cancel — accept a cancel intent (no body). */
  cancel(
    requestId: string,
    options?: RequestOptions,
  ): Promise<TurnCancelReceipt> {
    return this.transport.post<TurnCancelReceipt>(
      `/requests/${encodeURIComponent(requestId)}/cancel`,
      options,
    );
  }

  /**
   * GET /v2/requests/{id}/interactions — active/retained handle projection:
   * items, pending_items and an optional queued_request. Empty items do not
   * end the page; follow next_continuation.
   */
  interactions(
    requestId: string,
    params?: ListPageParams,
    options?: RequestOptions,
  ): Promise<InteractionPage> {
    return this.transport.get<InteractionPage>(
      `/requests/${encodeURIComponent(requestId)}/interactions`,
      { ...options, query: { ...params } },
    );
  }
}
