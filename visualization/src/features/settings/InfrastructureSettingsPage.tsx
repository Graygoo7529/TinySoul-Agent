import { Cpu, Network } from "lucide-react";
import { useState } from "react";

import type { TinySoulClient } from "../../api/tinysoul";
import type { ConfigCatalog, ConfigStatus } from "../../types";
import { ConfigSettingsPage } from "./ConfigSettingsPage";

export function InfrastructureSettingsPage({
  client,
  status,
  catalog,
}: {
  client: TinySoulClient;
  status: ConfigStatus;
  catalog: ConfigCatalog;
}) {
  const [section, setSection] = useState<"system" | "embedding">("system");
  return (
    <div>
      <div className="flex gap-1 border-b border-line bg-bg-sunken/30 px-4 py-2">
        <button
          type="button"
          onClick={() => setSection("system")}
          className={`flex h-8 items-center gap-2 rounded-md px-3 text-[12px] font-medium ${section === "system" ? "bg-active text-accent" : "text-fg-muted hover:bg-hover"}`}
        >
          <Cpu size={14} /> System
        </button>
        <button
          type="button"
          onClick={() => setSection("embedding")}
          className={`flex h-8 items-center gap-2 rounded-md px-3 text-[12px] font-medium ${section === "embedding" ? "bg-active text-accent" : "text-fg-muted hover:bg-hover"}`}
        >
          <Network size={14} /> Embedding
        </button>
      </div>
      <ConfigSettingsPage
        client={client}
        status={status}
        catalog={catalog}
        surface={section === "embedding" ? "embedding" : "infrastructure"}
      />
    </div>
  );
}
