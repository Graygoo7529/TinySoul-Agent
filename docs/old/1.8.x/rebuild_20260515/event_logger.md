
# Event Logger

Event Logger（structured event logging with level/category filtering and multi-sink output）

EventLogger 将 QueryLoop 中散落的 `print()` 调用替换为结构化事件日志。业务代码只负责 emit 事件（what happened）；Sink 负责决定如何、是否、以何种格式输出。二者解耦，使终端输出、测试捕获、静默模式可通过配置切换，无需修改业务代码。

## Design Principles

（1）**业务代码与输出格式解耦**
- `EventLogger` 只负责「过滤 + 路由」
- `Sink` 负责「格式化 + 输出目的地」
- 新增输出格式（如文件日志、JSON 流）只需新增 Sink，不改业务代码

（2）**四级日志级别，语义明确**
- `QUIET`：零输出，用于批量运行或测试静默模式
- `NORMAL`：核心流程 + 关键状态变更 + 简要错误
- `VERBOSE`：NORMAL + 错误详情（类型、消息、traceback）+ workspace 扫描 + LLM 重试/切换
- `DEBUG`：VERBOSE + 完整 state JSON + action meta/detail JSON + 完整 LLM prompt

（3）**分类过滤，精准降噪**
- `EventCategory`：LOOP | ACTION | STATE | PROMPT | WARN | ERROR | LLM
- 通过 `TINYSOUL_LOG_CATEGORIES` 环境变量可只订阅特定分类
- 例如：只关心 ACTION 和 ERROR，可过滤掉 PROMPT 和 LLM 的冗长输出

（4）**同步直调，无 Message Bus 开销**
- TinySoul 是单进程框架，无跨组件异步通信需求
- Sink 被同步调用，无队列、无回调、无并发问题
- 若未来需要异步/远程日志，可在外部 Sink 中自行封装

（5）**终端输出是设计目标，不是副作用**
- ConsoleSink 的格式化是核心体验，不是调试用的 "print 替代品"
- 固定列宽对齐、语义着色、智能换行、结构化参数，都是为「人眼可读」服务

## Log Level Semantics

| Level | 输出内容 | 典型场景 |
|---|---|---|
| QUIET | 无任何输出 | CI 批量测试、headless 运行 |
| NORMAL | Loop Ready / Turn 边界 / Step 1-3 核心流 / Todo & Milestone 内容 / 简要错误 / Loop Complete | 日常交互，关注 Agent 在做什么 |
| VERBOSE | NORMAL + 错误详情（error_type, message, traceback）/ workspace scan 结果 / LLM retry & failover | 调试行为异常，查看错误根因 |
| DEBUG | VERBOSE + 完整 state JSON / action meta/detail JSON / 完整 LLM prompt（system + user）| 深度调试 LLM 交互和状态演化 |

log level semantics(additional explanation)
- `NORMAL` 是默认级别，平衡信息量与可读性
- `VERBOSE` 的 error detail 只在 step 失败时输出，不污染正常流程
- `DEBUG` 的 JSON dump 可能很长，通过折叠或截断避免刷屏（ConsoleSink 对超长的 JSON 自动截断到 20 行）

## Event Category

| Category | 用途 | 默认级别 |
|---|---|---|
| LOOP | Turn 开始/结束、Loop Ready/Complete、中断 | NORMAL |
| ACTION | Action 选择、参数、结果 | NORMAL |
| STATE | Todo/Milestone 变更、workspace 扫描 | NORMAL / VERBOSE |
| ERROR | Step 失败、通用错误 | NORMAL / VERBOSE |
| LLM | 重试、模型切换 | VERBOSE |
| PROMPT | 完整 LLM prompt dump | DEBUG |
| WARN | 警告信息 | NORMAL |

