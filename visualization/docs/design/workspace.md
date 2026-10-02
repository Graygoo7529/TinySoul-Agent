# Workspace 视图

Workspace 页面浏览和操作当日工作区资源。前端不直接访问磁盘，所有资源身份由 v2 Workspace owner 解析，所有写入通过 Endpoint 原子提交。

## 读取

`WorkspaceClient.manifest` 提供目录和标签；`resource` 提供有界文本页并支持 continuation，`readBlob` 提供二进制响应和 Range 读取。归档日可以显式传入 day，只读访问不会悄悄回退到今天。

## 写入

文本、二进制、目录、移动、标签、edit、append、trash 和 restore 都使用 v2 owner routes。页面只提交用户明确的资源 Link 和操作参数，不拼接物理路径，也不在客户端维护 digest/CAS 状态机。

编辑器负责展示 Markdown/文本和有限预览；保存成功后重新读取 owner manifest/resource，Observation 只触发刷新提示。Workspace 事件不能替代正式读取，也不会改变 Session 或 Turn 的事实。
