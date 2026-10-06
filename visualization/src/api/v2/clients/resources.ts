/**
 * API-18: resolve an absolute or relative reference into a logical
 * ResourceLocator. Relative references need origin_ref; dynamic Memory
 * references need their original day/turn binding (missing bindings answer
 * 422 resource.unresolved_origin — never substitute today's latest).
 */

import type { HomeView, ResourceResolve } from "../types";
import type { RequestOptions, V2Transport } from "../transport";

export interface ResourceResolveParams {
  ref: string;
  origin_ref?: string;
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
