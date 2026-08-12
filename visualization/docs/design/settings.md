# Settings 与配置管理

## 定位

Settings 是主导航中的独立页面，不是覆盖当前业务视图的对话框。页面负责三类配置表面：

- 项目业务配置：运行根目录内的 TOML 配置源；
- 项目凭据：配置声明引用并由项目 `.env` 持有的环境变量；
- 客户端偏好：项目连接路径和界面主题。

前端不直接读取或写入项目文件。TOML 与 `.env` 的查询、校验、持久化和运行实例激活都由 Endpoint 配置控制面拥有。

## 页面结构

Settings 使用稳定的二级导航：

- Overview 展示 Runtime Generation、运行活动、配置源和进程外壳摘要；
- Models、Embedding、Capabilities、Memory、Workspace、Maintenance、Behavior、System 按配置路径归属展示 TOML 字段；System 包含 `config.*` 和除 embedding 外的 `infra.*`，因此进程持有的不可写字段仍然逐项可读；
- Credentials 单独展示和编辑 `.env` 原始键值；
- Application 管理仅属于前端的项目连接和主题偏好。

配置分区由 TOML 顶层路径的模块所有权决定。页面分组只组织展示，不建立前端配置 schema，不解释后端业务默认值，也不复制模块配置解析器。

## 状态所有权

`appStore` 继续拥有连接句柄、事件、工作区缓存和持久化客户端偏好。`configStore` 是独立、非持久化的 Endpoint 配置快照：

- `GET /v1/config` 是页面读取事实源；
- 实例切换或断开时清空快照，不能把旧实例配置带入新连接；
- `/v1/status` 中 Runtime activity 变化以及 Turn、Maintenance、Daily Transition 状态事件都会触发权威重读，使统一只读状态跟随当前实例；
- `config.activation.started/completed/failed` 只使快照失效并触发重读，不从 Observation payload 派生第二份激活状态；
- 并发重读使用最后一次请求获胜，旧请求以及旧实例迟到的 PATCH/GET 结果不能覆盖更新后的 Generation。

TOML source value 是控件编辑的持久值，effective field 用于判断最终来源、运行值和可写性。正常项目 TOML 字段两者一致；若 process environment 或 override 赢得优先级，控件只读并明确显示 effective source/value。

## 写入与激活

每次字段编辑生成一个 source-aware mutation，并直接调用 `PATCH /v1/config`。该请求在后端完成候选校验、Runtime Generation 重建、文件原子提交和句柄切换后才返回 `state=active`。

- 布尔值通过 switch 单字段即时提交；
- 字符串、数值和结构值在字段内确认后单字段提交；
- `.env` 值必须是字符串，支持设置和删除；
- 任意 User Turn、Maintenance Turn 或其他非 idle 活动期间，配置页面完整可读但统一只读；
- 成功提示使用 PATCH receipt 的 Generation id，随后重新读取权威快照；快照重读失败不反转已经成功的激活结果。

前端不提供独立 Apply Runtime 操作，也不先调用 validate 再调用 patch。PATCH 本身就是“持久化 + 当前实例激活”的完整用户操作。

## Credentials

Credentials 从两处构造列表：TOML 中的 `api_key_env` / `api_key_envs` 声明，以及 `.env` 中已有的原始变量。值只保存在非持久化配置 store 中，输入默认遮罩，可显式查看、更新、删除或新增合法环境变量名；变量未写入、已写入空值和已配置非空值是三个不同状态。

系统进程环境仍可作为后端高优先级覆盖，但不是前端配置表面。前端不枚举、不修改进程环境；出现覆盖时只按 Endpoint 的 effective source 投影为只读状态。

## 扩展规则

新增后端模块配置时，只在路径到 Settings 子页的归属表中增加稳定映射。字段控件继续由 JSON 值类型选择，不为每个 TOML 文件建立专用表单。只有确有领域交互语义的字段才增加局部专用控件，不能让展示层演化为第二套配置解释器。
