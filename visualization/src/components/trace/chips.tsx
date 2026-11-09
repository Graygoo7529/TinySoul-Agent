/**
 * Semantic chips shared by the chat view and the turn-trace drawer: action
 * domains, resource links, and compact ids get one consistent visual
 * language across the app.
 */

import { useI18n } from "../../i18n";
import { Check, Copy, FileText, Home, MemoryStick } from "lucide-react";
import { useState } from "react";
import { Badge, type BadgeTone } from "../ui/Badge";
import { shortId } from "./labels";

/* ------------------------------ domains ------------------------------ */

const domainTones: Record<string, BadgeTone> = {
  workspace: "blue",
  execution: "orange",
  shell: "orange",
  script: "orange",
  web: "teal",
  home: "purple",
  memory: "pink",
  core: "accent",
  supervised_process: "yellow",
  context: "gray",
};

function domainTone(domain: string): BadgeTone {
  return domainTones[domain] ?? "gray";
}

/** True when the value names a registered action domain. */
export function isKnownDomain(value: string): boolean {
  return value in domainTones;
}

const domainColorTokens: Record<string, string> = {
  core: "var(--domain-core)",
  workspace: "var(--domain-workspace)",
  execution: "var(--domain-execution)",
  shell: "var(--domain-execution)",
  script: "var(--domain-execution)",
  supervised_process: "var(--domain-execution)",
  web: "var(--domain-web)",
  home: "var(--domain-home)",
  memory: "var(--domain-memory)",
  context: "var(--domain-maintenance)",
};

/** The domain's semantic color as a CSS token (group headers, tints). */
export function domainColorToken(domain: string): string | undefined {
  return domainColorTokens[domain];
}

export function DomainChip({ domain }: { domain: string }) {
  return (
    <Badge tone={domainTone(domain)} className="font-mono text-[11px]">
      {domain}
    </Badge>
  );
}

/**
 * Left-border hue per action domain (tool-call cards). Kept as literal class
 * names so Tailwind can see them.
 */
export function domainBorderClass(domain: string): string {
  switch (domain) {
    case "workspace":
      return "border-l-domain-workspace";
    case "execution":
    case "shell":
    case "script":
    case "supervised_process":
      return "border-l-domain-execution";
    case "web":
      return "border-l-domain-web";
    case "home":
      return "border-l-domain-home";
    case "memory":
      return "border-l-domain-memory";
    case "core":
      return "border-l-accent";
    default:
      return "border-l-line-strong";
  }
}

/* ------------------------------ ids ---------------------------------- */

/**
 * Short id chip with click-to-copy. Only for non-button contexts (definition
 * lists, headers) — inside a button row, render `{shortId(id)}` with
 * `title={id}` instead so the markup stays valid.
 */
export function IdChip({ id, className = "" }: { id: string; className?: string }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard may be unavailable; fail quietly.
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      title={id}
      aria-label={t("common.copyValue", { value: id })}
      className={`inline-flex items-center gap-1 rounded-md bg-hover px-1.5 py-0.5 font-mono text-[10.5px] text-fg-muted transition-colors hover:text-fg ${className}`}
    >
      {shortId(id)}
      {copied ? (
        <Check size={10} className="text-success" />
      ) : (
        <Copy size={10} className="opacity-50" />
      )}
    </button>
  );
}

/* ------------------------------ links -------------------------------- */

function linkNamespace(resourceRef: string): string {
  const colon = resourceRef.indexOf(":");
  return colon > 0 ? resourceRef.slice(0, colon) : "";
}

export function LinkChip({ resourceRef, className = "" }: { resourceRef: string; className?: string }) {
  const ns = linkNamespace(resourceRef);
  const Icon =
    ns === "workspace"
      ? FileText
      : ns === "home"
        ? Home
        : ns === "memory"
          ? MemoryStick
          : FileText;
  return (
    <span
      title={resourceRef}
      className={`inline-flex max-w-full items-center gap-1 rounded-md bg-hover px-1.5 py-0.5 font-mono text-[11px] text-fg-muted ${className}`}
    >
      <Icon size={11} className="shrink-0" />
      <span className="truncate">{resourceRef}</span>
    </span>
  );
}
