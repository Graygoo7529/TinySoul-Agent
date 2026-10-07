/**
 * API-10: Home reading. The default view is effective (what the next run
 * uses); actual is the accepted baseline. All reads are page.json envelopes;
 * content/diff items carry {ref, text} plus owner metadata (locator,
 * paged reference hints, baseline_diverged).
 */

import type {
  HomeCatalogPage,
  HomeChangesPage,
  HomeContentPage,
  HomeDiffPage,
  HomeView,
} from "../types";
import type { RequestOptions, V2Transport } from "../transport";
import type { ContinuationParams, ListPageParams } from "./paging";

export class HomeClient {
  constructor(private readonly transport: V2Transport) {}

  /** GET /v2/home/catalog — locators/titles; query filters names only. */
  catalog(
    params?: ListPageParams & { view?: HomeView; space?: string; query?: string },
    options?: RequestOptions,
  ): Promise<HomeCatalogPage> {
    return this.transport.get<HomeCatalogPage>("/home/catalog", {
      ...options,
      query: { ...params },
    });
  }

  /** GET /v2/home/content?ref= — body text plus direct refs. */
  content(
    params: { ref: string; view?: HomeView } & ContinuationParams,
    options?: RequestOptions,
  ): Promise<HomeContentPage> {
    return this.transport.get<HomeContentPage>("/home/content", {
      ...options,
      query: { ...params },
    });
  }

  /** GET /v2/home/changes — overlay create/modify/delete entries (read-only). */
  changes(
    params?: ListPageParams,
    options?: RequestOptions,
  ): Promise<HomeChangesPage> {
    return this.transport.get<HomeChangesPage>("/home/changes", {
      ...options,
      query: { ...params },
    });
  }

  /** GET /v2/home/diff?ref= — actual/effective diff chunks. */
  diff(
    params: { ref: string } & ContinuationParams,
    options?: RequestOptions,
  ): Promise<HomeDiffPage> {
    return this.transport.get<HomeDiffPage>("/home/diff", {
      ...options,
      query: { ...params },
    });
  }
}
