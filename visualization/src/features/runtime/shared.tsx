/**
 * Small shared UI rows of the runtime-observation tabs (plan §14/P09).
 */

import type { ReactElement } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";

/** Loading row shared by the runtime tabs. */
export function LoadingRow({ text = "Reading…" }: { text?: string }): ReactElement {
  return (
    <div className="flex items-center gap-2 px-1 py-3 text-[12px] text-fg-faint">
      <Loader2 size={13} className="animate-spin-slow" />
      {text}
    </div>
  );
}

/** Bounded read failure with an explicit retry. */
export function ReadError({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}): ReactElement {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-[12px] text-danger">
      <AlertTriangle size={12} className="shrink-0" />
      <span className="min-w-0 flex-1">The read failed ({message}).</span>
      {onRetry !== undefined && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 font-medium hover:underline"
        >
          Retry
        </button>
      )}
    </div>
  );
}
