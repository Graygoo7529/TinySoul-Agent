# Reflection

`GET /v1/reflection` 返回 owner 派生的内存 availability projection，包括 Home pending、可再次整理的 memory_days、其中尚无 daily 的 missing_daily_days、scanned_days 和 next_before。每页最多检查 64 个日期，使用 `?before=YYYY-MM-DD` 读取更早页；无后续页时 next_before 为 null。候选不是待办队列，已有 daily 仍可整理；不写 availability.json，不自动遍历历史执行。Endpoint 不扫描 Archive，也不建立第二份维护状态。

`POST /v1/reflection` 提交 `kind=home|memory`、command id、metadata 与可选 instructions（最多 16000 字符）；Memory 必须携带 target_day。该入口表示用户明确允许本次指定整理，只受理一个独立 Reflection Turn，正常对话不持有 Reflection 能力。相同身份与内容在活动及结果保留窗口内去重；受理成功不等于整理完成。容量不足返回 accepted=false、state=full。daily 仅由内部自动策略拆分受理，HTTP 不接受 daily 或 rebuild_memory。

User Turn、Reflection Turn 或 daily transition 期间仍可读取配置并 PATCH 保存候选；`POST /v1/config/reload` 返回 `409 config.activation_unavailable`，待 idle 后激活。维护请求本身按其所属队列语义处理。

## Lifecycle Observation

Endpoint 的 `/v1/events` 和 WebSocket 会转发 Reflection owner 的生命周期事件。`reflection.started`
的 payload 形状为：

```json
{
  "business_day": "2026-08-18",
  "request": {
    "scope": "memory",
    "trigger": "manual",
    "request_id": "command_x",
    "target_day": "2026-08-17",
    "source": "endpoint",
    "metadata": {},
    "instructions": "整理这一天的项目决定"
  }
}
```

顶层 `business_day` 是维护请求的当前执行日；`request.target_day` 是 Memory 目标日。维护任务
启动的 `turn.started.business_day` 同样是执行日，历史 Session、Memory 与归档 Workspace 独立绑定目标日。
Reflection 不写入 User Session。`reflection.completed` 使用 `request_id` 和同一
`business_day`，允许历史恢复在缺少新版 started 字段时补全执行日。`request_id` 是两类事件与
`turn.started.request_id` 的关联键。
