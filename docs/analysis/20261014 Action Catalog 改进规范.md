# Action Catalog 语义改进规范

**创建时间**: 2026-10-14  
**状态**: dropped（批量应用方案已停用，保留原始候选文案供参考）

**更新时间**: 2026-10-18

**原目的**: 为非 core actions 定义 semantic 候选内容

后续直接维护 Catalog，已删除批量覆盖脚本。当前范围与进度以《20261014 模型可见内容完整改进计划》和《20261014 实施清单》为准；下文保留设计时的内容与标记，不作为当前实施状态或覆盖现有文案的依据。

---

## 改进原则

对每个 action 的 [semantic] 块：
1. **use_when**: 3-5条具体场景，说明何时使用
2. **avoid_when**: 2-4条具体场景，说明何时避免，并指出替代方案
3. **effects**: 保持现有值（read_only 或 modifying）
4. **examples**: 2-4个具体、实用的例子

---

## 已完成 Actions（17个）

### Core Domain (已完成)
- [x] core/domain.toml
- [x] core/actions/answer.toml
- [x] core/actions/ask.toml
- [x] core/actions/reason.toml
- [x] core/actions/context_inspect.toml
- [x] core/actions/context_search.toml
- [x] core/actions/session_organize.toml
- [x] core/actions/wait.toml
- [x] core/actions/job_status.toml
- [x] core/actions/job_stop.toml

### 其他 Domains (已完成)
- [x] workspace/domain.toml
- [x] memory/domain.toml
- [x] home/domain.toml
- [x] execution/domain.toml
- [x] web/domain.toml
- [x] subagent/domain.toml
- [x] expand/domain.toml

---

## 待改进 Actions 详细规范（53个）

### Workspace Actions (18个)

#### 1. workspace.inspect
**当前理解**: 读取已知 Workspace 引用，支持行范围、标题片段、目录列表、非文本元数据

**改进内容**:
```toml
[semantic]
use_when = [
    "Read a known Workspace reference returned by search or another action",
    "Follow a workspace: reference with optional line range or heading",
    "Continue a previous text or directory page with continuation",
    "List direct children of a known directory"
]
avoid_when = [
    "Discovering unknown resources; use workspace.search",
    "Modifying resource content; use write/edit/append",
    "Need deeper analysis; consider workspace.analyze"
]
effects = ["read_only"]
examples = [
    "Inspect workspace:notes/plan.md to read the file",
    "Inspect workspace:notes/plan.md#L10-L50 to read specific lines",
    "Inspect workspace:src to list direct children of the directory",
    "Continue reading with the returned continuation token"
]
```

#### 2. workspace.search
**当前理解**: 发现资源，支持文本/正则查询、目录发现、反向链接、语义选择

**改进内容**:
```toml
[semantic]
use_when = [
    "Discover resources by content pattern (literal text or regex)",
    "Find incoming Markdown references to a resource (backlinks)",
    "Explore directory structure with semantic discovery",
    "Locate resources before deeper reading or mutation"
]
avoid_when = [
    "The exact reference is already known; use workspace.inspect",
    "Need to change resource content; search then mutate",
    "Pattern is too broad; narrow the scope first"
]
effects = ["read_only"]
examples = [
    "Search workspace for 'TODO' items",
    "Find backlinks to workspace:docs/api.md",
    "Discover Python files about 'authentication' in workspace:src",
    "List all Markdown files in workspace"
]
```

#### 3. workspace.read
**当前理解**: 读取指定行范围（旧接口，inspect 也支持）

**改进内容**:
```toml
[semantic]
use_when = [
    "Read specific line ranges from a known text file",
    "Legacy line-range reading (workspace.inspect also supports line ranges)"
]
avoid_when = [
    "File is not text or line range is not applicable",
    "Could use workspace.inspect with #L10-L20 syntax instead"
]
effects = ["read_only"]
examples = [
    "Read workspace:src/main.py lines 10-50"
]
```

#### 4. workspace.write
**当前理解**: 创建新文件或完全覆盖

**改进内容**:
```toml
[semantic]
use_when = [
    "Create a new file with complete UTF-8 content",
    "Overwrite an existing file completely (with overwrite=true)",
    "Write generated or composed content to workspace"
]
avoid_when = [
    "File already exists and should be preserved; use workspace.edit",
    "Only appending content; use workspace.append",
    "Content needs LLM generation; use workspace.compose"
]
effects = ["modifying"]
examples = [
    "Write complete content to workspace:output/result.md",
    "Overwrite workspace:config.json with new configuration (overwrite=true)"
]
```

