import pyaudio
import wave
import argparse
import numpy as np
import subprocess

from g1chat.utils.logging import default_logger as logger


def get_device_sample_rate(p, device_index):
    """获取设备支持的采样率"""
    try:
        device_info = p.get_device_info_by_index(device_index)
        default_rate = int(device_info['defaultSampleRate'])
        
        # 测试常用采样率
        test_rates = [44100, 48000, 22050, 24000, 16000, 8000, default_rate]
        
        for rate in test_rates:
            try:
                test_stream = p.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=rate,
                    output=True,
                    output_device_index=device_index,
                    frames_per_buffer=1024
                )
                test_stream.close()
                return rate
            except:
                continue
        
        return default_rate
    except:
        return 44100  # 默认采样率

def resample_audio(audio_data, original_rate, target_rate):
    """重采样音频数据"""
    if original_rate == target_rate:
        return audio_data
    
    # 计算重采样后的长度
    target_length = int(len(audio_data) * target_rate / original_rate)
    
    # 使用线性插值进行重采样
    resampled = np.interp(
        np.linspace(0, len(audio_data), target_length),
        np.arange(len(audio_data)),
        audio_data
    ).astype(audio_data.dtype)
    
    return resampled

def apply_limiter(audio_data, threshold=0.95, ratio=5.0):
    """应用音频限制器防止削波"""
    # 将int16数据转换为float32进行处理，范围[-1, 1]
    audio_float = audio_data.astype(np.float32) / 32767.0
    
    # 计算峰值
    peak = np.max(np.abs(audio_float))
    
    if peak > threshold:
        # 计算压缩比
        excess = peak - threshold
        reduction = excess / ratio
        
        # 计算增益衰减
        gain_reduction = (threshold + reduction) / peak
        
        # 应用限制
        limited_audio = audio_float * gain_reduction
    else:
        limited_audio = audio_float
    
    # 最终安全限制并转换回int16
    limited_audio = np.clip(limited_audio, -0.99, 0.99)
    return (limited_audio * 32767.0).astype(np.int16)

def process_audio_volume(audio_data, volume_boost=1.0, limiter_threshold=0.95):
    """完整的音频音量处理流程"""
    # 将int16数据转换为float32进行处理
    audio_float = audio_data.astype(np.float32) / 32767.0
    
    # 1. 应用音量增强
    boosted_audio = audio_float * volume_boost
    
    # 2. 转换回int16格式用于限制器处理
    boosted_int16 = np.clip(boosted_audio * 32767.0, -32767, 32767).astype(np.int16)
    
    # 3. 应用音频限制器
    processed_audio = apply_limiter(boosted_int16, limiter_threshold)
    
    return processed_audio

