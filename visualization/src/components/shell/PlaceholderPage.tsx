import type { AppTab } from "../../types";
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
 * contracts. Settings is served by features/settings (F2) and no longer uses
 * this placeholder.
 */
export function PlaceholderPage({ page }: { page: AppTab }) {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <EmptyState
        title={pageTitles[page]}
        description="This page is being rebuilt against the v2 contracts."
      />
    </div>
  );
}
