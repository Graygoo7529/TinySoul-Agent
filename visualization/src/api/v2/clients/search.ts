/**
 * API-13: page-level Search over the SDK owner services. Scopes are
 * effective Home, persistent Memory and the active Workspace (no actual-Home
 * or archive search). A continuation request body carries only the original
 * `continuation` token — never the query/steps again. The result cursor is
 * the top-level SearchPage.continuation; page.continuation is window
 * metadata. Frozen pages never re-run model steps.
 */

import type { SearchContinuationRequest, SearchPage, SearchRequest } from "../types";
import type { RequestOptions, V2Transport } from "../transport";

export type SearchRequestBody = SearchRequest | SearchContinuationRequest;

export class SearchClient {
  constructor(private readonly transport: V2Transport) {}

  /** POST /v2/home/search — effective Home scope. */
  searchHome(
    request: SearchRequestBody,
    options?: RequestOptions,
  ): Promise<SearchPage> {
    return this.transport.post<SearchPage>("/home/search", {
      ...options,
      body: request,
    });
  }

  /** POST /v2/memory/search — persistent Memory scope. */
  searchMemory(
    request: SearchRequestBody,
    options?: RequestOptions,
  ): Promise<SearchPage> {
    return this.transport.post<SearchPage>("/memory/search", {
      ...options,
      body: request,
    });
  }

  /** POST /v2/workspace/search — active Workspace scope. */
  searchWorkspace(
    request: SearchRequestBody,
    options?: RequestOptions,
  ): Promise<SearchPage> {
    return this.transport.post<SearchPage>("/workspace/search", {
      ...options,
      body: request,
    });
  }
}
