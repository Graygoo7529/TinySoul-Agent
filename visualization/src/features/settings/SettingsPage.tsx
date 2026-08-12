import { useEffect, useState } from "react";
import { AlertCircle, Loader2, RefreshCw, Settings2 } from "lucide-react";

import { IconButton } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { useAppStore } from "../../store/appStore";
import { useConfigStore } from "../../store/configStore";
import { ApplicationSettingsPage } from "./ApplicationSettingsPage";
import { ConfigSettingsPage } from "./ConfigSettingsPage";
import { CredentialsSettingsPage } from "./CredentialsSettingsPage";
import { OverviewSettingsPage } from "./OverviewSettingsPage";
import { SettingsNavigation } from "./SettingsNavigation";
import type { SettingsPageId } from "./model";

const pageTitles: Record<SettingsPageId, string> = {
  overview: "Overview",
  models: "Models",
  embedding: "Embedding",
  capabilities: "Capabilities",
  memory: "Memory",
  workspace: "Workspace",
  maintenance: "Maintenance",
  behavior: "Behavior",
  system: "System",
  credentials: "Credentials",
  application: "Application",
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

  return (
    <div className="flex h-full min-h-0 flex-col bg-bg">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-bg-elev px-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-hover text-fg-muted">
          <Settings2 size={17} />
        </div>
        <div className="min-w-0">
          <h1 className="truncate text-[15px] font-semibold text-fg">Settings</h1>
          <div className="text-[10px] text-fg-faint">{pageTitles[page]}</div>
        </div>
        {client && connected && (
          <IconButton
            label="Refresh configuration"
            disabled={loading}
            onClick={() => void refresh(client)}
            className="ml-auto"
          >
            {loading ? <Loader2 size={15} className="animate-spin-slow" /> : <RefreshCw size={15} />}
          </IconButton>
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
          ) : !status ? (
            <EmptyState
              icon={<Loader2 size={22} className={loading ? "animate-spin-slow" : ""} />}
              title={loading ? "Loading configuration" : "Configuration unavailable"}
            />
          ) : page === "overview" ? (
            <OverviewSettingsPage status={status} />
          ) : page === "credentials" ? (
            <CredentialsSettingsPage client={client} status={status} />
          ) : (
            <ConfigSettingsPage client={client} status={status} page={page} />
          )}
        </div>
      </div>
    </div>
  );
}
