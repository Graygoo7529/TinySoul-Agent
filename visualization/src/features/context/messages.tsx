/**
 * Rendering of installed segment body messages (API-09
 * `messages[{message_index, message}]`).
 *
 * The `message` value keeps TinySoul's provider-neutral semantics
 * (`role`/`label`/`parts`); text parts render as-is, non-text parts and
 * unknown shapes fall back to a collapsed JSON view — never dropped.
 */

import type { ReactElement } from "react";

import type { ContextMessage, JsonObject, JsonValue } from "../../api/v2/types";
import { Badge } from "../../components/ui/Badge";
import { JsonTree } from "../../components/ui/JsonTree";

function isRecord(value: JsonValue): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

interface MessageView {
  role: string | null;
  label: string | null;
  /** Text parts in declared order. */
  texts: string[];
  /** Non-text parts, kept raw. */
  extras: JsonValue[];
}

/** Narrow the dynamic message value; null means "unknown shape". */
export function narrowMessage(message: JsonValue): MessageView | null {
  if (typeof message === "string") {
    return { role: null, label: null, texts: [message], extras: [] };
  }
  if (!isRecord(message)) return null;
  const role = typeof message.role === "string" ? message.role : null;
  const label = typeof message.label === "string" ? message.label : null;
  const texts: string[] = [];
  const extras: JsonValue[] = [];
  if (Array.isArray(message.parts)) {
    for (const part of message.parts) {
      if (
        isRecord(part) &&
        part.type === "text" &&
        typeof part.text === "string"
      ) {
        texts.push(part.text);
      } else {
        extras.push(part);
      }
    }
  } else if (typeof message.text === "string") {
    texts.push(message.text);
  } else {
    return null;
  }
  return { role, label, texts, extras };
}

export function MessageList({ items }: { items: ContextMessage[] }): ReactElement {
  return (
    <div className="space-y-2">
      {items.map((item) => (
        <MessageCard key={item.message_index} item={item} />
      ))}
    </div>
  );
}

function MessageCard({ item }: { item: ContextMessage }): ReactElement {
  const view = narrowMessage(item.message);
  return (
    <div className="rounded-lg border border-line bg-bg-elev px-3 py-2.5">
      <div className="mb-1.5 flex items-center gap-1.5">
        <span className="text-[11px] font-medium text-fg-faint">
          #{item.message_index}
        </span>
        {view?.role && <Badge tone="blue">{view.role}</Badge>}
        {view?.label && <Badge>{view.label}</Badge>}
      </div>
      {view === null ? (
        <JsonTree value={item.message} defaultExpanded={false} />
      ) : (
        <>
          {view.texts.map((text, index) => (
            <div
              key={index}
              className="text-[13px] leading-5 break-words whitespace-pre-wrap text-fg"
            >
              {text}
            </div>
          ))}
          {view.extras.map((part, index) => (
            <JsonTree key={index} value={part} defaultExpanded={false} />
          ))}
        </>
      )}
    </div>
  );
}
