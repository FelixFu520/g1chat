#!/usr/bin/env python3
"""
豆包ASR测试脚本
测试豆包语音识别服务，支持文件ASR和实时录音ASR两种模式

用法：
    文件ASR: python3 03_doubao_asr.py --mode file --file /path/to/audio.wav
    实时录音ASR: python3 03_doubao_asr.py --mode realtime --duration 100
"""

import argparse
import wave
import asyncio
import numpy as np

from g1chat.audio.audio_device import AudioDevice
from g1chat.audio.volcengine_doubao_asr import AsrWsClient
from g1chat.utils.logging import default_logger as logger


async def test_file_asr(url: str, seg_duration: int, file: str):
    """
    测试文件ASR识别
    
    Args:
        url: WebSocket服务器URL
        seg_duration: 音频片段时长(毫秒)
        file: 音频文件路径
    """
    logger.info("=== 测试文件ASR ===")
    
    # 创建ASR客户端并执行文件识别
    async with AsrWsClient(url, seg_duration) as client:
        try:
            # 遍历识别结果
            async for response in client.execute(file):
                # 检查响应中是否包含识别文本
                if "text" in response.to_dict()['payload_msg']['result']:
                    result = response.to_dict()['payload_msg']['result']
                    text = result['text']
                    # 获取识别结果的确定状态
                    is_definite = result['utterances'][0]['definite']
                    logger.info(f"{text}   {is_definite}")
        except Exception as e:
            logger.error(f"ASR processing failed: {e}")


def resample_pcm(pcm_data, src_rate, dst_rate, channels):
    """
    使用线性插值将int16 PCM数据从src_rate重采样到dst_rate。

    Args:
        pcm_data: 原始PCM数据(bytes), int16格式
        src_rate: 原始采样率
        dst_rate: 目标采样率
        channels: 声道数

    Returns:
        重采样后的PCM数据(bytes), int16格式
    """
    if src_rate == dst_rate or not pcm_data:
        return pcm_data

    audio = np.frombuffer(pcm_data, dtype=np.int16)

    if channels > 1:
        # [num_samples * channels] -> [num_frames, channels]
        num_frames = audio.size // channels
        if num_frames == 0:
            return b""
        audio = audio[: num_frames * channels].reshape(num_frames, channels)
    else:
        if audio.size == 0:
            return b""
        num_frames = audio.size
        audio = audio.reshape(num_frames, 1)

    src_len = audio.shape[0]
    dst_len = max(1, int(round(src_len * dst_rate / src_rate)))

    # 构造时间轴，使用线性插值进行重采样
    x_old = np.linspace(0.0, 1.0, src_len, endpoint=False)
    x_new = np.linspace(0.0, 1.0, dst_len, endpoint=False)

    resampled = np.empty((dst_len, channels), dtype=np.float32)
    for ch in range(channels):
        resampled[:, ch] = np.interp(x_new, x_old, audio[:, ch].astype(np.float32))

    # 限幅并转换回int16
    resampled = np.clip(resampled, -32768, 32767).astype(np.int16)

    if channels == 1:
        resampled = resampled.reshape(-1)

    return resampled.tobytes()


def create_wav_chunk(pcm_data, sample_rate, channels):
    """
    创建WAV格式的音频数据
    
    Args:
        pcm_data: PCM原始音频数据(bytes)
        sample_rate: 采样率(Hz)
        channels: 声道数
        
    Returns:
        WAV格式的音频数据(bytes)
    """
    import io
    
    # 创建内存缓冲区
    buffer = io.BytesIO()
    
    # 写入WAV文件头和数据
    with wave.open(buffer, 'wb') as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)  # 16-bit，每个样本2字节
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    
    # 返回完整的WAV文件数据
    return buffer.getvalue()


