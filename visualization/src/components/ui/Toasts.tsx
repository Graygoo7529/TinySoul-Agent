import { useEffect } from "react";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { useAppStore, type ToastItem } from "../../store/appStore";

const kindStyle = {
  success: { icon: CheckCircle2, className: "text-success" },
  error: { icon: XCircle, className: "text-danger" },
  info: { icon: Info, className: "text-info" },
} as const;

function Toast({ toast }: { toast: ToastItem }) {
  const dismissToast = useAppStore((s) => s.dismissToast);
  useEffect(() => {
    const timer = setTimeout(() => dismissToast(toast.id), 4500);
    return () => clearTimeout(timer);
  }, [toast.id, dismissToast]);

  const { icon: Icon, className } = kindStyle[toast.kind];
  return (
    <div className="animate-fade-in pointer-events-auto flex items-start gap-2.5 rounded-lg border border-line bg-bg-elev px-3.5 py-2.5 shadow-(--shadow-pop)">
      <Icon size={16} className={`mt-0.5 shrink-0 ${className}`} />
      <div className="min-w-0 flex-1 text-[13px] leading-5 break-words">{toast.text}</div>
      <button
        onClick={() => dismissToast(toast.id)}
        className="shrink-0 rounded p-0.5 text-fg-faint hover:bg-hover hover:text-fg"
      >
        <X size={13} />
      </button>
    </div>
  );
}

export function Toasts() {
  const toasts = useAppStore((s) => s.toasts);
  if (toasts.length === 0) return null;
  return (
    <div className="pointer-events-none fixed right-4 bottom-4 z-[60] flex w-[360px] flex-col gap-2">
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} />
      ))}
    </div>
  );
}
