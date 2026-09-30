# 代码块渲染器（Mermaid / TikZJax）

> 建立：2026-09-29。本文记录计划 §21.1 中 CodeBlockRegistry 两个复杂渲染器的技术验证结论与最小真实实现（F0 / W2）。组件位于 `src/components/markdown/blocks/`，是后续 CodeBlockRegistry（F6）直接复用的 renderer；本阶段不接线到 `Markdown.tsx`，不建设动态插件市场。

## 依赖与许可

| 渲染器 | 包 | 锁定版本 | 许可 | 选择理由 |
| --- | --- | --- | --- | --- |
| Mermaid | `mermaid` | 12.0.0 | MIT | 官方包，`initialize` + `render` API 输出 SVG；flowchart 语法由 Mermaid 自身承担，不引入平行引擎。 |
| TikZJax | `@drgrice1/tikzjax` | 1.0.0-beta24 | GPL-3.0+ | 上游 kisonecat/tikzjax 未发布 npm（`tikzjax` 占位包已于 2025-01 下架）；drgrice1 维护分支面向 npm 交付且运行时资源全部随包自带，是脱离 CDN 的现实路径。 |

版本锁定在 `pnpm-lock.yaml`；两包的许可随本文记录。TikZJax 为 GPL-3.0+，以独立运行时资源（独立文件、运行时按需加载）形式随应用分发。

## MermaidBlock

`src/components/markdown/blocks/MermaidBlock.tsx`。

- **按需加载**：`import("mermaid")` 动态导入，首次渲染时才加载；构建产物中 mermaid 核心与各图族是独立 async chunk，不进主 chunk。
- **官方 API**：`mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme })` + `mermaid.render(id, source)`；不使用已废弃的 `mermaid.init` 全局扫描。`initialize` 是全局配置，组件记录当前已初始化主题，主题切换时重新 initialize 后再 render。
- **触发时机**：默认 `IntersectionObserver` 进入视区才渲染（jsdom 无此 API 时立即渲染以便测试）；`eager` prop 跳过等待。空源码不触发加载。
- **缓存**：模块级 Map，key 为渲染器版本 + `theme + source`（升级 mermaid 包后旧条目自然失效），LRU 上限 50 条。
- **失败回退**：render 抛错时显示源码 + 有限错误（错误首行截断至 200 字符，不含原始异常对象）与"重试"入口；`finally` 清理 mermaid 渲染沙箱的临时 DOM 元素。
- **卸载**：组件卸载仅取消挂起的状态更新；mermaid render 本身不可中断。

## TikZBlock

`src/components/markdown/blocks/TikZBlock.tsx`。

### 隔离方案的验证结论：iframe 可行，shadow DOM 不可行

tikzjax 运行时（`tikzjax.js`）硬绑定其所在 `document`：`getElementsByTagName("script")` 扫描 `type="text/tikz"`、`MutationObserver` 挂在 `<body>` 上、用 `document.currentScript.src` 推导自身资源基准 URL。这三者都不会进入 shadow root，因此 shadow DOM 路径不可行。采用 **sandbox iframe（srcdoc）**：运行时与其全局扫描被限制在 iframe 文档内，不接触 React 主文档；编译在主文档外的独立 Worker（iframe 内 `run-tex.js`）中进行。

### 资源离线交付（无 CDN）

运行时所有资源以 `tikzjax.js` 自身 URL 为基准相对解析：`run-tex.js`（Worker）、`tex.wasm.gz`、`core.dump.gz`、`tex_files/*.gz`、`fonts.css` + `fonts/*.woff2`。因此 `vite.config.ts` 的 `tinysoul-tikzjax-assets` 插件以锁定的 npm 包为唯一来源：

- dev：`/@fs` 之外的中间件把包内 `dist/` 伺服在 `/tikzjax/*`；
- build：把 `dist/`（跳过 source map）拷贝进 `<outDir>/tikzjax/`，随应用分发（约 15 MB）。

组件用 `import.meta.env.BASE_URL + "tikzjax/"` 构造基准 URL，Browser 与 Tauri（`frontendDist: ../dist`）走同一份本地资源。

### 编译与结果提取

- srcdoc 内含 `fonts.css` link、一个 `type="text/tikz"` script（TeX 源码）和 `tikzjax.js` script。源码含 `</script` 序列会被拒绝（raw-text 元素无法表达），回退为源码 + 错误。
- 成功：运行时把 script 替换为 `svg[role=img]` 并派发 `tikzjax-load-finished`（在 svg 元素上、capture 可捕获）；组件取出 `outerHTML` 渲染进主文档，并向主文档 `<head>` 注入一次 `fonts.css`（SVG 文本使用 BaKoMa 字体，`@font-face` 必须属于渲染文档）。
- 失败：运行时静默把加载占位替换成 `img[src^="//invalid.site/"]`，**不派发错误事件**；组件用 iframe 文档上的 MutationObserver 识别该标记，另有 90 秒编译超时。失败显示源码 + 有限错误；TeX 详细日志留在 iframe 控制台（`data-show-console` 调试时可开）。
- 缓存：运行时自带 IndexedDB 缓存（按 sourceHash），srcdoc iframe 与主文档同源，可用。
- 卸载：React 移除 iframe 即终止其 Worker 与观察器；组件同时清理自身定时器/observer。

