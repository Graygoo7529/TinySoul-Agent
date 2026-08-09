import { useState } from "react";
import { Copy, PlugZap, TerminalSquare } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { Button } from "../ui/Button";

/**
 * Shown when no backend connection is available: explains the run model
 * (the Terminal-owned backend is the single entry point) and lets the user
 * point at a project root and retry.
 */
export function DisconnectedScreen({
  connect,
}: {
  connect: (projectRoot: string) => Promise<void>;
}) {
  const connection = useAppStore((s) => s.connection);
  const projectRoot = useAppStore((s) => s.projectRoot);
  const setProjectRoot = useAppStore((s) => s.setProjectRoot);
  const [copied, setCopied] = useState(false);

  const connecting =
    connection.status === "connecting" || connection.status === "initializing";
  const command = `tinysoul start --root "${projectRoot}" --mode normal`;

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-md rounded-xl border border-line bg-bg-elev p-6 shadow-card">
        <div className="mb-1 flex items-center gap-2">
          <PlugZap size={17} className="text-accent" />
          <h1 className="text-base font-semibold">Connect to TinySoul</h1>
        </div>
        <p className="text-[13px] leading-5 text-fg-muted">
          The desktop app is a pure client: the backend is owned by the
          Terminal. Start it, and this window discovers it through the
          project's instance lease.
        </p>

        <label className="mt-4 mb-1 block text-xs font-medium text-fg-muted">
          Project root
        </label>
        <input
          value={projectRoot}
          onChange={(e) => setProjectRoot(e.target.value)}
          className="h-9 w-full rounded-lg border border-line bg-bg-elev px-3 font-mono text-[12px] outline-none focus-ring focus:border-accent"
        />

        <div className="mt-3 flex items-center gap-2 rounded-lg bg-bg-sunken px-3 py-2">
          <TerminalSquare size={14} className="shrink-0 text-fg-faint" />
          <code className="min-w-0 flex-1 truncate font-mono text-[11px] text-fg-muted">
            {command}
          </code>
          <button
            onClick={() => {
              void navigator.clipboard.writeText(command);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            }}
            className="shrink-0 rounded p-1 text-fg-faint hover:bg-hover hover:text-fg"
            title="Copy command"
          >
            <Copy size={12} />
          </button>
        </div>
        {copied && <div className="mt-1 text-[11px] text-success">Copied.</div>}

        {connection.error && (
          <div className="mt-3 rounded-lg bg-danger-soft px-3 py-2 text-[12px] text-danger">
            {connection.error}
          </div>
        )}
        {connection.status === "not_running" && !connection.error && (
          <div className="mt-3 rounded-lg bg-bg-sunken px-3 py-2 text-[12px] text-fg-muted">
            No running TinySoul instance was found for this project root.
          </div>
        )}
        {connection.status === "initializing" && (
          <div className="mt-3 rounded-lg bg-info-soft px-3 py-2 text-[12px] text-info">
            The backend is starting up (archive preflight)… retrying automatically.
          </div>
        )}

        <Button
          variant="primary"
          className="mt-4 w-full"
          loading={connecting}
          onClick={() => void connect(projectRoot)}
        >
          {connecting ? "Connecting…" : "Retry connection"}
        </Button>
      </div>
    </div>
  );
}