event category semantics(additional explanation)
- ERROR 分类在 NORMAL 级别输出简要错误，在 VERBOSE 级别输出详细错误
- STATE 分类在 NORMAL 级别输出 Todo/Milestone 变更，在 VERBOSE 级别输出 workspace 扫描
- 分类过滤与级别过滤是正交的：一个事件必须同时满足「级别 >= 阈值」且「分类在订阅集合中」才会被输出

## Console Sink Output Design

ConsoleSink 是终端用户体验的核心。其格式化遵循三条原则：**固定列对齐**、**语义着色最小化**、**长内容智能换行**。

### Fixed-Column Alignment

所有带标签的输出采用固定列宽对齐：

```
[Step 1]  Action  create_markdown_file
          Reason  Need to save the computed result as a markdown
                  report for the user to review
[Step 2]  Args    file_path: report.md
                  content: # Dog Weight Report

                  Border collie: 15-20 kg
                  Scottish terrier: 8-10 kg

                  Combined: 23-30 kg
          Result  created
[Step 3]  State   TODO: add | MILESTONE: no-change | FINISHED: no
          Todo    <add>  Save the computed result as a markdown
                  report
          Mile    Computed combined dog weight
```

列宽分配：
- 第 1 列（label）：10 字符，如 `[Step 1]`、`[Error]  `
- 第 2 列（key）：6 字符，如 `Action`、`Reason`、`Todo`
- 分隔：`  `（2 空格）
- 第 3 列（value）：从第 18 列开始，到终端右边界

fixed-column semantics(additional explanation)
- 固定列宽确保视觉对齐，不受 value 长度影响
- ANSI 颜色码不计入视觉宽度：ConsoleSink 在计算 pad 时使用纯文本长度，再附加颜色码
- 终端宽度通过 `shutil.get_terminal_size()` 动态获取，value 可用宽度 = `term_width - 18`
- 若终端过窄（< 38 列），回退到 80 列作为 value 可用宽度

### Semantic Color Policy

颜色遵循「最小化且语义化」原则——只有结构标记和语义值着色，普通文本保持原色：

| 元素 | 颜色 | 说明 |
|---|---|---|
| `[Step N]` / 边界线 `═` | 蓝色 + 粗体 | 步骤标记和 turn 面板边框 |
| `Action` / `Reason` / `Args` / `Result` / `State` / `Todo` / `Mile` | 青色 | 结构标签，统一突出 |
| Action 名称（value） | 绿色 | 表示「执行了什么」|
| Milestone 文本（value） | 青色 | 表示「达成了什么」|
| 错误标签 `[Error]` | 红色 + 粗体 | 致命信号 |
| 错误详情 / ABORT Disposition | 红色 | 需要关注 |
| CONTINUE 错误 | 黄色 | 非致命，已恢复 |
| 边界线 / Loop Ready / Complete | 白色 + 粗体 | 宏观结构分隔 |

semantic color semantics(additional explanation)
- key 标签统一用青色，形成视觉层级：蓝色(Step) → 青色(key) → 绿色/原色(value)
- 错误使用红/黄两色区分严重程度，不滥用红色导致告警疲劳
- value 中的普通文本（如 Reason、Args 内容）不着色，保证长文本的可读性
- 颜色可通过 `TINYSOUL_LOG_COLOR=0` 关闭，自动检测 tty

### Smart Wrapping with Indent Preservation

长 value 不截断（`...`），而是智能换行，续行保持与首行 value 的起始列对齐：

```
          Reason  Need to save the computed result as a markdown
                  report for the user to review
```

实现策略：
1. 计算 value 可用宽度（终端宽 - 18）
2. 若纯文本长度 <= 可用宽度，单行输出
3. 若超长，使用 `textwrap.wrap` 按可用宽度分多行
4. 续行以 18 空格缩进（与首行 value 起始列对齐）
5. 若 value 包含显式 `\n`（如多行字符串参数），先按 `\n` 分段，再对每段独立 wrap，保留段落结构

