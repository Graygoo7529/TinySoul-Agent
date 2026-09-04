# ConfigSource 异常边界执行记录

## 状态

- 文档状态：`done`
- 规约偏差修复：`done`
- 异常边界测试补充：`done`
- Runtime bridge 覆盖补充：`done`
- 完整门禁验证：`done`

## 实施范围

`ConfigSource` 作为 Infra 配置公共对象统一使用 `ConfigError` 表达构造契约失败，并校验来源名称、来源类型、路径、source id 和扁平配置键；输入 values 映射在对象边界复制，避免 frozen dataclass 持有外部可变映射。该实现沿用既有 `ConfigDocument` 与 `ConfigError` 约定，没有新增异常类型或 Runtime reason。

测试只增加公开契约和实际遗漏的桥接分支：ConfigSource 构造边界、continuation 本地解析错误包装、Endpoint/Maintenance failure namespace 以及对应 Runtime bridge 映射。Infra config 的 AST 护栏只限制该配置子包，不约束 continuation 等有意在局部捕获的解析哨兵。

## 验证

聚焦 Infra、Endpoint、Maintenance、Runtime 与架构测试通过后，继续运行仓库 Fast、Full、Generation 套件和 `ty` 类型检查。External 套件仍按项目规约需要显式凭据，不纳入本次门禁。
