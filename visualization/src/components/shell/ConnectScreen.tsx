import { useState, type FormEvent } from "react";
import { PlugZap } from "lucide-react";
import { autoConnect, connect } from "../../app/connection";
import { isTauriShell } from "../../app/discovery";
import { useAppStore } from "../../store/appStore";
import { useConnectionStore } from "../../store/connectionStore";
import { Button } from "../ui/Button";

/**
 * Shown when no backend connection is established: a manual address + token
 * form, and inside the Tauri shell a one-click discovery of the local
 * instance published for the configured project root.
 */
export function ConnectScreen() {
  const phase = useConnectionStore((s) => s.phase);
  const error = useConnectionStore((s) => s.error);
  const projectRoot = useAppStore((s) => s.projectRoot);
  const [address, setAddress] = useState("");
  const [token, setToken] = useState("");
  const [localPending, setLocalPending] = useState(false);

  const connecting = phase === "connecting" || localPending;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!address.trim() || !token.trim()) return;
    void connect({ address: address.trim(), token: token.trim() });
  };

  const connectLocal = () => {
    setLocalPending(true);
    void autoConnect(projectRoot).finally(() => setLocalPending(false));
  };

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-md rounded-xl border border-line bg-bg-elev p-6 shadow-card">
        <div className="mb-1 flex items-center gap-2">
          <PlugZap size={17} className="text-accent" />
          <h1 className="text-base font-semibold">Connect to TinySoul</h1>
        </div>
        <p className="text-[13px] leading-5 text-fg-muted">
          The app is a pure client of a running TinySoul Endpoint. Enter the
          client-reachable address (<code>IP:Port</code>, http(s) URL) and the
          access token the instance published.
        </p>

        <form onSubmit={submit} className="mt-4">
          <label className="mb-1 block text-xs font-medium text-fg-muted">
            Address
          </label>
          <input
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="127.0.0.1:1430"
            className="h-9 w-full rounded-lg border border-line bg-bg-elev px-3 font-mono text-[12px] outline-none focus-ring focus:border-accent"
          />
          <label className="mt-3 mb-1 block text-xs font-medium text-fg-muted">
            Token
          </label>
          <input
            value={token}
            onChange={(e) => setToken(e.target.value)}
            type="password"
            className="h-9 w-full rounded-lg border border-line bg-bg-elev px-3 font-mono text-[12px] outline-none focus-ring focus:border-accent"
          />

          {error && (
            <div className="mt-3 rounded-lg bg-danger-soft px-3 py-2 text-[12px] text-danger">
              {error}
            </div>
          )}

          <Button
            type="submit"
            variant="primary"
            className="mt-4 w-full"
            loading={connecting}
            disabled={connecting || !address.trim() || !token.trim()}
          >
            {connecting ? "Connecting…" : "Connect"}
          </Button>
        </form>

        {isTauriShell() && (
          <Button
            variant="outline"
            className="mt-2 w-full"
            loading={localPending}
            disabled={connecting}
            onClick={connectLocal}
          >
            Use the local instance of this project
          </Button>
        )}
      </div>
    </div>
  );
}
