# Environment 设计

Environment 封装外部 I/O，依赖注入的端口交付线索或执行定时回调，不拥有 Workspace、Reflection、Turn 或根队列状态。

FileWatcher 使用单一 watchfiles 后端，按 owner 提供的过滤规则合并原生通知。通知不证明最终文件事实；Workspace 插件完成 reconcile 后才发布领域事件。启动等待监听就绪，随后 owner 建立扫描基线；停止设置停止事件并等待后台读取和已进入的回调结束。没有独立轮询后端、持久文件日志或自动恢复状态机。

原生监听故障由注入的失败回调报告有限类型；owner 回调失败保留其业务异常归属，不转换成“监听暂不可用”。Workspace 插件决定领域失败反馈，Agent 在来源停止时收集有限清理诊断。来源不能从没有运行 frame 的后台任务直接抛 Runtime 转移。

DeadlineTimer 只等待策略返回的秒数并支持及时停止；Reflection 插件拥有到期计算、固定到期日、满载重试与类型化根请求提交。文件监听与定时器都在同一 asyncio 运行环境中启动，创建对象本身不启动后台任务。

监听仅覆盖当前 Workspace；日切与世代切换由 Agent 暂停来源、join owner 操作、完成独占切换后重新绑定。终端和 Endpoint 继续由 Gateway 显式挂载，来源没有进程退出权。
