import time
import os
import wave
from typing import Optional
import asyncio
import numpy as np
import io
from pydub import AudioSegment

from g1chat.audio.audio_device import AudioDevice
from g1chat.audio.volcengine_doubao_asr import AsrWsClient
from g1chat.utils.logging import default_logger as logger


def record_and_playback(duration: float = 5.0, enable_aec: bool = False, monitor: bool = True,) -> None:
    """
    使用 AudioDevice 录音一段时间：
    1. 实时从扬声器监听
    2. 同时把录音内容保存为 WAV 文件
    """
    device = AudioDevice(enable_aec=enable_aec)

    try:
        device.start_streams()
        logger.info(f"开始录音并实时回放 {duration} 秒，请对着麦克风说话...")

        frames = []  # 经过限幅后的录音数据，用于最终保存

        # 目标采样点数
        target_frames = int(duration * device.sample_rate)
        collected_frames = 0

        # 录音阶段：从 recording_queue 取数据，同时立刻送入播放队列，实现实时监听
        # 流程：
        #   1. 先做软件限幅，避免数字削波带来的爆破音
        #   2. 保存到 frames（用于写 WAV）
        #   3. 对要实时播放的音频再做简单低通 + 衰减，减少啸叫和高频噪声
        # 循环直到累计的采样点数达到目标长度
        while collected_frames < target_frames:
            data = device.get_recorded_data(block=True, timeout=1.0)
            if data:
                # 步骤 1：软件限幅（limiter），先在 float32 域操作
                audio_f = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                peak = np.max(np.abs(audio_f)) if audio_f.size > 0 else 0.0
                # 目标峰值略低于 int16 上限，留更多 headroom，进一步减少爆破感
                target_peak = 22000.0
                if peak > target_peak and peak > 0:
                    gain = target_peak / peak
                    audio_f *= gain
                # 转回 int16，作为“干净版本”保存和后续处理的基础
                limited_int16 = np.clip(audio_f, -32768, 32767).astype(np.int16)

                # 步骤 2：保存到 frames，用于写 WAV（这样导出的文件也不会数字削波）
                frames.append(limited_int16.tobytes())
                collected_frames += limited_int16.size

                # 步骤 3：实时回放用的版本，再做简单低通 + 额外衰减
                play_f = limited_int16.astype(np.float32)
                if play_f.size > 4:
                    kernel = np.ones(5, dtype=np.float32) / 5.0
                    play_f = np.convolve(play_f, kernel, mode="same")
                if monitor:
                    # 监听音量再降低一点，减少声学反馈
                    play_f *= 0.05
                    play_int16 = np.clip(play_f, -32768, 32767).astype(np.int16)
                    device.put_playback_data(play_int16.tobytes())

        # 录音时间结束后，把录音队列里尚未消费完的数据也读出来，避免只保存到一部分音频
        while True:
            extra = device.get_recorded_data(block=False)
            if not extra:
                break
            audio_f = np.frombuffer(extra, dtype=np.int16).astype(np.float32)
            peak = np.max(np.abs(audio_f)) if audio_f.size > 0 else 0.0
            target_peak = 22000.0
            if peak > target_peak and peak > 0:
                gain = target_peak / peak
                audio_f *= gain
            limited_int16 = np.clip(audio_f, -32768, 32767).astype(np.int16)
            frames.append(limited_int16.tobytes())

        logger.info(f"录音结束，期间采集到 {len(frames)} 个音频块（已实时回放）。")

        # 把录音内容保存为 WAV 文件（使用设备当前的采样率 / 通道 / 采样位宽）
        if frames:
            filename = f"record_{int(time.time())}.wav"
            filepath = os.path.abspath(filename)
            with wave.open(filepath, "wb") as wf:
                wf.setnchannels(device.channels)
                wf.setsampwidth(device.p.get_sample_size(device.format))
                wf.setframerate(device.sample_rate)
                all_data = b"".join(frames)
                wf.writeframes(all_data)

            bytes_per_second = 2 * device.channels * device.sample_rate
            approx_seconds = len(all_data) / bytes_per_second if bytes_per_second > 0 else 0
            logger.info(
                f"录音内容已保存到: {filepath} "
                f"(按 header 估算时长约 {approx_seconds:.2f} 秒, sample_rate={device.sample_rate})"
            )
        else:
            logger.info("未采集到任何音频数据，未生成录音文件。")

    finally:
        device.cleanup()


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


def convert_mp3_to_pcm(mp3_data: bytes, target_sample_rate: int = 16000) -> bytes:
    """
    将 MP3 音频数据转换为 PCM 格式
    
    Args:
        mp3_data: MP3 格式的音频数据（字节流）
        target_sample_rate: 目标采样率，默认 16000 Hz
    
    Returns:
        PCM 格式的音频数据（字节流），如果转换失败则返回空字节流
    """
    try:
        # 使用 pydub 从字节流加载 MP3 数据
        audio = AudioSegment.from_file(io.BytesIO(mp3_data), format="mp3")
        
        # 转换为单声道
        audio = audio.set_channels(1)
        
        # 转换采样率到目标采样率
        audio = audio.set_frame_rate(target_sample_rate)
        
        # 转换为 16 位 PCM（2 字节 = 16 位）
        audio = audio.set_sample_width(2)
        
        # 获取原始 PCM 数据
        pcm_data = audio.raw_data
        
        return pcm_data
    except Exception as e:
        logger.error(f"转换MP3到PCM失败: {e}")
        return b""


def get_resource_id(voice: str) -> str:
    """
    根据语音类型获取资源 ID
    
    Args:
        voice: 语音类型字符串，如果以 "S_" 开头则使用默认资源，否则使用服务类型资源
    
    Returns:
        资源 ID 字符串
    """
    if voice.startswith("S_"):
        return "volc.megatts.default"
    return "volc.service_type.10029"