#### 5. workspace.edit
**当前理解**: 精确字符串替换，原子操作

**改进内容**:
```toml
[semantic]
use_when = [
    "Apply precise text replacements to an existing file",
    "Multiple exact string replacements in one atomic operation",
    "Preserve most of the file while changing specific parts"
]
avoid_when = [
    "Creating a new file; use workspace.write",
    "Old_text doesn't occur exactly once in the file",
    "Need to generate new content; consider workspace.compose"
]
effects = ["modifying"]
examples = [
    "Replace 'old_function_name' with 'new_function_name' in workspace:src/main.py",
    "Apply multiple edits atomically to workspace:config.yaml"
]
```

#### 6. workspace.append
**当前理解**: 追加内容到文件末尾

**改进内容**:
```toml
[semantic]
use_when = [
    "Add content to the end of an existing file",
    "Incrementally build a file across multiple Cycles"
]
avoid_when = [
    "File doesn't exist yet; use workspace.write to create it",
    "Need to insert or replace content; use workspace.edit",
    "Generating complete new content; use workspace.compose"
]
effects = ["modifying"]
examples = [
    "Append new section to workspace:notes/log.md",
    "Add test case to existing test file"
]
```

#### 7. workspace.compose
**当前理解**: LLM 生成完整文本

**改进内容**:
```toml
[semantic]
use_when = [
    "Generate complete UTF-8 artifact using LLM with task-local resources",
    "Create or overwrite file based on instruction and references",
    "Need LLM to compose content from multiple sources"
]
avoid_when = [
    "Content is already known; use workspace.write directly",
    "Only editing existing content; use workspace.edit",
    "Simple text manipulation; don't need LLM"
]
effects = ["modifying"]
examples = [
    "Compose workspace:summary.md from multiple docs with instruction 'Create executive summary'",
    "Generate report from analysis results"
]
```

#### 8. workspace.analyze
**当前理解**: LLM 分析指定引用并回答有界问题

**改进内容**:
```toml
[semantic]
use_when = [
    "Need LLM to analyze specific workspace references and answer a bounded question",
    "Synthesize information from multiple workspace files",
    "Extract structured information from workspace content"
]
avoid_when = [
    "References are not known; use workspace.search first",
    "Only need to read content; use workspace.inspect",
    "Analysis would exceed reference budget; narrow scope or use search"
]
effects = ["read_only"]
examples = [
    "Analyze test and source files with intent 'What test cases are missing?'",
    "Extract API endpoints from workspace:src/routes.py"
]
```

#### 9. workspace.describe
**当前理解**: 为资源生成简洁描述

**改进内容**:
```toml
[semantic]
use_when = [
    "Generate a concise description for a resource using LLM",
    "Update resource metadata with human-readable summary"
]
avoid_when = [
    "Description is already clear from filename and context",
    "Resource is too large; description would be generic"
]
effects = ["modifying"]
examples = [
    "Describe workspace:output/analysis_20241014.json"
]
```

#### 10. workspace.delete
**当前理解**: 删除文件或空目录

**改进内容**:
```toml
[semantic]
use_when = [
    "Remove a file or empty directory from workspace",
    "Clean up temporary or obsolete resources"
]
avoid_when = [
    "Resource might be needed later; consider workspace.tag as tmp",
    "Should check trash first; deletion moves to trash for recovery"
]
effects = ["modifying"]
examples = [
    "Delete workspace:temp/build_output.txt",
    "Remove empty directory workspace:old_src"
]
```

#### 11. workspace.move
**当前理解**: 重命名或移动资源

**改进内容**:
```toml
[semantic]
use_when = [
    "Rename a file or directory",
    "Move a resource to a different directory path",
    "Reorganize workspace structure"
]
avoid_when = [
    "Target path already exists",
    "Need to change content; use edit/write instead"
]
effects = ["modifying"]
examples = [
    "Rename workspace:draft.md to workspace:final.md",
    "Move workspace:temp/file.txt to workspace:docs/file.txt"
]
```

#### 12. workspace.mkdir
**当前理解**: 创建目录

