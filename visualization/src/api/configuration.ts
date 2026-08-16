/** Configuration status, catalog and activation client. */

import type {
  ActionCatalog,
  ConfigCatalog,
  ConfigPatchRequest,
  ConfigPatchResult,
  ConfigStatus,
} from "../types";
import type { EndpointHttpTransport } from "./transport";

export class EndpointConfigurationClient {
  constructor(private readonly transport: EndpointHttpTransport) {}

  status(): Promise<ConfigStatus> {
    return this.transport.request<ConfigStatus>("GET", "/v1/config");
  }

  catalog(): Promise<ConfigCatalog> {
    return this.transport.request<ConfigCatalog>("GET", "/v1/config/catalog");
  }

  actions(): Promise<ActionCatalog> {
    return this.transport.request<ActionCatalog>("GET", "/v1/config/actions");
  }

  patch(request: ConfigPatchRequest): Promise<ConfigPatchResult> {
    return this.transport.request<ConfigPatchResult>("PATCH", "/v1/config", {
      body: request,
    });
  }
}
