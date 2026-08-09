/**
 * Answer family: core.answer. The input is the composed guide/input prompt
 * blocks; the output is the final answer Markdown plus its references.
 * Migrated from the retired actionRenderers.tsx special case.
 */

import { asRecord, asString } from "../../../derive/actions/common";
import { Markdown } from "../../markdown/Markdown";
import { LinkChip } from "../semantic";
import { GenericBlock } from "./GenericBlock";
import { isResourceLink } from "./probe";

interface PromptBlock {
  label: string | null;
  text: string;
}

function blocksOf(value: unknown): PromptBlock[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .map((item) => ({ label: asString(item.label) ?? null, text: asString(item.text) ?? "" }))
    .filter((block) => block.text.length > 0);
}

export function AnswerInput({ params }: { params: Record<string, unknown> }) {
  const blocks = [...blocksOf(params.guide_blocks), ...blocksOf(params.input_blocks)];
  if (blocks.length === 0) return <GenericBlock value={params} />;
  return (
    <div className="space-y-1.5">
      {blocks.map((block, i) => (
        <div key={i} className="rounded-lg border border-line bg-bg-elev px-2.5 py-1.5">
          {block.label && (
            <div className="mb-0.5 text-[10px] font-semibold tracking-wide text-fg-faint uppercase">
              {block.label}
            </div>
          )}
          <div className="text-[12px] leading-5 whitespace-pre-wrap text-fg-muted">
            {block.text}
          </div>
        </div>
      ))}
    </div>
  );
}

export function AnswerOutput({ payload }: { payload: Record<string, unknown> }) {
  const text = asString(payload.text);
  const references = Array.isArray(payload.references) ? payload.references : [];
  if (!text && references.length === 0) return <GenericBlock value={payload} />;
  return (
    <div className="space-y-1.5">
      {text && (
        <div className="rounded-lg border border-line bg-bg-elev px-3 py-2">
          <Markdown>{text}</Markdown>
        </div>
      )}
      <ReferenceList references={references} />
    </div>
  );
}

function ReferenceList({ references }: { references: unknown[] }) {
  if (references.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="text-[10px] font-semibold tracking-wide text-fg-faint uppercase">
        References
      </span>
      {references.map((reference, i) => (
        <ReferenceChip key={i} reference={reference} />
      ))}
    </div>
  );
}

function ReferenceChip({ reference }: { reference: unknown }) {
  const record = asRecord(reference);
  const link = record
    ? (asString(record.link) ?? asString(record.target_link) ?? asString(record.url))
    : asString(reference);
  const label = record ? (asString(record.title) ?? asString(record.label)) : undefined;
  if (link && isResourceLink(link)) return <LinkChip link={link} />;
  if (link) return <span className="font-mono text-[10px] break-all text-info">{link}</span>;
  if (label) return <span className="text-[11px] text-fg-muted">{label}</span>;
  return null;
}