**改进内容**:
```toml
[semantic]
use_when = [
    "Create a new directory in workspace",
    "Ensure parent directories exist for future writes"
]
avoid_when = [
    "Directory already exists",
    "Could let write operations create parent directories implicitly"
]
effects = ["modifying"]
examples = [
    "Create workspace:output/reports directory"
]
```

#### 13. workspace.tag
**当前理解**: 标记资源（pinned, tmp, library）

**改进内容**:
```toml
[semantic]
use_when = [
    "Mark resource with metadata tags (pinned, tmp, library)",
    "Organize resources by lifecycle or importance"
]
avoid_when = [
    "Resource doesn't exist yet"
]
effects = ["modifying"]
examples = [
    "Tag workspace:important.md as pinned",
    "Tag workspace:temp_output.txt as tmp"
]
```

#### 14. workspace.list
**当前理解**: 列出当前 workspace 资源概览

**改进内容**:
```toml
[semantic]
use_when = [
    "Get overview of current workspace resources",
    "Check workspace state before operations"
]
avoid_when = [
    "Need detailed content; use workspace.inspect on specific refs",
    "Searching for specific pattern; use workspace.search"
]
effects = ["read_only"]
examples = [
    "List all current workspace resources"
]
```

#### 15. workspace.trash_list
**当前理解**: 列出回收站内容

**改进内容**:
```toml
[semantic]
use_when = [
    "Check what resources are in trash",
    "Find deleted resource to restore"
]
avoid_when = [
    "Nothing has been deleted yet"
]
effects = ["read_only"]
examples = [
    "List trashed resources to find deleted file"
]
```

#### 16. workspace.restore
**当前理解**: 从回收站恢复

**改进内容**:
```toml
[semantic]
use_when = [
    "Recover a deleted resource from trash",
    "Undo accidental deletion"
]
avoid_when = [
    "Resource is not in trash; check workspace.trash_list first",
    "Would overwrite existing resource at target path"
]
effects = ["modifying"]
examples = [
    "Restore trash:workspace/abc123"
]
```

#### 17. workspace.convert_with_markitdown
**当前理解**: 用 markitdown 转换文档

**改进内容**:
```toml
[semantic]
use_when = [
    "Convert Office documents, PDFs, or other formats to Markdown using markitdown",
    "Need readable text from binary workspace resources"
]
avoid_when = [
    "File is already text",
    "Conversion quality matters; try workspace.convert_with_pypdf for PDFs"
]
effects = ["modifying"]
examples = [
    "Convert workspace:document.docx to markdown"
]
```

#### 18. workspace.convert_with_pypdf
**当前理解**: 用 pypdf 转换 PDF

**改进内容**:
```toml
[semantic]
use_when = [
    "Convert PDF to text using pypdf extractor",
    "Higher quality PDF text extraction needed"
]
avoid_when = [
    "File is not PDF",
    "Quick conversion is sufficient; try markitdown"
]
effects = ["modifying"]
examples = [
    "Convert workspace:paper.pdf to text with pypdf"
]
```

### Memory Actions (5个)

#### 19. memory.search
**当前理解**: 搜索持久 Memory 文档

**改进内容**:
```toml
[semantic]
use_when = [
    "Need to discover persistent Memory documents (daily/entity/concept/fact/note)",
    "Search for patterns across Memory knowledge base",
    "Find backlinks or related Memory documents"
]
avoid_when = [
    "Exact memory:entity/name reference is already known; use memory.inspect",
    "Current Memory.md is sufficient; memory.search is for persistent docs",
    "Should search workspace or session instead"
]
effects = ["read_only"]
examples = [
    "Search Memory for entity 'TinySoul'",
    "Find Memory documents referencing memory:concept/context-model",
    "Discover facts about 'agent architecture'"
]
```

#### 20. memory.inspect
**当前理解**: 读取已知 Memory 文档

**改进内容**:
```toml
[semantic]
use_when = [
    "Read content of a known Memory document",
    "Inspect memory:daily/YYYY-MM-DD, memory:entity/name, etc.",
    "Follow memory: references found in search or context"
]
avoid_when = [
    "Memory document is not known; use memory.search first",
    "Current Memory.md is sufficient (visible in Context)",
    "Should inspect workspace or home resources instead"
]
effects = ["read_only"]
examples = [
    "Inspect memory:entity/tinysoul",
    "Inspect memory:daily/2026-10-13",
    "Inspect memory:concept/agent-design"
]
```