def unmute_and_set_system_volume(device_index=None, volume_percent=100):
    """
    取消音频设备静音并设置系统音量

    Args:
        device_index: PyAudio设备索引（可选，暂未使用）
        volume_percent: 音量百分比 (0-150)

    Returns:
        bool: 设置是否成功
    """
    try:
        # 方法1: 使用 pactl (PulseAudio) 取消静音并设置音量
        logger.info(f"正在设置系统音量为 {volume_percent}% 并取消静音...")

        # 获取所有sink列表
        result = subprocess.run(['pactl', 'list', 'short', 'sinks'], 
                              capture_output=True, text=True)

        if result.returncode == 0:
            sinks = result.stdout.strip().split('\n')
            if sinks and sinks[0]:
                logger.info(f"找到 {len(sinks)} 个音频输出设备")

                for sink_line in sinks:
                    if sink_line.strip():
                        sink_name = sink_line.split()[1]
                        # 取消静音
                        subprocess.run(['pactl', 'set-sink-mute', sink_name, '0'], 
                                     check=True)
                        # 设置音量
                        subprocess.run(['pactl', 'set-sink-volume', sink_name, 
                                      f'{volume_percent}%'], check=True)
                        logger.info(f"✓ 设备 {sink_name}: 音量={volume_percent}%, 静音已关闭")

                return True

        # 方法2: 如果 pactl 失败，尝试使用 amixer
        logger.info("pactl 命令失败，尝试使用 amixer...")
        subprocess.run(['amixer', 'sset', 'Master', 'unmute'], check=True)
        subprocess.run(['amixer', 'sset', 'Master', f'{volume_percent}%'], 
                     check=True)
        logger.info(f"✓ 已使用 amixer 设置: 音量={volume_percent}%, 静音已关闭")
        return True

    except FileNotFoundError as e:
        logger.error(f"⚠ 警告: 未找到音频控制命令 ({e})")
        logger.error("  建议安装: sudo apt-get install pulseaudio-utils alsa-utils")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"⚠ 警告: 执行音频命令时出错: {e}")
        return False
    except Exception as e:
        logger.error(f"⚠ 警告: 设置系统音量时出错: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav_file", type=str, default="xiaozhan_rate_16000.wav")
    parser.add_argument("--device_index", type=int, default=24)
    parser.add_argument("--volume_boost", type=float, default=1.0, help="音量放大倍数 (默认: 2.0)")
    parser.add_argument("--limiter_threshold", type=float, default=0.95, help="限制器阈值 (0-1, 默认: 0.95)")
    parser.add_argument("--system_volume", type=int, default=60, help="系统音量百分比 (0-150, 默认: 100)")
    parser.add_argument("--no_unmute", action="store_true", help="不自动取消静音和设置系统音量")
    args = parser.parse_args()  

    # 取消静音并设置系统音量
    if not args.no_unmute:
        unmute_and_set_system_volume(device_index=args.device_index, 
                                     volume_percent=args.system_volume)
        logger.info("-" * 60)

    # 打开WAV文件
    wave_file = wave.open(args.wav_file, 'rb')

    # 获取WAV文件的参数
    channels = wave_file.getnchannels()
    sample_width = wave_file.getsampwidth()
    frame_rate = wave_file.getframerate()
    n_frames = wave_file.getnframes()

    # 初始化PyAudio
    p = pyaudio.PyAudio()

    # 获取设备支持的采样率
    device_sample_rate = get_device_sample_rate(p, args.device_index)
    
    logger.info(f"WAV文件采样率: {frame_rate} Hz")
    logger.info(f"设备采样率: {device_sample_rate} Hz")
    logger.info(f"需要重采样: {'是' if frame_rate != device_sample_rate else '否'}")
    logger.info(f"音量放大倍数: {args.volume_boost}x")
    logger.info(f"限制器阈值: {args.limiter_threshold}")
    logger.info(f"p.get_format_from_width(sample_width):{p.get_format_from_width(sample_width)}")
    logger.info(f"channels:{channels}")
    logger.info(f"frame_rate:{frame_rate}")
    logger.info(f"n_frames:{n_frames}")
    logger.info(f"sample_width:{sample_width}")

    # 使用设备采样率创建音频流
    stream = p.open(format=p.get_format_from_width(sample_width),
                    channels=channels,
                    rate=device_sample_rate,
                    output_device_index=args.device_index,
                    output=True)
    try:
        logger.info("开始播放音频文件...")
        # 读取并播放音频数据
        chunk_size = 1024
        data = wave_file.readframes(chunk_size)
        
        while data:
            # 将字节数据转换为numpy数组
            audio_array = np.frombuffer(data, dtype=np.int16)
            
            # 如果需要重采样
            if frame_rate != device_sample_rate:
                # 重采样音频数据
                audio_array = resample_audio(audio_array, frame_rate, device_sample_rate)
            
            # 应用音量处理（放大 + 限制器）
            processed_array = process_audio_volume(
                audio_array, 
                volume_boost=args.volume_boost, 
                limiter_threshold=args.limiter_threshold
            )
            
            # 转换回字节数据并播放
            processed_data = processed_array.tobytes()
            stream.write(processed_data)
            
            data = wave_file.readframes(chunk_size)
        
        logger.info("播放完成！")

    finally:
        # 清理资源
        stream.stop_stream()
        stream.close()
        p.terminate()
        wave_file.close()