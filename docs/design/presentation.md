# 项目展示配置与资产

Gateway 的 PresentationService 拥有项目共享界面配置和展示资产读取语义。它绑定项目目录，复用 Infra 的 TOML、原子写入和有界 I/O 设施；Endpoint 只进行鉴权、协议映射和请求错误转换，前端负责交互及视觉效果。

## 来源与生命周期

`tinysoul/assets/common/presentation/` 是项目模板。init/reset 通过既有物化流程将它复制到项目的 `presentation/`，运行期间读取和修改项目副本。reset 沿用仅保留 `.env` 的项目重建语义。

`presentation/configs/` 保存受支持的 typed 配置文档，`presentation/assets/` 保存可分目录组织的真实展示文件。展示配置不进入 Agent include/document_sets、运行方案、Context、Home、Workspace 或按日归档。

EndpointHost 首次绑定项目时装配服务，后续 generation bind/unbind 保留该实例。展示请求不经过 Agent 的可用性门禁；Agent 忙碌或重新绑定时仍可读写。HTTP 服务本身必须已经启动。服务不启动额外 watcher、后台同步或恢复状态机。

## 保存与使用

界面文档统一保存主题、字体、字号、行高、密度及动画偏好。服务每次读取当前文件，将请求声明字段合并为完整候选，校验后单文件原子保存；短写操作串行并在传播取消前完成 join。文档缺失时纯读取返回类型默认值，首次有效保存创建物理文件。无效文件返回请求错误，不以默认值掩盖或覆盖。

文档 ID 由服务映射到明确相对路径；增加配置类型时同时增加字段语义和实际消费者。任意放入的 TOML 不会自动生成界面。读写共用基础设施，不引入动态发现或通用文件编辑协议。结构化保存会重新排版 TOML，不保证注释保留。

前端只保存内存投影和待提交字段，完成一次控件操作后即时预览、自动保存，并反馈结果。保存失败保留未保存修改，可重试或重新读取。主题导航按钮、界面页和图表共用同一偏好入口。连接信息和导航状态仍属于客户端。

项目修改在其它客户端下次连接、重新连接、进入界面设置或显式刷新时可见。同字段最后成功保存的值生效；不提供实时推送或 revision 合并。界面保存不经过 Agent 配置草稿、apply/reload 或 generation 重建。

## 资产

资产列表来自实际目录，读取目标限定在 presentation/assets 内并受 Endpoint 资源字节上限约束。前端通过带 Bearer 的传输读取 Blob，以 Object URL 预览普通图片或下载文件；切换资源、连接和卸载时回收 URL。资产目录缺失时列表为空。

资产不自动成为字体选项或可执行代码；本接口不提供上传、删除或重命名，也不声明新的模型资源 ref。失败沿既有请求 envelope 返回，不进入 Runtime Trap。

接口细节见 [Presentation Endpoint](../endpoint/presentation.md)，前端交互见 [Settings 设计](../../visualization/docs/design/settings.md)。
