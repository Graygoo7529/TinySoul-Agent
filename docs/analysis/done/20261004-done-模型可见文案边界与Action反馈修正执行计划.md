# 模型可见文案边界与 Action 反馈修正执行计划

状态：done（2026-10-04，完成实现、文档与完整本地门禁核对）

## 确认范围

本计划承接模型可见固定文案集中管理工作。目标是调整文案的源码维护位置，不改变模型可见结果的来源、信息量、动态值或业务语义。`tinysoul/prompts` 继续作为随代码维护的 Python 内容包；消息装配、Action Catalog、输入校验、执行状态、结果 payload 和异常分类仍由原 owner 负责。

## 已确认的问题

1. `105e65e` 中按 owner 提取固定文案的总体方向正确。Catalog 的 domain/action 描述、schema、可配置限制和运行时 timeout 仍由原 owner 读取与装配，不应复制到 `prompts`。
2. `c49d5d4` 将 Web Action 原本的具体 `WebProcessingError`/`WebProcessTimeout` 反馈压缩为按 reason 选择的少量通用句子，改变了反馈语义并丢失了业务 owner 已整理的具体说明。这超出了固定文案提取范围。
3. `str(exc)` 不是可靠的架构判断条件。`WebProcessingError` 已声明为可映射到 ActionResult 的稳定 Web 失败；Action schema 校验也通过受控异常字符串向模型传递字段和当前约束。应区分 owner 已整理的稳定反馈与未经处理的底层异常。
4. `ActionLocalFailure.feedback`、`constraint`、ActionResult `payload` 是现有模型可见结果协议；`frame_data` 主要是内部 trace 诊断，不能替代模型需要的动态约束、执行结果或结果说明。
5. 当前部分动态信息本来就没有进入模型，例如 Web HTTP 状态码和某些配置上限只保留在内部 payload/frame data。这属于独立的反馈能力评估，不应通过固定文案提取掩盖，也不能与本次回归混淆。
6. 归档复核记录在 Full 尚未稳定通过时标记为 `done`，完成本计划时必须更新状态和证据，未通过的验证不得归档为完成。

## 改进方案

### 1. 恢复既有具体反馈

- 移除 Web Action 的按 reason 通用反馈压缩和新增的重复通用句子。
- 由 Web owner 明确提供稳定、已整理的模型反馈；Action 边界只负责将其放入 `ActionLocalFailure.feedback`，保留 reason、disposition、payload/frame_data 的既有协议。
- 继续屏蔽底层供应商异常对象、traceback、敏感路径和大块正文。必要时保留受限结构化摘要；不以禁止 `str(exc)` 这种语法形式代替内容契约检查。
- 超时反馈表达执行语义；实际生效的 timeout 由 Catalog/运行控制决定。若模型确实需要数值，必须由 owner 将当前已校验值作为动态参数传入，不在 `prompts` 写死默认值。

### 2. 保持固定文案与动态内容的分工

- 固定引导、固定包装和固定反馈继续在相应 `tinysoul/prompts/<owner>.py` 中维护。
- Catalog 的用户可定义 description、use/avoid/effects/examples、schema、enum 和限制值继续从当前 Catalog 装配到 ToolSpec 或校验反馈。
- Action 成功结果、失败具体说明、约束事实、状态、退出码、输出摘要和引用继续由 owner 通过 ActionResult 的 payload/feedback/constraint 提供；不把运行时数据硬编码进 prompts。
- 只在实际模型可见路径成立时提取固定文案，逐个检查消费者；内部异常 message、日志和 Runtime 诊断不因文本存在就自动提取。

### 3. 测试与规约

- 删除以 `"str(exc)" not in source` 为条件的实现约束。
- 增加或调整代表性测试，验证：具体稳定反馈仍可见；Catalog/schema 动态值随配置变化；Action payload 与 failure constraint 进入模型结果；原始底层异常仍不会泄露。
- 修正 `AGENTS.md`、`docs/design/prompts.md`、`tinysoul/prompts/README.md` 的异常反馈措辞，明确“固定文案提取不改变动态结果”和“按内容契约判断，不按 `str(exc)` 语法判断”。
- 将本计划和上一份复核记录的状态与验证结果保持一致；只有实现、文档和必要门禁全部核对后才归档为 `-done-`。