#### 21. memory.memorize
**当前理解**: patch 当日 memory:current

**改进内容**:
```toml
[semantic]
use_when = [
    "A preference, decision, open thread, or useful Memory ref should persist across Turns today",
    "User explicitly asks to remember or forget something temporary",
    "Preserve canonical memory: refs that Context already shows for later recall"
]
avoid_when = [
    "Creating or changing persistent Memory documents (daily/entity/concept/fact/note); that's Memory Reflection only",
    "Information is already clear in current Memory.md",
    "Should record as milestone instead (task-specific, not cross-Turn)"
]
effects = ["modifying"]
examples = [
    "Append today's decision: 'Use FastAPI for new API' with reference memory:concept/api-design",
    "Remove completed reminder from current Memory",
    "Preserve useful memory:entity/project-x reference for later Turns"
]
```

#### 22. memory.write_daily
**当前理解**: Memory Reflection 写持久 daily

**改进内容**:
```toml
[semantic]
use_when = [
    "Memory Reflection: write or update a persistent daily document",
    "Consolidate today's Memory.md into persistent memory:daily/YYYY-MM-DD"
]
avoid_when = [
    "Not in Memory Reflection; ordinary Turns cannot write persistent Memory",
    "Should use memory.memorize for current Memory.md instead"
]
effects = ["modifying"]
examples = [
    "Write memory:daily/2026-10-14 from reviewed current Memory"
]
```

#### 23. memory.write
**当前理解**: Memory Reflection 写持久 entity/concept/fact/note

**改进内容**:
```toml
[semantic]
use_when = [
    "Memory Reflection: write or update persistent entity/concept/fact/note document",
    "Create new Memory knowledge or update existing with proper redirects"
]
avoid_when = [
    "Not in Memory Reflection; ordinary Turns cannot write persistent Memory",
    "Should update daily instead; entities/concepts are for durable knowledge"
]
effects = ["modifying"]
examples = [
    "Write memory:entity/tinysoul with project overview",
    "Update memory:concept/context-model with refined understanding",
    "Create memory:fact/f-abc with sourced fact"
]
```

### Home Actions (12个)

#### 24. home.search
**当前理解**: 搜索 Home 资源

**改进内容**:
```toml
[semantic]
use_when = [
    "Discover relevant Home agent or Skill resources",
    "Find Home knowledge not yet exposed in Context",
    "Search for topics across Home skills"
]
avoid_when = [
    "Exact home:top/path reference is already known; use home.inspect",
    "Should use load_background for top-level content instead",
    "Searching workspace or memory; use those domains"
]
effects = ["read_only"]
examples = [
    "Search Home for skills about 'context usage'",
    "Find Home resources referencing home:top/agent/identity/soul",
    "Discover agent guidance on 'working principles'"
]
```

#### 25. home.inspect
**当前理解**: 读取 Home 资源

**改进内容**:
```toml
[semantic]
use_when = [
    "Read a known Home resource progressively",
    "Inspect home:resource/path or home:top/path references",
    "Continue reading with continuation from previous inspect"
]
avoid_when = [
    "Top-level content should be loaded into Background; use load_background",
    "Home resource is not known; use home.search first",
    "Should inspect workspace or memory instead"
]
effects = ["read_only"]
examples = [
    "Inspect home:resource/skills/tinysoul-docs/references/guide.md",
    "Continue reading Home resource with continuation token"
]
```

#### 26. home.diff
**当前理解**: Home Reflection 查看待定更改

**改进内容**:
```toml
[semantic]
use_when = [
    "Home Reflection: inspect pending effective Home changes",
    "List Home Links or inspect baseline vs candidate details",
    "Prepare for home.review accept/reject decisions"
]
avoid_when = [
    "Not in Home Reflection; ordinary Turns don't use home.diff",
    "No pending Home changes exist yet"
]
effects = ["read_only"]
examples = [
    "List all Home Links with changes",
    "Inspect detailed diff for specific Home paths"
]
```

#### 27. home.review
**当前理解**: Home Reflection 接受/拒绝更改

**改进内容**:
```toml
[semantic]
use_when = [
    "Home Reflection: accept or reject pending Home changes",
    "Finalize reviewed Home Links to actual Home baseline"
]
avoid_when = [
    "Not in Home Reflection; ordinary Turns cannot review Home",
    "Haven't inspected changes with home.diff first"
]
effects = ["modifying"]
examples = [
    "Accept home:top/agent/identity/soul after review",
    "Reject problematic Home changes"
]
```

