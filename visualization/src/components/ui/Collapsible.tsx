import { useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";

/** Generic collapsible section with a compact header row. */
export function Collapsible({
  title,
  meta,
  defaultOpen = false,
  children,
  className = "",
  tone = "default",
}: {
  title: ReactNode;
  meta?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
  className?: string;
  tone?: "default" | "sunken";
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div
      className={`rounded-lg border border-line ${
        tone === "sunken" ? "bg-bg-sunken" : "bg-bg-elev"
      } ${className}`}
    >
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <ChevronRight
          size={13}
          className={`shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{title}</span>
        {meta && <span className="flex shrink-0 items-center gap-1.5">{meta}</span>}
      </button>
      {open && <div className="border-t border-line px-3 py-2.5">{children}</div>}
    </div>
  );
}
