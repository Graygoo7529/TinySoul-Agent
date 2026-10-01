# P1：v2 Chat Presentation Projection 设计

日期：2026-09-30  
前置：P0 基线清单完成  
目标：在 `features/chat/` 与 `features/trace/` 建立面向呈现的纯类型和适配函数，作为旧版组件消费 v2 数据的桥接层。

## 设计原则

1. **分层清晰**：
   - **Owner snapshot**（turnStore、sessionStore）：正式状态，决定 Turn 状态、问题、预算、结果、取消、是否允许输入
   - **Observation buffer**（短生命周期）：过程细节和动画输入，不覆盖正式状态
   - **Presentation projection**（本层）：纯函数，将 owner 数据映射为 UI 消费的呈现模型

2. **单向数据流**：
   - v2 TurnSnapshot → Presentation Model → UI Component
   - Observation events → Activity Buffer → Presentation Model → UI Component
   - 不逆向修改 owner snapshot
   - 不保存跨 Turn 的第二份业务事实

3. **类型安全**：
   - 明确的 TypeScript 接口
   - 不使用 `any` 或 `unknown` 传递状态
   - 运行时校验动态边界（WebSocket events）

## 核心类型设计

### 1. Turn 呈现模型

```typescript
// features/chat/presentation.ts

import type {
  TurnSnapshot,
  Interaction,
  PendingItem,
  TurnResult,
  Question,
  Budget,
} from "../api/v2/types";

/**
 * Turn 的完整呈现模型，供 TurnView 消费。
 * 由 TurnSnapshot 和 Activity Buffer 组合而成。
 */
export interface TurnPresentation {
  /** 唯一标识 */
  turnId: string;
  
  /** Turn 正式状态（来自 owner snapshot） */
  status: TurnStatus;
  
  /** 用户输入（初始 + 追加） */
  inputs: TurnInput[];
  
  /** 活动状态（仅 running 时有值） */
  activity: ActivityPresentation | null;
  
  /** 等待问题（仅 waiting_for_question 时有值） */
  question: QuestionPresentation | null;
  
  /** 预算等待（仅 suspended_budget 时有值） */
  budgetSuspension: BudgetPresentation | null;
  
  /** 最终回答（settled 后有值） */
  answer: AnswerPresentation | null;
  
  /** pending items（等待外部事件） */
  pendingItems: PendingItemPresentation[];
  
  /** 时间戳 */
  timestamps: {
    created: string;
    answered?: string;
    stopped?: string;
    cancelled?: string;
  };
}

/**
 * Turn 状态（UI 关心的状态）
 */
export type TurnStatus =
  | "running"             // 执行中
  | "waiting_question"    // 等待用户回答问题
  | "waiting_budget"      // 等待预算补充
  | "answered"            // 已回答
  | "stopped"             // 已停止
  | "cancelled"           // 已取消
  | "failed";             // 失败

/**
 * 用户输入
 */
export interface TurnInput {
  type: "initial" | "append" | "reply";
  text: string;
  timestamp: string;
}

/**
 * 活动状态呈现（running 时）
 */
export interface ActivityPresentation {
  /** 当前 phase headline */
  headline: PhaseHeadline;
  
  /** Thinking 流（最新推理摘要） */
  thinking: ThinkingStream;
  
  /** 活动轨迹（最近的语义步骤） */
  trail: ActivityStep[];
  
  /** Working 状态（todos/milestones） */
  working: WorkingState;
  
  /** 计时 */
  timing: {
    startedAt: string;
    elapsedMs: number;
  };
  
  /** 是否可停止 */
  canStop: boolean;
}

/**
 * Phase headline（当前活动阶段）
 */
export interface PhaseHeadline {
  phase: "phase1" | "phase2" | "phase3";
  label: string;  // "Understanding", "Planning", "Executing"
  domain?: string;  // 选中的 domain
  skill?: string;   // 挂载的 skill
}

/**
 * Thinking 流
 */
export interface ThinkingStream {
  /** 最新推理段落 */
  current: string;
  /** 是否展开 */
  expanded: boolean;
  /** 完整历史（折叠时不可见） */
  history: string[];
}

/**
 * 活动步骤（语义条目）
 */
export interface ActivityStep {
  id: string;
  type: ActivityStepType;
  timestamp: string;
  
  /** 步骤呈现内容 */
  content: ActivityStepContent;
  
  /** 是否自动展开 gist */
  autoExpandGist: boolean;
}

export type ActivityStepType =
  | "phase_start"      // Phase 开始
  | "thinking"         // Thinking 更新
  | "domain_select"    // Domain 选择
  | "skill_mount"      // Skill 挂载
  | "context_update"   // Context 更新
  | "action_plan"      // Action 规划
  | "action_result"    // Action 结果
  | "provider_retry"   // Provider 重试
  | "milestone"        // Milestone 更新
  | "todo";            // Todo 更新

/**
 * 活动步骤内容（联合类型）
 */
export type ActivityStepContent =
  | { type: "phase_start"; phase: PhaseHeadline }
  | { type: "thinking"; text: string }
  | { type: "domain_select"; domains: string[] }
  | { type: "skill_mount"; skill: string; domain: string }
  | { type: "context_update"; summary: string }
  | { type: "action_plan"; glimpse: ActionGlimpseData }
  | { type: "action_result"; glimpse: ActionGlimpseData }
  | { type: "provider_retry"; provider: string; attempt: number }
  | { type: "milestone"; text: string; status: "done" | "blocked" | "skipped" }
  | { type: "todo"; text: string; status: "pending" | "done" };

/**
 * Action 预览数据（双阶段）
 */
export interface ActionGlimpseData {
  /** Canonical action ID */
  actionId: string;
  /** Domain */
  domain: string;
  /** Stage */
  stage: "plan" | "result";
  /** 参数摘要（plan 阶段） */
  params?: Record<string, unknown>;
  /** 结果摘要（result 阶段） */
  result?: {
    status: "success" | "failure" | "timeout" | "cancelled" | "not_executed";
    durationMs?: number;
    preview?: string;  // 前 N 行预览
  };
}

/**
 * Working 状态
 */
export interface WorkingState {
  todos: TodoItem[];
  milestones: MilestoneItem[];
}

export interface TodoItem {
  id: string;
  text: string;
  status: "pending" | "done";
}

export interface MilestoneItem {
  id: string;
  text: string;
  status: "done" | "blocked" | "skipped";
}

/**
 * Question 呈现
 */
export interface QuestionPresentation {
  question: string;
  options: QuestionOption[];
  allowOther: boolean;
  requireComment: boolean;
}

export interface QuestionOption {
  id: string;
  label: string;
  description?: string;
}

/**
 * Budget 呈现
 */
export interface BudgetPresentation {
  reason: string;
  requested: {
    inputTokens: number;
    outputTokens: number;
  };
  current: {
    inputTokens: number;
    outputTokens: number;
  };
}

/**
 * Answer 呈现
 */
export interface AnswerPresentation {
  /** 回答内容（Markdown） */
  content: string;
  /** 是否是 terminal 态（打字机） */
  isTerminal: boolean;
  /** 是否已 settle */
  isSettled: boolean;
}

/**
 * Pending item 呈现
 */
export interface PendingItemPresentation {
  id: string;
  type: string;
  label: string;
  status: "pending" | "resolved" | "failed";
}
```