#### 28. home.top_write
**当前理解**: 写入顶层 Home 条目（运行时覆盖层）

**改进内容**:
```toml
[semantic]
use_when = [
    "Write or replace a top-level Home content entry in runtime overlay",
    "Create new agent identity, skill, or guidance in effective Home"
]
avoid_when = [
    "In Home Reflection; changes go through review, not direct write",
    "Should edit resources; top is for logical entries"
]
effects = ["modifying"]
examples = [
    "Write home:top/agent/custom-guidance with new guidance"
]
```

#### 29. home.top_patch
**当前理解**: patch 顶层条目

**改进内容**:
```toml
[semantic]
use_when = [
    "Apply precise edits to top-level Home content in runtime overlay",
    "Update existing Home top entry incrementally"
]
avoid_when = [
    "In Home Reflection; use review workflow",
    "Creating new content; use home.top_write"
]
effects = ["modifying"]
examples = [
    "Patch home:top/agent/identity/soul with refinements"
]
```

#### 30. home.top_delete
**当前理解**: 删除顶层条目

**改进内容**:
```toml
[semantic]
use_when = [
    "Remove a top-level Home entry from runtime overlay",
    "Clean up temporary or obsolete Home content"
]
avoid_when = [
    "In Home Reflection; use review workflow",
    "Deleting from actual Home; ordinary Turns only affect overlay"
]
effects = ["modifying"]
examples = [
    "Delete obsolete home:top/agent/temp-guidance"
]
```

#### 31. home.resource_write
**当前理解**: 写入 Home 资源文件

**改进内容**:
```toml
[semantic]
use_when = [
    "Write or replace a Home resource file in runtime overlay",
    "Create new Skill resources or guidance files"
]
avoid_when = [
    "In Home Reflection; use review workflow",
    "Should write top-level entry; resource is for files"
]
effects = ["modifying"]
examples = [
    "Write home:resource/skills/custom-skill/guide.md"
]
```

#### 32. home.resource_patch
**当前理解**: patch 资源文件

**改进内容**:
```toml
[semantic]
use_when = [
    "Apply precise edits to Home resource file in runtime overlay",
    "Update existing Skill or guidance file incrementally"
]
avoid_when = [
    "In Home Reflection; use review workflow",
    "Creating new file; use home.resource_write"
]
effects = ["modifying"]
examples = [
    "Patch home:resource/skills/tinysoul-docs/guide.md"
]
```

#### 33. home.resource_delete
**当前理解**: 删除资源文件

**改进内容**:
```toml
[semantic]
use_when = [
    "Remove a Home resource file from runtime overlay",
    "Clean up temporary or obsolete Skill files"
]
avoid_when = [
    "In Home Reflection; use review workflow",
    "Deleting from actual Home; ordinary Turns affect overlay only"
]
effects = ["modifying"]
examples = [
    "Delete obsolete home:resource/skills/old-skill/guide.md"
]
```

#### 34. home.prompt_mount_write
**当前理解**: 写入任务局部 Skill mount

**改进内容**:
```toml
[semantic]
use_when = [
    "Write domain or action-specific Skill mount in runtime overlay",
    "Create task-local guidance for specific actions"
]
avoid_when = [
    "General Home content; use top_write or resource_write",
    "In Home Reflection; use review workflow"
]
effects = ["modifying"]
examples = [
    "Write home:mount/action/workspace/analyze with analysis guidance"
]
```

#### 35. home.prompt_mount_patch
**当前理解**: patch 任务局部 mount

**改进内容**:
```toml
[semantic]
use_when = [
    "Update domain or action Skill mount incrementally",
    "Refine task-local guidance"
]
avoid_when = [
    "Creating new mount; use home.prompt_mount_write",
    "In Home Reflection; use review workflow"
]
effects = ["modifying"]
examples = [
    "Patch home:mount/domain/workspace with refined guidance"
]
```

### Execution Actions (4个)

#### 36. execution.run
**当前理解**: 运行有界命令并等待结果

**改进内容**:
```toml
[semantic]
use_when = [
    "A bounded shell command or script should finish within the action timeout",
    "Deterministic local processing with known completion time",
    "Quick scripts that don't need Job supervision"
]
avoid_when = [
    "Command might take longer than action timeout; use execution.start",
    "Interactive input is needed during execution",
    "Process is already running as a Job"
]
effects = ["modifying"]
examples = [
    "Run ls command to list workspace files",
    "Execute python script with known quick completion",
    "Run bash command 'grep pattern file.txt'"
]
```

