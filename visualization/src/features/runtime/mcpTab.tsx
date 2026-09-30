/**
 * MCP tab (plan §14 MCP, API-16).
 *
 * Four facts stay separate everywhere: configured/enabled (configuration),
 * connected (runtime transport), discovered (directory cache) and callable
 * (per tool, with its reason). Opening the tab or filtering by name issues
 * only side-effect-free reads — it never connects; the explicit "Refresh
 * directory" button is the only path that asks the owner to connect, and it
 * binds exactly one server. A tool's configuration selection comes from the
 * active configuration view (one lazy read per tab), shown next to the
 * discovered definition — never merged into a single traffic light.
 */

import { useMemo, useRef, useState, type ReactElement } from "react";
import { ChevronRight, Plug, RefreshCw, Send } from "lucide-react";

import type {
  Configuration,
  McpServerEntry,
  McpServersPage,
} from "../../api/v2/types";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Collapsible } from "../../components/ui/Collapsible";
import { EmptyState } from "../../components/ui/EmptyState";
import { JsonTree } from "../../components/ui/JsonTree";
import { useAppStore } from "../../store/appStore";
import { useSettingsUiStore } from "../settings/uiStore";
import { useComposerDraft } from "../chat/composerDraft";
import { usePagedSequence } from "../history/usePagedSequence";
import { useAsyncRead } from "../trace/panelShared";
import {
  narrowToolDetail,
  narrowToolSummary,
  toolSelection,
  type McpToolSummary,
} from "./mcpModel";
import { errorMessage, runtimeClients } from "./runtimeModel";
import { LoadingRow, ReadError } from "./shared";

/** Tools page with its items narrowed past the dynamic boundary. */
interface ToolPage {
  items: McpToolSummary[];
  next_continuation?: string | null;
}

export function McpTab({ epoch }: { epoch: number }): ReactElement {
  const [filter, setFilter] = useState("");
  const [selectedServer, setSelectedServer] = useState<string | null>(null);
  // One lazy active-configuration read per tab; tool details derive their
  // selection from it without re-reading per tool.
  const configRef = useRef<Promise<Configuration> | null>(null);
  const activeConfig = (): Promise<Configuration> => {
    configRef.current ??= runtimeClients(epoch).config.get("active");
    return configRef.current;
  };

  const servers = usePagedSequence<McpServerEntry, McpServersPage>(
    (token, signal) =>
      runtimeClients(epoch).capabilities.servers(
        { continuation: token ?? undefined, limit: 50 },
        { signal },
      ),
    (page) => page.next_continuation ?? null,
    [epoch],
  );

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (needle === "") return servers.items;
    return servers.items.filter(
      (server) =>
        server.server_id.toLowerCase().includes(needle) ||
        server.description.toLowerCase().includes(needle),
    );
  }, [servers.items, filter]);

  if (servers.loading) {
    return <LoadingRow text="Reading the server directory…" />;
  }
  if (servers.items.length === 0 && servers.error === null) {
    return (
      <EmptyState
        icon={<Plug size={26} />}
        title="No MCP servers configured"
        description="Servers are configuration facts — configure one in settings before its directory can be discovered."
        action={
          <Button variant="outline" size="sm" onClick={() => openMcpSettings()}>
            Configure servers
          </Button>
        }
      />
    );
  }
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter by name or description…"
          className="h-8 w-64 rounded-lg border border-line bg-bg-elev px-2.5 text-[13px] outline-none placeholder:text-fg-faint focus:border-line-strong"
        />
        <span className="text-[11px] text-fg-faint">
          Filtering never connects — only the explicit refresh does.
        </span>
      </div>
      {servers.error !== null && (
        <ReadError message={servers.error} onRetry={servers.reload} />
      )}
      <div className="space-y-1.5">
        {visible.map((server) => (
          <ServerRow
            key={server.server_id}
            epoch={epoch}
            server={server}
            selected={server.server_id === selectedServer}
            onSelect={() =>
              setSelectedServer((current) =>
                current === server.server_id ? null : server.server_id,
              )
            }
            onRefreshed={() => servers.reload()}
          />
        ))}
      </div>
      {servers.next !== null && (
        <Button
          variant="outline"
          size="xs"
          loading={servers.loadingMore}
          onClick={servers.loadMore}
        >
          More servers
        </Button>
      )}
      {selectedServer !== null && (
        <ServerTools
          epoch={epoch}
          serverId={selectedServer}
          activeConfig={activeConfig}
        />
      )}
    </div>
  );
}

