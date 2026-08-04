import { useState } from "react";
import { Check, Copy } from "lucide-react";

export function CopyButton({
  text,
  label = "Copy",
  className = "",
}: {
  text: () => string;
  label?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text());
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard may be unavailable in some contexts; fail quietly.
    }
  };

  return (
    <button
      onClick={copy}
      title={label}
      className={`inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-[11px] text-fg-faint transition-colors hover:bg-hover hover:text-fg ${className}`}
    >
      {copied ? <Check size={12} className="text-success" /> : <Copy size={12} />}
      {copied ? "Copied" : label}
    </button>
  );
}
