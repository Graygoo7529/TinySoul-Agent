/** Maintenance availability and request client. */

import type {
  CommandReceipt,
  MaintenanceRequest,
  MaintenanceStatus,
} from "../types";
import type { EndpointHttpTransport } from "./transport";

export class EndpointMaintenanceClient {
  constructor(private readonly transport: EndpointHttpTransport) {}

  status(): Promise<MaintenanceStatus> {
    return this.transport.request<MaintenanceStatus>("GET", "/v1/maintenance");
  }

  request(request: MaintenanceRequest): Promise<CommandReceipt> {
    return this.transport.request<CommandReceipt>("POST", "/v1/maintenance", {
      body: request,
    });
  }
}
