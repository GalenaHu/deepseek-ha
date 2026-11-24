# v0.1.2 验证结果

验证日期：2026-11-24（Asia/Shanghai）。本次验证在隔离工作区进行，没有修改现有 HA，没有使用真实 DeepSeek API Key，也没有连接家庭设备。后续用户已授权将源码推送至个人账号 GalenaHu 的 GitHub 仓库；不创建 Release。最初为私有，核对本次修复时已为公开；本次未更改仓库可见性。

## 环境与结果

- Python **3.14.7**，真实 `homeassistant==2026.11.2`。
- 官方 `pytest-homeassistant==2026.11.2`；不使用锁定旧版 HA 的旧测试插件。
- 完整测试：**97 passed，0 failed，0 skipped**，7.80 秒。
- Ruff 代码检查与格式检查通过。
- Mypy：**20个集成源文件无类型错误**，包含真实 HA 公共钩子签名检查。
- `pip check`：无损坏依赖。
- 官方 HA **2026.11.2** hassfest 源码六项检查通过：`manifest,json,config_schema,integration_type,translations,config_flow`；**Invalid integrations: 0**。不是全部 Core 仓库检查。
- ZIP 内容、SHA-256与重复构建一致性测试通过；交付校验值见 `dist/SHA256SUMS`。

逐项机器可读记录见 [TEST_RESULTS.json](TEST_RESULTS.json)。

推送前复查的两项问题与修复证据见 [REVIEW.md](REVIEW.md)；检查了81个历史文件对象与50个当前跟踪文件，未命中所检查的 GitHub/API/私钥/AWS凭据模式。此模式扫描不等同完整安全审计。

完整测试出现5条上游弃用警告，来自 HA HTTP 应用继承及 backoff 对 `asyncio.iscoroutinefunction` 的使用。没有通过跳过测试或 HA 替代桩规避这些警告。

## 验证范围

| 范围 | 验证方式 |
|---|---|
| 凭据与多个功能子项、重认证/重新配置/重载/卸载 | 真实 HA config entry / subentry flow、实体与服务注册 |
| 原生 AI Task 严格结构化任务 | 真实 `ai_task.generate_data`，完整 Schema与本地 selector 双重验证 |
| 错误 JSON、重复键、NaN/Infinity/溢出、缺字段、错误类型、拒答、截断 | 模拟 Responses SSE与结构化结果验证 |
| 多轮、工具调用、失败恢复 | 原生 ChatLog / APIInstance，工具已执行后的503不自动重放 |
| 暴露实体与管理员权限 | HA 原生 intent 匹配、暴露设置、真实用户/组权限；普通用户、降权管理员与无身份卫星被拒绝 |
| 已有工具 API 接入 | 通过真实 HA LLM API 注册的模拟 MCP API验证透传、并行调用及取消；不连接真实 MCP 服务器 |
| 联网与控制互斥 | 配置和持久配置校验；联网代理只提供官方搜索/读取工具 |
| 实验性评估 | 原生 `ai_task.evaluate` 三类型，显式确认、概率范围/归一化/一致性，默认偏好不变 |
| 图片、文档与 Schema组合 | 真实 AITaskEntity、附件对象与模拟 `/files` 上传；按类型选择官方解析 purpose |
| 摄像头快照 | 真实 camera 组件与 HA media-source 解析，测试摄像头返回本地生成 PNG |
| 文件生命周期 | 真实 HA Store，已知ID清理、失败保留、重启后丢失上传响应的所有权恢复、文件分页、不删除其他文件 |
| STT | 原生 STT 实体；PCM WAV 封装及有效 Ogg Opus静音；体积/时长/格式拒绝与请求超时 |
| TTS | 原生完整文本和流式实体入口；本机 aiohttp WebSocket模拟 Stella/Tide、二进制PCM、结束、失败、取消、消费者关闭、恶意源与发送失败 |
| 取消和卸载 | 真实异步任务，活跃 SSE 卸载、总时限到期、并行工具取消和完整结果配对 |
| 隐私与运维 | 诊断和 DEBUG 日志不包含测试 Key、提示/输出标记；真实统计恢复与原生按钮重置 |
| 中英文与安装包 | 翻译键一致、官方元数据检查、手动/HACS ZIP布局、许可证、缓存/环境排除、确定性打包 |

