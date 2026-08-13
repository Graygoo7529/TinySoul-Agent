import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Loader2, RefreshCw, Settings2 } from "lucide-react";

import { IconButton } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { useAppStore } from "../../store/appStore";
import { useConfigStore } from "../../store/configStore";
import { ApplicationSettingsPage } from "./ApplicationSettingsPage";
import { ConfigSettingsPage } from "./ConfigSettingsPage";
import { CredentialsSettingsPage } from "./CredentialsSettingsPage";
import { InfrastructureSettingsPage } from "./InfrastructureSettingsPage";
import { ModelsSettingsPage } from "./ModelsSettingsPage";
import { OverviewSettingsPage } from "./OverviewSettingsPage";
import { ProvidersSettingsPage } from "./ProvidersSettingsPage";
import { SettingsNavigation } from "./SettingsNavigation";
import { TaskChainsSettingsPage } from "./TaskChainsSettingsPage";
import { pageSurface, type SettingsPageId } from "./model";

const clientPages: Record<"overview" | "application" | "credentials", { title: string; description: string }> = {
  overview: { title: "Overview", description: "Runtime generation and configuration source status." },
  application: { title: "Application", description: "Desktop connection and interface preferences." },
  credentials: { title: "Credentials", description: "Project dotenv values referenced by configuration." },
};

export function SettingsPage({
  connect,
}: {
  connect: (projectRoot: string) => Promise<void>;
}) {
  const client = useAppStore((state) => state.client);
  const connected = useAppStore((state) => state.connection.status === "connected");
  const runtimeActivity = useAppStore((state) => state.status?.runtime?.activity);
  const status = useConfigStore((state) => state.status);
  const catalog = useConfigStore((state) => state.catalog);
  const actionCatalog = useConfigStore((state) => state.actionCatalog);
  const loading = useConfigStore((state) => state.loading);
  const error = useConfigStore((state) => state.error);
  const refresh = useConfigStore((state) => state.refresh);
  const reset = useConfigStore((state) => state.reset);
  const [page, setPage] = useState<SettingsPageId>(connected ? "overview" : "application");

  useEffect(() => {
    if (client && connected) {
      void refresh(client);
    } else {
      reset();
      setPage("application");
    }
  }, [client, connected, refresh, reset, runtimeActivity]);

  const pageMeta = useMemo(() => {
    if (page === "overview" || page === "application" || page === "credentials") {
      return clientPages[page];
    }
    const surface = pageSurface[page];
    const descriptor = catalog?.surfaces.find((item) => item.id === surface);
    return descriptor ?? { title: page, description: "" };
  }, [catalog, page]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-bg">
      <header className="flex min-h-14 shrink-0 items-center gap-3 border-b border-line bg-bg-elev px-5 py-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-hover text-fg-muted">
          <Settings2 size={17} />
        </div>
        <div className="min-w-0">
          <h1 className="truncate text-[15px] font-semibold text-fg">{pageMeta.title}</h1>
          <div className="line-clamp-1 text-[10px] text-fg-faint">{pageMeta.description}</div>
        </div>
        {client && connected && (
          <div className="ml-auto flex items-center gap-2">
            {status && (
              <span className={`hidden text-[10px] sm:block ${status.activity.can_write ? "text-success" : "text-warning"}`}>
                {status.activity.can_write ? "Runtime idle" : status.activity.state}
              </span>
            )}
            <IconButton
              label="Refresh configuration"
              disabled={loading}
              onClick={() => void refresh(client)}
            >
              {loading ? <Loader2 size={15} className="animate-spin-slow" /> : <RefreshCw size={15} />}
            </IconButton>
          </div>
        )}
      </header>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <SettingsNavigation active={page} connected={connected} onSelect={setPage} />
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">
          {error && (
            <div className="flex items-center gap-2 border-b border-danger/30 bg-danger-soft px-5 py-2.5 text-[12px] text-danger">
              <AlertCircle size={14} /> {error}
            </div>
          )}

          {page === "application" ? (
            <ApplicationSettingsPage connect={connect} />
          ) : !client || !connected ? (
            <EmptyState icon={<Settings2 size={22} />} title="Connect a project to view configuration" />
          ) : !status || !catalog || !actionCatalog ? (
            <EmptyState
              icon={<Loader2 size={22} className={loading ? "animate-spin-slow" : ""} />}
              title={loading ? "Loading configuration" : "Configuration unavailable"}
            />
          ) : page === "overview" ? (
            <OverviewSettingsPage status={status} catalog={catalog} />
          ) : page === "credentials" ? (
            <CredentialsSettingsPage client={client} status={status} catalog={catalog} />
          ) : page === "providers" ? (
            <ProvidersSettingsPage client={client} status={status} catalog={catalog} />
          ) : page === "models" ? (
            <ModelsSettingsPage client={client} status={status} catalog={catalog} />
          ) : page === "task_chains" ? (
            <TaskChainsSettingsPage
              client={client}
              status={status}
              catalog={catalog}
              actions={actionCatalog}
            />
          ) : page === "infrastructure" ? (
            <InfrastructureSettingsPage client={client} status={status} catalog={catalog} />
          ) : (
            <ConfigSettingsPage
              client={client}
              status={status}
              catalog={catalog}
              surface={pageSurface[page] ?? page}
            />
          )}
        </div>
      </div>
    </div>
  );
}
