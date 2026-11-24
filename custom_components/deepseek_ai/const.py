"""Provider capabilities; never infer support from a successful HTTP status."""

from homeassistant.const import Platform

DOMAIN = "deepseek_ai"
NAME = "DeepSeek AI"
VERSION = "0.1.0"
MIN_HA = "2026.11.3"
API_ROOT = "https://api.deepseek.com"
TTS_URL = "wss://api.deepseek.com/v1/tools/tts?format=pcm"
MODELS = ["deepseek-flash", "deepseek-v4-pro"]
SUBTYPES = ("conversation", "ai_task", "evaluation", "stt", "tts")
PLATFORMS = (Platform.CONVERSATION, Platform.AI_TASK, Platform.STT, Platform.TTS, Platform.SENSOR, Platform.BUTTON)
DEFAULTS = {
    "model": "deepseek-flash",
    "thinking": "none",
    "max_tokens": 4096,
    "max_tool_rounds": 10,
    "history_turns": 10,
    "timeout": 60,
    "total_timeout": 180,
    "web": False,
    "prompt": "You are a helpful Home Assistant assistant. Reply concisely in the user's language. Never claim an action succeeded without a successful tool result.",
    "voice": "stella",
}
STT_LANGUAGES = ["zh-CN", "yue-HK", "en-US", "ja-JP", "ko-KR", "de-DE", "fr-FR", "es-ES", "pt-PT", "it-IT", "ru-RU", "ar-SA", "hi-IN", "id-ID", "vi-VN", "th-TH", "tr-TR", "ms-MY", "fil-PH", "pl-PL", "hu-HU"]
TTS_LANGUAGES = ["zh-CN", "yue-HK", "en-US", "ja-JP", "ko-KR", "ms-MY", "ar-SA", "id-ID", "th-TH", "vi-VN"]
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENTS = 5
MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_AUDIO_SECONDS = 120
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_EVENT_BYTES = 1024 * 1024
FILE_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xlsx", ".xls", ".txt", ".md", ".csv", ".json", ".epub", ".mobi"}
IMAGE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

