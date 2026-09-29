/**
 * API-15/16: ACP subagent directory and the MCP expand directory. All GETs
 * are side-effect free snapshots of the current generation — they never
 * connect or discover; only refreshServer() explicitly asks the owner to
 * connect/refresh one server.
 */

import type {
  AcpDirectory,
  McpServerRefresh,
  McpServersPage,
  McpToolsPage,
} from "../types";
import type { RequestOptions, V2Transport } from "../transport";
import type { ListPageParams } from "./paging";

export class CapabilitiesClient {
  constructor(private readonly transport: V2Transport) {}

  /** GET /v2/subagent — configured targets and live connections. */
  subagent(options?: RequestOptions): Promise<AcpDirectory> {
    return this.transport.get<AcpDirectory>("/subagent", options);
  }

  /** GET /v2/expand/servers — configured/enabled/connected/discovered page. */
  servers(
    params?: ListPageParams,
    options?: RequestOptions,
  ): Promise<McpServersPage> {
    return this.transport.get<McpServersPage>("/expand/servers", {
      ...options,
      query: { ...params },
    });
  }

  /**
   * GET /v2/expand/tools?server_id= — discovered tool summaries; a tool_name
   * returns that tool's complete schema.
   */
  tools(
    params: {
      server_id: string;
      tool_name?: string;
    } & ListPageParams,
    options?: RequestOptions,
  ): Promise<McpToolsPage> {
    return this.transport.get<McpToolsPage>("/expand/tools", {
      ...options,
      query: { ...params },
    });
  }

  /** POST /v2/expand/servers/{server_id}/refresh — explicit directory refresh. */
  refreshServer(
    serverId: string,
    options?: RequestOptions,
  ): Promise<McpServerRefresh> {
    return this.transport.post<McpServerRefresh>(
      `/expand/servers/${encodeURIComponent(serverId)}/refresh`,
      options,
    );
  }
}
