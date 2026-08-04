import { useState } from "react";
import { useAppStore } from "../../store/appStore";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

export function SettingsDialog() {
  const open = useAppStore((s) => s.settingsOpen);
  const setOpen = useAppStore((s) => s.setSettingsOpen);
  const projectRoot = useAppStore((s) => s.projectRoot);
  const setProjectRoot = useAppStore((s) => s.setProjectRoot);
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);
  const [draft, setDraft] = useState<string | null>(null);

  if (!open) return null;

  const value = draft ?? projectRoot;

  return (
    <Modal title="Settings" onClose={() => setOpen(false)}>
      <div className="space-y-4">
        <div>
          <label className="mb-1 block text-xs font-medium text-fg-muted">
            Project root
          </label>
          <input
            value={value}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Absolute path of the TinySoul project"
            className="h-9 w-full rounded-lg border border-line bg-bg-elev px-3 text-[13px] outline-none focus:border-accent focus:ring-2 focus:ring-accent/20"
          />
          <p className="mt-1 text-[11px] leading-4 text-fg-faint">
            The running backend is discovered from the instance lease file of
            this project. Start it with{" "}
            <code className="rounded bg-code-bg px-1 font-mono">
              tinysoul start --root &lt;project&gt;
            </code>
            .
          </p>
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-fg-muted">Theme</label>
          <div className="inline-flex items-center gap-0.5 rounded-lg bg-bg-sunken p-0.5">
            {(["light", "dark"] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => setTheme(mode)}
                className={`h-7 rounded-md px-3 text-[13px] font-medium capitalize transition-colors ${
                  theme === mode
                    ? "bg-bg-elev text-fg shadow-sm"
                    : "text-fg-muted hover:text-fg"
                }`}
              >
                {mode}
              </button>
            ))}
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              if (draft !== null && draft.trim()) setProjectRoot(draft.trim());
              setOpen(false);
            }}
          >
            Save
          </Button>
        </div>
      </div>
    </Modal>
  );
}
