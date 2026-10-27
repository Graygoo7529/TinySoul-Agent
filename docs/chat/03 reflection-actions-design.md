
## 20260920

reflection 考虑将 将 reflection actions 也纳入通用的 memory/home domain，但在 reflection 期间才会开启可见；既不影响通用 turn，在 reflection 期间能够使用通用 actions 和专用 reflection actions；可能需要定义结合身份/场景的 action 掩码/action 可见性。

TurnProfile 承载同一个 Agent 的执行情景；domain 表示能力分组；action 表示具体操作；

纳入 R2C.3：基于已有 action 目录裁剪能力，统一 domain/action 两级情景策略。模型可见范围、实际执行范围和服务权限保持一致；Reflection 保留适用的通用动作并获得专属能力。
留作 S3 评估：将 Reflection 动作并入 Home/Memory 通用分组。目前普通 Memory 动作属于 `core.memory.*`，归并还涉及规划域、动作身份、配置和 Skill 引用迁移，因此不作为 R2 完成条件。


## 20260930

记忆与知识沉淀：把 maintenance 重构为  Reflection，但还是建议区分 专属的 memory_reflection/home_reflection Domain（不合并单一 reflection，同时与常规运行的 action domain 分开，仅在相应的  memory/home Reflection 时使用）；Memory Reflection 可以删除 8 步控制器、preview、多文档事务与 CAS、evision/activation_count/session_revision/digest，做更加轻量的 memory_reflection；Home 还是需要 review，白天 turn 会通过常规 home domain 改写 home 副本，home_reflection actions 可以检查副本 diff，查看 diff 详情，接收/拒绝/改写 diff；可以不引入 git；最关键的设计是：User Turn 仍不写持久 Memory、不直接更新 Home，持久 memory 和 home 更新通过 reflection 插件以及相应的专属 domain 实现。
