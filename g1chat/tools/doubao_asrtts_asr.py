from g1chat.audio.asr_tts import ASRTTS
from g1chat.utils.logging import default_logger as logger
import asyncio
import os

# ─────────────────────────────────────────────
# 可强制断开的 AsrWsClient 子类
# ─────────────────────────────────────────────
import g1chat.audio.volcengine_doubao_asr as _asr_mod
from g1chat.audio.volcengine_doubao_asr import AsrWsClient as _OrigAsrWsClient


class _InjectableAsrWsClient(_OrigAsrWsClient):
    """
    AsrWsClient 的可注入子类。

    额外暴露 force_disconnect()，供外部断网模拟任务调用：
    - force_disconnect(): 设置内部中断事件，让正在运行的 execute_stream 抛出
                          ConnectionError, 触发 ASRTTS.start_realtime_asr 的重连机制。
    不需要 root 权限，不依赖 iptables。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 断网触发事件：被设置时，execute_stream 会抛 ConnectionError
        self._disconnect_event: asyncio.Event = asyncio.Event()

    async def force_disconnect(self):
        """触发断网：设置中断事件，让 execute_stream 抛出 ConnectionError。"""
        if not self._disconnect_event.is_set():
            logger.info("[断网模拟] 触发断网事件，中断当前 ASR 连接...")
            self._disconnect_event.set()
        else:
            logger.warning("[断网模拟] 断网事件已触发，跳过重复操作")

    async def execute_stream(self, audio_stream):
        """
        重写 execute_stream: 在后台监视 _disconnect_event,
        一旦被设置就关闭 WebSocket 连接并抛出 ConnectionError,
        让 ASRTTS.start_realtime_asr 的 except 分支执行重连
        """
        if not self.url:
            raise ValueError("URL is empty")

        self.seq = 1
        self._disconnect_event.clear()  # 每次新连接前重置

        try:
            await self.create_connection()
            await self.send_full_client_request()

            # 后台监视断网事件
            async def _watch_disconnect():
                await self._disconnect_event.wait()
                if self.conn and not self.conn.closed:
                    logger.info("[断网模拟] 强制关闭 WebSocket 连接...")
                    await self.conn.close()

            watch_task = asyncio.ensure_future(_watch_disconnect())
            try:
                async for response in self.start_realtime_audio_stream(audio_stream):
                    yield response
            finally:
                watch_task.cancel()
                try:
                    await watch_task
                except asyncio.CancelledError:
                    pass

            # 如果是因为断网事件触发而退出，抛出 ConnectionError 让外层重连
            if self._disconnect_event.is_set():
                raise ConnectionError("[断网模拟] WebSocket 连接已被强制关闭，触发重连")

        except ConnectionError:
            raise
        except Exception as e:
            logger.error(f"Error in streaming ASR execution: {e}")
            raise
        finally:
            if self.conn:
                await self.conn.close()


# 全局变量：记录最近一次被创建的 _InjectableAsrWsClient 实例
_latest_client: "_InjectableAsrWsClient | None" = None


class _TrackingAsrWsClient(_InjectableAsrWsClient):
    """
    在 __aenter__ 时把自身注册到全局变量，供断网任务获取。

    __aexit__ 中若断网事件已触发，主动抛出 ConnectionError，使其穿透
    asr_tts.py 中 `async with AsrWsClient(...)` 块，被外层 while True 的
    except 分支捕获，从而触发重连逻辑。
    """

    async def __aenter__(self):
        global _latest_client
        result = await super().__aenter__()
        _latest_client = self
        return result

    async def __aexit__(self, exc_type, exc, tb):
        global _latest_client
        if _latest_client is self:
            _latest_client = None
        await super().__aexit__(exc_type, exc, tb)
        # 断网事件触发过 → 抛出异常，让 asr_tts.py 外层 while True 的
        # except 分支捕获并执行重连（不能改 asr_tts.py，只能从这里抛）
        if self._disconnect_event.is_set():
            raise ConnectionError("[断网模拟] WebSocket 已被强制关闭，触发重连")


def _patch_asr_client():
    """
    将 volcengine_doubao_asr 模块中的 AsrWsClient 替换为 _TrackingAsrWsClient，
    同时替换 asr_tts 模块中已导入的引用，使 ASRTTS 内部的
    `async with AsrWsClient(...)` 实际使用带追踪功能的子类。
    """
    import g1chat.audio.asr_tts as _asr_tts_mod
    _asr_mod.AsrWsClient = _TrackingAsrWsClient
    _asr_tts_mod.AsrWsClient = _TrackingAsrWsClient


# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

async def monitor_queue(asr_tts: ASRTTS):
    """
    监控ASR队列, 完成一次识别后显示队列内容(不删除队列内容)
    
    Args:
        asr_tts: ASRTTS实例
    """
    logger.info("开始监控ASR队列...")
    
    if asr_tts.asr_queue_event is None:
        asr_tts.asr_queue_event = asyncio.Event()
    
    while True:
        try:
            await asr_tts.asr_queue_event.wait()
            asr_tts.asr_queue_event.clear()
            
            if not asr_tts.asr_queue.empty():
                temp_results = []
                while not asr_tts.asr_queue.empty():
                    try:
                        result = asr_tts.asr_queue.get_nowait()
                        if result:
                            temp_results.append(result)
                    except Exception:
                        break
                
                if temp_results:
                    logger.info(f"\n[队列内容] 共有 {len(temp_results)} 条结果:")
                    for i, result in enumerate(temp_results, 1):
                        logger.info(f"  {i}. chat_id: {result['chat_id']}, text: {result['text']}")
                    for result in temp_results:
                        asr_tts.asr_queue.put(result)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"队列监控异常: {e}")
            await asyncio.sleep(0.1)


async def simulate_network_disconnect(
    disconnect_after: float,
    disconnect_duration: float,
):
    """
    模拟断网场景（无需 root 权限）。

    实现方式：直接关闭 AsrWsClient 内部的 aiohttp WebSocket 连接，
    触发连接断开异常，让 ASRTTS.start_realtime_asr 的重连机制自动生效。

    Args:
        disconnect_after:   多少秒后触发断网（秒）
        disconnect_duration: 断网持续时间（秒）；期间不做任何操作，
                             ASRTTS 的重连退避会等待后自动重建连接。
    """
    await asyncio.sleep(disconnect_after)
    logger.info(f"[断网模拟] 触发断网，持续 {disconnect_duration:.1f}s ...")

    # 等待全局客户端实例出现（ASRTTS 需要一点时间建立第一条连接）
    waited = 0.0
    while _latest_client is None and waited < 10.0:
        await asyncio.sleep(0.1)
        waited += 0.1

    if _latest_client is None:
        logger.warning("[断网模拟] 未找到活跃的 AsrWsClient 实例，跳过断网模拟")
        return

    await _latest_client.force_disconnect()

    # 等待断网持续时间；重连由 ASRTTS 内部自动处理，这里只需静默等待
    await asyncio.sleep(disconnect_duration)
    logger.info("[断网模拟] 断网持续时间结束，ASRTTS 应已自动重连")


# ─────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────

async def main():
    """
    测试程序主函数
    """
    import argparse

    parser = argparse.ArgumentParser(description="ASRTTS实时ASR测试工具")
    parser.add_argument("--silence-timeout", type=int, default=600,
                       help="静音超时时间(毫秒)，默认: 600")
    parser.add_argument("--simulate-disconnect", action="store_true",
                       help="模拟断网场景（直接关闭 WebSocket，无需 root 权限）")
    parser.add_argument("--disconnect-after", type=float, default=5.0,
                       help="断网模拟：正常运行多少秒后触发断网，默认: 5.0")
    parser.add_argument("--disconnect-duration", type=float, default=1.0,
                       help="断网模拟：断网持续时间(秒)，默认: 1.0")

    args = parser.parse_args()

    # 在创建 ASRTTS 之前注入追踪子类，确保 ASRTTS 内部使用我们的子类
    if args.simulate_disconnect:
        _patch_asr_client()

    asr_tts = ASRTTS()

    queue_task = None
    disconnect_task = None
    try:
        queue_task = asyncio.create_task(monitor_queue(asr_tts))

        if args.simulate_disconnect:
            logger.info(
                f"[断网模拟] 已启用, WebSocket 直接断开, 无需 root: "
                f"{args.disconnect_after:.1f}s 后断网，"
                f"持续 {args.disconnect_duration:.1f}s 后恢复"
            )
            disconnect_task = asyncio.create_task(
                simulate_network_disconnect(
                    disconnect_after=args.disconnect_after,
                    disconnect_duration=args.disconnect_duration,
                )
            )

        await asr_tts.start_realtime_asr(silence_timeout_ms=args.silence_timeout)

    except KeyboardInterrupt:
        logger.info("收到中断信号，正在停止...")
    except Exception as e:
        logger.error(f"测试失败: {e}")
        raise
    finally:
        if disconnect_task and not disconnect_task.done():
            disconnect_task.cancel()
            try:
                await disconnect_task
            except asyncio.CancelledError:
                pass

        if queue_task:
            queue_task.cancel()
            try:
                await queue_task
            except asyncio.CancelledError:
                pass

        asr_tts.audio_device.cleanup()
        logger.info("测试结束，资源已清理")


if __name__ == "__main__":
    asyncio.run(main())
