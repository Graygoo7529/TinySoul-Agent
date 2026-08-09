# 需求：编辑类 Action 结果携带内容预览/diff（可选、非阻塞）

日期：2026-08-09 · 提出方：前端（visualization） · 状态：pending

## 背景

前端 Details 抽屉的 ActionCard 已按 action 家族做差异化呈现。其中 patch 家族
（`workspace.patch`、`execution.patch_script`、`home.*.patch`）的输入侧可用 params 中的
`old_text`/`new_text` 渲染行级 diff 预览，效果良好。

但生成类 action 的输出侧没有可呈现的内容事实：

- `workspace.create` / `workspace.rewrite`：result 只有资源元数据
  `{link, summary, kind, size, digest, ...}`，LLM 生成的文本对前端不可见；
- `execution.create_script` / `rewrite_script` / `promote_script`：result 为
  `{link, digest, size, state, language}`，无源码回显；
- `execution.apply`：result 的 `workspace_changes[{link, change}]` 只有变更类型，无内容。

前端目前只能经 `/v1/workspace/resource` 按需补拉最终正文，无法呈现"这次执行改了什么"
（before/after 或内容预览），Activity 时间线里的结果行也只有元数据。

## 需求（建议）

在上述 action 的 result payload 中增加可选的内容预览字段，例如：

```json
{
  "content_preview": { "text": "…前 N 行或有界摘要…", "truncated": true, "chars": 4200 }
}
```

或对变更类结果提供统一 diff 摘要（逐 link 的 before/after 行级 diff 或有界 unified diff 文本）。
字段应有界（如 ≤ 8KB）、JSON 安全，并遵循 payload 不携带大块资源正文的既有约束——
一个"预览"量级的内容即可，全文仍由前端经 workspace 资源接口按需获取。

## 现状

不阻塞。前端已上线：patch diff 视图（params 驱动）、生成类 instruction 预览 + 元数据格、
`/v1/workspace/resource` 补拉路径。仅放弃"执行结果内容差异"的直接呈现。
