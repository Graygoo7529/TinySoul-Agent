/**
 * Presentation descriptors for the core domain: the user-facing answer, the
 * internal reasoning step, context/session inspection, and active-memory
 * read/write operations.
 */

import type { ActionDescriptor } from "./types";
import { asString, defaultTargetOf } from "./common";

export const CORE_ACTIONS: ActionDescriptor[] = [
  {
    action: "core.answer",
    verb: "Composing answer",
    family: "answer",
    summarizeCall: () => ({ headline: "进行回答" }),
  },
  {
    action: "core.reason",
    verb: "Reasoning",
    family: "reason",
    summarizeCall: () => ({ headline: "推理" }),
  },
  {
    action: "core.context.inspect",
    verb: "Inspecting context",
    family: "inspect",
    summarizeCall: (params) => {
      const ref = asString(params.ref);
      return {
        headline: ref ? `检查上下文 ${ref}` : "检查上下文",
        target: ref ? { subject: ref } : undefined,
      };
    },
  },
  {
    action: "core.session.inspect",
    verb: "Inspecting session",
    family: "inspect",
    summarizeCall: (params) => {
      const ref = asString(params.ref);
      return {
        headline: ref ? `检查会话 ${ref}` : "检查会话",
        target: ref ? { subject: ref } : undefined,
      };
    },
  },
  {
    action: "core.memory.inspect",
    verb: "Inspecting memory",
    family: "search",
    summarizeCall: (params) => {
      const query = asString(params.query);
      const link = asString(params.memory_link);
      const headline = query
        ? `检索记忆 “${query}”`
        : link
          ? `探查记忆 ${link}`
          : "检索记忆";
      return { headline, target: defaultTargetOf("core.memory.inspect", params) };
    },
  },
  {
    action: "core.memory.memorize",
    verb: "Memorizing",
    family: "memory-write",
    summarizeCall: (params) => {
      const ops = Array.isArray(params.operations) ? params.operations.length : 0;
      return {
        headline: "更新活动记忆",
        target: defaultTargetOf("core.memory.memorize", params),
        chips: ops > 0 ? [`${ops} 项操作`] : undefined,
      };
    },
  },
  {
    action: "core.memory.recall",
    verb: "Recalling",
    family: "memory-read",
    summarizeCall: (params) => {
      const link = asString(params.memory_link);
      return {
        headline: link ? `召回 ${link}` : "召回记忆",
        target: defaultTargetOf("core.memory.recall", params),
      };
    },
  },
];
