import os
import json

# 工作目录
G1CHAT_WORK_DIR = os.getenv("G1CHAT_WORK_DIR") if os.getenv("G1CHAT_WORK_DIR") else os.path.expanduser('~/.g1chat')

# 设备名称
G1CHAT_AUDIO_DEVICE_SPEAKER_NAME = os.getenv("G1CHAT_AUDIO_DEVICE_SPEAKER_NAME") if os.getenv("G1CHAT_AUDIO_DEVICE_SPEAKER_NAME") else "USB"
G1CHAT_AUDIO_DEVICE_MIC_NAME = os.getenv("G1CHAT_AUDIO_DEVICE_MIC_NAME") if os.getenv("G1CHAT_AUDIO_DEVICE_MIC_NAME") else "USB"

# 设置语言系统
G1CHAT_LANGUAGE = os.getenv("G1CHAT_LANGUAGE") if os.getenv("G1CHAT_LANGUAGE") else "zh"

# WAKE_UP & SLEEP
G1CHAT_WAKE_UP_TEXT = os.getenv("G1CHAT_WAKE_UP_TEXT") if os.getenv("G1CHAT_WAKE_UP_TEXT") else "地瓜地瓜"
G1CHAT_SLEEP_TEXT = os.getenv("G1CHAT_SLEEP_TEXT") if os.getenv("G1CHAT_SLEEP_TEXT") else "再见"

# Hooks
G1CHAT_HOOKS_PATH = os.path.join(G1CHAT_WORK_DIR, "hooks.json")
if os.path.exists(G1CHAT_HOOKS_PATH):
    with open(G1CHAT_HOOKS_PATH, "r") as f:
        _hooks = json.load(f)
        # 按照order排序
        hooks = {}
        for k, v in _hooks.items():
            if k == "control_hooks" or k == "control_signals":
                hooks[k] = v
                continue
            hooks[k] = sorted(v, key=lambda x: x["order"])
else:
    hooks = {}
G1CHAT_HOOKS = hooks

# LLM
G1CHAT_SYSTEM_PROMPT_PATH = os.path.join(G1CHAT_WORK_DIR, f"system_prompt_{G1CHAT_LANGUAGE}.txt")
if os.path.exists(G1CHAT_SYSTEM_PROMPT_PATH):
    with open(G1CHAT_SYSTEM_PROMPT_PATH, "r") as f:
        system_prompt = f.read()
else:
    system_prompt = "你是一个助手，叫做地瓜，请根据用户的问题给出回答。"
G1CHAT_DEFAULT_SYSTEM_PROMPT = system_prompt
G1CHAT_DEFAULT_MODEL = os.getenv("G1CHAT_DEFAULT_MODEL") if os.getenv("G1CHAT_DEFAULT_MODEL") else "doubao-seed-2-0-lite-260215"
G1CHAT_ARK_API_KEY = os.getenv("G1CHAT_ARK_API_KEY") if os.getenv("G1CHAT_ARK_API_KEY") else ""
G1CHAT_ARK_BASE_URL = os.getenv("G1CHAT_ARK_BASE_URL") if os.getenv("G1CHAT_ARK_BASE_URL") else "https://ark.cn-beijing.volces.com/api/v3"

# ASR & TTS（静默超时：判定“一句话结束”的等待时间，默认 400ms，可通过 SILENCE_TIMEOUT_MS 覆盖）
G1CHAT_SILENCE_TIMEOUT_MS = int(os.getenv("G1CHAT_SILENCE_TIMEOUT_MS")) if os.getenv("G1CHAT_SILENCE_TIMEOUT_MS") else 400
G1CHAT_ASR_APP_KEY = os.getenv("G1CHAT_ASR_APP_KEY") if os.getenv("G1CHAT_ASR_APP_KEY") else ""
G1CHAT_ASR_ACCESS_KEY = os.getenv("G1CHAT_ASR_ACCESS_KEY") if os.getenv("G1CHAT_ASR_ACCESS_KEY") else ""
G1CHAT_TTS_APP_KEY = os.getenv("G1CHAT_TTS_APP_KEY") if os.getenv("G1CHAT_TTS_APP_KEY") else ""
G1CHAT_TTS_ACCESS_KEY = os.getenv("G1CHAT_TTS_ACCESS_KEY") if os.getenv("G1CHAT_TTS_ACCESS_KEY") else ""