### 2. 适配函数

```typescript
// features/chat/adapters.ts

import type {
  TurnSnapshot,
  Interaction,
} from "../api/v2/types";
import type {
  TurnPresentation,
  TurnStatus,
  TurnInput,
  QuestionPresentation,
  BudgetPresentation,
  AnswerPresentation,
  PendingItemPresentation,
} from "./presentation";

/**
 * 将 v2 TurnSnapshot 映射为 TurnPresentation（不含活动状态）
 */
export function snapshotToPresentation(
  snapshot: TurnSnapshot,
): Omit<TurnPresentation, "activity"> {
  const status = deriveTurnStatus(snapshot);
  
  return {
    turnId: snapshot.turn_id,
    status,
    inputs: deriveInputs(snapshot),
    activity: null,  // 由 activity buffer 提供
    question: deriveQuestion(snapshot),
    budgetSuspension: deriveBudget(snapshot),
    answer: deriveAnswer(snapshot),
    pendingItems: derivePendingItems(snapshot),
    timestamps: {
      created: snapshot.created_at,
      answered: snapshot.answered_at,
      stopped: snapshot.stopped_at,
      cancelled: snapshot.cancelled_at,
    },
  };
}

/**
 * 推导 Turn 状态
 */
function deriveTurnStatus(snapshot: TurnSnapshot): TurnStatus {
  if (snapshot.cancelled_at) return "cancelled";
  if (snapshot.stopped_at) return "stopped";
  if (snapshot.answered_at) return "answered";
  if (snapshot.failure) return "failed";
  if (snapshot.question) return "waiting_question";
  if (snapshot.budget_suspension) return "waiting_budget";
  return "running";
}

/**
 * 推导用户输入
 */
function deriveInputs(snapshot: TurnSnapshot): TurnInput[] {
  const inputs: TurnInput[] = [];
  
  // Initial input
  if (snapshot.initial_input) {
    inputs.push({
      type: "initial",
      text: snapshot.initial_input.text,
      timestamp: snapshot.initial_input.timestamp || snapshot.created_at,
    });
  }
  
  // Appends
  for (const append of snapshot.appends || []) {
    inputs.push({
      type: "append",
      text: append.text,
      timestamp: append.timestamp,
    });
  }
  
  // Reply
  if (snapshot.reply) {
    inputs.push({
      type: "reply",
      text: snapshot.reply.text,
      timestamp: snapshot.reply.timestamp,
    });
  }
  
  return inputs;
}

/**
 * 推导 Question
 */
function deriveQuestion(
  snapshot: TurnSnapshot,
): QuestionPresentation | null {
  if (!snapshot.question) return null;
  
  return {
    question: snapshot.question.question,
    options: snapshot.question.options.map((opt) => ({
      id: opt.id,
      label: opt.label,
      description: opt.description,
    })),
    allowOther: snapshot.question.allow_other,
    requireComment: snapshot.question.require_comment || false,
  };
}

/**
 * 推导 Budget
 */
function deriveBudget(
  snapshot: TurnSnapshot,
): BudgetPresentation | null {
  if (!snapshot.budget_suspension) return null;
  
  return {
    reason: snapshot.budget_suspension.reason,
    requested: {
      inputTokens: snapshot.budget_suspension.requested.input_tokens,
      outputTokens: snapshot.budget_suspension.requested.output_tokens,
    },
    current: {
      inputTokens: snapshot.budget_suspension.current.input_tokens,
      outputTokens: snapshot.budget_suspension.current.output_tokens,
    },
  };
}

/**
 * 推导 Answer
 */
function deriveAnswer(snapshot: TurnSnapshot): AnswerPresentation | null {
  if (!snapshot.answer) return null;
  
  return {
    content: snapshot.answer.content,
    isTerminal: snapshot.answer.mode === "terminal",
    isSettled: snapshot.answer.mode === "document",
  };
}

/**
 * 推导 Pending Items
 */
function derivePendingItems(
  snapshot: TurnSnapshot,
): PendingItemPresentation[] {
  return (snapshot.pending_items || []).map((item) => ({
    id: item.id,
    type: item.type,
    label: item.label,
    status: item.status as "pending" | "resolved" | "failed",
  }));
}
```

