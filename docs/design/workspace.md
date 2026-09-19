# Workspace 设计

## 所有权与内部边界

Workspace 是当前 CalendarDay 的文件、目录、索引与 Trash owner。磁盘是内容事实；manifest 保存可重建的分类、大小和时间信息，以及不可因扫描而丢弃的标签与说明。Working 段只接收 Link/summary 投影，不保存文件正文。

对外装配入口是 WorkspaceEngineBuilder/WorkspaceEngine；Action、SDK 与 Endpoint 通过 WorkspaceService 调用同一个 owner。服务由 Agent 注入世代与日级准入作用域，切换后旧对象失效。归档访问使用 WorkspaceArchiveView，只读目标日快照，旧日 Link 不解析到新日同名文件。

内部 storage 封装 manifest、reconcile、文件变更与 Trash，inspection 提供有界文本/图像/文档读取和搜索。Engine 组合这些职责并拥有同一进程内锁、日期与变更发布。actions 按显式操作、LLM 生成/分析和结果投影划分，不建立第二份文件或索引状态。

## 文件与轻量索引

资源身份使用 `workspace:<relative-path>`。owner 拒绝绝对路径、越界、内部元数据目录以及 symlink/junction 跳转。目录也是可列举、标记、移动和删除的资源。pinned/tmp/library 标签只表达使用意图，不影响日生命周期，也不授予自动删除或跨日保留权。

Manifest schema v4 严格校验字段与版本，不接受旧 CAS 格式。reconcile 根据磁盘更新派生字段，保留同一 Link 的说明与标签；外部程序改写内容不会抹去人工元数据。扫描受数量上限约束并返回覆盖情况；未完整扫描时保留原 manifest，不能把未访问资源当作删除。不能解释的存储数据作为 owner 不变量失败报告，不自动清空或迁移。

同一 Engine 的短操作由可重入锁串行化，单文件内容使用原子替换。没有 digest/revision、read-set、mtime CAS 或提交前来源复验。外部进程共写时可能覆盖内容，owner 锁不构成跨进程锁或文件系统快照。调用方须明确创建/覆盖意图。

## 行动与提交

| 行动 | 行为 |
|---|---|
| list/search/read | 有界列举、literal/regex 搜索和显式正文读取 |
| write | 写入明确 UTF-8 文本，默认拒绝覆盖已有目标 |
| edit/append | 有序精确替换或追加，验证完整结果后一次写入 |
| move/mkdir | 移动文件/目录或创建目录，已有目标冲突不覆盖 |
| delete/restore/trash_list | 可恢复删除、按原位置恢复、查询仍持有内容的 Trash |
| tag/describe | 维护标签与说明；describe 的模型输入只在当前 Action 中存在 |
| compose/analyze | 局部模型生成完整文本工件，或基于显式来源返回结构化分析 |

edit 对每一项在前项结果中检查匹配，零匹配或歧义均失败；后项失败不留下前项修改。append 和生成覆盖也受 owner 的完整写入上限约束。move 更新资源及子项的元数据身份，不重写已保存的 Session 引用。

move 与 restore 共用 owner 内部迁移边界：同一锁内先把目标及子项的说明、标签保存到现有 manifest，保留源记录，再原子移动内容，最后由普通 reconcile 按磁盘更新资源投影。元数据保存失败时不移动内容；移动未发生则扫描保留源，移动已发生则扫描保留目标，重新打开 owner 也不依赖丢失的内存参数。中间记录是 owner 的迁移元数据，不发布为成功变更。这里没有新增 journal、恢复状态机或多文件回滚承诺。

Resource/Web 通过 write_bundle 预检全部目标、覆盖策略及待删旧资产，在同一锁内依次提交并刷新索引。每个文件原子替换，多个文件不构成断电事务。后续文件或索引失败时，WorkspaceIOError 保留 committed_links；已发生的副作用不回滚，也不伪称整个操作未执行。

批次的唯一性、写删冲突、父子冲突与结果匹配都基于 owner 解析后的 Path，不能仅比较输入 Link 字符串；Windows 大小写等价路径不能成为同一批中的两个目标。reconcile 按同一平台路径身份保留元数据。包装内部删除或索引失败时，外层合并内层已经确认的 committed_links，准确保留全部已提交内容变化；这些事实沿既有 bridge、SDK 与 Endpoint 协议传播。

