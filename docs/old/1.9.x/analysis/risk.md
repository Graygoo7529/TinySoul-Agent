**主要风险**
- `ParallelDispatcher` 超时基于线程池；future 标记超时后，线程仍可能继续跑，且 executor shutdown 会等待已启动线程结束。结果上过滤了 late result，但不是真正硬中断。
- Sandbox 是 best-effort，不是生产级隔离；线程无法强杀，`os.chdir()` 是进程全局，`pathlib` 文件 I/O 也有绕过代理的风险。
- `delete_file` 的 destructive profile 只暴露给 LLM，框架没有强制用户确认。
- `git` action 白名单了 subcommand，但 `path` 没绑定 workspace 边界。
- `include_context` 已实现但 Step1/2/3 尚未使用，默认会注入全量 context，后续 token 成本会增长。
- `reasoning` 的 `LOOP_NEXT_TURN` 会跳过 Step3；这和部分文档里“成功数据 + NEXT_TURN 保留 Step3”的描述略有出入，但测试当前认可这个行为。

**建议优先级**
1. 先把 Step1/2/3 的 `include_context` 裁剪接上，降低 prompt 成本。
2. 为 destructive action 加框架级确认策略，至少对 `DESTRUCTIVE` profile 可配置拦截。
3. 把脚本执行改为进程级隔离，解决线程超时和全局 CWD 污染。
4. 约束 `git.path` 到 workspace 或显式允许的 repo root。
5. 整理文档小差异：README 文档索引仍写 `docs/core/core_design_query.md`，实际文件是 `docs/design/core_design_query.md`。



主要风险**
1. **真实 LLM 调用没有传入 system prompt**  
   `AIClient.chat(..., system=...)` 会把 system 保存到 `AIRequest`，但 provider adapter 构造请求时只使用了 `request.messages`，没有拼入 `request.system`。这会导致 Loop/System/Action 的系统提示在真实 API 调用中失效。位置：[base.py](B:/WorkSpace/TinySoul/tinysoul/llm/provider/adapters/base.py:144)。

2. **`ActionRegistry.with_allowlist()` 会丢失注入的环境能力**  
   它重新创建 `ActionRegistry()`，共享 registry/cache，但没有继承原来的 `_env_caps`。如果外部注入了 capability，allowlist view 里动态注册时可能使用重新探测的环境能力。位置：[registry.py](B:/WorkSpace/TinySoul/tinysoul/action/framework/registry.py:67)。

3. **Action 记录里的 `action_target` 可能丢失**  
   dispatcher 发出的成功信号里 `target` 和 `result` 是同级字段，但 `InterruptHandler` 写记录时从 `action_result` 里取 `target`，导致成功 action 的选择理由通常为空。这个会削弱可追溯性。

4. **`QueryAction` 对 handler 有隐式接口假设**  
   `ActionHandler` 抽象类没有声明 `resolve_run_config()`，但 `QueryAction.execute()` 直接调用它。内置 `ActionBase` 没问题，自定义非 `ActionBase` handler 会运行期失败。位置：[manager.py](B:/WorkSpace/TinySoul/tinysoul/action/framework/manager.py:94)。

5. **Sandbox 是 best-effort，不是安全隔离**  
   文档也承认没有 OS 级隔离。代码允许 `pathlib`，而 prompt 又告诉动态脚本可以用 `pathlib`，这与 `open()` 代理边界控制存在冲突。路径校验也用了字符串前缀判断，建议改为 `Path.relative_to()`。位置：[sandbox.py](B:/WorkSpace/TinySoul/tinysoul/infra/sandbox.py:78)。

6. **并行动作超时是协作式的**  
   `ParallelDispatcher` 超时后会请求 termination 并 cancel future，但正在运行的线程无法强杀；不配合 `RunConfig` 的 action 可能继续跑。位置：[parallel_dispatcher.py](B:/WorkSpace/TinySoul/tinysoul/loop/parallel_dispatcher.py:142)。

7. **Prompt context 裁剪能力没有接入 Step 任务**  
   `PromptBuilder` 支持 `include_context`，但 choose/execute/update 三个 Step 调用时没有传入，长任务下 token 控制会比较粗。位置：[choose.py](B:/WorkSpace/TinySoul/tinysoul/loop/steps/choose.py:40)。

8. **README 有少量文档漂移**  
   例如 `docs/core/core_design_query.md`、`basic_system`、`prompts.py` 等引用已与当前代码不完全一致。位置：[README.md](B:/WorkSpace/TinySoul/README.md:324)。
