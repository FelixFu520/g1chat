import asyncio
from g1chat.g1chat import G1Chat
from g1chat.utils.logging import default_logger as logger

async def main():
    """示例：运行 G1Chat 直到 Ctrl+C。"""
    chat = G1Chat()
    await chat.start()
    try:
        # 永久等待，Ctrl+C 会取消当前任务并触发 finally
        await asyncio.Future()
    except asyncio.CancelledError:
        logger.info("收到中断，正在停止...")
    finally:
        await chat.stop()


if __name__ == "__main__":
    asyncio.run(main())