### 4. 独立评估动态信息不足

实施时记录原有但尚未进入模型的动态信息，包括 Web 限制类型/当前值、HTTP 状态、worker/provider 受控摘要以及 Action 成功结果的必要字段。先保持当前 owner 协议和数据边界；只有确认对模型决策有实际价值时，才在本计划内提出最小的后续字段或格式化改进，不新增平行结果协议。

## 执行顺序与验收

1. 修正 Web Action 和 Web 文案模块，恢复具体反馈并删除通用映射。
2. 按 Action 现有异常、结果和 Runtime 体系补充显式反馈边界及测试。
3. 同步规约、设计文档、README 和分析记录。
4. 运行 Web/Action 聚焦测试、Fast、Full、typecheck；分析并记录与本次变更无关的环境抖动。
5. 对照本计划逐项检查实现、动态值、模型结果和文档；全部完成后将状态改为 done，并移动到 `docs/analysis/done/`。

## 当前核对记录

- 已完成：移除 Web Action 的 reason 通用反馈映射；Action 直接保留 owner 的稳定 `feedback`，并继续传递既有 reason、disposition、payload 与 trace facts。
- 已完成：将实际到达 Web worker/Action 结果的固定反馈集中到 Web prompts；限制、实际长度、token 数、状态码、结果大小和 Action timeout 使用 owner 传入的动态值。仅用于 Action runner 生命周期转移的取消/截止检查继续由 Action 控制，不复制为 Web 文案。
- 已完成：删除源码禁止 `str(exc)` 的架构测试，增加 Web feedback、动态限制、HTTP 状态隔离、ToolSpec/schema/timeout 和结果渲染测试；原始 provider 响应仍未进入模型结果。
- 已完成：同步 `AGENTS.md`、固定文案设计、Action/Web capability 设计和 prompts README；上一份复核记录曾重新置为 `in_progress`，原先矛盾的结论标明为历史记录，最终随本计划完成重新归档。
- 已完成验证：Web/Discovery、Action planning/rendering、架构聚焦测试通过；`ty check` 通过。原四次 Full 均失败，详情和后续根因复核见下节；不能由隔离重跑通过推定全量门禁已完成，也不能把全部失败都归为环境抖动。

## 独立评估记录

本次确认并改善了原有动态信息不足中的 Web 查询限制、搜索 token、输出/源数据大小、HTTP 状态和 Action 生效 timeout；它们沿现有 feedback/constraint/payload 协议传递。worker/provider shape facts 仍是有界内部诊断，Action 成功结果仍复用原 payload。未新增平行错误协议；其它动态信息是否值得模型看到，留待有明确使用场景时按同一 owner 协议评估。

Discovery crawler 内部的跨域重定向、页面 HTML 解析异常由 failed handler 消费，仅保留 reason；原 message 不进入 worker 顶层反馈。因此这两条文字保留在 backend，不能仅因异常类型相同就提取为模型文案。只有 `WebProcessingError`/`WebProcessTimeout` 明确携带 feedback；不在包含内部契约错误的基类上新增通用模型反馈或兜底句子。

## 测试失败复核与改进

维护者确认允许改进测试后，沿失败路径重新检查，纠正此前将全部失败归为环境抖动的结论：

