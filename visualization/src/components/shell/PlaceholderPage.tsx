import { disconnect } from "../../app/connection";
import { clearStoredBrowserTarget } from "../../app/discovery";
import { useConnectionStore } from "../../store/connectionStore";
import type { AppTab } from "../../types";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";

const pageTitles: Record<AppTab, string> = {
  chat: "Chat",
  workspace: "Workspace",
  home: "Home",
  memory: "Memory",
  runtime: "Runtime",
  settings: "Settings",
};

/**
 * Neutral placeholder for pages that are still being rebuilt against the v2
 * contracts. The settings placeholder additionally carries the connection
 * section (current endpoint, disconnect / change address).
 */
export function PlaceholderPage({ page }: { page: AppTab }) {
  const info = useConnectionStore((s) => s.info);
  const phase = useConnectionStore((s) => s.phase);

  if (page === "settings") {
    return (
      <div className="flex h-full items-start justify-center overflow-y-auto p-6">
        <div className="w-full max-w-md rounded-xl border border-line bg-bg-elev p-6 shadow-card">
          <h1 className="text-base font-semibold">Settings</h1>
          <p className="mt-1 text-[13px] leading-5 text-fg-muted">
            The settings pages are being rebuilt against the v2 contracts.
          </p>
          <div className="mt-4 border-t border-line pt-4">
            <div className="text-xs font-medium text-fg-muted">Connection</div>
            <div className="mt-1 font-mono text-[12px] break-all text-fg">
              {info ? info.address.httpBaseUrl : "not connected"}
            </div>
            {info && (
              <div className="mt-0.5 font-mono text-[11px] break-all text-fg-faint">
                {info.projectIdentity}
              </div>
            )}
            {phase === "connected" && (
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() => {
                  disconnect();
                  clearStoredBrowserTarget();
                }}
              >
                Disconnect and change address
              </Button>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full items-center justify-center p-6">
      <EmptyState
        title={pageTitles[page]}
        description="This page is being rebuilt against the v2 contracts."
      />
    </div>
  );
}
