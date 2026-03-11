"""
G1Chat: 语音对话流水线

实现 语音输入 -> ASR -> LLM -> TTS -> 播放语音 的完整流程
"""

import asyncio
import re
import os
import json
from datetime import datetime
import traceback
from token import OP
from queue import Queue
from typing import Optional
from typing import Optional
from openai import AsyncOpenAI

from g1chat.audio.asr_tts import ASRTTS
from g1chat.utils.logging import default_logger as logger
from g1chat.utils.env import (
    G1CHAT_DEFAULT_SYSTEM_PROMPT, G1CHAT_DEFAULT_MODEL, G1CHAT_ARK_API_KEY, G1CHAT_ARK_BASE_URL,
    G1CHAT_SILENCE_TIMEOUT_MS, G1CHAT_HOOKS, G1CHAT_LANGUAGE, G1CHAT_WAKE_UP_TEXT, G1CHAT_SLEEP_TEXT,
    G1CHAT_WORK_DIR
)

# 用于流式回复按句切分
_SENTENCE_SPLIT = re.compile(r"([，,。.！？\n]+)")


class G1Chat:
    """
    语音对话类：语音输入 -> ASR -> LLM -> TTS -> 播放

    - 语音输入：通过麦克风录音，由 ASR 实时识别
    - ASR: 识别结果放入队列，由流水线取出
    - LLM: 调用豆包大模型生成回复
    - TTS: 将回复文本放入 TTS 队列
    - 播放: TTS 处理器将语音播放到扬声器
    """

    def __init__(self):
                
        # 初始化 ASR 和 TTS
        self._asr_tts = ASRTTS()

        # 初始化 LLM 客户端
        self._client = AsyncOpenAI(api_key=G1CHAT_ARK_API_KEY, base_url=G1CHAT_ARK_BASE_URL)

        # 多轮对话历史
        self._messages: Optional[list[dict[str, str]]] = None

        self.wakeup = False # 是否唤醒
        self._running = False # 是否运行
        self.text_queue = Queue() # 文本队列, 用于传输信号, 例如停止信号, 挥手信号
        self.control_queue = Queue() # 控制队列, 用于传输控制信号, 例如到达某地点后播放一段音频
        self._asr_task: Optional[asyncio.Task] = None # ASR 任务
        self._tts_task: Optional[asyncio.Task] = None # TTS 任务
        self._pipeline_task: Optional[asyncio.Task] = None # 流水线任务

    async def _call_llm(self, user_text: str, asr_end_ts: Optional[float] = None) -> str:
        """
        调用 LLM 获取回复（异步流式，不阻塞事件循环）

        Args:
            user_text: 用户输入文本(ASR 结果)
            asr_end_ts: ASR 结束时间, 用于计算延时

        Returns:
            助手回复的完整文本
        """
        self._messages.append({"role": "user", "content": user_text})

        full_content: list[str] = []                        # LLM流式回复完整内容, 用于拼接LLM流式回复内容
        stream_start_ts = asyncio.get_event_loop().time()   # 流式开始时间
        first_tts_ts: Optional[float] = None                # 首句入 TTS 队列时间
        first_chunk_sent = False    # LLM流式回复首片段是否已发送到TTS队列中, 用于判断是否需要发送首片段, 如果已发送则不发送首片段
        first_buf = ""              # LLM流式回复首片段缓冲区, 用于累积首片段内容, 用于拼接首片段内容
        buffer = ""                 # LLM流式回复缓冲区(去除first_buf后的内容), 用于累积LLM流式回复内容, 用于拼接LLM流式回复内容
        MIN_FIRST_CHARS = 4         # 首片段最少字符数, 首片段最少字符数，尽量小以换取更快响应

        stream = await self._client.chat.completions.create(
            messages=self._messages,
            model=G1CHAT_DEFAULT_MODEL,
            stream=True,
            extra_body={"thinking": {"type": "disabled"}},
        )

        is_first_response = True    # 是否是LLM流式回复的第一包
        llm_response_type = None    # LLM 回复类型, 用于判断是位置信息还是音频信息
        async for chunk in stream:
            delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
            if not delta:
                continue

            # 判断LLM回复类型
            if is_first_response:
                is_first_response = False
                if "{" in delta:
                    llm_response_type = "location"
                else:
                    llm_response_type = "audio"

            # 首包快速首发：在还没有发送过任何 TTS 文本之前，
            # 只要累计到一定长度的内容就立即送入 TTS 队列，而不等待标点。
            if not first_chunk_sent:
                first_buf += delta
                if len(first_buf.strip()) >= MIN_FIRST_CHARS:
                    sentence = first_buf.strip()
                    if sentence:
                        full_content.append(sentence)
                        # 如果LLM回复类型是音频, 则直接发送给TTS队列
                        if llm_response_type == "audio":
                            self._asr_tts.put_tts_text(sentence, asr_end_ts=asr_end_ts)
                        first_tts_ts = asyncio.get_event_loop().time()
                        first_chunk_sent = True
                        first_buf = ""
                        continue
                # 在首片段发送前，不进入按句切分逻辑，继续累积
                if not first_chunk_sent:
                    continue

            buffer += delta
            # 按句号、问号、感叹号、换行切分，有完整句就送 TTS
            parts = _SENTENCE_SPLIT.split(buffer)
            buffer = ""
            for i, part in enumerate(parts):
                if _SENTENCE_SPLIT.match(part): # 如果part是标点符号, 则把前一个句子与part拼接后发送给TTS队列
                    if i > 0 and parts[i - 1]:
                        sentence = (parts[i - 1] + part).strip()
                        if sentence:
                            full_content.append(sentence)
                            if llm_response_type == "audio":
                                self._asr_tts.put_tts_text(sentence, asr_end_ts=asr_end_ts if first_tts_ts is None else None,)  # 如果没有经过first_chunk_sent, 就没有first_tts_ts, 则asr_end_ts作为asr_end_ts
                            if first_tts_ts is None:
                                first_tts_ts = asyncio.get_event_loop().time()
                    buffer = ""
                    continue
                buffer = part   # 如果part不是完整句子, 则继续累积

        # 处理流结束时剩余的内容：
        # - 如果首片段尚未发送，则把首片段和 buffer 合并后一并发送；
        # - 否则只处理 buffer 中剩余的尾巴。
        if not first_chunk_sent:
            tail_source = first_buf + buffer
        else:
            tail_source = buffer

        tail = tail_source.strip()
        if tail:
            full_content.append(tail)
            if llm_response_type == "audio":
                self._asr_tts.put_tts_text(tail, asr_end_ts=asr_end_ts if first_tts_ts is None else None,)
            if first_tts_ts is None:
                first_tts_ts = asyncio.get_event_loop().time()

        if first_tts_ts is not None:
            llm_to_first_tts_ms = (first_tts_ts - stream_start_ts) * 1000
            if asr_end_ts is not None:
                asr_to_first_tts_ms = (first_tts_ts - asr_end_ts) * 1000
                logger.info(
                    f"LLM 请求到首句入 TTS 队列耗时: {llm_to_first_tts_ms:.1f} ms | "
                    f"从\u201c静默判定完成\u201d到首句入 TTS 队列耗时: {asr_to_first_tts_ms:.1f} ms"
                )
            else:
                logger.info(
                    f"LLM 请求到首句入 TTS 队列耗时: {llm_to_first_tts_ms:.1f} ms"
                )
        content = "".join(full_content) if full_content else ""
        if content:
            self._messages.append({"role": "assistant", "content": content})
        return content, llm_response_type

    async def _pipeline_loop(self):
        """
        流水线协程：从 ASR 队列取文本 -> 调用 LLM -> 将回复放入 TTS 队列。
        """
        asr_tts = self._asr_tts
        if asr_tts.asr_queue_event is None:
            asr_tts.asr_queue_event = asyncio.Event()

        while self._running:
            try:
                await asr_tts.asr_queue_event.wait()
                asr_tts.asr_queue_event.clear()

                while not asr_tts.asr_queue.empty():
                    # ============== ASR ==============
                    result = asr_tts.asr_queue.get_nowait()
                    if not result or not isinstance(result, dict):
                        continue
                    text = result.get("text", "").strip()
                    if not text:
                        continue
                    end_ts = result.get("end_ts")   # ASR 结束时间
                    now_ts = asyncio.get_event_loop().time()   # 当前时间
                    if end_ts is not None:
                        asr_delay_ms = (now_ts - end_ts) * 1000   # ASR 延迟时间
                        logger.info(f"User: {result} | 从\u201c静默判定完成\u201d到出队耗时: {asr_delay_ms:.1f} ms")
                    else:
                        logger.info(f"User: {result}")

                    # ============== WAKE_UP & SLEEP Hook ==============
                    if "wake_sleep_hooks" not in G1CHAT_HOOKS or len(G1CHAT_HOOKS["wake_sleep_hooks"]) == 0:
                        if G1CHAT_LANGUAGE == "zh":
                            response_text = "请正确配置唤醒和睡眠的钩子"
                        else:
                            response_text = "Please configure the wake_sleep_hooks correctly"
                        self._asr_tts.put_tts_text(response_text)
                        continue
                        
                    if not self.wakeup and G1CHAT_WAKE_UP_TEXT in text:
                        self.wakeup = True

                        if G1CHAT_LANGUAGE == "zh":
                            response_text = G1CHAT_HOOKS["wake_sleep_hooks"][0]["response_zh"]
                        elif G1CHAT_LANGUAGE == "en":
                            response_text = G1CHAT_HOOKS["wake_sleep_hooks"][0]["response_en"]
                        self._asr_tts.put_tts_text(response_text)

                        self.text_queue.put(G1CHAT_HOOKS["wake_sleep_hooks"][0]["signal"])

                        # 更新对话历史
                        self._messages = [{"role": "system", "content": G1CHAT_DEFAULT_SYSTEM_PROMPT,}]
                        self._messages.append({"role": "user", "content": text})
                        self._messages.append({"role": "assistant", "content": response_text})

                        continue
                    
                    if self.wakeup and G1CHAT_SLEEP_TEXT in text:
                        self.wakeup = False

                        if G1CHAT_LANGUAGE == "zh":
                            response_text = G1CHAT_HOOKS["wake_sleep_hooks"][1]["response_zh"]
                        elif G1CHAT_LANGUAGE == "en":
                            response_text = G1CHAT_HOOKS["wake_sleep_hooks"][1]["response_en"]
                        self._asr_tts.put_tts_text(response_text)
                        
                        self.text_queue.put(G1CHAT_HOOKS["wake_sleep_hooks"][1]["signal"])

                        # 保存历史对话
                        save_history_dialog_path = os.path.join(G1CHAT_WORK_DIR, "dialogs", f"{datetime.now().strftime('%Y%m%d%H%M%S')}.json")
                        os.makedirs(os.path.dirname(save_history_dialog_path), exist_ok=True)
                        with open(save_history_dialog_path, "w") as f:
                            json.dump(self._messages, f)

                        # 清空对话历史
                        self._messages = []

                        continue

                    if not self.wakeup:
                        continue

                    # ============== ASR Hook ==============
                    if "asr_hooks" not in G1CHAT_HOOKS:
                        if G1CHAT_LANGUAGE == "zh":
                            response_text = "请正确配置语音识别的钩子"
                        else:
                            response_text = "Please configure the asr_hooks correctly"
                        self._asr_tts.put_tts_text(response_text)
                        continue

                    is_asr_hook_found = False
                    for hook in G1CHAT_HOOKS["asr_hooks"]:
                        if hook['relate'] == "and":
                            if all(name.lower() in text.strip().lower() for name in hook['name']):
                                is_asr_hook_found = True
                            else:
                                is_asr_hook_found = False
                        elif hook['relate'] == "or":
                            if any(name.lower() in text.strip().lower() for name in hook['name']):
                                is_asr_hook_found = True
                            else:
                                is_asr_hook_found = False
                        if is_asr_hook_found:
                            if G1CHAT_LANGUAGE == "zh":
                                response_text = hook['response_zh']
                            else:
                                response_text = hook['response_en']
                            self._asr_tts.put_tts_text(response_text)

                            self.text_queue.put(hook["signal"])
                            is_asr_hook_found = True
                            break
                    if is_asr_hook_found:
                        continue

                    # ============== LLM ==============
                    try:
                        llm_start = asyncio.get_event_loop().time()
                        reply, llm_response_type = await self._call_llm(text, asr_end_ts=end_ts)
                        llm_end = asyncio.get_event_loop().time()
                        llm_cost_ms = (llm_end - llm_start) * 1000

                        logger.info(
                            f"Assistant: {reply.strip()} | "
                            f"LLM 流式完成耗时: {llm_cost_ms:.1f} ms"
                        )
                        
                        # 如果返回的是location信息, 需要提取出来, 发送给queue_text
                        if llm_response_type == "location":
                            try:
                                if reply.startswith("{{"):
                                    location_info = json.loads(reply[1:-1])
                                elif reply.startswith("{"):
                                    location_info = json.loads(reply)
                                else:
                                    location_info = ""
                            except Exception as e:
                                if G1CHAT_LANGUAGE == "zh":
                                    response_text = "抱歉, 我提取位置信息失败了, 请再说一次"
                                else:
                                    response_text = "Sorry, I'm having trouble extracting the location information. Please try again."
                                self._asr_tts.put_tts_text(response_text)
                                logger.error(f"提取位置信息失败: {traceback.format_exc()}")
                                location_info = ""
                            self.text_queue.put(f"location:{json.dumps(location_info)}")
                            
                             # ============== location Hook ==============
                            if "location_hooks" not in G1CHAT_HOOKS:
                                if G1CHAT_LANGUAGE == "zh":
                                    response_text = "请正确配置位置信息的钩子"
                                else:
                                    response_text = "Please configure the location_hooks correctly"
                                self._asr_tts.put_tts_text(response_text)
                                continue

                            is_location_hook_found = False
                            for hook in G1CHAT_HOOKS["location_hooks"]:
                                if hook['relate'] == "and":
                                    if all(name.lower() in reply.strip().lower() for name in hook['name']):
                                        is_location_hook_found = True
                                    else:
                                        is_location_hook_found = False
                                elif hook['relate'] == "or":
                                    if any(name.lower() in reply.strip().lower() for name in hook['name']):
                                        is_location_hook_found = True
                                    else:
                                        is_location_hook_found = False
                                if is_location_hook_found:
                                    if G1CHAT_LANGUAGE == "zh":
                                        response_text = hook['response_zh']
                                    else:
                                        response_text = hook['response_en']
                                    self._asr_tts.put_tts_text(response_text)

                                    self.text_queue.put(hook["signal"])
                                    is_location_hook_found = True
                                    break

                    except Exception as e:
                        logger.error(f"LLM 调用失败: {traceback.format_exc()}")
                        asr_tts.put_tts_text("抱歉，我这边出错了，请再说一次。")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"流水线异常: {traceback.format_exc()}")
                await asyncio.sleep(0.1)

    async def start(self):
        """
        启动语音对话：同时运行 ASR、TTS 处理器和 ASR->LLM->TTS 流水线。
        """
        self._running = True
        self._asr_task = asyncio.create_task(self._asr_tts.start_realtime_asr(silence_timeout_ms=G1CHAT_SILENCE_TIMEOUT_MS))
        self._tts_task = asyncio.create_task(self._asr_tts.start_tts_processor())
        self._pipeline_task = asyncio.create_task(self._pipeline_loop())
        logger.info("已启动：语音输入 -> ASR -> LLM -> TTS -> 播放")

    async def stop(self):
        """停止 ASR、流水线和 TTS 处理器，并清理音频设备。"""
        self._running = False
        self._asr_tts.stop_tts_processor()
        if self._asr_tts.asr_queue_event:
            self._asr_tts.asr_queue_event.set()

        for task in (self._pipeline_task, self._asr_task, self._tts_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._asr_task = None
        self._tts_task = None
        self._pipeline_task = None
        if self._asr_tts.audio_device:
            self._asr_tts.audio_device.cleanup()
        logger.info("已停止，资源已清理")

    @property
    def asr_tts(self) -> ASRTTS:
        """底层的 ASR/TTS 实例，便于测试或扩展。"""
        return self._asr_tts
