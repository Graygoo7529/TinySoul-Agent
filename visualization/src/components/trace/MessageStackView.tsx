import { useState } from "react";
import { ChevronRight, Image as ImageIcon } from "lucide-react";
import type { MessagePart, ModelMessage } from "../../derive/model";
import { Badge, type BadgeTone } from "../ui/Badge";
import { JsonTree } from "../ui/JsonTree";
import { CopyButton } from "../ui/CopyButton";
import { formatSize, shorten } from "../../utils/format";

/**
 * The constructed message stack of one LLM call. Messages are grouped into
 * semantic context sections (identity / user inputs / background / working /
 * turn trace / task prompt) derived from their labels, matching how the
 * Context module composes the stack. Sections and individual messages are
 * collapsible.
 */
export function MessageStackView({ messages }: { messages: ModelMessage[] }) {
  const sections = groupSections(messages);
  return (
    <div className="space-y-2">
      {sections.map((section) => (
        <SectionView key={section.name} section={section} />
      ))}
    </div>
  );
}

interface Section {
  name: string;
  color: string;
  defaultOpen: boolean;
  messages: { index: number; value: ModelMessage }[];
}

const sectionStyle: Record<string, { color: string; defaultOpen: boolean }> = {
  Identity: { color: "bg-domain-home", defaultOpen: false },
  "User Inputs": { color: "bg-domain-workspace", defaultOpen: true },
  Background: { color: "bg-domain-web", defaultOpen: false },
  "Working Context": { color: "bg-warning", defaultOpen: true },
  "Turn Trace": { color: "bg-domain-execution", defaultOpen: false },
  "Task Prompt": { color: "bg-domain-memory", defaultOpen: false },
  Other: { color: "bg-fg-faint", defaultOpen: false },
};

function sectionOf(message: ModelMessage): string {
  const label = message.label ?? "";
  if (message.role === "system" || label === "identity") return "Identity";
  if (label === "user_input") return "User Inputs";
  if (label.startsWith("background")) return "Background";
  if (label === "working" || label === "todo" || label === "milestone") {
    return "Working Context";
  }
  if (
    label.startsWith("trace") ||
    label === "decision" ||
    label === "phase_note" ||
    label.startsWith("action_result")
  ) {
    return "Turn Trace";
  }
  if (label.startsWith("task_prompt") || !label) return "Task Prompt";
  return "Other";
}

const sectionOrder = [
  "Identity",
  "User Inputs",
  "Background",
  "Turn Trace",
  "Working Context",
  "Task Prompt",
  "Other",
];

function groupSections(messages: ModelMessage[]): Section[] {
  const map = new Map<string, { index: number; value: ModelMessage }[]>();
  messages.forEach((message, index) => {
    const name = sectionOf(message);
    const list = map.get(name) ?? [];
    list.push({ index, value: message });
    map.set(name, list);
  });
  return sectionOrder
    .filter((name) => map.has(name))
    .map((name) => ({
      name,
      color: sectionStyle[name].color,
      defaultOpen: sectionStyle[name].defaultOpen,
      messages: map.get(name)!,
    }));
}

