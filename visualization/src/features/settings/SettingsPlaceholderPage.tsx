import { Construction } from "lucide-react";

import { EmptyState } from "../../components/ui/EmptyState";
import { SETTINGS_GROUPS, SETTINGS_PAGES, type SettingsPageId } from "./pages";

/**
 * Honest placeholder for settings pages whose workflow lands in a later F2
 * milestone. Carries the owning group so the navigation structure is visible.
 */
export function SettingsPlaceholderPage({ page }: { page: SettingsPageId }) {
  const def = SETTINGS_PAGES[page];
  const group = SETTINGS_GROUPS.find((item) => item.id === def.group);
  return (
    <div className="flex h-full items-center justify-center p-6">
      <EmptyState
        icon={<Construction size={22} />}
        title={def.title}
        description={
          <>
            {def.description}
            <span className="mt-1 block text-fg-faint">
              {group?.title} · this page is under construction — its editing
              workflow arrives with a later F2 milestone.
            </span>
          </>
        }
      />
    </div>
  );
}
