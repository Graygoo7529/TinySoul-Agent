/**
 * Presentation descriptors for the workspace domain: bounded text artifacts
 * (create/rewrite/patch/append), reads, literal search, resource scanning
 * and trash, plus document conversion.
 */

import { truncate } from "../activitySemantics";
import type { ActionDescriptor } from "./types";
import {
  asNumber,
  asRecord,
  asString,
  defaultResultSummary,
  defaultTargetOf,
  resultToneOf,
} from "./common";

function linkHeadline(verbPhrase: string, params: Record<string, unknown>): string {
  const link = asString(params.target_link) ?? asString(params.link) ?? asString(params.source_link);
  return link ? `${verbPhrase} ${link}` : verbPhrase;
}

export const WORKSPACE_ACTIONS: ActionDescriptor[] = [
  {
    action: "workspace.create",
    verb: "Creating",
    family: "generate",
    summarizeCall: (params) => ({
      headline: linkHeadline("生成", params),
      target: defaultTargetOf("workspace.create", params),
    }),
  },
  {
    action: "workspace.rewrite",
    verb: "Rewriting",
    family: "generate",
    summarizeCall: (params) => ({
      headline: linkHeadline("重写", params),
      target: defaultTargetOf("workspace.rewrite", params),
    }),
  },
  {
    action: "workspace.patch",
    verb: "Editing",
    family: "patch",
    summarizeCall: (params) => ({
      headline: linkHeadline("编辑", params),
      target: defaultTargetOf("workspace.patch", params),
    }),
  },
  {
    action: "workspace.append",
    verb: "Appending to",
    family: "patch",
    summarizeCall: (params) => ({
      headline: linkHeadline("追加", params),
      target: defaultTargetOf("workspace.append", params),
    }),
  },
  {
    action: "workspace.read",
    verb: "Reading",
    family: "read",
    summarizeCall: (params) => {
      const start = asNumber(params.start_line);
      const end = asNumber(params.end_line);
      return {
        headline: linkHeadline("读取", params),
        target: defaultTargetOf("workspace.read", params),
        chips: start !== undefined && end !== undefined ? [`${start}-${end} 行`] : undefined,
      };
    },
    summarizeResult: (result) => {
      // Protocol: actual is a {start, end} line range (tinysoul/workspace/actions.py);
      // tolerate a bare count for robustness.
      const range = asRecord(result.payload?.actual);
      const start = asNumber(range?.start);
      const end = asNumber(range?.end);
      const lines =
        start !== undefined && end !== undefined
          ? Math.max(0, end - start + 1)
          : asNumber(result.payload?.actual);
      if (lines === undefined) return defaultResultSummary(result);
      const truncated = result.payload?.truncated === true;
      return {
        headline: `${lines} 行`,
        tone: resultToneOf(result.status),
        chips: truncated ? ["截断"] : undefined,
      };
    },
  },
  {
    action: "workspace.delete",
    verb: "Deleting",
    family: "delete",
    summarizeCall: (params) => ({
      headline: linkHeadline("删除", params),
      target: defaultTargetOf("workspace.delete", params),
    }),
  },
  {
    action: "workspace.restore",
    verb: "Restoring",
    family: "delete",
    summarizeCall: (params) => {
      const ref = asString(params.trash_ref);
      return {
        headline: ref ? `恢复 ${ref}` : "恢复",
        target: defaultTargetOf("workspace.restore", params),
      };
    },
  },
  {
    action: "workspace.scan",
    verb: "Scanning workspace",
    family: "scan",
    summarizeCall: () => ({ headline: "扫描工作区" }),
    summarizeResult: (result) => {
      const count = asNumber(result.payload?.count);
      if (count === undefined) return defaultResultSummary(result);
      return { headline: `${count} 个资源`, tone: resultToneOf(result.status) };
    },
  },
  {
    action: "workspace.describe",
    verb: "Describing",
    family: "scan",
    summarizeCall: (params) => ({
      headline: linkHeadline("描述", params),
      target: defaultTargetOf("workspace.describe", params),
    }),
  },
  {
    action: "workspace.analyze",
    verb: "Analyzing",
    family: "scan",
    summarizeCall: (params) => {
      const intent = asString(params.intent);
      const refs = Array.isArray(params.reference_links) ? params.reference_links.length : 0;
      return {
        headline: intent ? `分析 ${truncate(intent.replace(/\s+/g, " "), 40)}` : "分析",
        target: defaultTargetOf("workspace.analyze", params),
        chips: refs > 0 ? [`${refs} 个引用`] : undefined,
      };
    },
  },
  {
    action: "workspace.search_text",
    verb: "Searching workspace",
    family: "search",
    summarizeCall: (params) => {
      const query = asString(params.query);
      const locator = asString(asRecord(params.scope)?.locator);
      return {
        headline: query ? `检索 “${query}”` : "检索",
        target: defaultTargetOf("workspace.search_text", params),
        chips: locator ? [locator] : undefined,
      };
    },
    summarizeResult: (result) => {
      const matches =
        asNumber(result.payload?.match_line_count) ??
        (Array.isArray(result.payload?.fragments)
          ? (result.payload?.fragments as unknown[]).length
          : undefined);
      if (matches === undefined) return defaultResultSummary(result);
      return { headline: `${matches} 处匹配`, tone: resultToneOf(result.status) };
    },
  },
  {
    action: "workspace.trash.list",
    verb: "Listing trash",
    family: "scan",
    summarizeCall: () => ({ headline: "查看回收站" }),
  },
  {
    action: "workspace.convert_with_markitdown",
    verb: "Converting",
    family: "process",
    summarizeCall: (params) => ({
      headline: linkHeadline("转换", params),
      target: defaultTargetOf("workspace.convert_with_markitdown", params),
    }),
  },
  {
    action: "workspace.convert_with_pypdf",
    verb: "Converting",
    family: "process",
    summarizeCall: (params) => ({
      headline: linkHeadline("转换", params),
      target: defaultTargetOf("workspace.convert_with_pypdf", params),
    }),
  },
];
