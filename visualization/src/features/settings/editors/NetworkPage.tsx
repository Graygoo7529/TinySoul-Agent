import { t, useI18n } from "../../../i18n";
import { useEffect, useState } from "react";

import type { NetworkProxyAddress, NetworkRouteStatus, NetworkStatus } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { SectionCard } from "../../../components/ui/Card";
import { useConnectionStore } from "../../../store/connectionStore";
import { useConfigDraftStore } from "../draft/store";
import { pageForPath } from "../pages";
import { useSettingsUiStore } from "../uiStore";
import { SettingsPageBody } from "./controls";
import { NetworkPolicyField } from "./NetworkPolicyEditor";

/** Root network policy plus a read-only view of every configured consumer. */
export function NetworkPage() {
  const { t } = useI18n();
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
        title={t("settings.rootNetworkProxy")}
        parentLabel={t("settings.processEnvironmentThenProjectEnvHttpProxyHttpsProxy")}
      />
      <SectionCard
        title={t("settings.savedNetworkRoutes")}
        description={t("settings.routesResolvedFromSavedSettingsIncludingDisabledEntriesEdit")}
      >
        {status === null && error === null && (
          <p className="text-xs text-fg-faint">{t("settings.loadingNetworkStatus")}</p>
        )}
        {error !== null && <p className="text-xs text-danger">{t("settings.networkStatusCouldNotBeLoaded")} {error}</p>}
        {status !== null && (
          <div className="space-y-3">
            <NetworkRouteRow route={status.root} root />
            {status.consumers.length > 0 && (
              <div className="divide-y divide-line rounded-lg border border-line">
                {status.consumers.map((route) => <NetworkRouteRow key={route.path} route={route} />)}
              </div>
            )}
            {status.consumers.length === 0 && (
              <p className="text-xs text-fg-faint">{t("settings.noNetworkConsumersAreConfigured")}</p>
            )}
          </div>
        )}
      </SectionCard>
    </SettingsPageBody>
  );
}

function NetworkRouteRow({ route, root = false }: { route: NetworkRouteStatus; root?: boolean }) {
  const { t } = useI18n();
  const navigateTo = useSettingsUiStore((state) => state.navigateTo);
  const page = pageForPath(route.path);
  const modeLabel = { inherit: t("settings.networkInherit"), direct: t("settings.networkDirect"), override: t("settings.networkOverride") }[route.mode];
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
        {route.effective.no_proxy.length > 0 && <span>{t("settings.bypass")}: {route.effective.no_proxy.join(", ")}</span>}
      </div>
      {!root && route.parent_path !== null && (
        <div className="break-all text-[10px] text-fg-faint">{t("settings.parent")}: {route.parent_path}</div>
      )}
      {!root && page !== null && (
        <button
          type="button"
          className="text-left text-[11px] text-accent hover:underline"
          onClick={() => navigateTo(page.id, route.path)}
        >
          {t("settings.openConsumerSettings")}
        </button>
      )}
    </div>
  );
}

function proxyAddress(value: NetworkProxyAddress | null): string {
  if (value === null) return t("settings.direct");
  const host = value.host.includes(":") ? `[${value.host}]` : value.host;
  return `${value.scheme}://${host}${value.port === null ? "" : `:${value.port}`}`;
}
