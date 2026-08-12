import { useEffect, useState } from "react";
import { Check, FolderOpen } from "lucide-react";

import { Button } from "../../components/ui/Button";
import { useAppStore, type ThemeMode } from "../../store/appStore";

const themes: { value: ThemeMode; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export function ApplicationSettingsPage({
  connect,
}: {
  connect: (projectRoot: string) => Promise<void>;
}) {
  const projectRoot = useAppStore((state) => state.projectRoot);
  const setProjectRoot = useAppStore((state) => state.setProjectRoot);
  const theme = useAppStore((state) => state.theme);
  const setTheme = useAppStore((state) => state.setTheme);
  const connection = useAppStore((state) => state.connection);
  const [draft, setDraft] = useState(projectRoot);
  const [connecting, setConnecting] = useState(false);

  useEffect(() => setDraft(projectRoot), [projectRoot]);

  const applyProject = async () => {
    const root = draft.trim();
    if (!root) return;
    setProjectRoot(root);
    setConnecting(true);
    try {
      await connect(root);
    } finally {
      setConnecting(false);
    }
  };

  return (
    <div>
      <section className="border-b border-line px-5 py-4">
        <h3 className="text-[12px] font-semibold text-fg-muted">Project</h3>
        <div className="mt-3 grid gap-3 md:grid-cols-[minmax(180px,1fr)_minmax(320px,2fr)] md:items-center">
          <div>
            <div className="text-[13px] font-medium text-fg">Project root</div>
            <div className="mt-0.5 text-[10px] text-fg-faint">{connection.status}</div>
          </div>
          <div className="flex min-w-0 items-center gap-2">
            <div className="relative min-w-0 flex-1">
              <FolderOpen
                size={14}
                className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-fg-faint"
              />
              <input
                aria-label="Project root"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void applyProject();
                }}
                className="focus-ring h-8 w-full rounded-lg border border-line bg-bg-elev pr-2.5 pl-8 font-mono text-[12px] outline-none focus:border-accent"
              />
            </div>
            <Button
              variant="primary"
              size="xs"
              loading={connecting}
              disabled={!draft.trim() || (draft === projectRoot && connection.status === "connected")}
              onClick={() => void applyProject()}
            >
              <Check size={13} /> Apply
            </Button>
          </div>
        </div>
      </section>

      <section className="border-b border-line px-5 py-4">
        <h3 className="text-[12px] font-semibold text-fg-muted">Appearance</h3>
        <div className="mt-3 grid gap-3 md:grid-cols-[minmax(180px,1fr)_minmax(320px,2fr)] md:items-center">
          <div className="text-[13px] font-medium text-fg">Theme</div>
          <div className="flex w-fit rounded-lg border border-line bg-bg-sunken p-0.5">
            {themes.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setTheme(option.value)}
                className={`h-7 min-w-20 rounded-md px-3 text-[12px] font-medium transition-colors ${
                  theme === option.value
                    ? "bg-bg-elev text-fg shadow-sm"
                    : "text-fg-muted hover:text-fg"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      {connection.info && (
        <section className="px-5 py-4">
          <h3 className="text-[12px] font-semibold text-fg-muted">Connected instance</h3>
          <div className="mt-2 divide-y divide-line">
            <Fact label="Endpoint" value={`${connection.info.host}:${connection.info.port}`} />
            <Fact label="Instance" value={connection.info.instance_id} />
            <Fact label="Protocol" value={String(connection.info.protocol_version)} />
          </div>
        </section>
      )}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5">
      <span className="text-[12px] text-fg-muted">{label}</span>
      <span className="min-w-0 truncate font-mono text-[11px] text-fg" title={value}>
        {value}
      </span>
    </div>
  );
}