smart wrapping semantics(additional explanation)
- 显式换行符的保留对 action_args 尤为重要：LLM 生成的 markdown 内容、脚本代码等内部换行结构必须完整呈现
- 空行（`\n\n`）被保留为空字符串行，视觉上形成段落分隔
- wrap 算法设置 `break_long_words=True`，防止超长无空格字符串（如 base64、路径）撑爆行宽

### Structured Multi-Parameter Args

Args 的呈现规则：每个参数独占一行，key:value 格式：

```
[Step 2]  Args    file_path: report.md
                  content: # Dog Weight Report

                  Border collie: 15-20 kg
                  Scottish terrier: 8-10 kg

                  Combined: 23-30 kg
```

结构化规则：
- 首个参数带 `[Step 2]  Args` 标签
- 后续参数以 18 空格缩进续行
- 字符串值直接拼接 `k: v`
- 非字符串值使用 `json.dumps(v, ensure_ascii=False)`
- 配合 smart wrapping，长值自动多行展开且缩进对齐

structured args semantics(additional explanation)
- 一参数一行取代了过去「所有参数挤在一行 JSON」的呈现方式
- JSON 序列化用于复杂嵌套值（dict/list），纯字符串用于简单值，兼顾可读性和信息完整性
- 若 args 为空字典，显示 `(none)`

### Todo Operation Indicator

Todo 变更行附加操作符标记，NORMAL 级别可见：

```
          Todo    <add>     Save the computed result as a markdown report
          Todo    <complete>  todo-1  Save the computed result as a markdown report
          Todo    <cancel>    todo-3  Some cancelled task
```

呈现规则：
- `<add>` / `<complete>` / `<cancel>`：尖括号包裹，与描述文本空格分隔
- NORMAL：只显示 `操作符 + 描述`
- VERBOSE：追加 `key`，格式为 `操作符 + key + 描述`

todo indicator semantics(additional explanation)
- 操作符使用尖括号 `<>` 使其在文本流中更醒目，区别于普通描述词
- `complete` 操作符使用 `<complete>` 而非 `<done>`，与 LLM 协议中的 operation 字段保持一致
- VERBOSE 模式下 key 的暴露便于开发者追踪 todo 生命周期（尤其是同名 todo 的多次 add/complete）

## Sink Architecture

```
┌─────────────────────────────────────────┐
│  EventLogger                            │
│  - level / category filtering            │
│  - route to all registered sinks         │
├─────────────────────────────────────────┤
│  Sink (ABC)                              │
│  - emit(event: Event) -> None            │
├──────────┬──────────────┬───────────────┤
│ConsoleSink│ NullSink     │ CaptureSink   │
│- ANSI color│ - discard    │ - record to   │
│- alignment│   all events │   list        │
│- wrapping │              │ - for test    │
└──────────┴──────────────┴───────────────┘
```

### ConsoleSink

终端输出 Sink，支持：
- ANSI 颜色（自动检测 tty，可通过环境变量关闭）
- 固定列对齐（处理 ANSI 码的视觉宽度）
- 智能换行（保留显式换行 + textwrap 溢出段）
- 事件标题到格式化器的映射（`self._formatters` dict）

### NullSink

静默丢弃所有事件。用于测试中的「不关心日志」场景。

### CaptureSink

记录所有事件到 `self.events: list[Event]`。用于测试中断言事件内容（取代过去的 `capsys` stdout 断言）。

capture sink semantics(additional explanation)
- 测试从「匹配 stdout 字符串」迁移到「断言 Event 的 title 和 data」
- 测试不再依赖格式化细节（如空格数、颜色码），只验证语义事件是否发生
- 若需要测试 ConsoleSink 的格式化，直接实例化 ConsoleSink 并调用 emit，不经过 EventLogger 过滤

## Query Loop Integration

EventLogger 通过构造函数注入 `QueryLoop`，所有 step 和 state 变更都通过 logger 方法发出事件。

