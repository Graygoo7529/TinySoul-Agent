# Session 设计

## 定位

Session 拥有一个 business day 内已经完成的 prior Turns。它保存不可变业务事实，以 immutable Summary graph 收缩活动历史头部，并从同一记录图派生 Session Background、模型渐进检查和 Memory facts。Session 不保存当前 Turn 的运行时 heap，不是通用日志或前端审计数据库。

## 持久事实

Turn record 使用 schema v4，显式保存：

- ref、day 与 recorded time；
- 有序输入文本和接收时间；
- Working 终态与 Background links；
- 可选最终输出、references 与 exhausted；
- 按发生顺序排列的 Action 业务记录。

Action record 只保存 Action name、schema request、success/failed/timeout outcome、canonical result、typed failure 与 references。内存记录直接持有 Action 公共 SPI 的 `ActionLocalFailure`；持久 JSON 恢复复用同一类型的严格解析边界，不能将任意非空对象解释为失败事实。不保存 call id、trace location、cycle、phase、stage、backend metadata 或 pairing 审计。

正常完成的 Turn 必须拥有可唯一配对的 Phase2 Action call 与 Phase3 ActionResult。missing、orphan、duplicate、name mismatch 或外层 ToolResult 状态不一致属于 completion invariant failure，不持久化 incomplete 诊断记录。

Summary record 与 Turn 使用同一 schema version，只保存 deterministic ref、day、recorded time 和至少两个有序 direct child refs。Summary 是索引节点，不复制子节点 Background、Action counts 或正文。

Manifest 使用 schema v2，只保存 day、内部 revision 与有序 root refs。v4 record 和 v2 manifest 严格拒绝未知字段；Session 不读取、不迁移旧 schema。

## 唯一验证边界

Session-owned validator 在写入、读取、reconciliation、archive snapshot、Background、inspect 与 Memory projection 前验证 typed record identity。Store 对同 ref 的相同业务事实幂等复用，内容冲突成为 invariant failure；recorded time 不参与幂等事实比较。

Reconciliation 验证 day、缺失引用、重复可达引用和 graph cycle，按 recorded time 收养未提交 orphan Turn。不可达 Summary 只作为完整性事实报告，不自动接入 active root。

## Background 与 Summary Heap

Session Background 在每个 Turn preparation 期间从当前 Manifest root 派生：

- Turn item 包含 kind/ref、`user_ask`、可选 answer/references/exhausted；
- 存在 Action 时包含一个 `#actions` 集合 ref、Action 数量和按 Action name 聚合的非零 success/failed/timeout counts；
- Summary item 只包含 kind/ref、turn count 与 direct child count；
- 极端预算不足时使用 overflow head，提示调用 `core.session.inspect`。

Background 不包含 trace、pairing、digest、revision、occurrence detail 或 ActionResult payload。ask/answer 有 owner 上限；整体不足时只保留可容纳的连续最近后缀，不能跳过较新的大节点再选择更旧节点。

超过 summary watermark 时，Session 把保留最近 Turn 之前的连续 roots 组成 immutable Summary，并尽量回收到 target ratio。原 Turn 和旧 Summary record 不删除，因此 archive 和 Memory 仍可递归恢复完整业务事实。

## 渐进检查

模型只通过 Core domain 的 `core.session.inspect` 探索 prior Turns：

```text
active head -> Summary -> Turn -> Action collection -> Action leaf
```

- 无 ref：返回 active root 的直接 headers；
- Summary ref：返回 direct children headers；
- Turn ref：返回 ask、answer、references、exhausted、Action outcomes 与 Action collection ref；
- Action collection ref：按发生顺序返回 compact Action leaf headers，可按已知 Action name 过滤；
- Action leaf ref：返回该 Action 的 request、outcome、result/references 或 failure。

失败/timeout leaf header 可以内联有界 failure feedback 和简短 result，避免仅为确认失败多调用一次；成功 header 不复制 result。Action collection/leaf ref 从 immutable ordered Actions 确定性派生，不落盘、不进入 Manifest，模型只复制 owner 签发的 ref。

`ref` 决定向下展开的节点；`continuation` 只继续同一节点未交付完的 direct children 或单个超大语义对象。active head continuation 在 opaque token 内绑定内部 Manifest revision，过滤后的集合 continuation 绑定 filter；这些事实不进入模型字段。响应不暴露 cursor、index、offset、digest、coverage 或 requested/effective limits。

`core.session.inspect` 是 foldable Action，完整结果和 continuation 只进入当前 Turn Interaction；compact canonical payload 不保存 continuation，也不改写固定 Session Background。Session 不提供独立 actions/recall Action，也不提供模型或 Endpoint canonical trace 查询。

## Memory 与 Daily

Daily Lifecycle 归档 Session 根后，`archive_snapshot()` 用同一 manifest/record validator 校验只读图。Memory facts 递归展开 Summary，按输入开始时间和 ref 稳定排序，交付输入、Working、Background links、输出、Actions 与 exhausted；不交付 trace 或执行元数据。

SessionEngine 只负责自身初始化、提交、reconciliation、archive 与 projection。Loop 决定 business day 和归档位置；Memory 只消费 typed facts；Context 只消费 Background snapshot；Endpoint 不直接依赖 SessionEngine。

## 失败边界

无效模型 ref/continuation 由 `SessionInspectRequestError` 转成局部 Action failure。持久 I/O、graph 损坏和内部不变量经 RuntimeSessionBridge 结束当前流程，不能伪装成可修正 inspect 请求。配置拒绝未知键，字符预算只由 owner settings 控制，模型不能覆盖。
