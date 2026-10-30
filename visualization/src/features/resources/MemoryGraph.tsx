/**
 * The Memory ego graph (plan §12 improvement 7): the current document sits at
 * the center, documents referencing it (explicit backlinks) form the left
 * column with edges into the center, and its direct refs form the right
 * column with edges out — direction always follows the real reference edge.
 *
 * Pure SVG over facts the panel already holds: no similarity guesses, no edge
 * type labels, no force simulation — columns are deterministic. Hovering one
 * node or edge highlights only that real edge and its peer; clicking a
 * neighbor opens it through the panel's router entry, which re-anchors the
 * whole panel and rebuilds the graph around the new document.
 */

import { useState, type ReactElement } from "react";
import { Unlink } from "lucide-react";

import type { DirectReference } from "../../api/v2/common";
import type { SearchItem } from "../../api/v2/types";
import { refTypeIcon } from "./refTypeIcon";

export type BacklinksState = "loading" | "error" | "undeclared" | "ready";

export interface MemoryGraphProps {
  /** Center document ref (the backlinks anchor). */
  anchor: string;
  /** Owner display of the center document; falls back to the ref segment. */
  anchorTitle: string | null;
  /** Direct refs already read with the document (outgoing edges). */
  directRefs: DirectReference[];
  /** Loaded backlink items; null until the query settles. */
  backlinks: SearchItem[] | null;
  /** Left-column data state. */
  backlinksState: BacklinksState;
  /** Open one neighbor through the panel's router entry. */
  onOpenRef: (ref: string) => void;
}

const SVG_W = 600;
const NODE_W = 150;
const NODE_H = 34;
const ROW_GAP = 22;
const HEADER_H = 26;
const LEFT_X = 8;
const CENTER_X = 225;
const RIGHT_X = 442;
const MAX_PER_SIDE = 12;
const TEXT_X = 32;

function lastSegment(ref: string): string {
  const path = ref.includes("/") ? ref.slice(ref.lastIndexOf("/") + 1) : ref;
  return path.includes(":") ? path.slice(path.lastIndexOf(":") + 1) : path;
}

/** Greedy width fit for SVG text (CJK ≈ 11px, latin ≈ 6.2px at 11px font). */
export function fitGraphTitle(title: string, maxWidth = 112): string {
  let width = 0;
  let used = 0;
  for (const char of title) {
    const w = char >= "⺀" ? 11 : 6.2;
    if (width + w > maxWidth) break;
    width += w;
    used += char.length;
  }
  return used >= title.length ? title : `${title.slice(0, used)}…`;
}

interface GraphNodeData {
  key: string;
  ref: string;
  label: string;
  x: number;
  y: number;
}

function edgePath(fromX: number, fromY: number, toX: number, toY: number): string {
  const midX = (fromX + toX) / 2;
  return `M${fromX},${fromY} C${midX},${fromY} ${midX},${toY} ${toX},${toY}`;
}

