
## 20260920

reflection 考虑将 将 reflection actions 也纳入通用的 memory/home domain，但在 reflection 期间才会开启可见；既不影响通用 turn，在 reflection 期间能够使用通用 actions 和专用 reflection actions；可能需要定义结合身份/场景的 action 掩码/action 可见性。

TurnProfile 承载同一个 Agent 的执行情景；domain 表示能力分组；action 表示具体操作；

纳入 R2C.3：基于已有 action 目录裁剪能力，统一 domain/action 两级情景策略。模型可见范围、实际执行范围和服务权限保持一致；Reflection 保留适用的通用动作并获得专属能力。
留作 S3 评估：将 Reflection 动作并入 Home/Memory 通用分组。目前普通 Memory 动作属于 `core.memory.*`，归并还涉及规划域、动作身份、配置和 Skill 引用迁移，因此不作为 R2 完成条件。
