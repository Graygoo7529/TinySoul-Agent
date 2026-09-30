/**
 * MCP Servers settings (config-coverage §4.5): configured servers are
 * collection objects edited atomically; the read-only runtime directory
 * (connected/discovered/tools) is a summary with a jump to Runtime
 * Observation — editing configuration never starts a server.
 */

import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";

import type { JsonValue, McpServersPage } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { SectionCard } from "../../../components/ui/Card";
import { Collapsible } from "../../../components/ui/Collapsible";
import { useConnectionStore } from "../../../store/connectionStore";
import { useAppStore } from "../../../store/appStore";
import { FieldSection } from "./controls";
import {
  CollectionObjectEditor,
  ObjBoolean,
  ObjMap,
  ObjRow,
  ObjStringList,
  ObjText,
  type ObjectEditContext,
} from "./collection";

const ROOT = "capabilities.expand.servers";

export function McpPage() {
  return (
    <CollectionObjectEditor
      collectionId="capabilities.expand.servers"
      runtimeSummary={<McpRuntimeSummary />}
      renderFields={(ctx) => <McpServerFields ctx={ctx} />}
      limits={
        <FieldSection
          title="Shared MCP Limits"
          description="Directory and call bounds shared by all servers."
          paths={[
            "capabilities.expand.timeout_seconds",
            "capabilities.expand.max_tools",
            "capabilities.expand.max_catalog_bytes",
            "capabilities.expand.max_result_bytes",
            "capabilities.expand.max_inline_chars",
            "capabilities.expand.search_max_chars",
            "capabilities.expand.page_size",
          ]}
          overrides={{
            "capabilities.expand.timeout_seconds": { min: 1 },
            "capabilities.expand.max_tools": { min: 1 },
            "capabilities.expand.max_catalog_bytes": { min: 1 },
            "capabilities.expand.max_result_bytes": { min: 1 },
            "capabilities.expand.max_inline_chars": { min: 1 },
            "capabilities.expand.search_max_chars": { min: 1 },
            "capabilities.expand.page_size": { min: 1 },
          }}
        />
      }
    />
  );
}

