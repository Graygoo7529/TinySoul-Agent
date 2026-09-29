/**
 * Typed v2 clients, one per Endpoint owner (API-01…API-18). Each client is
 * stateless beyond the shared transport: no caching, no retry scheduling.
 * Page-returning methods read one page; use drainPages (paging.ts) when a
 * caller explicitly wants a whole read sequence.
 */

import type { V2Transport } from "../transport";
import { CapabilitiesClient } from "./capabilities";
import { ConfigClient } from "./config";
import { ContextClient } from "./context";
import { EventsClient } from "./events";
import { HealthClient } from "./health";
import { HomeClient } from "./home";
import { JobsClient } from "./jobs";
import { MemoryClient } from "./memory";
import { ReflectionClient } from "./reflection";
import { ResourcesClient } from "./resources";
import { SearchClient } from "./search";
import { SessionClient } from "./session";
import { TurnsClient } from "./turns";
import { WorkspaceClient } from "./workspace";

export { CapabilitiesClient } from "./capabilities";
export { ConfigClient } from "./config";
export { ContextClient } from "./context";
export {
  EventsClient,
  EventsSocket,
  eventsAuthFrame,
  parseEventsServerFrame,
} from "./events";
export type {
  EventsReplayParams,
  EventsSocketCloseInfo,
  EventsSocketHandlers,
  EventsSocketParams,
  EventsWebSocketFactory,
  EventsWebSocketLike,
} from "./events";
export { HealthClient } from "./health";
export { HomeClient } from "./home";
export { JobsClient } from "./jobs";
export { MemoryClient } from "./memory";
export {
  drainPages,
} from "./paging";
export type {
  ContinuationParams,
  DrainOptions,
  DrainPageShape,
  DrainResult,
  ListPageParams,
} from "./paging";
export { ReflectionClient } from "./reflection";
export { ResourcesClient } from "./resources";
export type { ResourceResolveParams } from "./resources";
export { SearchClient } from "./search";
export type { SearchRequestBody } from "./search";
export { SessionClient } from "./session";
export { TurnsClient } from "./turns";
export { formatByteRange, WorkspaceClient } from "./workspace";
export type { ByteRange } from "./workspace";

/** All owner clients over one shared transport. */
export interface V2Clients {
  health: HealthClient;
  turns: TurnsClient;
  reflection: ReflectionClient;
  config: ConfigClient;
  session: SessionClient;
  context: ContextClient;
  home: HomeClient;
  memory: MemoryClient;
  workspace: WorkspaceClient;
  search: SearchClient;
  jobs: JobsClient;
  capabilities: CapabilitiesClient;
  events: EventsClient;
  resources: ResourcesClient;
}

export function createV2Clients(transport: V2Transport): V2Clients {
  return {
    health: new HealthClient(transport),
    turns: new TurnsClient(transport),
    reflection: new ReflectionClient(transport),
    config: new ConfigClient(transport),
    session: new SessionClient(transport),
    context: new ContextClient(transport),
    home: new HomeClient(transport),
    memory: new MemoryClient(transport),
    workspace: new WorkspaceClient(transport),
    search: new SearchClient(transport),
    jobs: new JobsClient(transport),
    capabilities: new CapabilitiesClient(transport),
    events: new EventsClient(transport),
    resources: new ResourcesClient(transport),
  };
}