export function MemoryGraph(props: MemoryGraphProps): ReactElement {
  const { anchor, anchorTitle, directRefs, backlinks, backlinksState, onOpenRef } = props;
  const [hovered, setHovered] = useState<string | null>(null);
  const [expandLeft, setExpandLeft] = useState(false);
  const [expandRight, setExpandRight] = useState(false);

  const leftItems = backlinksState === "ready" ? (backlinks ?? []) : [];
  const leftVisible = expandLeft ? leftItems : leftItems.slice(0, MAX_PER_SIDE);
  const rightVisible = expandRight ? directRefs : directRefs.slice(0, MAX_PER_SIDE);
  const leftHidden = leftItems.length - leftVisible.length;
  const rightHidden = directRefs.length - rightVisible.length;

  // Both sides factually empty: say so instead of drawing an empty canvas.
  const nothingToDraw =
    directRefs.length === 0 &&
    (backlinksState === "undeclared" ||
      (backlinksState === "ready" && leftItems.length === 0));
  if (nothingToDraw) {
    return (
      <div className="flex flex-col items-center gap-2 py-10 text-center text-[12px] text-fg-faint">
        <Unlink size={18} />
        这篇文档还没有引用边。
      </div>
    );
  }

  const leftRows = Math.max(leftVisible.length + (leftHidden > 0 ? 1 : 0), 1);
  const rightRows = Math.max(rightVisible.length + (rightHidden > 0 ? 1 : 0), 1);
  const sideSpan = (rows: number) => rows * NODE_H + (rows - 1) * ROW_GAP;
  const leftSpan = sideSpan(leftRows);
  const rightSpan = sideSpan(rightRows);
  const contentH = Math.max(leftSpan, rightSpan, NODE_H);
  const height = HEADER_H + contentH + 8;
  const leftStart = HEADER_H + (contentH - leftSpan) / 2;
  const rightStart = HEADER_H + (contentH - rightSpan) / 2;
  const centerY = HEADER_H + contentH / 2 - NODE_H / 2;
  const centerMidY = centerY + NODE_H / 2;

  const leftNodes: GraphNodeData[] = leftVisible.map((item, index) => ({
    key: `L${index}`,
    ref: item.ref,
    label: item.title || lastSegment(item.ref),
    x: LEFT_X,
    y: leftStart + index * (NODE_H + ROW_GAP),
  }));
  const rightNodes: GraphNodeData[] = rightVisible.map((item, index) => ({
    key: `R${index}`,
    ref: item.ref,
    label: item.title || lastSegment(item.ref),
    x: RIGHT_X,
    y: rightStart + index * (NODE_H + ROW_GAP),
  }));

  const centerLabel = anchorTitle ?? lastSegment(anchor);
  const hover = (key: string) => setHovered(key);
  const unhover = (key: string) =>
    setHovered((current) => (current === key ? null : current));

  const renderNode = (node: GraphNodeData): ReactElement => {
    const { Icon, className: iconClass } = refTypeIcon(node.ref);
    const dimmed = hovered !== null && hovered !== node.key;
    return (
      <g
        key={node.key}
        transform={`translate(${node.x},${node.y})`}
        role="button"
        tabIndex={0}
        aria-label={`${node.label}（${node.ref}）`}
        className="cursor-pointer outline-none"
        style={{ opacity: dimmed ? 0.4 : 1, transition: "opacity 150ms" }}
        onClick={() => onOpenRef(node.ref)}
        onKeyDown={(event) => {
          if (event.key === "Enter") onOpenRef(node.ref);
        }}
        onMouseEnter={() => hover(node.key)}
        onMouseLeave={() => unhover(node.key)}
      >
        <title>{node.ref}</title>
        <rect
          width={NODE_W}
          height={NODE_H}
          rx={8}
          style={{
            fill: "var(--bg-elev)",
            stroke: hovered === node.key ? "var(--accent)" : "var(--line)",
            strokeWidth: hovered === node.key ? 1.4 : 1,
            transition: "stroke 150ms",
          }}
        />
        <g transform="translate(10,10)">
          <Icon size={14} className={iconClass} />
        </g>
        <text x={TEXT_X} y={21} fontSize={11} style={{ fill: "var(--fg)" }}>
          {fitGraphTitle(node.label)}
        </text>
      </g>
    );
  };

  const renderEdge = (node: GraphNodeData, side: "left" | "right"): ReactElement => {
    const active = hovered === node.key;
    const fromX = side === "left" ? node.x + NODE_W : CENTER_X + NODE_W;
    const fromY = side === "left" ? node.y + NODE_H / 2 : centerMidY;
    const toX = side === "left" ? CENTER_X : node.x;
    const toY = side === "left" ? centerMidY : node.y + NODE_H / 2;
    const d = edgePath(fromX, fromY, toX, toY);
    return (
      <g key={`e-${node.key}`}>
        <path
          d={d}
          fill="none"
          strokeWidth={active ? 1.8 : 1.3}
          markerEnd={active ? "url(#ego-arr-hl)" : "url(#ego-arr)"}
          pointerEvents="none"
          style={{
            stroke: active ? "var(--accent)" : "var(--line)",
            strokeOpacity: hovered !== null && !active ? 0.16 : 1,
            transition: "stroke 150ms, stroke-opacity 150ms",
          }}
        />
        {/* generous hover target */}
        <path
          d={d}
          fill="none"
          stroke="transparent"
          strokeWidth={12}
          onMouseEnter={() => hover(node.key)}
          onMouseLeave={() => unhover(node.key)}
        />
      </g>
    );
  };

  const renderMore = (side: "left" | "right", hidden: number): ReactElement | null => {
    if (hidden <= 0) return null;
    const x = side === "left" ? LEFT_X : RIGHT_X;
    const count = side === "left" ? leftVisible.length : rightVisible.length;
    const y = (side === "left" ? leftStart : rightStart) + count * (NODE_H + ROW_GAP);
    return (
      <g
        transform={`translate(${x},${y})`}
        role="button"
        tabIndex={0}
        aria-label={`展开该侧其余 ${hidden} 个节点`}
        className="cursor-pointer outline-none"
        onClick={() => (side === "left" ? setExpandLeft(true) : setExpandRight(true))}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            side === "left" ? setExpandLeft(true) : setExpandRight(true);
          }
        }}
      >
        <rect
          width={NODE_W}
          height={NODE_H}
          rx={8}
          fill="transparent"
          strokeDasharray="4 3"
          style={{ stroke: "var(--fg-faint)" }}
        />
        <text
          x={NODE_W / 2}
          y={21}
          textAnchor="middle"
          fontSize={11}
          style={{ fill: "var(--fg-muted)" }}
        >
          +{hidden} 更多
        </text>
      </g>
    );
  };

  return (
    <svg
      viewBox={`0 0 ${SVG_W} ${height}`}
      className="block w-full"
      role="img"
      aria-label={`${centerLabel} 的引用关系图`}
    >
      <defs>
        <marker
          id="ego-arr"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M0,0 L10,5 L0,10 z" style={{ fill: "var(--fg-faint)" }} />
        </marker>
        <marker
          id="ego-arr-hl"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M0,0 L10,5 L0,10 z" style={{ fill: "var(--accent)" }} />
        </marker>
      </defs>

      <text x={LEFT_X + NODE_W / 2} y={17} textAnchor="middle" fontSize={10} style={{ fill: "var(--fg-faint)" }}>
        被引用 ↓
      </text>
      <text x={CENTER_X + NODE_W / 2} y={17} textAnchor="middle" fontSize={10} style={{ fill: "var(--accent)" }}>
        当前文档
      </text>
      <text x={RIGHT_X + NODE_W / 2} y={17} textAnchor="middle" fontSize={10} style={{ fill: "var(--fg-faint)" }}>
        引用了 →
      </text>

      {leftNodes.map((node) => renderEdge(node, "left"))}
      {rightNodes.map((node) => renderEdge(node, "right"))}

      {backlinksState !== "ready" && (
        <text
          x={LEFT_X + NODE_W / 2}
          y={HEADER_H + contentH / 2 + 4}
          textAnchor="middle"
          fontSize={11}
          className={backlinksState === "loading" ? "animate-pulse" : undefined}
          style={{ fill: "var(--fg-faint)" }}
        >
          {backlinksState === "loading"
            ? "正在查询被引用的文档…"
            : backlinksState === "error"
              ? "反链查询失败"
              : "此资源所有者未声明反链检索"}
        </text>
      )}
      {backlinksState === "ready" && leftItems.length === 0 && (
        <text
          x={LEFT_X + NODE_W / 2}
          y={HEADER_H + contentH / 2 + 4}
          textAnchor="middle"
          fontSize={11}
          style={{ fill: "var(--fg-faint)" }}
        >
          无
        </text>
      )}
      {directRefs.length === 0 && (
        <text
          x={RIGHT_X + NODE_W / 2}
          y={HEADER_H + contentH / 2 + 4}
          textAnchor="middle"
          fontSize={11}
          style={{ fill: "var(--fg-faint)" }}
        >
          无
        </text>
      )}

      {leftNodes.map(renderNode)}
      {rightNodes.map(renderNode)}
      {renderMore("left", leftHidden)}
      {renderMore("right", rightHidden)}

      <g transform={`translate(${CENTER_X},${centerY})`}>
        <title>{anchor}</title>
        <rect
          width={NODE_W}
          height={NODE_H}
          rx={8}
          style={{
            fill: "var(--bg-elev)",
            stroke: "var(--accent)",
            strokeOpacity: 0.55,
            filter: "drop-shadow(0 0 10px color-mix(in srgb, var(--accent) 18%, transparent))",
          }}
        />
        <g transform="translate(10,10)">
          {(() => {
            const { Icon, className } = refTypeIcon(anchor);
            return <Icon size={14} className={className} />;
          })()}
        </g>
        <text
          x={TEXT_X}
          y={21}
          fontSize={11}
          fontWeight={600}
          style={{ fill: "var(--fg)" }}
        >
          {fitGraphTitle(centerLabel)}
        </text>
      </g>
    </svg>
  );
}