async def realtime_audio_generator(audio_device: AudioDevice, duration_seconds: int = 10, chunk_duration_ms: int = 200, sample_rate: int = 16000):
    """
    实时音频生成器, 从AudioDevice录音并产生音频片段
    
    Args:
        audio_device: AudioDevice实例
        duration_seconds: 录音时长(秒), None表示无限录音
        chunk_duration_ms: 每个音频片段的时长(毫秒)
        sample_rate: 目标采样率(Hz), None表示使用AudioDevice的采样率
        
    Yields:
        音频数据片段(bytes), WAV格式
    """
    # 获取音频设备参数
    device_sample_rate = audio_device.sample_rate
    channels = audio_device.channels
    chunk_size = audio_device.chunk_size

    # 目标输出采样率
    target_sample_rate = sample_rate if sample_rate else device_sample_rate
    
    # 计算每个chunk的字节数
    samples_per_chunk = chunk_size
    bytes_per_sample = 2  # int16格式，每个样本2字节
    bytes_per_chunk = samples_per_chunk * channels * bytes_per_sample
    
    # 计算需要累积多少个chunk才能达到目标时长
    # 目标字节数 = 设备采样率 × 声道数 × 每样本字节数 × 时长(秒)
    # 这里按设备采样率来累计时长，随后再做重采样
    target_bytes = int(device_sample_rate * channels * bytes_per_sample * chunk_duration_ms / 1000)
    chunks_needed = max(1, target_bytes // bytes_per_chunk)
    
    logger.info(
        f"实时录音配置: 设备采样率={device_sample_rate}, 输出采样率={target_sample_rate}, "
        f"块大小={chunk_size}, 每{chunk_duration_ms}ms发送一次"
    )
    logger.info(f"每次发送需要累积 {chunks_needed} 个chunk, 约 {target_bytes} 字节")
    
    # 初始化录音状态
    start_time = asyncio.get_event_loop().time()
    accumulated_data = b''  # 累积的音频数据
    chunk_count = 0         # 已累积的chunk数量
    
    try:
        while True:
            # 检查是否达到录音时长限制
            if duration_seconds is not None:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= duration_seconds:
                    logger.info(f"录音时长达到 {duration_seconds} 秒，停止录音")
                    break
            
            # 异步获取录音数据，超时时间1秒
            audio_chunk = await audio_device.async_get_recorded_data(timeout=1.0)
            if audio_chunk is None:
                continue
            
            # 累积音频数据
            accumulated_data += audio_chunk
            chunk_count += 1
            
            # 当累积足够的数据后，转换为WAV格式并发送
            if chunk_count >= chunks_needed:
                # 根据需要重采样后，再将PCM数据转换为WAV格式
                pcm_data = accumulated_data
                if target_sample_rate != device_sample_rate:
                    pcm_data = resample_pcm(
                        pcm_data,
                        device_sample_rate,
                        target_sample_rate,
                        channels,
                    )
                wav_data = create_wav_chunk(pcm_data, target_sample_rate, channels)
                yield wav_data
                
                # 重置累积状态，准备下一批数据
                accumulated_data = b''
                chunk_count = 0
        
        # 发送剩余的音频数据（如果有）
        if accumulated_data:
            pcm_data = accumulated_data
            if target_sample_rate != device_sample_rate:
                pcm_data = resample_pcm(
                    pcm_data,
                    device_sample_rate,
                    target_sample_rate,
                    channels,
                )
            wav_data = create_wav_chunk(pcm_data, target_sample_rate, channels)
            yield wav_data
        
        # 发送结束信号（None表示音频流结束）
        yield None
        
    except Exception as e:
        logger.error(f"录音生成器错误: {e}")
        raise


async def test_realtime_asr(url: str, seg_duration: int, duration: int):
    """
    测试实时录音ASR识别
    
    Args:
        url: WebSocket服务器URL
        seg_duration: 音频片段时长(毫秒)
        duration: 录音时长(秒)
    """
    logger.info("=== 测试实时录音ASR ===")
    
    # 创建音频设备，配置录音参数
    audio_device = AudioDevice(
        channels=1,         # 单声道
        chunk_size=1024,    # 每次读取1024个样本
        enable_aec=False    # 实时ASR测试时可以关闭回声消除
    )
    
    try:
        # 启动音频输入流
        audio_device.start_streams()        
        logger.info(f"开始录音，时长: {duration} 秒")
        logger.info("请开始说话...")
        
        # 创建ASR客户端并开始识别
        async with AsrWsClient(url, seg_duration) as client:
            # 创建实时音频生成器，将录音数据转换为WAV格式片段
            audio_stream = realtime_audio_generator(
                audio_device,
                duration_seconds=duration,
                chunk_duration_ms=seg_duration
            )
            
            # 开始实时ASR识别，处理音频流
            try:
                async for response in client.execute_stream(audio_stream):
                    # 解析响应数据
                    resp_dict = response.to_dict()
                    
                    # 检查响应中是否包含识别结果
                    if resp_dict.get('payload_msg') and 'result' in resp_dict['payload_msg']:
                        result = resp_dict['payload_msg']['result']
                        
                        # 如果包含识别文本，则输出
                        if 'text' in result:
                            text = result['text']
                            # 获取识别结果的确定状态（是否为最终结果）
                            is_definite = result.get('utterances', [{}])[0].get('definite', False) if result.get('utterances') else False
                            logger.info(f"[{'确定' if is_definite else '临时'}] {text}")
                            
            except Exception as e:
                logger.error(f"实时ASR处理失败: {e}")
                raise
                
    finally:
        # 清理音频设备资源
        audio_device.cleanup()
        logger.info("音频设备已清理")


async def main():
    """
    主函数，解析命令行参数并执行相应的测试模式
    """
    parser = argparse.ArgumentParser(description="豆包ASR WebSocket客户端测试工具")
    
    # 添加命令行参数
    parser.add_argument("--mode", type=str, choices=['file', 'realtime'], default='realtime',
                       help="测试模式: file=文件ASR, realtime=实时录音ASR(默认: realtime)")
    parser.add_argument("--file", type=str, 
                       default="/home/drobotics/projects/robota/assets/xiaozhan_ref_16000_concatenated.wav", 
                       help="音频文件路径(用于file模式)")
    parser.add_argument("--url", type=str, 
                       default="wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async", 
                       help="WebSocket服务器URL")
    parser.add_argument("--seg-duration", type=int, default=200, 
                       help="每个音频包的时长(毫秒), 默认: 200")
    parser.add_argument("--duration", type=int, default=10,
                       help="录音时长(秒), 仅用于realtime模式, 默认: 10")
    
    # 解析命令行参数
    args = parser.parse_args()
    
    # 根据模式执行相应的测试
    if args.mode == 'file':
        await test_file_asr(args.url, args.seg_duration, args.file)
    elif args.mode == 'realtime':
        await test_realtime_asr(args.url, args.seg_duration, args.duration)


if __name__ == "__main__":
    asyncio.run(main())