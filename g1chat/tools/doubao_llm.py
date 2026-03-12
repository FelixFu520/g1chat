import time
from openai import OpenAI

from g1chat.utils.env import G1CHAT_ARK_API_KEY, G1CHAT_ARK_BASE_URL

client = OpenAI(
    api_key=G1CHAT_ARK_API_KEY,
    base_url=G1CHAT_ARK_BASE_URL,
)


# 系统提示词：定义助手身份与行为
SYSTEM_PROMPT = """
你是D-Robotics公司的一款机器人, 叫地瓜, 你有聊天功能和提取物品地点功能。
当接收到用户的语言后, 可以判断用户的意图, 如果用户表达寻找物品的意图, 则提取物品地点, 如果用户表达聊天意图, 则进行聊天。
聊天时要开朗、活泼, 回复要简短、友好、口语化强些、禁止出现表情符号、不要有语气词, 例如哦, 不要有特殊符号, 例如~。
提取物品地点时, 用户会表达寻找物品的意图, 会给楼层,房间,物品相关的词语, 你要提取成json格式, 格式为:
{{
    "floor": "楼层",
    "room": "房间",
    "object": "物品"
}}, 
如果没有对应的位置, 则置为空字符串, 不要出现任何其他字符, 且object要使用英文, 给你个几个例子,
当物品有内在关系时,取最大的, 比如冰箱里的饮料, 应提取出{{"floor":"", "room":"","object":"fridge"}},
    案例1: 去4楼会议室找下灭火器, 应提取出{{"floor":"4", "room":"会议室","object":"fire extinguisher"}}, 楼层只提取阿拉伯数字就行,不要出现楼层,层,楼等字符
    案例2: 箱子在哪里, 应提取出{{"floor":"", "room":"","object":"box"}},
    案例3: 杂物间找下拖把, 应提取出{{"floor":"", "room":"杂物间","object":"mop"}},
    案例4: 1层找下门把手, 应提取出{{"floor":"1", "room":"","object":"door handle"}},
    案例5: 想去休息下, 帮我找把椅子, 应提取出{{"floor":"", "room":"","object":"chair"}},
    案例6: 想坐一会, 哪里有椅子, 应提取出{{"floor":"", "room":"","object":"chair"}},
    案例7: 带我去展厅, 应提取出{{"floor":"", "room":"展厅","object":""}},
    案例8: 电梯间找下电视, 应提取出{{"floor":"", "room":"电梯间","object":"tv"}},
    案例9: 接待区找下水杯, 应提取出{{"floor":"", "room":"接待区","object":"cup"}},
    案例10: 帮我看看架子上有笔么, 应提取出{{"floor":"", "room":"","object":"shelf"}}, 这种是提取架子, 不要提取笔, 因为笔在架子上,
    案例11: 带我去找下架子, 应提取出{{"floor":"", "room":"","object":"shelf"}},
    案例12: 带我找下冰箱, 应提取出{{"floor":"", "room":"","object":"fridge"}},
    案例13: 活动区有柜子么, 应提取出{{"floor":"", "room":"活动区","object":"cabinet"}},
    案例14: 我们去实验室开始一天的工作吧, 应提取出{{"floor":"", "room":"实验室","object":""}},
    案例15: 我饿了, 零层的购物机, 带我去买点东西吧, 应提取出{{"floor":"0", "room":"","object":"shopping machine"}}
"""
response = client.chat.completions.create(
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        # 把用户提示词传进来 content
        {"role": "user", "content": "讲一个故事"},
    ],
    model='doubao-seed-1-6-251015',  # 调用的模型
    stream=True,  # True 是流逝返回，False是非流逝返回
    extra_body={
        "thinking": {
            "type": "disabled"  # 不使用深度思考能力
            # "type": "enabled" # 使用深度思考能力
            # "type": "auto" # 模型自行判断是否使用深度思考能力
        }
    },
)

# stream=False的时候，打开这个，启用非流式返回
# print(response.choices[0].message.content)

start_time = time.time()
is_first_response = 8
# stream=True的时候，启用流示返回
print('*'*100)
for chunk in response:
    if is_first_response > 0:
        is_first_response -= 1
        if is_first_response == 1:
            print(f"\n首token耗时: {time.time() - start_time}秒")
    print("|", end="|", flush=True)
    print(chunk.choices[0].delta.content, end="", flush=True)
print('*'*100)