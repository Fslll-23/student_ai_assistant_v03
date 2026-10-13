# V0.4 原服务发布准备（未推送、未部署）

目标：更新 `Fslll-23/student_ai_assistant_v03` 的 `main` 到原服务，保留原公开网址 `https://student-ai-assistant-v03.onrender.com`。不创建新项目或新 Render 服务。

## 已核实与待核实

- 远端 main：`95fb063`；本地基线：`7e4a30d`。远端两个新增提交最终只给 requirements.txt 增加了 gunicorn。本地已保留这项依赖并固定为 26.2.0，没有覆盖远端或改写历史。
- 原网址 HTTP 200。用户已确认原服务名称 `student_ai_assistant_v03`、仓库与分支 `main`、线上版本 `95fb063`，且用户最新确认 Auto-Deploy 已关闭。控制台的实际构建命令、启动命令、Python 版本和变量名称仍待核对。
- 本地 V0.4 模板、聊天、解析和图片资产齐全，但部分仍未纳入 Git；发布时必须明确包含这些文件。
- 当前未修改任何 Render 设置、.env、AI Key 或模型配置。

## 建议原服务设置（待确认后执行）

- Repository：上述原仓库；Branch：main；Root Directory：仓库根目录。
- Build：`pip install -r requirements.txt`
- Start：`python serve.py`
- Health Check：`/healthz`
- 单实例。入口明确设置一个 Gunicorn worker、4 个线程、120 秒超时、关闭 preload，避免 Render 默认 preload 影响后台上下文清理线程，以及多 worker 导致附件上下文不一致。
- Python：本地测试使用 3.14；先核实现有 Render Python 版本并在同版本复测，不盲目升级运行时。
- 保留已有 `AI_BASE_URL`、`AI_API_KEY`、`AI_MODEL`，只核实变量名称存在，不读取值。
- 在 Render 另行添加 `BAOBAO_TEST_PASSWORD`：至少 16 字符的随机测试口令，不能使用 AI Key。用户名固定 `guest`。由用户在控制台设置，不写进仓库或聊天。
- Render 自动提供 `RENDER=true`，应用即强制启用公开保护。缺少合格口令返回 503，防止未配置即开放。其他平台需 `BAOBAO_PUBLIC_TEST=1`。
- `PORT` 由平台提供。只在 Render 受信入口使用转发协议头；不要直接公开后端监听端口。代理协议、Origin 和 Secure Cookie 已通过本地生产入口验证，还需真实 Render 验收。

## 已实现的公开体验保护

- HTTPS + 浏览器原生 Basic Auth，保护首页、静态资源和所有 AI/聊天入口，只有健康检查公开。无需重新设计首页。口令变更后浏览器会重新要求认证；共用设备应清除站点记录并关闭浏览器，Basic Auth 没有应用内注销按钮。
- 未认证尝试全站每分钟最多 30 次；已认证分析每浏览器每分钟 6 次、每天 30 次；全站每天 100 次；最多 2 个同时处理的分析请求。被拒绝的请求不会进入 AI 调用。
- 日界线为 UTC；无效文件等已接纳的分析尝试也计次数，避免免费解析滥用。清除 Cookie 可重置访客限额，但不能绕过全站限额。共享口令不是个人账号，第一阶段只适合可信朋友。
- SQLite 仅存身份哈希、计数和过期时间，不存 IP、口令、聊天或文件内容。默认 `/tmp/baobao-beta/quotas.sqlite3`，worker 重启仍保留；Render 临时文件系统重建后会重置。因此必须另外确认 AI 服务商的消费额度/预算，次数上限不是金额硬上限。
- 保留文件/截图各 8 MB、请求总计 18 MB、解析页数/解压/超时限制。公开模式再限制总表单文字 180,000 字符和单条问题 20,000 字符。
- 没有改变模型或输出参数；长初稿与最近问答仍按既有限制传递。全站用量超过上限后暂停分析，不自动付费扩容。
- Cookie/对话双重绑定附件；浏览器 IndexedDB 分区保留各自记录。共享同一浏览器配置的不同人不具备账号级隔离，交接前须清除记录或使用不同配置。
- 原始附件不永久保存；服务内存中的文件文字/截图最多 8 小时，重启、休眠、容量淘汰时需要重新上传。上线后这里的“服务内存”位于 Render，并且分析内容会发送到现有 AI 服务。

## 发布步骤（尚未授权执行）

1. 原服务和自动部署已由用户确认；发布前继续核实实际启动命令、Python 版本及访问口令是否已配置。
2. 检查候选文件与 Git 历史中的敏感内容，不使用 `git add .`；不包含 `.env`、上传文件、聊天、临时数据库、日志、虚拟环境或 preview.py 模拟入口。
3. 在本地保留远端 main 历史，使用受控分支整合 V0.4；远端仅增加的 Gunicorn 已在工作区保留。再次 fetch 后检查无新远端修改，禁止 force push。
4. 验证目标 Python/Linux 环境及依赖，运行全部回归、生产启动测试。确认朋友人数、次数额度与独立测试口令由用户设置。
5. 用户明确批准后才推送/修改 Render 配置并发布。Auto-Deploy 目前已关闭；推送与手动发布均需用户明确批准，操作前再次确认开关。
6. 公网验收：未认证拒绝、手机上传、真实 AI 完整协作、两个独立浏览器附件隔离、刷新/删除、限流、HTTPS Cookie、重启后到期提示。此前真实 AI 协作已测试；本轮保护测试不调用付费 AI。
7. 保留当前部署的 commit/release 标识用于回退。任何回退到旧 V0.3 可能同时移除新访问保护，须先限制访问，不能盲目回退。

## 本轮验证

`python -B -m unittest discover -s tests -q`；`node tests/test_chat_store.cjs`。
生产冒烟使用无凭据隔离应用：实际 Gunicorn 启动、健康检查、HTTPS要求、Basic Auth、首页、同源检查、Secure/HttpOnly/SameSite Cookie、单 worker/禁用 preload。未读取或传出 API Key。

仍待：Render 控制台核实、目标运行时复测、服务商预算设置、真实公网与实体手机验收。现阶段属于本地准备完成，不代表正式环境已验证可发布。


## 本次发布前复核

重新 fetch 后远端仍为 `95fb063`，相对本地基线仍只有 Gunicorn 依赖修复；此条为提交前检查记录；随后仅在本地提交并保留远端历史，不推送或部署。37 项 Python 测试、聊天存储测试、Gunicorn 隔离生产启动测试全部通过；pip check 无依赖冲突，git diff --check 无格式问题。所需模块及 12 个图片资源存在，候选文件中未发现上传文档、聊天数据库或日志，.env 未跟踪且已忽略。常见凭据模式扫描未发现命中，但不能替代发布时逐项审核。

本轮不重复修改业务代码。本地正式提交明确纳入应用模块、templates、static、tests、requirements、部署说明和忽略规则，排除模拟预览入口及任何临时数据。实际发布必须保留 origin/main 的提交历史，不强推。

阻断条件：Render 未设置 BAOBAO_TEST_PASSWORD 时新版本会返回 503；若仍用旧启动命令，无法保证本轮验证的单 worker、线程和 preload 设置生效。必须在批准发布时同步确认启动命令为 python serve.py、口令及预算就绪，避免手动发布后无法体验。
