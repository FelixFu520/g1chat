import os

# 工作目录
G1CHAT_WORK_DIR = os.getenv("G1CHAT_WORK_DIR") if os.getenv("G1CHAT_WORK_DIR") else os.path.expanduser('~/.g1chat')

# 设备名称
G1CHAT_AUDIO_DEVICE_SPEAKER_NAME = os.getenv("G1CHAT_AUDIO_DEVICE_SPEAKER_NAME") if os.getenv("G1CHAT_AUDIO_DEVICE_SPEAKER_NAME") else "USB"
G1CHAT_AUDIO_DEVICE_MIC_NAME = os.getenv("G1CHAT_AUDIO_DEVICE_MIC_NAME") if os.getenv("G1CHAT_AUDIO_DEVICE_MIC_NAME") else "USB"

# LLM
system_prompt_path = os.path.join(G1CHAT_WORK_DIR, "system_prompt.txt")
if os.path.exists(system_prompt_path):
    with open(system_prompt_path, "r") as f:
        system_prompt = f.read()
else:
    system_prompt = "你是一个助手，叫做地瓜，请根据用户的问题给出回答。"
DEFAULT_SYSTEM_PROMPT = system_prompt
DEFAULT_MODEL = os.getenv("G1CHAT_DEFAULT_MODEL") if os.getenv("G1CHAT_DEFAULT_MODEL") else "doubao-seed-1-6-251015"
ARK_API_KEY = os.getenv("ARK_API_KEY") if os.getenv("ARK_API_KEY") else ""
ARK_BASE_URL = os.getenv("ARK_BASE_URL") if os.getenv("ARK_BASE_URL") else "https://ark.cn-beijing.volces.com/api/v3"

# ASR & TTS
SILENCE_TIMEOUT_MS = os.getenv("SILENCE_TIMEOUT_MS") if os.getenv("SILENCE_TIMEOUT_MS") else 600