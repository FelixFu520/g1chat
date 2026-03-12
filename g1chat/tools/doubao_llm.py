import time
from openai import OpenAI

from g1chat.utils.env import (
    G1CHAT_ARK_API_KEY,
    G1CHAT_ARK_BASE_URL,
    G1CHAT_DEFAULT_MODEL,
    G1CHAT_DEFAULT_SYSTEM_PROMPT,
)
from g1chat.utils.logging import default_logger as logger


client = OpenAI(
    api_key=G1CHAT_ARK_API_KEY,
    base_url=G1CHAT_ARK_BASE_URL,
)

logger.info(f"模型: {G1CHAT_DEFAULT_MODEL}")

start_time = time.time()
response = client.chat.completions.create(
    messages=[
        {"role": "system", "content": G1CHAT_DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": "讲一个故事"},
    ],
    model=G1CHAT_DEFAULT_MODEL,
    stream=True,  # True 是流逝返回，False是非流逝返回
    extra_body={
        "thinking": {
            "type": "disabled"  # 不使用深度思考能力
            # "type": "enabled" # 使用深度思考能力
            # "type": "auto" # 模型自行判断是否使用深度思考能力
        }
    },
)

first_token_logged = False
print('*'*100)
for chunk in response:
    delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
    if not first_token_logged and delta:
        print(f"\n首token耗时: {time.time() - start_time:.4f}秒")
        first_token_logged = True
    print(f"||{delta}", end="", flush=True)
print()
print('*'*100)