#### 37. execution.start
**当前理解**: 启动长期 Job

**改进内容**:
```toml
[semantic]
use_when = [
    "Long-running command or script needs Job supervision",
    "Process might need interaction via execution.stdin",
    "Want to continue with other work while process runs"
]
avoid_when = [
    "Command completes quickly; use execution.run instead",
    "Process is already started as a Job"
]
effects = ["modifying"]
examples = [
    "Start long build process: start interpreter=bash command='make build'",
    "Start interactive script that needs stdin later"
]
```

#### 38. execution.collect
**当前理解**: 读取 Job 输出

**改进内容**:
```toml
[semantic]
use_when = [
    "Read output from a running or completed Job",
    "Check progress of a started execution Job"
]
avoid_when = [
    "Job hasn't started yet",
    "Should use core.wait to pause until Job produces output"
]
effects = ["read_only"]
examples = [
    "Collect output from started build Job",
    "Read partial output from running script"
]
```

#### 39. execution.stdin
**当前理解**: 向交互 Job 发送输入

**改进内容**:
```toml
[semantic]
use_when = [
    "Send input to an interactive Job waiting for stdin",
    "Respond to Job prompt or provide data to running process"
]
avoid_when = [
    "Job is not interactive or not waiting for input",
    "Process hasn't been started yet"
]
effects = ["modifying"]
examples = [
    "Send 'yes' to confirmation prompt in running Job",
    "Provide input data to interactive script"
]
```

### Web Actions (4个)

#### 40. web.search_by_kimi
**当前理解**: 搜索公开 Web

**改进内容**:
```toml
[semantic]
use_when = [
    "Need current public information from the Web",
    "Discover Web sources for a topic or question",
    "Find recent news, documentation, or public resources"
]
avoid_when = [
    "Information is available in Context, Memory, or workspace",
    "URL is already known; use web.fetch directly",
    "Local or private information is needed"
]
effects = ["read_only"]
examples = [
    "Search Web for 'FastAPI best practices 2024'",
    "Find recent documentation on 'React Server Components'",
    "Discover sources about 'TinySoul architecture'"
]
```

#### 41. web.fetch_with_trafilatura
**当前理解**: 用 trafilatura 提取网页

**改进内容**:
```toml
[semantic]
use_when = [
    "Fetch a known Web page and extract main content to Workspace Markdown",
    "Create readable local copy of Web page for analysis",
    "Trafilatura extractor for general Web pages"
]
avoid_when = [
    "URL is not public or requires authentication",
    "Page is already in workspace",
    "Extraction quality matters; try defuddle if trafilatura fails"
]
effects = ["modifying"]
examples = [
    "Fetch https://example.com/article to workspace using trafilatura"
]
```

#### 42. web.fetch_with_defuddle
**当前理解**: 用 defuddle 提取网页

**改进内容**:
```toml
[semantic]
use_when = [
    "Fetch Web page with defuddle extractor",
    "Alternative extraction when trafilatura quality is insufficient"
]
avoid_when = [
    "URL is not public",
    "Page is already in workspace",
    "Trafilatura works well; defuddle is alternative"
]
effects = ["modifying"]
examples = [
    "Fetch https://example.com/doc to workspace using defuddle"
]
```

#### 43. web.discover_pages
**当前理解**: 发现多个相关网页

**改进内容**:
```toml
[semantic]
use_when = [
    "Discover multiple related pages from a Web domain",
    "Explore sitemap or linked pages",
    "Batch discovery before fetching"
]
avoid_when = [
    "Single URL is sufficient",
    "URLs are already known"
]
effects = ["read_only"]
examples = [
    "Discover pages from https://example.com/docs/"
]
```

### Subagent Actions (6个)

#### 44. subagent.agents
**当前理解**: 列出可用 ACP Agents

**改进内容**:
```toml
[semantic]
use_when = [
    "List configured external ACP Agents",
    "Check available Agents before delegating"
]
avoid_when = [
    "No external Agents configured"
]
effects = ["read_only"]
examples = [
    "List available ACP Agents"
]
```

#### 45. subagent.connect
**当前理解**: 建立连接

