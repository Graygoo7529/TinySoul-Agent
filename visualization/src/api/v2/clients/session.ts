/**
 * API-08: day directory and committed Session reads. History is read from
 * these owner projections, not from event replay. `/days` and turn lists
 * page with before/continuation; a turn detail requires its owning day.
 */

import type {
  BackgroundPage,
  DaysPage,
  DisclosurePage,
  InteractionPage,
  SessionTurnsPage,
} from "../types";
import type { RequestOptions, V2Transport } from "../transport";
import type { ContinuationParams, ListPageParams } from "./paging";

export class SessionClient {
  constructor(private readonly transport: V2Transport) {}

  background(turnId: string, params: { day: string } & ContinuationParams, options?: RequestOptions): Promise<BackgroundPage> {
    return this.transport.get<BackgroundPage>(`/session/turns/${turnId.split("/").map(encodeURIComponent).join("/")}/background`,
      { ...options, query: { ...params } });
  }

  /**
   * GET /v2/days?before=&limit= — active and archived days, newest first.
   * Continue with `before=<next_before>`; null ends the sequence.
   */
  days(
    params?: { before?: string; limit?: number },
    options?: RequestOptions,
  ): Promise<DaysPage> {
    return this.transport.get<DaysPage>("/days", {
      ...options,
      query: { ...params },
    });
  }

  /** GET /v2/session/turns — committed Turn summaries (default: active day). */
  turns(
    params?: ListPageParams & { day?: string },
    options?: RequestOptions,
  ): Promise<SessionTurnsPage> {
    return this.transport.get<SessionTurnsPage>("/session/turns", {
      ...options,
      query: { ...params },
    });
  }

  /** GET /v2/session/turns/{id}?day= — formal Session interaction page. */
  turn(
    turnId: string,
    params: { day: string } & ContinuationParams,
    options?: RequestOptions,
  ): Promise<InteractionPage> {
    return this.transport.get<InteractionPage>(
      `/session/turns/${turnId.split("/").map(encodeURIComponent).join("/")}`,
      { ...options, query: { ...params } },
    );
  }

  /** GET /v2/session/map — the session:map DisclosurePage. */
  map(
    params?: { day?: string; continuation?: string },
    options?: RequestOptions,
  ): Promise<DisclosurePage> {
    return this.transport.get<DisclosurePage>("/session/map", {
      ...options,
      query: { ...params },
    });
  }

  /** GET /v2/session/inspect — deterministic disclosure of records/notes. */
  inspect(
    params: {
      day: string;
      ref?: string;
      query?: string;
      continuation?: string;
    },
    options?: RequestOptions,
  ): Promise<DisclosurePage> {
    return this.transport.get<DisclosurePage>("/session/inspect", {
      ...options,
      query: { ...params },
    });
  }
}