HTTP与SSE使用 `httpx2.MockTransport`；WebSocket在 `127.0.0.1` 启动真实模拟服务，通过只存在于测试中的适配器保留逻辑官方源。生产代码固定官方端点，无法配置为本机模拟地址。

## 复现命令

```sh
.venv/bin/python -m pytest -q --junitxml=/tmp/deepseek-ha-test-results.xml
.venv/bin/python -m ruff check custom_components tests scripts
.venv/bin/python -m ruff format --check custom_components tests scripts
.venv/bin/python -m mypy custom_components/deepseek_ai
.venv/bin/python -m pip check
.venv/bin/python scripts/check_metadata.py --ha-source /path/to/core-2026.11.2
.venv/bin/python scripts/package.py
```

官方源码精确提交：`ff5d56b825a0fb66b03d01bc297d49e206cdaba3`。如使用稀疏检出，包含 `script/hassfest`、`packages/hassfest` 即可；脚本从已安装的真实 HA 包获取平台与集成元数据。

## 未验证范围与限制

**模拟接口验证通过；真实 DeepSeek API和设备尚未验证。** 未验证真实 Key权限、服务可用性、计费、模型回答质量、文档/OCR效果、语音自然度、家庭设备执行，以及具体音箱/语音卫星的播放兼容性。GitHub Actions 会在源码推送后触发，远程运行状态以仓库 Actions 页面为准。

当前最低版本基线为 HA 2026.11.2；CI 同时对2026.11.2与2026.11.3执行完整验证，更高版本仍需持续兼容测试。首次部署后应显式选择少量实体进行实际验收。实验性评估为结构化生成的未经校准估计，不是供应商原生决策接口。

TTS完整文本与流式入口都通过官方 WebSocket校验结束事件；未实现单独 HTTP POST朗读后端。HA的 `tts.speak` 与 Assist 通过原生 TTS实体接口使用它。

关闭请求不能撤销已经发出的物理动作。会话历史包含已完成工具结果，中断且无法确认的动作标记为未知；不自动重试。上传补偿清理依赖本地所有权日志及有效凭据，失败记录会保留供下次加载重试。

加载期间原生对话 DEBUG日志全局脱敏的范围、HA自身会话/追踪仍然保留的行为见 README。源码目标仓库为 GalenaHu/deepseek-ha（核对时为公开）；Marketplace/HACS 从 main 源码安装，不依赖 Release。已确认匿名源码下载入口可访问。若改回私有，需要改用手动安装；原生 Marketplace 下载源码文件时不附带 GitHub API 凭据。


## 最低版本修复

保留用户将 `hacs.json` 最低版本改为2026.11.2的提交，并同步运行时 `MIN_HA`、开发依赖、文档及CI。此前仅改HACS元数据，Python运行时仍保留2026.11.3门槛；原生配置条目加载回归已复现并验证修复。另增加HACS/运行时版本一致性断言，防止再次漂移。集成版本升为0.1.1，安装后需要重启HA使新代码生效。

覆盖安装回归还复现了固定ZIP时间戳与同大小常量替换造成旧`.pyc`继续生效的问题。打包已改用可复现的提交时间（或显式SOURCE_DATE_EPOCH/源码manifest时间），回归会先编译旧`.3`门槛、覆盖新包并保留ZIP时间，确认加载结果为`.2`和当前 manifest 版本。

## Marketplace 下载 404 修复

旧 `hacs.json` 同时声明 `zip_release: true` 和 `filename: deepseek_ai.zip`，但仓库没有 Release。使用真实 HA Marketplace 的 `IntegrationRepository._async_download_version("main")` 复现了截图中的 `releases/download/main/deepseek_ai.zip` 请求；模拟该附件不存在时安装失败。

v0.1.2 移除这两个字段，沿用标准 `custom_components/deepseek_ai/` 源码目录。相同回归测试验证安装器选择 main 分支源码 ZIP、实际解压组件和中文翻译、读取 `.2` 最低版本，且完全不请求 Release 附件。只替换 GitHub 下载边界，安装器和解压实现均来自真实 HA；未操作用户的 HA/Marketplace 界面。

前一轮远程 CI 中，2026.11.2 完整验证通过；2026.11.3 在 Ubuntu 镜像下载阶段超时。已补充处理 GitHub runner 的 `mirror+file` 镜像列表配置，远程最新结果以 Actions 为准。
