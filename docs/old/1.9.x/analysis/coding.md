7.2 代码风险
| 风险 | 说明 | 建议 |
|------|------|------|
| **线程安全假设** | `QueryState` 的 `list.append` 依赖 CPython GIL 原子性 | 在 PyPy 中可能不成立；关键路径考虑加锁 |
| **沙箱隔离仍有限** | worker 子进程可被 terminate/kill，但缺少 OS 级 syscall/network 权限隔离 | 生产级需容器、低权限进程、job object/seccomp 等更强隔离 |
| **后台生命周期复杂度** | QueryLoop 终态会请求 shutdown，但长期 ONGOING action 仍需要更完整的生命周期管理 | 增加 ongoing manager 的持久化、健康检查和集中清理 |
