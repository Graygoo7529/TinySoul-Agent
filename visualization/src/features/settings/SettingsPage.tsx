import { useEffect } from "react";
import { Loader2, RefreshCw, Settings2, Unplug } from "lucide-react";

import { Button, IconButton } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { disconnect } from "../../app/connection";
import { clearStoredBrowserTarget } from "../../app/discovery";
import { useConnectionStore } from "../../store/connectionStore";
import { loadConfig } from "./applyController";
import {
  activationBlocker,
  selectDraftCount,
  useConfigDraftStore,
} from "./draft/store";
import { SETTINGS_PAGES } from "./pages";
import { SettingsBottomBar } from "./SettingsBottomBar";
import { SettingsNav } from "./SettingsNav";
import {
  ApplyFailureBanner,
  CleanupDiagnosticsBanner,
  SettingsOverviewPage,
} from "./SettingsOverviewPage";
import { SettingsPlaceholderPage } from "./SettingsPlaceholderPage";
import { useSettingsUiStore } from "./uiStore";

/**
 * The settings shell (P10): left group navigation, the active page, and the
 * shared draft bottom bar. Agent settings load their formal snapshots on
 * connect; local drafts survive leaving the tab (see AppShell's draft chip)
 * and guard the window close via beforeunload.
 */
export function SettingsPage() {
  const phase = useConnectionStore((s) => s.phase);
  const clients = useConnectionStore((s) => s.clients);
  const connected = phase === "connected" && clients !== null;

  // Load on (re-)connect; reset everything when the connection is dropped so
  // a different project never inherits this one's drafts.
  useEffect(() => {
    if (clients !== null) {
      void loadConfig(clients);
    } else {
      useConfigDraftStore.getState().reset();
    }
  }, [clients]);

  // Warn before closing the window with unapplied changes.
  const draftCount = useConfigDraftStore(selectDraftCount);
  useEffect(() => {
    if (draftCount === 0) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [draftCount]);

  const page = useSettingsUiStore((s) => s.page);
  const def = SETTINGS_PAGES[page];

  return (
    <div className="flex h-full min-h-0">
      <SettingsNav />
      <div className="flex min-w-0 flex-1 flex-col">
        <SettingsHeader connected={connected} />
        <div className="min-h-0 flex-1 overflow-y-auto">
          {!connected && page !== "interface" ? (
            <ConnectNotice />
          ) : (
            <PageContent pageId={page} />
          )}
        </div>
        {connected && <SettingsBottomBar />}
      </div>
    </div>
  );
}

function PageContent({ pageId }: { pageId: keyof typeof SETTINGS_PAGES }) {
  const loadPhase = useConfigDraftStore((s) => s.loadPhase);
  const loadError = useConfigDraftStore((s) => s.loadError);
  const applyFailure = useConfigDraftStore((s) => s.applyFailure);

  const banners = (
    <div className="mx-auto flex max-w-3xl flex-col gap-3 px-5 pt-4">
      {applyFailure !== null && <ApplyFailureBanner failure={applyFailure} />}
      <CleanupDiagnosticsBanner />
    </div>
  );

  if (pageId === "interface" || SETTINGS_PAGES[pageId].placeholder !== false) {
    return (
      <>
        {banners}
        <SettingsPlaceholderPage page={pageId} />
      </>
    );
  }
  if (loadPhase === "error") {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <EmptyState
          title="Configuration could not be loaded"
          description={loadError ?? "Unknown error"}
        />
      </div>
    );
  }
  return (
    <>
      {banners}
      {loadPhase === "ready" ? (
        <SettingsOverviewPage />
      ) : (
        <div className="flex h-full items-center justify-center p-6 text-fg-faint">
          <Loader2 size={18} className="animate-spin-slow" />
        </div>
      )}
    </>
  );
}

function SettingsHeader({ connected }: { connected: boolean }) {
  const page = useSettingsUiStore((s) => s.page);
  const def = SETTINGS_PAGES[page];
  const clients = useConnectionStore((s) => s.clients);
  const loadPhase = useConfigDraftStore((s) => s.loadPhase);
  const blocker = useConfigDraftStore(activationBlocker);

  return (
    <header className="flex min-h-14 shrink-0 items-center gap-3 border-b border-line bg-bg-elev px-5 py-2">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-hover text-fg-muted">
        <Settings2 size={17} />
      </div>
      <div className="min-w-0">
        <h1 className="truncate text-[15px] font-semibold text-fg">
          {def.title}
        </h1>
        <div className="line-clamp-1 text-[10px] text-fg-faint">
          {def.description}
        </div>
      </div>
      {connected && (
        <div className="ml-auto flex items-center gap-2">
          {blocker !== null && (
            <span
              className="hidden max-w-[280px] truncate text-[10px] text-warning sm:block"
              title={blocker}
            >
              {blocker}
            </span>
          )}
          <IconButton
            label="Refresh configuration"
            disabled={loadPhase === "loading"}
            onClick={() => clients !== null && void loadConfig(clients)}
          >
            {loadPhase === "loading" ? (
              <Loader2 size={15} className="animate-spin-slow" />
            ) : (
              <RefreshCw size={15} />
            )}
          </IconButton>
        </div>
      )}
    </header>
  );
}

/** Shown in place of Agent settings while there is no backend connection. */
function ConnectNotice() {
  const info = useConnectionStore((s) => s.info);
  return (
    <div className="flex h-full items-start justify-center overflow-y-auto p-6">
      <div className="w-full max-w-md rounded-xl border border-line bg-bg-elev p-6 shadow-card">
        <h2 className="text-base font-semibold">No backend connected</h2>
        <p className="mt-1 text-[13px] leading-5 text-fg-muted">
          Agent settings are read from and applied to a running TinySoul
          backend. Connect from the main screen, or change the address here.
        </p>
        {info !== null && (
          <div className="mt-4 border-t border-line pt-4">
            <div className="text-xs font-medium text-fg-muted">
              Last connection
            </div>
            <div className="mt-1 font-mono text-[12px] break-all text-fg">
              {info.address.httpBaseUrl}
            </div>
            <div className="mt-0.5 font-mono text-[11px] break-all text-fg-faint">
              {info.projectIdentity}
            </div>
            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={() => {
                disconnect();
                clearStoredBrowserTarget();
              }}
            >
              <Unplug size={13} className="mr-1" /> Disconnect and change address
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
