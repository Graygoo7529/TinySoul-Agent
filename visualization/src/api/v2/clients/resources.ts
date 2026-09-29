/**
 * API-18: resolve a link/ref/relative reference into a logical
 * ResourceLocator. Relative references need origin_link; dynamic Memory
 * references need their original day/turn binding (missing bindings answer
 * 422 resource.unresolved_origin — never substitute today's latest).
 */

import type { HomeView, ResourceResolve } from "../types";
import type { RequestOptions, V2Transport } from "../transport";

export interface ResourceResolveParams {
  reference: string;
  origin_link?: string;
  day?: string;
  turn_id?: string;
  view?: HomeView;
}

export class ResourcesClient {
  constructor(private readonly transport: V2Transport) {}

  /** GET /v2/resources/resolve — kind + locator + capabilities. */
  resolve(
    params: ResourceResolveParams,
    options?: RequestOptions,
  ): Promise<ResourceResolve> {
    return this.transport.get<ResourceResolve>("/resources/resolve", {
      ...options,
      query: { ...params },
    });
  }
}
