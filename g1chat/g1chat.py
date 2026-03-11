"""
G1Chat: 语音对话流水线

实现 语音输入 -> ASR -> LLM -> TTS -> 播放语音 的完整流程
"""

import asyncio
import re
import os
from typing import Optional
from typing import Optional
from openai import AsyncOpenAI

from g1chat.audio.asr_tts import ASRTTS
from g1chat.utils.logging import default_logger as logger
from g1chat.utils.env import (
    DEFAULT_SYSTEM_PROMPT, DEFAULT_MODEL, ARK_API_KEY, ARK_BASE_URL,
    SILENCE_TIMEOUT_MS
)

# 用于流式回复按句切分
_SENTENCE_SPLIT = re.compile(r"([，,。！？\n]+)")


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
        self._client = AsyncOpenAI(api_key=ARK_API_KEY, base_url=ARK_BASE_URL)

        # 多轮对话历史
        self._messages: list[dict[str, str]] = [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
        ]


        self._running = False
        self._asr_task: Optional[asyncio.Task] = None
        self._tts_task: Optional[asyncio.Task] = None
        self._pipeline_task: Optional[asyncio.Task] = None

    async def _call_llm(self, user_text: str, asr_end_ts: Optional[float] = None) -> str:
        """
        调用 LLM 获取回复（异步流式，不阻塞事件循环）

        Args:
            user_text: 用户输入文本(ASR 结果)

        Returns:
            助手回复的完整文本
        """
        self._messages.append({"role": "user", "content": user_text})

        full_content: list[str] = []
        stream_start_ts = asyncio.get_event_loop().time()
        first_tts_ts: Optional[float] = None

        stream = await self._client.chat.completions.create(
            messages=self._messages,
            model=DEFAULT_MODEL,
            stream=True,
            extra_body={"thinking": {"type": "disabled"}},
        )
        buffer = ""
        async for chunk in stream:
            delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
            if not delta:
                continue
            buffer += delta
            # 按句号、问号、感叹号、换行切分，有完整句就送 TTS
            parts = _SENTENCE_SPLIT.split(buffer)
            buffer = ""
            for i, part in enumerate(parts):
                if _SENTENCE_SPLIT.match(part):
                    if i > 0 and parts[i - 1]:
                        sentence = (parts[i - 1] + part).strip()
                        if sentence:
                            full_content.append(sentence)
                            self._asr_tts.put_tts_text(
                                sentence,
                                asr_end_ts=asr_end_ts if first_tts_ts is None else None,
                            )
                            if first_tts_ts is None:
                                first_tts_ts = asyncio.get_event_loop().time()
                    buffer = ""
                    continue
                buffer = part
        tail = buffer.strip()
        if tail:
            full_content.append(tail)
            self._asr_tts.put_tts_text(
                tail,
                asr_end_ts=asr_end_ts if first_tts_ts is None else None,
            )
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
        return content

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
                    try:
                        result = asr_tts.asr_queue.get_nowait()
                    except Exception:
                        break
                    if not result or not isinstance(result, dict):
                        continue
                    text = result.get("text", "").strip()
                    if not text:
                        continue
                    end_ts = result.get("end_ts")
                    now_ts = asyncio.get_event_loop().time()
                    if end_ts is not None:
                        asr_delay_ms = (now_ts - end_ts) * 1000
                        logger.info(
                            f"User: {result} | 从\u201c静默判定完成\u201d到出队耗时: {asr_delay_ms:.1f} ms"
                        )
                    else:
                        logger.info(f"User: {result}")

                    try:
                        llm_start = asyncio.get_event_loop().time()
                        reply = await self._call_llm(text, asr_end_ts=end_ts)
                        llm_end = asyncio.get_event_loop().time()
                        llm_cost_ms = (llm_end - llm_start) * 1000

                        logger.info(
                            f"Assistant: {reply} | "
                            f"LLM 流式完成耗时: {llm_cost_ms:.1f} ms"
                        )
                    except Exception as e:
                        logger.error(f"LLM 调用失败: {e}")
                        asr_tts.put_tts_text("抱歉，我这边出错了，请再说一次。")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"流水线异常: {e}")
                await asyncio.sleep(0.1)

    async def start(self):
        """
        启动语音对话：同时运行 ASR、TTS 处理器和 ASR->LLM->TTS 流水线。
        """
        self._running = True
        self._asr_task = asyncio.create_task(self._asr_tts.start_realtime_asr(silence_timeout_ms=SILENCE_TIMEOUT_MS))
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