### Injection Pattern

```python
class QueryLoop:
    def __init__(self, ..., logger: EventLogger | None = None):
        self._logger = logger or default_logger()
```

- `default_logger()` 从环境变量读取 `TINYSOUL_LOG_LEVEL`、`TINYSOUL_LOG_CATEGORIES`、`TINYSOUL_LOG_COLOR`
- 测试场景注入带 `CaptureSink` 的 `EventLogger`，断言事件序列
- main.py demo 不再使用 `print()`，所有输出由 EventLogger 接管

### Event Emission Points

| Loop 阶段 | 事件方法 | 级别 | 说明 |
|---|---|---|---|
| Init | `loop_ready()` | NORMAL | Query、Target、可用 Action 数 |
| Turn 开始 | `turn_started()` | NORMAL | Turn N / max_turns |
| Turn 结束 | `turn_ended()` | NORMAL | Turn 结束边界线 |
| Step 1 结束 | `action_selected()` | NORMAL | action_name + selection_reason |
| Step 2a 结束 | `action_args()` | NORMAL | 参数字典（含 action_name） |
| Step 2b 结束 | `action_result()` | NORMAL | 结果摘要（含 success / verbose / action_name 标记）|
| Step 3 结束 | `state_updated()` | NORMAL | todo / milestone / finished 变更摘要 |
| Todo add | `todo_added()` | NORMAL | `<add>` + desc (+ key in VERBOSE) |
| Todo complete | `todo_completed()` | NORMAL | `<complete>` + desc (+ key in VERBOSE) |
| Todo cancel | `todo_cancelled()` | NORMAL | `<cancel>` + desc (+ key in VERBOSE) |
| Milestone add | `milestone_added()` | NORMAL | milestone 文本 |
| Step 失败 | `step_failed()` | NORMAL | turn + step 名 + disposition + 简要错误 |
| 失败详情 | `step_failed_detail()` | VERBOSE | turn + step + error_type + message + traceback |
| Step 重试 | `step_retry()` | VERBOSE | step 重试信息（如模型切换）|
| LLM 就绪 | `llm_ready()` | NORMAL | 首个可用模型名称 + provider |
| LLM 重试 | `llm_retry()` | VERBOSE | step + 模型名 + attempt/max_attempts |
| LLM 切换 | `llm_failover()` | NORMAL | from_model -> to_model |
| Loop 结束 | `loop_complete()` | NORMAL | turns / finished / todo_summary / milestones |
| 中断 | `loop_interrupted()` | NORMAL | 用户中断 |

### Debug Events

| 事件方法 | 级别 | 内容 |
|---|---|---|
| `debug_state()` | DEBUG | 当前 turn 的完整 state JSON + step 名 |
| `debug_action_meta()` | DEBUG | 可用 actions 的 meta 列表 JSON |
| `debug_action_detail()` | DEBUG | 选中 action 的 detail JSON |
| `debug_prompt()` | DEBUG | 完整 system + user prompt + source 标记 |

debug events semantics(additional explanation)
- debug 事件只在 DEBUG 级别输出，不影响 NORMAL 和 VERBOSE 的可读性
- state JSON 和 prompt 可能很长，ConsoleSink 不截断 debug 内容（完整输出便于重定向到文件后分析）
- prompt debug 区分 `loop_step` 和 `action_internal` 两种来源，便于追踪 LLM 调用链

## Environment Variables

| 变量 | 默认值 | 说明 |
|---|---|---|
| `TINYSOUL_LOG_LEVEL` | `normal` | `quiet` / `normal` / `verbose` / `debug` |
| `TINYSOUL_LOG_CATEGORIES` | `all` | 逗号分隔，如 `loop,action,error` |
| `TINYSOUL_LOG_COLOR` | `1` (tty 检测) | `1` 启用 ANSI 颜色，`0` 禁用 |
