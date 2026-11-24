# DeepSeek AI for Home Assistant

全新独立的 Home Assistant 自定义集成，domain：`deepseek_ai`。最低版本 **HA 2026.11.3**。只连接 DeepSeek 官方 HTTPS/WSS 服务；无需 OpenAI 账户。

## 安装

1. 解压 `deepseek_ai-0.1.0-manual.zip` 到 HA 的 `/config/`，确认存在 `/config/custom_components/deepseek_ai/manifest.json`。
2. 重启 HA，进入「设置 → 设备与服务 → 添加集成」，搜索 **DeepSeek AI**。
3. 输入 DeepSeek API Key。验证使用 `/models`，不产生模型生成请求。
4. 默认创建对话、AI 数据任务、语音识别、语音合成四个子项。可继续添加多个独立子项，在各子项菜单中重新配置。
5. 在「设置 → 语音助手」选择本集成的对话、STT 和 TTS 实体。唤醒词继续使用 HA 现有方案。

`deepseek_ai.zip` 是 HACS release asset 格式；本项目附 `hacs.json`，但本次不创建或发布远程仓库。上传仓库及发布附件后才能作为 HACS 自定义仓库在线安装。安装期间不要把 API Key 写入源码或公开 issue。

## 支持能力

- 流式 Assist 对话、多轮上下文、指令模板、Flash/Pro、推理 none/low/high/max。
- HA 原生设备工具与管理员工具，复用 HA 的实体暴露及用户权限；支持已有 MCP Client 注册的工具。
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

日志与诊断只记录运行元数据，不包含 Key、对话、图片、文档和工具完整结果。诊断没有会自动消耗额度的探测功能。计数器是本集成观察到的实际请求/用量，不等同供应商账户账单。上传成功但响应丢失等情况可能无法完整计量。

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
