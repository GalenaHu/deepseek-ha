# DeepSeek AI for Home Assistant

全新独立的 Home Assistant 自定义集成，domain：`deepseek_ai`。最低版本 **HA 2026.11.2**。只连接 DeepSeek 官方 HTTPS/WSS 服务；无需 OpenAI 账户。

## 安装

1. 解压 `deepseek_ai-0.1.1-manual.zip` 到 HA 的 `/config/`，确认存在 `/config/custom_components/deepseek_ai/manifest.json`。
2. 重启 HA，进入「设置 → 设备与服务 → 添加集成」，搜索 **DeepSeek AI**。
3. 输入 DeepSeek API Key。验证使用 `/models`，不产生模型生成请求。
4. 默认创建对话、AI 数据任务、语音识别、语音合成四个子项。可继续添加多个独立子项，在各子项菜单中重新配置。
5. 在「设置 → 语音助手」选择本集成的对话、STT 和 TTS 实体。唤醒词继续使用 HA 现有方案。

`deepseek_ai.zip` 是 HACS release asset 格式；本项目附 `hacs.json`。目标源码仓库为个人账号下的 [GalenaHu/deepseek-ha](https://github.com/GalenaHu/deepseek-ha)，与 Biology 一样使用私有可见性。此次推送源码与 CI 配置，不创建 Release；HACS 在线安装还需要后续发布 Release 附件及配置相应仓库访问权限。安装期间不要把 API Key 写入源码或公开 issue。

## 支持能力

- 流式 Assist 对话、多轮上下文、指令模板、Flash/Pro、推理 none/low/high/max。
- HA 原生设备工具与管理员工具，复用 HA 的实体暴露及用户权限；支持已有 MCP Client 注册的工具。管理员身份会在后续轮次和工具执行前重新检查。
- 独立联网代理：DeepSeek Search 与网页读取，模型可附来源链接。
- 原生 `ai_task.generate_data`、严格 JSON Schema、本地字段验证、图片和文档附件。
- 显式添加的实验性 `ai_task.evaluate`：noul/choice/score。结果是未经校准的模型估计；不会自动选择它作为默认决策实体。
- STT：WAV PCM / Ogg Opus，最多 8 MiB、120 秒；API 不支持边说边识别。
- TTS：Stella/Tide，普通播放与增量文字流式播放。支持普通话、粤语等官方语言，无语速、情绪等不受支持的开关。
- 用量传感器、持久统计、重置按钮、HA 原生脱敏诊断及认证恢复。

不提供图像生成、托管 Python、第三方网关、OpenAI 服务等级或服务端会话存储。不是 DeepSeek 或 Home Assistant 官方项目。

## 安全边界

对话默认仅选择 Device control，限已暴露实体；Home Assistant 管理工具须显式选择且只能由 HA 管理员身份使用，语音卫星不具备这一身份。联网与任何 HA 工具不能放在同一代理。AI Task 和评估实体不提供家庭工具；自动化根据返回值执行后续动作。

联网、图片和文档会把相应内容发送至 DeepSeek。文档解析可能按页计费。每次最多5个附件，总原始体积最多20 MiB；仅处理HA提供的媒体附件，不新增任意文件路径服务。上传文件按本地所有权日志清理；删除失败或上传响应丢失时会保留记录并在重启后补偿。不要把密钥、门锁密码等放入提示模板或附件。

日志与诊断只记录运行元数据，不包含 Key、对话、图片、文档和工具完整结果。加载期间会统一脱敏 HA 原生 `conversation.chat_log` 与 `conversation.agent_manager` 的 DEBUG 日志，其他对话集成的这两个调试日志也会受到影响；其他集成的警告和错误保留。本集成不会禁用 HA 本身的会话记录、对话追踪或自动化追踪，请按 HA 的权限管理这些记录。诊断没有会自动消耗额度的探测功能。计数器是本集成观察到的实际请求/用量，不等同供应商账户账单。请求总数统计完成的模型和语音请求，搜索另行统计；文件操作、凭据检查和未收到完成信息的请求不计入总数。TTS字符数为提交的文字长度，不是账单字符数。上传成功但响应丢失等情况可能无法完整计量。

## 使用原生动作

```yaml
action: ai_task.generate_data
data:
  entity_id: ai_task.deepseek_ai_ai_task
  task_name: 门口情况
  instructions: 判断门口有没有包裹，返回结构化结果。
  attachments:
    - media_content_id: media-source://camera/camera.front_door
      media_content_type: image/jpeg
  structure:
    package_present:
      required: true
      selector:
        boolean:
response_variable: result
```

实际实体ID以你的HA为准。在「设置 → 系统 → AI」可手动选择本集成的数据生成实体，供原生“建议”按钮使用。本集成不会自动修改全局AI偏好。

添加实验性评估子项后，可调用：

```yaml
action: ai_task.evaluate
data:
  entity_id: ai_task.deepseek_ai_evaluation
  task_name: 通知分类
  state: 门口有一个包裹。
  questions:
    delivered:
      type: noul
      instructions: 包裹是否已送达？
response_variable: evaluation
```

`evaluation.answers.delivered.noul` 是模型估计概率。不要未经场景验证就用它决定门锁、报警或其他高影响动作。

## 开发与验证

使用 Python 3.14，创建虚拟环境并安装 `requirements_test.txt`，运行 `pytest`、`ruff check`、`mypy`；`python scripts/package.py` 生成两个安装包及SHA256。测试必须导入真实HA，不使用HA替代桩，也不默认调用真实DeepSeek或家庭设备。

首版实际检查结果见 `docs/VERIFICATION.md`。本地测试并不证明真实API响应质量、音箱兼容性或家庭自动化安全，部署后应从少量低影响实体开始验证。


## 参数与限制

默认模型 `deepseek-flash`，推理关闭，最多10轮工具调用（随后允许一轮最终答复），保留最近10个用户轮次，网络空闲超时60秒、任务总时限180秒、条目内最多2个并发任务。可在子项或凭据配置中调整。历史按完整用户轮次裁剪，并有40 MiB字节预算；单次请求最多48 MiB。当前轮次过大时明确失败，不拆散工具调用与结果。

只有 Flash 子项声明图片与文件能力；Pro 为文字任务。PDF/Word/PPT 使用官方 `rich_layout_recognition`；文本、表格和电子书使用 `user_data`。附件上限采用比供应商更保守的本地限制。上传响应丢失后，清理日志会通过本集成随机文件名匹配远端文件，不会清空账户文件列表。

STT 提供 HA 与官方共同支持的 8/16/32/44.1/48 kHz、16位、单/双声道，Opus 使用 Ogg 容器。官方另支持的 22.05/24 kHz 不在当前 HA STT 枚举内，因此不声明。所有识别在录音结束后发出。TTS 普通整句与流式入口均使用官方 WebSocket，以校验 `finish/success`；整句返回标准有限长度 WAV，流式返回带头 WAV。没有额外语速、情绪或第三方地址选项。

超时、取消、卸载和重新配置会停止在途请求及工具等待。已完成工具结果留在会话中；中断且无法确认的动作标记为结果未知，集成不会自动重试。已经发往设备的动作无法通过取消请求撤销。

## 复现验证与发布附件

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements_test.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check custom_components tests scripts
.venv/bin/python -m ruff format --check custom_components tests scripts
.venv/bin/python -m mypy custom_components/deepseek_ai
.venv/bin/python scripts/check_metadata.py --ha-source /path/to/core-2026.11.2
.venv/bin/python scripts/package.py
```

测试摄像头依赖系统 FFmpeg、libturbojpeg；测试语音会在本机回环地址启动模拟服务。配置、会话、权限与服务使用真实HA，外部DeepSeek通信全部模拟。CI配置位于 `.github/workflows/validate.yml`，推送后 GitHub Actions 会执行同样的验证并生成可下载安装附件；实际远程运行结果以仓库 Actions 页面为准。

`dist/deepseek_ai-0.1.1-manual.zip` 为手动安装包，`dist/deepseek_ai.zip` 为 HACS release asset，`dist/deepseek-ha-0.1.1-source.zip` 为源码、测试和指南。校验值见 `dist/SHA256SUMS`。安装包不含虚拟环境、API Key、测试缓存或用户HA配置。


接口依据：[Responses API](https://api-docs.deepseek.com/api/create-response/)、[文件解析](https://api-docs.deepseek.com/guides/document_parsing/)、[Search & Fetch](https://api-docs.deepseek.com/guides/search/)、[语音识别](https://api-docs.deepseek.com/guides/asr/)、[语音合成](https://api-docs.deepseek.com/guides/tts/)。接口封装以本次核实的公开文档为准，真实 API 行为仍需安装后验证。


从旧版更新时，HACS 元数据和集成运行时代码都需要更新。v0.1.1 将两处最低版本统一为2026.11.2。若 HACS仍提示需要2026.11.3，在HACS中刷新仓库信息并重新下载新版本；手动安装则用新包覆盖 `/config/custom_components/deepseek_ai/` 后重启HA。仅修改远端 `hacs.json` 不会替换 HA已经加载的Python代码。

安装包时间戳使用 `SOURCE_DATE_EPOCH`（如显式提供）、Git提交时间，或无Git源码副本中的manifest文件时间。这样同一源码可重复构建，同时避免所有版本固定同一时间戳，使保留文件时间的覆盖安装误用旧Python字节码缓存。
