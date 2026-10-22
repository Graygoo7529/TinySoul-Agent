# Turn 缓存路由与 Kimi 隐式缓存执行计划

状态：done

## 目标与确认语义

- 同一 Turn 的 Phase1、Phase2、Action 内部任务和 retrieval LLM 调用，通过现有 `PromptCache.key` 携带同一 Turn ID，作为支持此参数的 API 的缓存路由提示。重试沿用原值；新 Turn 改用新身份。
- Context 复用已有 Turn 身份并纯读取消息 provenance，提供 key 与候选边界；LLM 不推断 Turn 生命周期，不增加缓存 key 管理器或持久化。独立调用者仍可显式提供自己的 key。
- Kimi 复用 OpenAI Chat 的 key 与缓存选项映射；K3 开放 `implicit` 和 `5m`/`1h` TTL，development/standard 默认 `implicit + 5m`。K2 传 key 并使用服务端自动缓存，不套用 K3 的 TTL 配置。Kimi 不发送显式断点。
- Google 保持默认 implicit，只有显式选择 explicit 才创建缓存资源；本轮不扩展前端交互。
- key 是路由提示，实际复用由服务端匹配前缀；它不是内容指纹、缓存资源名或强制命中保证。

## 实施清单

- [x] Context/协议：调整 `kernel/context/engine.py` 的缓存意图装配，说明 `llm/protocol/cache.py` 中 key 的上层来源；保留纯读取及既有错误语义。
- [x] 主调用链：更新 `kernel/loop/phases/phase1.py`、`phase2.py`、`kernel/action/tasks.py`；无 Context 正文的 Turn 内任务也可携带只有 key 的意图。
- [x] retrieval：在 `kernel/retrieval/operations.py`、`selection.py` 传递现有类型的缓存意图；使用 Context 时保留对应边界，不使用 Context 时只传 key。
- [x] Kimi：调整 `llm/adapter/catalog.py` 的 K3 variant 选项及两个 profile 的 `configs/llm/models/kimi.toml`；复用通用 SDK 映射。
- [x] Google：明确 catalog 中 implicit 默认，保留现有 explicit 资源生命周期。
- [x] 文档：简要同步 `docs/design/llm.md`、`docs/endpoint/configuration.md` 和 `reference/api_mode/implementation-notes.md`（该参考目录被忽略，不作为交付唯一依据）；接口字段未变，不引入新的 Endpoint。
- [x] 验证：补齐稳定 key、任务传递与重试、retrieval 的有/无 Context 边界、Kimi 真实 SDK 序列化及 Google 默认不创建资源的代表性测试；运行聚焦测试、Fast、Full 和 typecheck。
- [x] 对照 AGENTS.md 和上述条目核对实现与验证证据，完成后改名带 `-done-` 并移入 `docs/analysis/done/`。

## 验收依据

1. 同 Turn 的请求 key 一致，跨 Turn 更新；消息正文不混入 key。
2. Kimi K3 的 SDK HTTP 请求包含 `prompt_cache_key`、`prompt_cache_options = {mode: implicit, ttl: 5m/1h}`，没有 breakpoint；K2 不新增 K3 专属参数。
3. Google 未设置缓存模式或选择 implicit 时均发送完整内容且不调用缓存资源创建；explicit 既有测试继续通过。
4. 沿用单一协议、catalog、配置加载和错误边界，没有新增平行缓存状态或前端专属规则。

参考：[Kimi Chat 参数](https://platform.kimi.com/docs/api/chat)、[Kimi 缓存指南](https://platform.kimi.com/docs/guide/context-caching)、[Google GenerateContent 缓存](https://ai.google.dev/gemini-api/docs/generate-content/caching)。

## 实施与核对记录

### 已核对的行为

- `tests/kernel/context/projection/test_composer.py`：Context 使用现有 Turn ID，不把 key 混入消息；无候选边界时保留 key，新 Turn 切换 key。
- `tests/kernel/loop/phases/test_phases.py`、`tests/kernel/action/test_model_tasks.py`：Phase1/Phase2、带/不带 Context 的 Action 任务与 selection input 都取得所属 Turn 的 key。
- `tests/kernel/retrieval/test_selection.py`：实际 SearchSession → CandidateSelector → TaskCall 链路保留 key；一个请求中使用 Context 的步骤保留边界，不使用 Context 的步骤剔除边界。
- `tests/llm/execution/test_task_runner.py`：真实重试与 provider 切换过程中原样传递 key。
- `tests/llm/adapter/test_api_modes.py`：安装的真实 OpenAI SDK 经 MockTransport 检查 HTTP JSON；K3 的 5m/1h 两档均发送 key 和 implicit，K2 只发送 key，两者无 breakpoint。这里验证请求序列化，不宣称远端命中。
- `tests/llm/adapter/test_messages_and_generate_content.py`：未设置模式和显式选择 implicit 都只生成、不创建资源；已有 explicit 生命周期测试通过。
- `tests/plugins/workspace/test_workspace_engine.py`：Action 测试夹具建立真实 Turn 身份，符合 ActionTaskFactory 所属生命周期；Workspace Search 的原有行为继续通过。

### 最终验证

- 聚焦测试：201 passed，2 deselected（真实外部测试），覆盖本轮调用链、adapter、配置加载及 Workspace Action。
- typecheck：通过（Python 3.13.12，ty 0.0.84）。
- Fast：1333 passed，28 deselected，322.10 秒。
- Full：1338 passed，23 deselected，337.47 秒，包含项目生成和 wheel 发布验收。
- `git diff --check`：通过。
- AGENTS.md 核对：复用单一协议与 Turn 身份，不增加缓存持久化、全局状态或 provider 私有会话；Context 失败仍在调用 owner 的既有 bridge 转换，配置错误沿 catalog 原有流程；Google 不扩展前端。
- 实施清单、实际修改、设计/Endpoint 说明及本地验证均已逐项核对完成。SDK HTTP 请求验证使用 MockTransport；服务端实际命中率不属于本轮本地验证结论。
