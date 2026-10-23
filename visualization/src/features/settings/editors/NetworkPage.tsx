import { useEffect, useState } from "react";

import type { NetworkProxyAddress, NetworkRouteStatus, NetworkStatus } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { SectionCard } from "../../../components/ui/Card";
import { useConnectionStore } from "../../../store/connectionStore";
import { useConfigDraftStore } from "../draft/store";
import { settingsText } from "../i18n";
import { pageForPath } from "../pages";
import { useSettingsUiStore } from "../uiStore";
import { SettingsPageBody } from "./controls";
import { NetworkPolicyField } from "./NetworkPolicyEditor";

/** Root network policy plus a read-only view of every configured consumer. */
export function NetworkPage() {
  const clients = useConnectionStore((state) => state.clients);
  const epoch = useConnectionStore((state) => state.epoch);
  const saved = useConfigDraftStore((state) => state.saved);
  const [status, setStatus] = useState<NetworkStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (clients === null) {
      setStatus(null);
      setError(null);
      return;
    }
    const controller = new AbortController();
    setStatus(null);
    setError(null);
    void clients.config.network({ signal: controller.signal }).then(
      (value) => { if (!controller.signal.aborted) setStatus(value); },
      (reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      },
    );
    return () => controller.abort();
  }, [clients, epoch, saved]);

  return (
    <SettingsPageBody>
      <NetworkPolicyField
        path="infra.network"
        root
        title={settingsText("Root network proxy")}
        parentLabel={settingsText("Process environment, then project .env (HTTP_PROXY / HTTPS_PROXY / ALL_PROXY / NO_PROXY)")}
      />
      <SectionCard
        title={settingsText("Saved network routes")}
        description={settingsText("Routes resolved from saved settings, including disabled entries. Edit overrides on the corresponding settings page; apply configuration to activate changes.")}
      >
        {status === null && error === null && (
          <p className="text-xs text-fg-faint">{settingsText("Loading network status…")}</p>
        )}
        {error !== null && <p className="text-xs text-danger">{settingsText("Network status could not be loaded.")} {error}</p>}
        {status !== null && (
          <div className="space-y-3">
            <NetworkRouteRow route={status.root} root />
            {status.consumers.length > 0 && (
              <div className="divide-y divide-line rounded-lg border border-line">
                {status.consumers.map((route) => <NetworkRouteRow key={route.path} route={route} />)}
              </div>
            )}
            {status.consumers.length === 0 && (
              <p className="text-xs text-fg-faint">{settingsText("No network consumers are configured.")}</p>
            )}
          </div>
        )}
      </SectionCard>
    </SettingsPageBody>
  );
}

function NetworkRouteRow({ route, root = false }: { route: NetworkRouteStatus; root?: boolean }) {
  const navigateTo = useSettingsUiStore((state) => state.navigateTo);
  const page = pageForPath(route.path);
  const modeLabel = { inherit: "继承", direct: "直连", override: "指定代理" }[route.mode];
  return (
    <div className={`space-y-1.5 ${root ? "rounded-lg border border-line bg-bg px-3 py-2" : "px-3 py-2.5"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="break-all font-mono text-[11px] text-fg">{route.path}</span>
        <Badge tone={route.mode === "override" ? "accent" : route.mode === "direct" ? "gray" : "green"}>
          {modeLabel}
        </Badge>
        {route.source !== "" && <span className="break-all text-[10px] text-fg-faint">{route.source}</span>}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-fg-muted">
        <span>HTTP: {proxyAddress(route.effective.http_proxy)}</span>
        <span>HTTPS: {proxyAddress(route.effective.https_proxy)}</span>
        {route.effective.no_proxy.length > 0 && <span>{settingsText("Bypass")}: {route.effective.no_proxy.join(", ")}</span>}
      </div>
      {!root && route.parent_path !== null && (
        <div className="break-all text-[10px] text-fg-faint">{settingsText("Parent")}: {route.parent_path}</div>
      )}
      {!root && page !== null && (
        <button
          type="button"
          className="text-left text-[11px] text-accent hover:underline"
          onClick={() => navigateTo(page.id, route.path)}
        >
          {settingsText("Open consumer settings")}
        </button>
      )}
    </div>
  );
}

function proxyAddress(value: NetworkProxyAddress | null): string {
  if (value === null) return settingsText("direct");
  const host = value.host.includes(":") ? `[${value.host}]` : value.host;
  return `${value.scheme}://${host}${value.port === null ? "" : `:${value.port}`}`;
}
