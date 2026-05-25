# AITask 多模态输入改进

## 背景

项目内 LLM 调用主路径应继续收敛到 `AITask`。`AIClient.chat()` 保持低层 message 通道，负责发送已经构造好的 provider-compatible messages；多模态输入的语义应主要放在 `LLMPrompt`、`Attachment` 和 `AITask` 这一层。

当前 `AITask` 已经可以通过 `LLMPrompt.attachments` 传递图文输入，但 attachment 类型、文件处理、音视频输入和 embedding 能力还需要进一步明确。

## 当前现状

- Loop step 和 LLM action 都通过 `AITask` 调用。
- `AITask` 会把 `LLMPrompt.attachments` 转成多模态 message content。
- image attachment 会转成 OpenAI-compatible `image_url` part。
- 非 image attachment 当前会退化为 text part。
- `AIClient.embed()` 当前只支持 `list[str]` 文本 embedding。

## 问题

### 1. `AIClient` 没有专门的图文聊天高层 API

这不是当前项目主路径的核心问题。

原因是项目内部主要通过 `AITask` 调用 LLM，而 `AITask` 已经支持 `attachments`。`AIClient.chat()` 作为低层通道，保留原始 `messages` 入参是合理的。

### 2. 文件 attachment 当前会退化为 text

这是实际能力缺口。

当前非 image attachment 会被转成 text part，容易让调用方误以为系统支持 provider 原生文件上传或文件解析。文本文件可以接受这种方式，但 PDF、DOCX、大文件和二进制文件不应静默退化。

### 3. 音频和视频没有一等输入封装

这是实际能力缺口。

当前 attachment 只对 image 做了特殊序列化。audio/video 没有明确类型、构造函数、provider 序列化规则和模型能力检查。

### 4. Embedding 当前仍是文本 embedding

这不是 `AITask` chat 主路径问题，但会影响后续检索和记忆能力。

当前 `AIClient.embed()` 只接受 `list[str]`，底层也是文本 embedding。若未来要做 workspace 资源检索、多模态记忆、图片检索或图文联合检索，需要单独设计。

## 建议

- 暂不优先新增 `AIClient.chat_with_images()`；如果后续把 `AIClient` 作为外部 SDK 暴露，再加薄封装。
- 优先增强 `Attachment` 类型系统，而不是在 client 层增加多个便捷方法。
- 文件输入不要静默降级：文本文件可以 inline，文档类文件需要解析器，大文件需要拒绝、截断或进入上传/检索流程。
- 为 audio/video 增加明确 attachment 类型和 provider 序列化边界。
- 为多模态输入增加模型能力检查，例如 vision、audio、video、file upload。
- 多模态 chat 和多模态 embedding 分开设计，不混在同一轮改造里。

## 实施方案

### 阶段 1：重构 Attachment 类型

目标是让调用方表达清楚“传入的是什么”，而不是只传 `type="file"`。

建议新增或调整：

- `Attachment.image_file(path)`
- `Attachment.image_base64(data, mime_type)`
- `Attachment.image_url(url)`
- `Attachment.text_file(path)`
- `Attachment.document_file(path)`
- `Attachment.audio_file(path)`
- `Attachment.video_file(path)`

同时保留必要的兼容入口，但对模糊类型给出 deprecation 或显式错误。

### 阶段 2：增加序列化层

目标是把 attachment 到 provider message part 的转换集中起来。

建议新增 `AttachmentSerializer` 或等价函数：

- 输入：`Attachment` 列表、目标 provider/model 能力。
- 输出：provider-compatible message content parts。
- 不支持的 attachment 类型直接抛出明确错误。

这样 `AITask` 不需要自己理解每种 provider 的消息格式。

### 阶段 3：增加能力检查

目标是在发送请求前失败，而不是把不支持的多模态请求发到 provider 后得到模糊错误。

建议扩展能力标记：

- `VISION`
- `AUDIO`
- `VIDEO`
- `FILE_UPLOAD`
- `DOCUMENT_PARSE`

当 prompt 带有对应 attachment 时，profile 必须能路由到具备相应能力的模型。

### 阶段 4：完善文件处理策略

目标是避免“文件输入”语义不清。

建议规则：

- `.txt/.md/.json/.csv` 等文本文件可以 inline。
- PDF/DOCX 等文档先接解析器；没有解析器时显式不支持。
- 超过 token 或大小阈值的文件不直接 inline。
- 大文件后续可以进入 retrieval 或 provider file upload 流程。

### 阶段 5：单独设计多模态 embedding

目标是为检索和记忆能力预留独立设计空间。

建议另起设计：

- 新的输入结构，例如 image/document/audio embedding request。
- 新的模型类型或能力标记。
- 新的返回结构，支持多个向量、metadata 和资源引用。
- 与 workspace resource index 或 memory 模块连接。

## 验收标准

- `AITask` 可以用明确 API 接收图片、文本文件、文档、音频、视频 attachment。
- 不支持的 attachment 类型会在调用前给出明确错误。
- image 输入继续兼容现有图文 chat 能力。
- 文本文件 inline 行为有大小和类型边界。
- PDF/DOCX 不再静默退化成普通 text。
- 多模态输入会参与模型能力检查。
- embedding 改造有独立 todo 或设计文档承接，不混入 chat attachment 实现。

## 设计原则

- `AITask` 面向项目内部任务语义，应该暴露清晰 attachment 接口。
- `AIClient.chat()` 面向 provider 通道，不承载过多高层语义。
- 不支持的多模态输入应显式失败，不静默降级。
- 多模态 chat 和多模态 embedding 是两条能力线，应分开设计。
