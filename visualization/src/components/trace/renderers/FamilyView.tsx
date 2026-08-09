/**
 * Family dispatch: maps an ActionRecord to the input/output renderer of its
 * presentation family (registry). Shapes that do not probe cleanly fall back
 * to the raw JSON tree, so no payload is ever hidden.
 */

import type { ReactNode } from "react";
import type { ActionRecord } from "../../../derive/model";
import { asNumber, asString } from "../../../derive/actions/common";
import { descriptorFor, type ActionFamily } from "../../../derive/actions/registry";
import { LinkChip } from "../semantic";
import { AnswerInput, AnswerOutput } from "./AnswerBlock";
import { DiffBlock } from "./DiffBlock";
import { FetchBlock } from "./FetchBlock";
import { GenerateInput, GenerateOutput } from "./GenerateBlock";
import { GenericBlock } from "./GenericBlock";
import { MemorizeOps, RecallBlock } from "./MemoryBlock";
import { MetaGrid, metaEntries } from "./MetaGrid";
import { ReadBlock, ReadInput } from "./ReadBlock";
import { ResultListBlock, resultItemsOf } from "./ResultListBlock";
import {
  CandidateList,
  CommandLine,
  hasTerminalContent,
  TerminalOutput,
} from "./TerminalBlock";
import { isResourceLink } from "./probe";

export function ActionInputView({ action }: { action: ActionRecord }) {
  return <>{inputFor(descriptorFor(action.action).family, action.params)}</>;
}

export function ActionOutputView({ action }: { action: ActionRecord }) {
  const payload = action.result?.payload;
  if (!payload) return null;
  return <>{outputFor(descriptorFor(action.action).family, payload)}</>;
}

/* ------------------------------- input ------------------------------- */

function inputFor(family: ActionFamily, params: Record<string, unknown>): ReactNode {
  switch (family) {
    case "answer":
      return <AnswerInput params={params} />;
    case "patch": {
      const oldText = asString(params.old_text);
      const newText = asString(params.new_text);
      // workspace.append carries `text` — a pure addition to the target.
      const appended = asString(params.text);
      if (oldText === undefined && newText === undefined && appended === undefined) {
        return <GenericBlock value={params} />;
      }
      return <DiffBlock oldText={oldText ?? ""} newText={newText ?? appended ?? ""} />;
    }
    case "generate": {
      const instruction = asString(params.instruction);
      const text = asString(params.text) ?? asString(params.content);
      if (!instruction && !text) return <GenericBlock value={params} />;
      return <GenerateInput instruction={instruction} text={text} />;
    }
    case "command": {
      const command = asString(params.command);
      if (!command) return <GenericBlock value={params} />;
      return <CommandLine command={command} cwd={asString(params.working_directory)} />;
    }
    case "process": {
      const link =
        asString(params.source_link) ?? asString(params.link) ?? asString(params.path);
      const executionId = asString(params.execution_id);
      const waitSeconds = asNumber(params.wait_seconds);
      if (!link && !executionId && waitSeconds === undefined) {
        return <GenericBlock value={params} />;
      }
      return (
        <div className="flex flex-wrap items-center gap-2">
          {link &&
            (isResourceLink(link) ? (
              <LinkChip link={link} />
            ) : (
              <span className="font-mono text-[11px] break-all text-info">{link}</span>
            ))}
          {executionId && (
            <span className="rounded bg-hover px-1.5 py-0.5 font-mono text-[10px] text-fg-muted">
              {executionId}
            </span>
          )}
          {waitSeconds !== undefined && (
            <span className="font-mono text-[10px] text-fg-faint">{waitSeconds}s</span>
          )}
        </div>
      );
    }
    case "search": {
      const query = asString(params.query);
      const link = asString(params.memory_link) ?? asString(params.link);
      if (query) return <div className="text-[12px] text-fg">“{query}”</div>;
      if (link) return <LinkChip link={link} />;
      return <GenericBlock value={params} />;
    }
    case "fetch": {
      const url = asString(params.url) ?? asString(params.start_url);
      const target = asString(params.target_link);
      if (!url && !target) return <GenericBlock value={params} />;
      return (
        <div className="flex flex-wrap items-center gap-2">
          {url && <span className="font-mono text-[11px] break-all text-info">{url}</span>}
          {target && <LinkChip link={target} />}
        </div>
      );
    }
    case "memory-read": {
      const link = asString(params.memory_link);
      return link ? <LinkChip link={link} /> : <GenericBlock value={params} />;
    }
    case "memory-write": {
      const operations = Array.isArray(params.operations) ? params.operations : [];
      return operations.length > 0 ? (
        <MemorizeOps operations={operations} />
      ) : (
        <GenericBlock value={params} />
      );
    }
    case "read": {
      const link = asString(params.link) ?? asString(params.target_link);
      const start = asNumber(params.start_line);
      const end = asNumber(params.end_line);
      if (!link && start === undefined) return <GenericBlock value={params} />;
      return <ReadInput link={link} start={start} end={end} />;
    }
    default:
      return <GenericBlock value={params} />;
  }
}

/* ------------------------------- output ------------------------------ */

function outputFor(family: ActionFamily, payload: Record<string, unknown>): ReactNode {
  switch (family) {
    case "answer":
      return <AnswerOutput payload={payload} />;
    case "patch":
    case "generate":
      return <GenerateOutput payload={payload} />;
    case "command":
      return hasTerminalContent(payload) ? (
        <TerminalOutput payload={payload} />
      ) : (
        <GenericBlock value={payload} />
      );
    case "process": {
      const candidates = Array.isArray(payload.candidates)
        ? (payload.candidates as unknown[])
        : [];
      if (!hasTerminalContent(payload) && candidates.length === 0) {
        return <GenericBlock value={payload} />;
      }
      return (
        <div>
          <TerminalOutput payload={payload} />
          <CandidateList candidates={candidates} />
        </div>
      );
    }
    case "search": {
      const items = resultItemsOf(payload);
      const answer = asString(payload.answer);
      return items.length > 0 || answer ? (
        <ResultListBlock items={items} answer={answer} />
      ) : (
        <GenericBlock value={payload} />
      );
    }
    case "fetch":
      return <FetchBlock payload={payload} />;
    case "memory-read":
      return <RecallBlock payload={payload} />;
    case "memory-write": {
      const entries = metaEntries(payload, ["revision", "digest", "changed", "chars"]);
      return entries.length > 0 ? (
        <MetaGrid entries={entries} />
      ) : (
        <GenericBlock value={payload} />
      );
    }
    case "read":
      return <ReadBlock payload={payload} />;
    default:
      return <GenericBlock value={payload} />;
  }
}
