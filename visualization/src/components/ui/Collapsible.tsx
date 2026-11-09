/**
 * Disclosure components. Pick by weight — do not hand-roll <details>:
 * - InlineDisclosure: light in-form toggles (chevron + hover, indented body);
 * - Collapsible: card-level sections with a header row and meta slot;
 * - settings/SettingsDisclosure: draft-aware sections (dirty/issue badges,
 *   focus auto-open).
 */

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
        aria-expanded={open}
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

/** Light in-form disclosure: chevron + hover affordance, content indented
 *  with a left rule; no card chrome. For secondary in-form content. */
export function InlineDisclosure({
  title,
  defaultOpen = false,
  children,
  className = "",
}: {
  title: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={className}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="-ml-1.5 flex items-center gap-1.5 rounded-md px-1.5 py-1 text-[12.5px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
      >
        <ChevronRight
          size={13}
          className={`shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
        />
        {title}
      </button>
      {open && (
        <div className="mb-1 ml-2 mt-1 border-l-2 border-line py-1 pl-3">{children}</div>
      )}
    </div>
  );
}
