/**
 * API-01: liveness, runtime status and host restart.
 * GET /v2/health is anonymous; /status and /restart still go through the
 * authenticated transport (a Bearer header on /health is harmless).
 */

import type { CommandReceipt, HealthStatus, RuntimeStatus } from "../types";
import type { RequestOptions, V2Transport } from "../transport";

export class HealthClient {
  constructor(private readonly transport: V2Transport) {}

  /** GET /v2/health — anonymous process liveness. */
  health(options?: RequestOptions): Promise<HealthStatus> {
    return this.transport.get<HealthStatus>("/health", options);
  }

  /** GET /v2/status — instance/project identity, ready flag, runtime. */
  status(options?: RequestOptions): Promise<RuntimeStatus> {
    return this.transport.get<RuntimeStatus>("/status", options);
  }

  /**
   * POST /v2/restart — ask the host to rebuild the Agent generation. The
   * receipt carries the new runtime projection; the Endpoint instance and
   * event cursor stay stable (docs/endpoint/runtime.md).
   */
  restart(options?: RequestOptions): Promise<CommandReceipt> {
    return this.transport.post<CommandReceipt>("/restart", options);
  }
}
