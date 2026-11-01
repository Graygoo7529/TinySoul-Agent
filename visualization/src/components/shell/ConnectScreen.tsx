import { useState, type FormEvent } from "react";
import { PlugZap } from "lucide-react";
import { connect } from "../../app/connection";
import { useConnectionStore } from "../../store/connectionStore";
import { Button } from "../ui/Button";

/**
 * Shown when no backend connection is established: a manual address + token
 * form. Browser and Tauri use the same address/token login path.
 */
export function ConnectScreen() {
  const phase = useConnectionStore((s) => s.phase);
  const error = useConnectionStore((s) => s.error);
  const [address, setAddress] = useState("");
  const [token, setToken] = useState("");

  const connecting = phase === "connecting";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!address.trim() || !token.trim()) return;
    void connect({ address: address.trim(), token: token.trim() });
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
          stable access token from the backend project&apos;s <code>.auth</code>
          file.
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

      </div>
    </div>
  );
}