### 3. Activity Buffer（短生命周期）

```typescript
// features/chat/activityBuffer.ts

import type { ObservationEvent } from "../api/v2/types";
import type {
  ActivityPresentation,
  ActivityStep,
  PhaseHeadline,
  ThinkingStream,
  WorkingState,
} from "./presentation";

/**
 * 短生命周期的 Observation activity buffer。
 * 
 * 职责：
 * - 接收当前 Turn 的 ObservationEvent
 * - 产生 phase headline、thinking、活动轨迹、working 状态
 * - 连接断开/gap/截断时保留已显示内容并标记"不完整"
 * - 不覆盖正式状态，不补造结果
 * 
 * 生命周期：
 * - 绑定单个活跃 Turn
 * - Turn 结束或切换时丢弃
 * - 重连或 gap 后通过 /v2/events replay 重建
 */
export class ActivityBuffer {
  private turnId: string;
  private events: ObservationEvent[] = [];
  private incomplete = false;
  
  constructor(turnId: string) {
    this.turnId = turnId;
  }
  
  /**
   * 添加新事件
   */
  addEvent(event: ObservationEvent): void {
    if (event.turn_id !== this.turnId) {
      console.warn(
        `ActivityBuffer: ignoring event for wrong turn ${event.turn_id}`,
      );
      return;
    }
    
    this.events.push(event);
  }
  
  /**
   * 批量加载事件（replay）
   */
  loadEvents(events: ObservationEvent[]): void {
    this.events = events.filter((e) => e.turn_id === this.turnId);
  }
  
  /**
   * 标记为不完整（连接断开/gap/截断）
   */
  markIncomplete(): void {
    this.incomplete = true;
  }
  
  /**
   * 生成活动呈现
   */
  toPresentation(startedAt: string): ActivityPresentation | null {
    if (this.events.length === 0) return null;
    
    const headline = this.deriveHeadline();
    const thinking = this.deriveThinking();
    const trail = this.deriveTrail();
    const working = this.deriveWorking();
    
    const now = Date.now();
    const startMs = new Date(startedAt).getTime();
    const elapsedMs = now - startMs;
    
    return {
      headline,
      thinking,
      trail,
      working,
      timing: {
        startedAt,
        elapsedMs,
      },
      canStop: true,  // TODO: 从 snapshot 读取
    };
  }
  
  private deriveHeadline(): PhaseHeadline {
    // TODO: 从最新 phase 相关事件推导
    return {
      phase: "phase1",
      label: "Understanding",
    };
  }
  
  private deriveThinking(): ThinkingStream {
    // TODO: 从 thinking 相关事件推导
    return {
      current: "",
      expanded: true,
      history: [],
    };
  }
  
  private deriveTrail(): ActivityStep[] {
    // TODO: 从事件流推导活动步骤
    return [];
  }
  
  private deriveWorking(): WorkingState {
    // TODO: 从 working 相关事件推导
    return {
      todos: [],
      milestones: [],
    };
  }
  
  /**
   * 是否不完整
   */
  isIncomplete(): boolean {
    return this.incomplete;
  }
}
```

