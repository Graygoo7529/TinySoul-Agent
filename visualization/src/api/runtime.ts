/** Runtime status and command client. */

import type {
  BackendStatus,
  CommandReceipt,
  ControlRequest,
  InputRequest,
} from "../types";
import type { EndpointHttpTransport } from "./transport";

export class EndpointRuntimeClient {
  constructor(private readonly transport: EndpointHttpTransport) {}

  status(): Promise<BackendStatus> {
    return this.transport.request<BackendStatus>("GET", "/v1/status");
  }

  submitInput(request: InputRequest): Promise<CommandReceipt> {
    return this.transport.request<CommandReceipt>("POST", "/v1/input", {
      body: request,
    });
  }

  submitControl(request: ControlRequest): Promise<CommandReceipt> {
    return this.transport.request<CommandReceipt>("POST", "/v1/control", {
      body: request,
    });
  }
}
