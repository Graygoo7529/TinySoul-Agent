# 需求：Phase2 任务事件显式携带 mounted_skills（可选、非阻塞）

日期：2026-08-08 · 提出方：前端（visualization） · 状态：pending

## 背景

前端的活动浮动层与 Details 抽屉现在会展示"Phase2 挂载了哪些领域 Skill"。目前前端从
`llm.model.request` 消息栈中 label 为 `task_prompt:guide:domain_skill:N` 的 PromptBlock 启发式
提取（取 Skill 正文首个 markdown 标题作为展示名）。

这一做法可用，但有两个弱点：

1. **无法可靠配对 domain**：后端 `HomeDomainSkillProvider.guidance_for(domains)` 按域顺序追加
   snippet，但没有 Skill 文件的域会被静默跳过，导致 `domain_skill:N` 的序号与
   `selected_domains` 的顺序不一定一一对应，前端只能展示"数量 + 标题"，不能标注所属域。
2. **展示名依赖正文格式**：标题取自 Skill 文件正文的第一个 `#` 标题，文件缺标题时退化为首行
   截断，展示名不稳定。

## 需求（建议）

在后端 Phase2 组 prompt 完成处（`Phase2Unit` 已有 `selected_domains` 与 skill snippet 的对应
关系），于 `llm.task.started`（或新增 `loop.phase2.skills`）事件的 payload 中显式携带：

```json
{
  "mounted_skills": [
    { "domain": "workspace", "name": "Workspace Editing", "link": "home:skills_domain:workspace" }
  ]
}
```

`name` 可由后端在读取 Skill 文件时解析标题得到，`link` 为既有 mount Link。前端收到后优先采用
该结构化列表，label 启发式仅作为旧事件回退。

## 现状

不阻塞。前端已上线 label 启发式版本（`src/derive/chat.ts` 的 phase2 skills 提取 +
`src/derive/activitySemantics.ts` 的 `skillTitleOf`），仅放弃"skill ↔ domain 精确配对"的展示。