## 集成到现有架构

### 1. turnStore 扩展

```typescript
// features/chat/turnStore.ts（扩展）

import { ActivityBuffer } from "./activityBuffer";
import { snapshotToPresentation } from "./adapters";
import type { TurnPresentation } from "./presentation";

export interface TurnStoreState {
  // ... 现有字段 ...
  
  /** 活动 buffer（仅当前 Turn） */
  activityBuffer: ActivityBuffer | null;
  
  /** 完整 presentation */
  presentation: TurnPresentation | null;
}

export const turnStore = create<TurnStoreState>((set, get) => ({
  // ... 现有实现 ...
  
  activityBuffer: null,
  presentation: null,
  
  /** 刷新 presentation */
  refreshPresentation: () => {
    const { current, activityBuffer } = get();
    if (!current) {
      set({ presentation: null });
      return;
    }
    
    const base = snapshotToPresentation(current);
    const activity = activityBuffer?.toPresentation(current.created_at) || null;
    
    set({
      presentation: {
        ...base,
        activity,
      },
    });
  },
  
  /** 创建活动 buffer */
  createActivityBuffer: (turnId: string) => {
    set({ activityBuffer: new ActivityBuffer(turnId) });
  },
  
  /** 添加事件到 buffer */
  addEvent: (event: ObservationEvent) => {
    const { activityBuffer } = get();
    activityBuffer?.addEvent(event);
    get().refreshPresentation();
  },
  
  /** 清除活动 buffer */
  clearActivityBuffer: () => {
    set({ activityBuffer: null });
    get().refreshPresentation();
  },
}));
```

### 2. WebSocket 集成

```typescript
// api/websocket.ts（扩展）

import { turnStore } from "../features/chat/turnStore";

function handleObservationEvent(event: ObservationEvent) {
  const currentTurnId = turnStore.getState().current?.turn_id;
  
  if (event.turn_id === currentTurnId) {
    // 当前 Turn 的事件 → activity buffer
    turnStore.getState().addEvent(event);
  } else {
    // 非当前 Turn 的事件 → 只触发 owner refresh
    turnStore.getState().refresh();
  }
}
```

### 3. 事件 replay 重建

```typescript
// features/chat/eventReplay.ts（新增）

import { fetchEvents } from "../api/v2/events";
import { turnStore } from "./turnStore";

/**
 * 重建活动窗口（重连或 gap 后）
 */
export async function rebuildActivityBuffer(
  turnId: string,
): Promise<void> {
  try {
    const events = await fetchEvents({
      turn_id: turnId,
      mode: "verbose",
      through: "latest",
    });
    
    const buffer = new ActivityBuffer(turnId);
    buffer.loadEvents(events);
    
    turnStore.setState({ activityBuffer: buffer });
    turnStore.getState().refreshPresentation();
  } catch (err) {
    console.error("Failed to rebuild activity buffer:", err);
    turnStore.getState().activityBuffer?.markIncomplete();
    turnStore.getState().refreshPresentation();
  }
}
```

## 下一步

完成 P1 后，继续 P2：实现 ActivityBuffer 的完整事件解析逻辑（从 ObservationEvent 推导 phase headline、thinking、trail、working）。

## 待决问题

1. **ObservationEvent 结构**：需确认后端 verbose 模式的完整 payload 结构
2. **事件类型枚举**：phase、action、execution、LLM、retrieval、context、working 的稳定 event type
3. **Gap 检测**：如何检测事件流 gap（sequence number？timestamp？）
4. **Truncated 标记**：后端是否会发送 truncated 事件？
5. **重连策略**：自动重建 or 显式"刷新"按钮？

这些问题将在 P2 实施时逐一确认和解决。