function ServerRow({
  epoch,
  server,
  selected,
  onSelect,
  onRefreshed,
}: {
  epoch: number;
  server: McpServerEntry;
  selected: boolean;
  onSelect: () => void;
  onRefreshed: () => void;
}): ReactElement {
  const [refreshing, setRefreshing] = useState(false);
  const [refreshNote, setRefreshNote] = useState<string | null>(null);

  const refresh = async (): Promise<void> => {
    setRefreshing(true);
    setRefreshNote(null);
    try {
      const result = await runtimeClients(epoch).capabilities.refreshServer(
        server.server_id,
      );
      if (result.status !== "available") {
        setRefreshNote(
          result.reason ?? `refresh answered "${result.status}" — the known directory stays`,
        );
      }
      onRefreshed();
    } catch (error) {
      setRefreshNote(errorMessage(error));
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="rounded-lg border border-line bg-bg-elev">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <button
          type="button"
          onClick={onSelect}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <ChevronRight
            size={13}
            className={`shrink-0 text-fg-faint transition-transform ${selected ? "rotate-90" : ""}`}
          />
          <span className="shrink-0 text-[13px] font-medium">
            {server.server_id}
          </span>
          <span className="min-w-0 truncate text-[12px] text-fg-muted">
            {server.description}
          </span>
        </button>
        <Badge tone={server.enabled ? "green" : "gray"}>
          {server.enabled ? "enabled" : "disabled"}
        </Badge>
        <Badge tone={server.connected ? "blue" : "gray"}>
          {server.connected ? "connected" : "not connected"}
        </Badge>
        <Badge tone={server.discovered ? "teal" : "gray"}>
          {server.discovered
            ? `discovered · ${server.tool_count} tools`
            : "not discovered"}
        </Badge>
        {server.stale && <Badge tone="yellow">stale</Badge>}
        {server.error !== null && (
          <Badge tone="red" title={server.error}>
            error
          </Badge>
        )}
        <Button
          variant="outline"
          size="xs"
          loading={refreshing}
          disabled={!server.enabled}
          title={
            server.enabled
              ? "Refresh this server's directory"
              : "Enable the server in settings before refreshing"
          }
          onClick={() => void refresh()}
        >
          <RefreshCw size={12} />
          Refresh directory
        </Button>
      </div>
      {refreshNote !== null && (
        <div className="border-t border-line px-3 py-1.5 text-[11px] text-warning">
          Refresh failed ({refreshNote}); the previous directory stays.
        </div>
      )}
      {server.error !== null && (
        <div className="border-t border-line px-3 py-1.5 text-[11px] text-danger">
          {server.error}
        </div>
      )}
    </div>
  );
}

/** The discovered tool directory of one server — paged, side-effect free. */
function ServerTools({
  epoch,
  serverId,
  activeConfig,
}: {
  epoch: number;
  serverId: string;
  activeConfig: () => Promise<Configuration>;
}): ReactElement {
  const [selectedTool, setSelectedTool] = useState<string | null>(null);
  // Page-level `discovered` fact of the latest tools page (the hook surfaces
  // items only; the fetch closure records the base fact alongside).
  const discoveredRef = useRef<boolean | null>(null);
  const tools = usePagedSequence<McpToolSummary, ToolPage>(
    async (token, signal) => {
      const page = await runtimeClients(epoch).capabilities.tools(
        { server_id: serverId, continuation: token ?? undefined, limit: 50 },
        { signal },
      );
      discoveredRef.current = page.discovered;
      return {
        items: page.items
          .map(narrowToolSummary)
          .filter((tool): tool is McpToolSummary => tool !== null),
        next_continuation: page.next_continuation,
      };
    },
    (page) => page.next_continuation ?? null,
    [epoch, serverId],
  );

  if (tools.loading) {
    return <LoadingRow text="Reading the discovered tools…" />;
  }
  return (
    <div className="space-y-1.5 rounded-lg border border-line bg-bg-sunken px-3 py-3">
      <div className="text-[12px] font-medium text-fg-faint">
        Tools of {serverId}
      </div>
      {tools.error !== null && (
        <ReadError message={tools.error} onRetry={tools.reload} />
      )}
      {tools.items.length === 0 && tools.error === null ? (
        <div className="flex flex-wrap items-center gap-2 text-[12px] text-fg-faint">
          {discoveredRef.current === false
            ? "This server's directory was never discovered — use its explicit refresh to read the tools."
            : "The discovered directory has no tools."}
        </div>
      ) : (
        tools.items.map((tool) => (
          <div key={tool.name}>
            <button
              type="button"
              onClick={() =>
                setSelectedTool((current) =>
                  current === tool.name ? null : tool.name,
                )
              }
              className={`flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors ${
                selectedTool === tool.name
                  ? "border-accent/50 bg-accent-soft"
                  : "border-line bg-bg-elev hover:border-line-strong hover:bg-hover"
              }`}
            >
              <span className="shrink-0 text-[13px] font-medium">
                {tool.name}
              </span>
              <span className="min-w-0 flex-1 truncate text-[12px] text-fg-muted">
                {tool.description}
              </span>
              {tool.callable ? (
                <Badge tone="green">callable</Badge>
              ) : (
                <Badge tone="red" title={tool.unavailable ?? "unavailable"}>
                  unavailable
                </Badge>
              )}
            </button>
            {selectedTool === tool.name && (
              <ToolDetail
                epoch={epoch}
                serverId={serverId}
                tool={tool}
                activeConfig={activeConfig}
              />
            )}
          </div>
        ))
      )}
      {tools.next !== null && (
        <Button
          variant="outline"
          size="xs"
          loading={tools.loadingMore}
          onClick={tools.loadMore}
        >
          More tools
        </Button>
      )}
    </div>
  );
}

/** One tool's complete definition plus its configuration selection. */
function ToolDetail({
  epoch,
  serverId,
  tool,
  activeConfig,
}: {
  epoch: number;
  serverId: string;
  tool: McpToolSummary;
  activeConfig: () => Promise<Configuration>;
}): ReactElement {
  const read = useAsyncRead(async (signal) => {
    const clients = runtimeClients(epoch);
    const [page, config] = await Promise.all([
      clients.capabilities.tools(
        { server_id: serverId, tool_name: tool.name },
        { signal },
      ),
      activeConfig(),
    ]);
    const detail = page.items.map(narrowToolDetail).find((item) => item !== null);
    return {
      definition: detail?.definition ?? null,
      selection: toolSelection(config.fields, serverId, tool.name),
    };
  }, [epoch, serverId, tool.name]);

  return (
    <div className="mt-1 space-y-2 rounded-lg border border-line bg-bg-elev px-3 py-2.5">
      {read.kind === "loading" && <LoadingRow text="Reading the tool…" />}
      {read.kind === "error" && <ReadError message={read.message} />}
      {!tool.callable && tool.unavailable !== null && (
        <div className="text-[12px] text-danger">{tool.unavailable}</div>
      )}
      {read.kind === "ready" && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-[12px]">
            <span className="text-fg-faint">Configuration selection</span>
            <Badge tone={read.value.selection.selected ? "green" : "gray"}>
              {read.value.selection.selected ? "selected" : "not selected"}
            </Badge>
            <span className="text-fg-faint">
              by {read.value.selection.basis}
            </span>
            <span className="flex-1" />
            <Button
              variant="ghost"
              size="xs"
              onClick={() => openMcpSettings(serverId)}
            >
              Edit configuration
            </Button>
            <Button
              variant="ghost"
              size="xs"
              onClick={() => useToolDraft(serverId, tool)}
            >
              <Send size={12} />
              Use in conversation
            </Button>
          </div>
          {read.value.definition !== null && (
            <Collapsible title="Definition">
              <JsonTree value={read.value.definition} defaultExpanded={false} />
            </Collapsible>
          )}
        </>
      )}
    </div>
  );
}

function openMcpSettings(serverId?: string): void {
  useSettingsUiStore
    .getState()
    .navigateTo(
      "mcp",
      serverId !== undefined
        ? `capabilities.expand.servers.${serverId}.tools`
        : null,
    );
  useAppStore.getState().setActiveTab("settings");
}

/** Fill an editable draft referencing the tool — it never calls the tool. */
function useToolDraft(serverId: string, tool: McpToolSummary): void {
  const description = tool.description !== "" ? ` — ${tool.description}` : "";
  useComposerDraft
    .getState()
    .setDraft(
      `Please use the MCP tool ${tool.name} of server ${serverId}${description}: `,
    );
  useAppStore.getState().setActiveTab("chat");
}