- execution 取消用例等待 `Path.exists()` 后便终止子进程，但文件创建早于内容写入完成，空文件失败是测试竞争条件。改为等待 `write_text` 返回后发出的 stdout 完成信号。相邻的父进程退出/子进程回收用例存在相同假设，改为子进程写完后通过 pipe 明确通知父进程，保留停止进程和文件内容的原断言。
- endpoint journal 过滤回放契约合理。失败工件中 manifest 停在 sequence 4，而 segment 已写到 5，符合 append 持久化失败后 journal 降级的路径；测试增加 `journal.failure` 前置诊断，不改为接受内存回放的结果。
- dotenv 的保存、注释保留和重新加载断言合理，未修改或 mock 持久化。
- 独立于 pytest 的原子写探针：仓库 `.local-test/probes` 两轮各 1000 次替换均出现 14 次 WinError 5；`B:\tmp` 两轮各 1000 次和另一 C 盘临时目录 1000 次均通过。证据说明失败与目录环境有关，尚未确定具体干扰进程，不据此修改生产原子写策略。
- 第四次原 Full 为 1237 passed、25 deselected、2 failed（journal 与 dotenv），均隔离重跑通过。前三次每次 1238 passed、25 deselected、1 failed，失败点分别为 journal、Reflection、execution。Reflection 未找到错误测试假设，保留原有真实集成覆盖。
- `scripts/test.ps1` 增加可选 `-ArtifactRoot`，默认路径及测试选择不变，仍创建并仅清理本次唯一 runs/uuid；本次在 `B:\tmp\tinysoul-tests` 运行完整门禁。未增加自动重试、skip、xfail 或宽松断言。README/AGENTS 同步用法。
- execution/journal/dotenv 聚焦验证：21 passed。随后 Fast 为 1234 passed、30 deselected；新增 Action 回归及其 owner 用例为 38 passed；最新 typecheck 通过。Full 与最终差异检查结果在最终核对中记录。
- Action owner 收尾复核发现真实实现缺陷：control.cancel_reason 以空字符串表示尚无取消原因，runner 却用 `is None` 判断；协作执行先发现 deadline 过期时会错误传播取消。新增不依赖 sleep 的用例，在修复前稳定得到 1 failed、1 passed；修正空值判断，显式 runtime transfer 仍保持取消事实，超时仍由 runner 生成局部结果，并在原 constraint 中传递当前 Action timeout。没有增加 Web 专用运行控制。

## 最终逐项核对

- [x] 保留 Python 固定文案内容包与 owner 依赖边界，Web 的 81 个定义均有实际消费者，无未使用、重复或未解析引用；Discovery 两条内部诊断留在原 owner。
- [x] 撤回 reason 通用句子映射，以显式 feedback 保留 Web owner 的具体说明；未将原始供应商响应、异常对象或 traceback 注入模型。
- [x] Catalog 的 description、semantic、schema、动态约束与生效 timeout 继续由当前配置装配。成功 payload、failure.constraint 与动态反馈通过既有结果协议进入模型。
- [x] 记录并改善原有 Web 动态信息不足；取消与超时复用 Action runner，修复协作 deadline 的空取消原因判断，显式取消不被覆盖。
- [x] 修正两个进程测试的写入完成同步，补足 journal 存储失败诊断；dotenv/Reflection 原契约不放宽。测试脚本支持独立工件目录，不新增重试或跳过。
- [x] AGENTS、README、prompts 导航、Action/Web 设计与历史复核记录已同步。
- [x] Fast、owner 聚焦、完整 Full、typecheck、格式与差异检查完成。

最终 Full：`scripts/test.ps1 -Suite Full -ArtifactRoot B:\tmp\tinysoul-tests`，**1241 passed、25 deselected，245.30 秒**；运行目录 `B:\tmp\tinysoul-tests\runs\e9901683c7534cdab3a4b6fffabf4b53`，成功后按脚本规则清理。包含 generation/wheel 与隔离安装验证，未启用 external provider/network。

最终类型检查：`scripts/typecheck.ps1`，Python 3.13.12 / ty 0.0.84，All checks passed。16 个改动 Python 文件的 `ruff format --check` 与 `git diff --check` 通过。没有修改生产原子写策略；仓库内临时目录的 WinError 5 干扰来源仍未定位，不将外部目录的一次完整通过描述为已解决宿主文件问题。
