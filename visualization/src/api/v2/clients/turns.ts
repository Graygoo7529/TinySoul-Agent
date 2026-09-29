/**
 * API-02/03: structured Turns.
 * create() always targets a new User Turn (kind=user); Reflection scenarios
 * are submitted through clients/reflection.ts. Receipts are acceptance facts,
 * not execution results — GET /v2/turns/{id} is the state source.
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
} from "../types";
import type { RequestOptions, V2Transport } from "../transport";
import type { ListPageParams } from "./paging";

export class TurnsClient {
  constructor(private readonly transport: V2Transport) {}

  /** POST /v2/turns — queue a new User Turn (202 acceptance fact). */
  create(
    body: TurnCreateBody,
    options?: RequestOptions,
  ): Promise<TurnCreateReceipt> {
    return this.transport.post<TurnCreateReceipt>("/turns", {
      ...options,
      body,
    });
  }

  /** GET /v2/turns/{id} — TurnSnapshot: state, question, budget, result. */
  get(turnId: string, options?: RequestOptions): Promise<TurnSnapshot> {
    return this.transport.get<TurnSnapshot>(
      `/turns/${encodeURIComponent(turnId)}`,
      options,
    );
  }

  /** POST /v2/turns/{id}/input — append text to an open Inbox. */
  appendInput(
    turnId: string,
    body: TurnInputBody,
    options?: RequestOptions,
  ): Promise<InboxReceipt> {
    return this.transport.post<InboxReceipt>(
      `/turns/${encodeURIComponent(turnId)}/input`,
      { ...options, body },
    );
  }

  /** POST /v2/turns/{id}/reply — answer the current question by id. */
  reply(
    turnId: string,
    body: TurnReplyBody,
    options?: RequestOptions,
  ): Promise<InboxReceipt> {
    return this.transport.post<InboxReceipt>(
      `/turns/${encodeURIComponent(turnId)}/reply`,
      { ...options, body },
    );
  }

  /** POST /v2/turns/{id}/grant — grant budget cycles; never a reply. */
  grant(
    turnId: string,
    body: TurnGrantBody,
    options?: RequestOptions,
  ): Promise<TurnGrantReceipt> {
    return this.transport.post<TurnGrantReceipt>(
      `/turns/${encodeURIComponent(turnId)}/grant`,
      { ...options, body },
    );
  }

  /** POST /v2/turns/{id}/cancel — accept a cancel intent (no body). */
  cancel(
    turnId: string,
    options?: RequestOptions,
  ): Promise<TurnCancelReceipt> {
    return this.transport.post<TurnCancelReceipt>(
      `/turns/${encodeURIComponent(turnId)}/cancel`,
      options,
    );
  }

  /**
   * GET /v2/turns/{id}/interactions — active/retained handle projection:
   * items, pending_items and an optional queued_request. Empty items do not
   * end the page; follow next_continuation.
   */
  interactions(
    turnId: string,
    params?: ListPageParams,
    options?: RequestOptions,
  ): Promise<InteractionPage> {
    return this.transport.get<InteractionPage>(
      `/turns/${encodeURIComponent(turnId)}/interactions`,
      { ...options, query: { ...params } },
    );
  }
}
