"""Generate checked-in EN/zh-Hans UI resources from explicit labels."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components/deepseek_ai"
FIELDS = {
    "api_key": ("API key", "API 密钥"),
    "max_concurrent": ("Maximum concurrent jobs", "最大并发任务"),
    "name": ("Name", "名称"), "model": ("Model", "模型"),
    "thinking": ("Reasoning effort (none disables thinking)", "推理强度（none 为关闭）"),
    "prompt": ("Instructions template", "指令模板"),
    "max_tokens": ("Maximum output tokens, including reasoning", "最大输出 token（包含推理）"),
    "max_tool_rounds": ("Maximum model rounds", "最大模型调用轮数"),
    "history_turns": ("User turns in history", "保留的用户历史轮数"),
    "llm_hass_api": ("Home Assistant tools", "Home Assistant 工具"),
    "web": ("Public web search and reading (cannot combine with HA tools)", "联网搜索与读取（不能与 HA 工具组合）"),
    "voice": ("Voice", "音色"),
    "timeout": ("Network idle timeout (seconds)", "网络空闲超时（秒）"),
    "total_timeout": ("Total job deadline (seconds)", "任务总时限（秒）"),
    "acknowledge_experimental": ("I understand these estimates are experimental and uncalibrated", "我了解评估结果是实验性的、未经校准的模型估计"),
}
ERRORS = {
    "invalid_auth": ("The API key was rejected.", "API 密钥无效或已被撤销。"),
    "cannot_connect": ("Could not reach the official DeepSeek API.", "无法连接 DeepSeek 官方 API。"),
    "invalid_subtype": ("Unsupported function type.", "不支持的功能类型。"),
    "invalid_model": ("Select a supported model and reasoning effort.", "请选择支持的模型与推理强度。"),
    "invalid_limits": ("A resource limit is invalid.", "资源限制设置无效。"),
    "invalid_tools": ("Invalid tool selection.", "工具选择无效。"),
    "task_tools_forbidden": ("Tasks cannot use Home Assistant tools.", "AI 任务不能使用家庭工具。"),
    "web_tools_conflict": ("Remove Home Assistant tools before enabling web access.", "启用联网前请清空 Home Assistant 工具。"),
    "invalid_options": ("Invalid options.", "配置选项无效。"),
    "experimental_required": ("Acknowledge experimental evaluation before adding it.", "添加前请确认已了解实验性评估的限制。"),
}
KINDS = {"conversation": ("Conversation agent", "对话代理"), "ai_task": ("AI data task", "AI 数据任务"), "evaluation": ("Experimental evaluation", "实验性评估"), "stt": ("Speech to text", "语音识别"), "tts": ("Text to speech", "语音合成")}
SENSORS = {"requests": ("Completed requests", "已完成请求"), "input_tokens": ("Input tokens", "输入 token"), "output_tokens": ("Output tokens", "输出 token"), "cached_tokens": ("Cached input tokens", "命中缓存的输入 token"), "reasoning_tokens": ("Reasoning tokens", "推理 token"), "searches": ("Successful searches", "成功搜索次数"), "stt_seconds": ("Recognized audio duration", "已识别音频时长"), "tts_characters": ("Submitted speech characters", "已提交合成字符"), "latency_ms": ("Last completed model latency", "最近完成的模型请求耗时")}


def build(language):
    errors = {key: value[language] for key, value in ERRORS.items()}
    data = {key: value[language] for key, value in FIELDS.items()}
    steps = {step: {"title": "DeepSeek AI", "description": ("Official DeepSeek only. Usage is billed to your DeepSeek API account." if language == 0 else "仅连接 DeepSeek 官方服务，调用费用由 DeepSeek API 账户承担。"), "data": {key: data[key] for key in ("api_key", "max_concurrent")}} for step in ("user", "reconfigure", "reauth_confirm")}
    return {
        "title": "DeepSeek AI",
        "config": {"step": steps, "error": errors, "abort": {"reauth_successful": ("Credentials updated." if language == 0 else "密钥已更新。"), "reconfigure_successful": ("Configuration updated." if language == 0 else "配置已更新。")}},
        "config_subentries": {kind: {"entry_type": names[language], "initiate_flow": {"user": ("Add " if language == 0 else "添加") + names[language], "reconfigure": ("Configure " if language == 0 else "配置") + names[language]}, "step": {"init": {"title": names[language], "data": {key: value for key, value in data.items() if key not in ("api_key", "max_concurrent")}}}, "error": errors, "abort": {"reconfigure_successful": ("Updated." if language == 0 else "已更新。")}} for kind, names in KINDS.items()},
        "entity": {"sensor": {key: {"name": value[language]} for key, value in SENSORS.items()}, "button": {"reset_usage": {"name": ("Reset usage counters" if language == 0 else "重置用量统计")}}},
    }


if __name__ == "__main__":
    (ROOT / "translations").mkdir(exist_ok=True)
    for name, index in (("en", 0), ("zh-Hans", 1)):
        (ROOT / "translations" / (name + ".json")).write_text(json.dumps(build(index), ensure_ascii=False, indent=2) + "\n")
    (ROOT / "strings.json").write_text(json.dumps(build(0), ensure_ascii=False, indent=2) + "\n")

