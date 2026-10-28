import type { JsonObject } from "../../api/v2/types";
import { asString } from "./facts";

export interface AnalysisNarrative {
  kind: "report" | "description";
  text: string;
}

export interface AnalysisGist extends AnalysisNarrative {
  title: string | null;
  summary: string | null;
}

export function analysisNarrative(
  actionId: string,
  payload: JsonObject,
): AnalysisNarrative | null {
  if (actionId === "workspace.describe") {
    const description = asString(payload.description);
    return description !== null && description.trim() !== ""
      ? { kind: "description", text: description }
      : null;
  }
  if (actionId !== "workspace.analyze") return null;
  const answer = asString(payload.answer) ?? asString(payload.text);
  return answer !== null && answer.trim() !== ""
    ? { kind: "report", text: answer }
    : null;
}

export function analysisGist(
  actionId: string,
  payload: JsonObject,
): AnalysisGist | null {
  const narrative = analysisNarrative(actionId, payload);
  if (narrative === null) return null;
  const title = narrative.kind === "report" ? markdownTitle(narrative.text) : null;
  return {
    ...narrative,
    title: title !== null ? truncate(title, 100) : null,
    summary: firstContentLine(narrative.text),
  };
}

function markdownTitle(text: string): string | null {
  for (const line of text.split("\n")) {
    const match = /^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$/.exec(line);
    if (match?.[1]?.trim()) return match[1].trim();
  }
  return null;
}

function firstContentLine(text: string): string | null {
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (
      trimmed === "" ||
      /^\s{0,3}#{1,6}\s+/.test(line) ||
      /^\s{0,3}(`{3,}|~{3,})/.test(line)
    ) {
      continue;
    }
    const content = trimmed
      .replace(/^>\s*/, "")
      .replace(/^(?:[-*+]|\d+[.)])\s+/, "")
      .trim();
    if (content !== "") return truncate(content, 180);
  }
  return null;
}

function truncate(text: string, limit: number): string {
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}
