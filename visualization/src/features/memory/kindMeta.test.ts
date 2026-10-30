import { CalendarDays, Lightbulb, Pin, StickyNote, User } from "lucide-react";
import { describe, expect, it } from "vitest";
import { memoryKindFromRef, memoryKindMeta, type MemoryKind } from "./kindMeta";

const cases: Array<[MemoryKind, string, string, typeof CalendarDays]> = [
  ["daily", "日记", "yellow", CalendarDays],
  ["entity", "实体", "blue", User],
  ["concept", "概念", "purple", Lightbulb],
  ["fact", "事实", "green", Pin],
  ["note", "便签", "pink", StickyNote],
];

describe("memory kind metadata", () => {
  it.each(cases)("maps %s to one icon, tone and Chinese label", (kind, label, tone, icon) => {
    const meta = memoryKindMeta(kind);
    expect(meta.label).toBe(label);
    expect(meta.tone).toBe(tone);
    expect(meta.icon).toBe(icon);
  });

  it("keeps unknown kinds raw and derives kinds only from memory refs", () => {
    const unknown = memoryKindMeta("custom");
    expect(unknown.label).toBe("custom");
    expect(unknown.tone).toBe("gray");
    expect(memoryKindFromRef("memory:fact/context-owner")).toBe("fact");
    expect(memoryKindFromRef("memory:custom/item")).toBe("custom");
    expect(memoryKindFromRef("memory:current")).toBeNull();
    expect(memoryKindFromRef("workspace:notes.md")).toBeNull();
  });
});