Trash 条目保存原身份、说明、标签、子项元数据和内容。内容存在是可恢复事实，没有多阶段 marker 或恢复 Trap。移动未发生或恢复已完成的仅元数据条目不列为可恢复内容；损坏或丢失元数据作为边界失败，原内容保留。恢复目标存在时返回局部冲突。Archive 的日切 journal 是不同的确定性存储协议，继续由 Archive owner 维护。

## 有界读取与模型输入

小文本可以完整读取，大文本按显式行范围和 continuation 渐进读取，结果标明覆盖与截断。continuation 表达同一读取请求的下一位置，不锁定文件版本；外部改写后分页可能看到新内容。编码、图像真实格式、字节大小和模型图像能力均在各自入口校验；二进制资源不自动注入语境。

search 明确区分文件、目录前缀和整个 Workspace。字符扫描、候选、片段与结果总大小各有预算，返回覆盖原因和紧凑行定位。正则使用 regex 的超时执行能力，每次搜索共享 0.2 秒匹配预算；超时报告不完整覆盖，不能当作零命中。搜索经 joined owner 边界执行，不阻塞事件循环。

read/search 的有界正文可在当前交互暂时展开，后续 Trace 折叠为紧凑定位事实。正文不进入 Working 或持久 Session 的资源摘要。LLM 内部任务通过 target_link/reference_links 局部读取，Phase2 只生成 Link 和意图。

compose 合并新建与替换生成。已有目标必须完整读入允许的写入预算；目标截断时在调用模型前失败，引导改用 edit/append。模型输出不完整、超限或取消时不提交。完整文本在 Action 内存中交给 owner，成功只返回元数据。生成期间不持文件锁，最终也不比较来源版本。analyze 消费明确有界来源，结论通过所属结果协议校验。

## Turn、进程与日切

Turn preparation、必要查询以及受控进程结束后进行 reconcile。execution 经窄内部接口取得真实当天 cwd 和输出位置，默认每个 Job 独立目录；文件即时存在，collect 只读取输出。停止或取消不回滚已写文件，详见 [Execution 与 Job](execution.md)。

活动 Turn 从准备到全部收尾持有同一日 lease；跨午夜 Job 仍使用旧日根。下一根请求前，Archive 协调各 owner 归档 Session、Workspace 和 active Trash，再建立新日。Home overlay 与持久 Memory 不随 Workspace 归档。

WorkspaceSignal 携带 owner 资源快照，Workspace 段在正常边界整体替换投影，没有版本序号或第二份索引。Context 压力只收缩模型投影，不移动或删除文件。真实文件监控来源属于后续环境能力，现有同步接点不等于已部署 watcher。

## 失败与观察

链接不存在、范围无效、编辑歧义、覆盖冲突或模型输出无效属于可修正局部结果。根不可用、索引/Trash 损坏和持久提交失败停在 Workspace 边界，经所属 runtime_bridge 转换，不伪装成参数反馈。Runtime payload 只保留 module/kind、错误类型和已提交 Link 等有限事实，不包含原始异常、绝对路径、traceback 或正文。

短 owner 操作开始后必须 join，再传播取消；长模型/进程工作使用各自执行生命周期。已提交文件与后续索引失败、取消或观察失败分别表达。

Engine 在成功提交后发布 workspace.changed，包含 created/updated/removed/affected Links。Action、SDK、Endpoint、转换能力共用该入口。Observation 是旁路，sink 失败不改变资源事实；Context 更新由类型化 Signal 消费。

## 验证

owner 测试覆盖创建/覆盖、编辑全或无、目录移动/恢复冲突、标签保留、损坏存储、扫描覆盖、正则超时、分页和局部生成。跨模块测试验证 Endpoint 共用服务、Context 压力不删除文件、真实进程跨午夜取消后才归档，以及旧日服务失效。旧 CAS、mirror、压力删除和 Trash 恢复状态机不作为保留契约。
