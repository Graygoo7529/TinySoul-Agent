import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";
import { IconButton } from "./Button";

export function Modal({
  title,
  onClose,
  children,
  width = "max-w-lg",
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  width?: string;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-(--z-drawer) flex items-center justify-center bg-black/40 backdrop-blur-[2px]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={`animate-fade-in max-h-[85vh] w-full ${width} overflow-hidden rounded-xl border border-line bg-bg-elev shadow-pop`}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <div className="text-sm font-semibold">{title}</div>
          <IconButton label="Close" onClick={onClose}>
            <X size={15} />
          </IconButton>
        </div>
        <div className="max-h-[calc(85vh-52px)] overflow-y-auto px-5 py-4">
          {children}
        </div>
      </div>
    </div>
  );
}
