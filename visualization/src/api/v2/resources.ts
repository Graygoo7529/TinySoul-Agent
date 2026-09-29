/**
 * Reference resolution.
 * Schema: resource-resolve.json. There is no dedicated example in
 * docs/endpoint/contracts/examples/; the memory-fragment example is a
 * ResourceResolveResponse instance for `memory:current#notes`.
 */

import type { ResourceLocator } from "./common";

/** Schema: resource-resolve.json (GET /v2/resources/resolve). */
export interface ResourceResolve {
  kind: string;
  locator: ResourceLocator;
  capabilities?: string[];
  resolved_from?: string | null;
  [key: string]: unknown;
}