function McpServerFields({ ctx }: { ctx: ObjectEditContext }) {
  const disabled = ctx.readOnly !== null;
  const at = (name: string) => `${ROOT}.${ctx.id}.${name}`;
  const text = (name: string): string =>
    typeof ctx.object[name] === "string" ? (ctx.object[name] as string) : "";
  const bool = (name: string, fallback: boolean): boolean =>
    typeof ctx.object[name] === "boolean" ? (ctx.object[name] as boolean) : fallback;
  const list = (name: string): string[] =>
    Array.isArray(ctx.object[name])
      ? ctx.object[name].filter(
          (item): item is string => typeof item === "string",
        )
      : [];
  const map = (name: string): Record<string, JsonValue> =>
    ctx.object[name] !== null &&
    typeof ctx.object[name] === "object" &&
    !Array.isArray(ctx.object[name])
      ? (ctx.object[name] as Record<string, JsonValue>)
      : {};

  const transport = text("transport") === "streamable_http" ? "streamable_http" : "stdio";

  return (
    <>
      <ObjRow path={at("enabled")}>
        <ObjBoolean
          value={bool("enabled", false)}
          disabled={disabled}
          onChange={(next) => ctx.update({ enabled: next })}
        />
      </ObjRow>
      <ObjRow path={at("description")}>
        <ObjText
          value={text("description")}
          disabled={disabled}
          placeholder="What this server provides"
          onChange={(next) => ctx.update({ description: next })}
        />
      </ObjRow>
      <ObjRow path={at("transport")}>
        <select
          className="h-8 rounded-md border border-line bg-bg px-2 text-[12.5px] text-fg outline-none focus:border-accent disabled:opacity-50"
          value={transport}
          disabled={disabled}
          onChange={(event) =>
            ctx.update({ transport: event.target.value })
          }
        >
          <option value="stdio">Local stdio</option>
          <option value="streamable_http">Streamable HTTP</option>
        </select>
      </ObjRow>
      {transport === "stdio" ? (
        <>
          <ObjRow path={at("command")}>
            <ObjText
              value={text("command")}
              mono
              disabled={disabled}
              placeholder="e.g. npx"
              onChange={(next) => ctx.update({ command: next })}
            />
          </ObjRow>
          <ObjRow path={at("args")}>
            <ObjStringList
              value={list("args")}
              disabled={disabled}
              onChange={(next) => ctx.update({ args: next })}
            />
          </ObjRow>
          <ObjRow path={at("cwd")}>
            <ObjText
              value={text("cwd")}
              mono
              disabled={disabled}
              placeholder="Working directory (optional)"
              onChange={(next) => ctx.update({ cwd: next })}
            />
          </ObjRow>
          <ObjRow path={at("env")} label="env">
            <ObjMap
              value={map("env")}
              disabled={disabled}
              keyPlaceholder="VARIABLE"
              valuePlaceholder="value"
              onChange={(next) => ctx.update({ env: next })}
            />
          </ObjRow>
          <ObjRow path={at("env_refs")} label="env_refs">
            <ObjMap
              value={map("env_refs")}
              disabled={disabled}
              credentialValues
              keyPlaceholder="VARIABLE"
              valuePlaceholder="DOTENV_NAME"
              onChange={(next) => ctx.update({ env_refs: next })}
            />
          </ObjRow>
        </>
      ) : (
        <>
          <ObjRow path={at("url")}>
            <ObjText
              value={text("url")}
              mono
              disabled={disabled}
              placeholder="https://…"
              onChange={(next) => ctx.update({ url: next })}
            />
          </ObjRow>
          <ObjRow path={at("headers")} label="headers">
            <ObjMap
              value={map("headers")}
              disabled={disabled}
              keyPlaceholder="Header-Name"
              valuePlaceholder="value"
              onChange={(next) => ctx.update({ headers: next })}
            />
          </ObjRow>
          <ObjRow path={at("header_refs")} label="header_refs">
            <ObjMap
              value={map("header_refs")}
              disabled={disabled}
              credentialValues
              keyPlaceholder="Header-Name"
              valuePlaceholder="DOTENV_NAME"
              onChange={(next) => ctx.update({ header_refs: next })}
            />
          </ObjRow>
        </>
      )}
      <ObjRow path={at("tools_default")} label="tools_default">
        <ObjBoolean
          value={bool("tools_default", true)}
          disabled={disabled}
          onChange={(next) => ctx.update({ tools_default: next })}
        />
      </ObjRow>
      <ObjRow path={at("tools")} label="tools">
        <Collapsible
          title={
            <span className="text-fg-muted">
              Per-tool overrides ({Object.keys(map("tools")).length})
            </span>
          }
          tone="sunken"
        >
          <div className="mb-1.5 text-[10.5px] leading-4 text-fg-faint">
            Exact remote tool names (dots included) map to booleans; each
            choice overrides the default policy. The whole map applies as one
            value.
          </div>
          <ObjMap
            value={map("tools")}
            disabled={disabled}
            booleanValues
            keyPlaceholder="remote.tool.name"
            onChange={(next) => ctx.update({ tools: next })}
          />
        </Collapsible>
      </ObjRow>
    </>
  );
}

/** Read-only runtime directory summary; configuration edits never connect. */
function McpRuntimeSummary() {
  const clients = useConnectionStore((s) => s.clients);
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const [page, setPage] = useState<McpServersPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (clients === null) return;
    clients.capabilities
      .servers()
      .then((result) => {
        if (!cancelled) setPage(result);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "Unavailable");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [clients]);

  return (
    <SectionCard
      title="Runtime directory"
      description="Live connection facts of the running generation. Applying configuration does not connect servers by itself; refresh happens on activation or from Runtime Observation."
      actions={
        <button
          type="button"
          className="flex items-center gap-1 text-[12px] font-medium text-accent hover:underline"
          onClick={() => setActiveTab("runtime")}
        >
          Runtime Observation <ArrowRight size={12} />
        </button>
      }
    >
      {clients === null ? (
        <div className="text-[12px] text-fg-faint">
          No backend connection — runtime facts are unavailable.
        </div>
      ) : error !== null ? (
        <div className="text-[12px] text-fg-faint">
          The runtime directory is unavailable: {error}
        </div>
      ) : page === null ? (
        <div className="text-[12px] text-fg-faint">Loading…</div>
      ) : page.items.length === 0 ? (
        <div className="text-[12px] text-fg-faint">
          No servers are visible to the running generation yet.
        </div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {page.items.map((item) => (
            <span
              key={item.server_id}
              className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-[11.5px]"
              title={item.error ?? undefined}
            >
              <span className="font-mono text-fg">{item.server_id}</span>
              {!item.enabled ? (
                <Badge tone="gray">disabled</Badge>
              ) : item.connected ? (
                <Badge tone="green">connected</Badge>
              ) : (
                <Badge tone="yellow">not connected</Badge>
              )}
              {item.discovered && (
                <Badge tone={item.stale ? "yellow" : "blue"}>
                  {item.tool_count} tools{item.stale ? " (stale)" : ""}
                </Badge>
              )}
              {item.error !== null && <Badge tone="red">error</Badge>}
            </span>
          ))}
        </div>
      )}
    </SectionCard>
  );
}