function SectionView({ section }: { section: Section }) {
  const [open, setOpen] = useState(section.defaultOpen);
  const totalChars = section.messages.reduce(
    (sum, m) =>
      sum +
      m.value.parts.reduce(
        (s, part) => s + (part.text?.length ?? JSON.stringify(part.value ?? "").length),
        0,
      ),
    0,
  );
  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="mb-1 flex w-full items-center gap-2 rounded-md px-1 py-0.5 text-left hover:bg-hover"
      >
        <ChevronRight
          size={12}
          className={`shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className={`h-2 w-2 rounded-full ${section.color}`} />
        <span className="text-[11px] font-semibold tracking-wide text-fg-muted uppercase">
          {section.name}
        </span>
        <span className="text-[10px] text-fg-faint">
          {section.messages.length} msg · {formatSize(totalChars)}
        </span>
      </button>
      {open && (
        <div className="space-y-1.5">
          {section.messages.map((message) => (
            <MessageView key={message.index} message={message.value} index={message.index} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ----------------------------- message ------------------------------ */

const roleTones: Record<string, BadgeTone> = {
  system: "purple",
  user: "blue",
  assistant: "accent",
  tool_result: "orange",
};

function MessageView({ message, index }: { message: ModelMessage; index: number }) {
  const [open, setOpen] = useState(false);
  const chars = message.parts.reduce(
    (sum, part) => sum + (part.text?.length ?? JSON.stringify(part.value ?? "").length),
    0,
  );

  return (
    <div className="rounded-lg border border-line bg-bg-sunken">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left"
      >
        <ChevronRight
          size={12}
          className={`shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="font-mono text-[10px] text-fg-faint">#{index + 1}</span>
        <Badge tone={roleTones[message.role] ?? "gray"} className="font-mono text-[10px]">
          {message.role}
        </Badge>
        {message.label && (
          <span className="truncate rounded bg-hover px-1 py-0.5 font-mono text-[10px] text-fg-muted">
            {message.label}
          </span>
        )}
        <span className="ml-auto shrink-0 text-[10px] text-fg-faint">
          {formatSize(chars)}
        </span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-line px-3 py-2.5">
          {message.reasoning?.summary && (
            <div className="rounded-lg bg-accent-soft px-2.5 py-2">
              <div className="mb-1 text-[10px] font-semibold tracking-wide text-accent uppercase">
                Reasoning summary
              </div>
              <div className="text-[12px] leading-5 whitespace-pre-wrap text-fg-muted">
                {message.reasoning.summary}
              </div>
            </div>
          )}
          {message.parts.map((part, i) => (
            <PartView key={i} part={part} />
          ))}
          {message.tool_calls && message.tool_calls.length > 0 && (
            <div className="space-y-1">
              <div className="text-[10px] font-semibold tracking-wide text-fg-faint uppercase">
                Tool calls
              </div>
              {message.tool_calls.map((call) => (
                <div key={call.id} className="rounded-lg border border-line bg-bg-elev px-2.5 py-1.5">
                  <div className="mb-1 flex items-center gap-2">
                    <span className="font-mono text-[11px] font-medium text-accent">
                      {call.name}
                    </span>
                    <span className="font-mono text-[10px] text-fg-faint">{call.id}</span>
                  </div>
                  <JsonTree value={call.arguments} />
                </div>
              ))}
            </div>
          )}
          {message.role === "tool_result" && (
            <div className="text-[10px] text-fg-faint">
              result of {message.tool_name ?? "tool"} · call {message.call_id ?? "?"} ·{" "}
              {message.status ?? "unknown"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const TEXT_CLAMP = 1200;

function PartView({ part }: { part: MessagePart }) {
  const [expanded, setExpanded] = useState(false);
  switch (part.type) {
    case "text": {
      const text = part.text ?? "";
      const clamped = !expanded && text.length > TEXT_CLAMP;
      return (
        <div className="relative rounded-lg border border-line bg-bg-elev px-2.5 py-2">
          <div className="absolute top-1 right-1">
            <CopyButton text={() => text} />
          </div>
          <pre className="pr-14 font-sans text-[12px] leading-5 whitespace-pre-wrap break-words text-fg">
            {clamped ? text.slice(0, TEXT_CLAMP) + " …" : text}
          </pre>
          {text.length > TEXT_CLAMP && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="mt-1 text-[11px] font-medium text-accent hover:underline"
            >
              {expanded ? "Show less" : `Show all (${formatSize(text.length)})`}
            </button>
          )}
        </div>
      );
    }
    case "json":
      return <JsonTree value={part.value} />;
    case "image":
      return (
        <div className="flex items-center gap-2 rounded-lg border border-line bg-bg-elev px-2.5 py-1.5 text-[11px] text-fg-muted">
          <ImageIcon size={12} className="shrink-0" />
          image · {part.mime_type ?? "unknown"} · {formatSize(part.size ?? 0)} · digest{" "}
          {shorten(part.digest ?? "", 16)}
        </div>
      );
    case "image_url":
      return (
        <div className="flex items-center gap-2 rounded-lg border border-line bg-bg-elev px-2.5 py-1.5 text-[11px] text-fg-muted">
          <ImageIcon size={12} className="shrink-0" />
          <span className="truncate">{part.url}</span>
        </div>
      );
    default:
      return <JsonTree value={part} />;
  }
}
