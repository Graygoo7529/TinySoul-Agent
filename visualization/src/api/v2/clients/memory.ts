/**
 * API-11: Memory reading. The active Memory.md (per day) and the persistent
 * daily/entity/concept/fact/note documents are separate objects; a redirect
 * keeps the original document identity and resolution chain in metadata.
 */

import type {
  MemoryActivePage,
  MemoryCatalogPage,
  MemoryDocumentKind,
  MemoryDocumentPage,
} from "../types";
import type { RequestOptions, V2Transport } from "../transport";
import type { ContinuationParams, ListPageParams } from "./paging";

export class MemoryClient {
  constructor(private readonly transport: V2Transport) {}

  /** GET /v2/memory/active — the active day's Memory.md (or an archive day). */
  active(
    params?: { day?: string } & ContinuationParams,
    options?: RequestOptions,
  ): Promise<MemoryActivePage> {
    return this.transport.get<MemoryActivePage>("/memory/active", {
      ...options,
      query: { ...params },
    });
  }

  /** GET /v2/memory/catalog — persistent documents by kind; query filters. */
  catalog(
    params?: ListPageParams & { kind?: MemoryDocumentKind; query?: string },
    options?: RequestOptions,
  ): Promise<MemoryCatalogPage> {
    return this.transport.get<MemoryCatalogPage>("/memory/catalog", {
      ...options,
      query: { ...params },
    });
  }

  /** GET /v2/memory/document?link= — document body, refs and redirect chain. */
  document(
    params: { link: string } & ContinuationParams,
    options?: RequestOptions,
  ): Promise<MemoryDocumentPage> {
    return this.transport.get<MemoryDocumentPage>("/memory/document", {
      ...options,
      query: { ...params },
    });
  }
}