## 共享结构

- `BlockFrame`：统一的语言标签头、图/源码切换、缩放控制（0.5×–3×，作用于图视图的 CSS zoom 包裹层）、"导出 SVG"（当前渲染结果经 objectURL 下载）、失败时的"错误 + 源码 + 重试"呈现与排队态（"排队等待编译…"）。
- `useInViewport`：视区触发 hook，两个渲染器共用。
- `tikzSlots`：TikZ 编译槽位（上限 2 并发）：可见块进入视区后先取槽再挂载 iframe，槽满排队（取消的等待者被跳过、让位给后续块）；编译收敛（成功/失败/超时）或块卸载即释放槽位，iframe 随之卸载以终止其 Worker。
- `cb-*` className 当前只有 dev 验证页的临时样式；正式视觉归 F6。

## 验证入口与证据

- dev-only 页面：`codeblocks-dev.html`（vite 根级 HTML，仅 dev server 提供，不进 `pnpm build` 产物）+ `src/dev/codeblocks-dev.tsx`，渲染 Mermaid/TikZ 的正常与错误各一例。
- 真实浏览器验证：`test/e2e/playwright.config.ts` + `test/e2e/codeblocks.pw.ts`（`.pw.ts` 后缀避开 vitest 默认 include），命令：

  ```
  pnpm exec playwright test -c test/e2e/playwright.config.ts
  ```

  断言：两渲染器真实产出 SVG、失败块保留源码与错误、无 pageerror、无失败请求，且全部请求（含 tikzjax.js / run-tex.js / tex.wasm.gz / core.dump.gz / fonts.css）均为本地 origin，无任何外部/CDN 请求。
  结果（2026-09-29，chromium 1234 / Windows）：**1 passed**；4 个用例块（Mermaid 正常/错误、TikZ 正常/错误）均符合预期；共 61 个请求全部同源，其中 15 个 tikzjax 资产；控制台无 error 级条目。注意 webServer 需 `--host 127.0.0.1`（本机 vite 默认只绑 IPv6 `::1`）且 `cwd` 必须指向 visualization 根（Playwright 默认以 config 所在目录为 cwd，否则 404）。
- 单元测试：`test/blocks/codeblocks.test.tsx`（BlockFrame 切换与失败回退、srcdoc 构造与注入防护、iframe 懒创建、空源码不加载）；`pnpm test` 共 191 用例通过（184 既有 + 7 新增）。
- bundle 证据：主应用 chunk 不含 mermaid 引用（`dist/assets/index-*.js` 1,054 kB，与接入前一致）；按需分包证据可复现：`pnpm exec vite build --config test/e2e/vite.bundle-evidence.config.ts`（只构建 dev 入口到 `.local-test/codeblocks-dist`），入口 chunk 约 200 kB，`mermaid.core` 669 kB 及各图族为独立 async chunk，`tikzjax/` 目录（约 14 MB，跳过 source map）随产物交付。
- Tauri（2026-09-29，cargo 1.97.1）：`pnpm tauri build` 成功（EXIT=0），产出 MSI（13.5 MB）与 NSIS（12.5 MB）安装包；`tauri.conf.json` 的 `frontendDist: ../dist` 含全部渲染资源，构建产物自包含、无运行时 CDN 依赖。**未覆盖**：webview 内实际打开页面的交互式渲染验证（需要 WebView2 驱动或人工确认）；iframe srcdoc + 同源 Worker 路径在 Chromium 系 webview 中与已验证的浏览器路径一致，风险低但未实测。

## 已知限制与未覆盖项

- 每个编译中的 TikZBlock 占一个 iframe + Worker，首次需加载 tex.wasm.gz + core.dump.gz（约 2 MB）；并发上限 2（`tikzSlots`）限制同时存活的实例数，其余可见块排队等待，未实现跨块共享运行时（编译已在 Worker，但多实例内存各自一份）。
- TikZ 编译失败的详情只有 iframe 内的 TeX 日志，组件层只呈现有限错误 + 用户触发的重试；向用户暴露日志需要运行时支持，本轮不扩展。
- Mermaid `initialize` 是全局配置：主题不同的块并发渲染时以最后一次 initialize 为准（渲染调用顺序执行，实际无交错，但这是一个全局性约束）。
- 流式未闭合 fence 的识别与 ReactMarkdown 的 registry 接线已在 F3-A 完成；缩放/导出/重试与 TikZ 并发上限已在 F6-A 完成。Mermaid 失败块的重试为整图重渲染；导出文件名固定为 `diagram.svg`（同源多图各自下载，不带块标识）。
- Tauri：`pnpm tauri build` 已通过（桌面安装器含全部自包含资源），但 webview 内真实渲染未做交互式验证（见上节）。
