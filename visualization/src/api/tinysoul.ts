/** Aggregate client for the TinySoul local Endpoint protocol. */

import type { ConnectionInfo } from "../types";
import { EndpointConfigurationClient } from "./configuration";
import { EndpointEventsClient } from "./events";
import { EndpointMaintenanceClient } from "./maintenance";
import { EndpointRuntimeClient } from "./runtime";
import { EndpointHttpTransport } from "./transport";
import { EndpointWorkspaceClient } from "./workspace";

export class TinySoulClient {
  readonly runtime: EndpointRuntimeClient;
  readonly maintenance: EndpointMaintenanceClient;
  readonly events: EndpointEventsClient;
  readonly configuration: EndpointConfigurationClient;
  readonly workspace: EndpointWorkspaceClient;

  constructor(info: ConnectionInfo) {
    const transport = new EndpointHttpTransport(info);
    this.runtime = new EndpointRuntimeClient(transport);
    this.maintenance = new EndpointMaintenanceClient(transport);
    this.events = new EndpointEventsClient(transport, info);
    this.configuration = new EndpointConfigurationClient(transport);
    this.workspace = new EndpointWorkspaceClient(transport);
  }
}

export { TinySoulApiError } from "./transport";
