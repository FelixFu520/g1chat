import pyaudio
import wave
import time
import sys
import numpy as np
import argparse

from g1chat.utils.logging import default_logger as logger


def record_audio(output_filename="output.wav", record_seconds=20, device_index=0, dst_rate=16000, chunk_size=1024):
    # 初始化 PyAudio
    p = pyaudio.PyAudio()
    
    # 获取指定设备的信息
    try:
        device_info = p.get_device_info_by_index(device_index)
        logger.info(f"\n选择的设备信息:")
        logger.info(f"  名称: {device_info['name']}")
        logger.info(f"  输入通道数: {device_info['maxInputChannels']}")
        logger.info(f"  默认采样率: {device_info['defaultSampleRate']}")
        logger.info(f"  设备索引: {device_index}")
        logger.info(f"  目标采样率: {dst_rate}")
            
        # 音频参数设置
        FORMAT = pyaudio.paInt16    # 采样格式
        CHANNELS = 2 if device_info['maxInputChannels'] >= 2 else 1  # 根据设备支持的通道数设置
        RATE = int(device_info['defaultSampleRate'])  # 使用设备默认采样率
        DST_RATE = dst_rate
        CHUNK = int(chunk_size * RATE / DST_RATE)               # 每个缓冲区的帧数
        DST_CHUNK = chunk_size

        # 打开音频流
        stream = p.open(format=FORMAT,
                       channels=CHANNELS,
                       rate=RATE,
                       input=True,
                       input_device_index=device_index,
                       frames_per_buffer=CHUNK)
        
        logger.info(f"\n开始录音，持续 {record_seconds} 秒...")
        frames = []
        
        start_time = time.time()
        while time.time() - start_time < record_seconds:
            sys.stdout.write(f"\r录音进度: {(time.time() - start_time)/record_seconds*100:.1f}%")
            sys.stdout.flush()
            data = stream.read(CHUNK)
            # 重采样
            audio_array = np.frombuffer(data, dtype=np.int16)
            # 重采样到目标大小
            resampled = np.interp(
                np.linspace(0, len(audio_array), DST_CHUNK),
                np.arange(len(audio_array)),
                audio_array
            ).astype(np.int16)
        
            frames.append(resampled.tobytes())
            
        logger.info("\n录音完成!")
        
        # 停止并关闭音频流
        stream.stop_stream()
        stream.close()
        
        # 保存录音文件
        wf = wave.open(output_filename, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(DST_RATE)
        wf.writeframes(b''.join(frames))
        wf.close()
        
        logger.info(f"录音已保存到: {output_filename}")
        
    except Exception as e:
        logger.error(f"录音过程中出现错误: {str(e)}")
    
    finally:
        # 终止 PyAudio
        p.terminate()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=str, default="output.wav")
    parser.add_argument("--record_seconds", type=int, default=10)
    parser.add_argument("--device_index", type=int, default=0)
    parser.add_argument("--dst_rate", type=int, default=16000)
    parser.add_argument("--chunk_size", type=int, default=1024)
    args = parser.parse_args()
    # 默认录制5秒钟的音频
    record_audio(args.output, args.record_seconds, args.device_index, args.dst_rate, args.chunk_size)
