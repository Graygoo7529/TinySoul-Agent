import type { SettingsGroupDef, SettingsPageDef, SettingsPageId } from "./pages";

/** Human-facing Chinese labels; protocol ids and configuration paths stay unchanged. */
const PAGE_LABELS: Record<SettingsPageId, { title: string; description: string }> = {
  overview: { title: "配置状态", description: "运行中的配置、待激活内容和本地修改。" },
  plans: { title: "运行方案", description: "从配置保存的命名方案。" },
  "llm-providers": { title: "LLM 提供方", description: "对话模型端点、适配器和凭据引用。" },
  "llm-models": { title: "LLM 模型", description: "模型能力与提供方顺序。" },
  "llm-tasks": { title: "LLM 任务链", description: "有序模型链和任务参数。" },
  "dedicated-providers": { title: "专用模型提供方", description: "Embedding 与结构化评估端点。" },
  "dedicated-models": { title: "专用模型与用途", description: "Embedding/JEV 模型及其业务用途。" },
  credentials: { title: "凭据", description: "配置引用的项目 dotenv 值。" },
  "image-generation": { title: "图像生成", description: "后端暂未提供图像配置项。" },
  "phase-bindings": { title: "阶段绑定", description: "Phase 1 和 Phase 2 使用的任务链。" },
  actions: { title: "Actions 与模型用途", description: "Action 可见性、运行策略和模型绑定。" },
  "search-policies": { title: "Search 策略", description: "检索来源、操作、语境和分页预算。" },
  budgets: { title: "预算", description: "Turn、Reflection 和 Context/Session 预算。" },
  reflection: { title: "Reflection 计划", description: "每日整理时间与归档位置。" },
  execution: { title: "执行与 Job", description: "Shell/script 解释器、限制和 Job 容量。" },
  web: { title: "Web 与资源获取", description: "Web 发现、检索和资源转换限制。" },
  acp: { title: "ACP 子智能体", description: "委派目标、命令、环境和限制。" },
  mcp: { title: "MCP 服务", description: "外部工具服务、传输方式和环境引用。" },
  workspace: { title: "Workspace", description: "当日工作区根目录、读写限制和监听。" },
  session: { title: "Session", description: "Session 根目录、背景预算和 Inspect 限制。" },
  home: { title: "Home", description: "Home 根目录、读写限制和 Embedding 用途。" },
  memory: { title: "Memory", description: "活动/持久记忆限制和 Embedding 用途。" },
  system: { title: "端点与来源", description: "进程状态、配置来源和 Observation。" },
  interface: { title: "界面", description: "主题、字体和密度；仅保存在本地并立即生效。" },
};

const GROUP_LABELS: Record<SettingsGroupDef["id"], string> = {
  overview: "概览与方案",
  models: "模型与服务",
  behavior: "行为与调用",
  tools: "工具与连接",
  data: "数据与知识",
  system: "系统与诊断",
  interface: "界面",
};

export function settingsTitle(page: SettingsPageDef): string {
  return PAGE_LABELS[page.id]?.title ?? page.title;
}

export function settingsDescription(page: SettingsPageDef): string {
  return PAGE_LABELS[page.id]?.description ?? page.description;
}

export function settingsGroupTitle(group: SettingsGroupDef): string {
  return GROUP_LABELS[group.id] ?? group.title;
}