**改进内容**:
```toml
[semantic]
use_when = [
    "Establish connection to a configured external ACP Agent",
    "Prepare Agent for delegation"
]
avoid_when = [
    "Agent is already connected",
    "Agent is not configured"
]
effects = ["modifying"]
examples = [
    "Connect to ACP Agent 'research-agent'"
]
```

#### 46. subagent.delegate
**当前理解**: 委派工作

**改进内容**:
```toml
[semantic]
use_when = [
    "Delegate bounded work to connected external ACP Agent",
    "Send task prompt to subagent for execution"
]
avoid_when = [
    "Agent is not connected; use subagent.connect first",
    "Work can be done locally with available actions"
]
effects = ["modifying"]
examples = [
    "Delegate 'Research FastAPI authentication patterns' to research-agent"
]
```

#### 47. subagent.respond
**当前理解**: 响应 subagent 请求

**改进内容**:
```toml
[semantic]
use_when = [
    "Respond to subagent's request for information or decision",
    "Provide input to blocked subagent"
]
avoid_when = [
    "Subagent hasn't requested input",
    "Should wait for subagent to complete instead"
]
effects = ["modifying"]
examples = [
    "Respond to subagent's question about API design choice"
]
```

#### 48. subagent.collect
**当前理解**: 收集结果

**改进内容**:
```toml
[semantic]
use_when = [
    "Collect completed result from subagent Job",
    "Check subagent progress or partial results"
]
avoid_when = [
    "Subagent hasn't completed or hasn't been delegated work",
    "Should use core.wait to pause until subagent completes"
]
effects = ["read_only"]
examples = [
    "Collect research results from research-agent Job"
]
```

#### 49. subagent.disconnect
**当前理解**: 断开连接

**改进内容**:
```toml
[semantic]
use_when = [
    "Close connection to external ACP Agent after work is done",
    "Clean up idle subagent connection"
]
avoid_when = [
    "Still need the Agent for more work",
    "Agent is not connected"
]
effects = ["modifying"]
examples = [
    "Disconnect from research-agent after collecting all results"
]
```

### Expand Actions (4个)

#### 50. expand.describe_servers
**当前理解**: 列出 MCP servers

**改进内容**:
```toml
[semantic]
use_when = [
    "List all configured MCP servers",
    "Check available MCP capabilities"
]
avoid_when = [
    "No MCP servers configured",
    "Already know which tools are needed"
]
effects = ["read_only"]
examples = [
    "List all configured MCP servers and their status"
]
```

#### 51. expand.describe_tools
**当前理解**: 列出所有 MCP tools

**改进内容**:
```toml
[semantic]
use_when = [
    "List all MCP tools from all servers",
    "Get detailed tool schemas and descriptions"
]
avoid_when = [
    "Need to filter tools semantically; use expand.search",
    "No MCP servers configured"
]
effects = ["read_only"]
examples = [
    "List all available MCP tools across servers"
]
```

#### 52. expand.search
**当前理解**: 语义搜索 MCP tools

**改进内容**:
```toml
[semantic]
use_when = [
    "Search for relevant MCP tools by natural language query",
    "Discover MCP tools for specific task without knowing exact names",
    "Filter large MCP tool catalog semantically"
]
avoid_when = [
    "Exact tool name is known; use expand.call directly",
    "Few tools available; expand.describe_tools is sufficient",
    "No MCP servers configured"
]
effects = ["read_only"]
examples = [
    "Search MCP tools for 'database query' functionality",
    "Find MCP tools related to 'file system operations'"
]
```

#### 53. expand.call
**当前理解**: 调用 MCP tool

**改进内容**:
```toml
[semantic]
use_when = [
    "Call a known MCP tool with bounded parameters",
    "Execute MCP tool capability after discovery"
]
avoid_when = [
    "Tool name is not known; use expand.search first",
    "Native actions can accomplish the same goal",
    "MCP server is not available"
]
effects = ["modifying"]
examples = [
    "Call MCP tool 'filesystem_read' with path parameter",
    "Execute MCP database query tool"
]
```

---

## 总结

- **待改进数量**: 53 个 actions
- **每个改进**: use_when (3-5条) + avoid_when (2-4条) + examples (2-4个)
- **改进原则**: 具体、实用、引导性强，避免模糊表述
- **验证方式**: 改进后逐一检查 TOML 语法正确性、语义清晰性
