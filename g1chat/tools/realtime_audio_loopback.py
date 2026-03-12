import pyaudio
import numpy as np
import threading
import time
import sys
import argparse
from collections import deque

from g1chat.utils.logging import default_logger as logger

class RealtimeAudioLoopback:
    def __init__(self, input_device_name="USB", output_device_name="USB", 
                 buffer_size=1024, auto_gain=True, delay_ms=100, volume_boost=1.0):
        """
        实时音频回环播放
        
        Args:
            input_device_name: 录音设备名称关键字
            output_device_name: 播放设备名称关键字  
            buffer_size: 音频缓冲区大小
            auto_gain: 是否启用自动增益控制
            delay_ms: 播放延迟（毫秒）
            volume_boost: 额外音量增强倍数（默认1.0，可设置更大值如2.0）
        """
        self.input_device_name = input_device_name
        self.output_device_name = output_device_name
        self.buffer_size = buffer_size
        self.auto_gain = auto_gain
        self.delay_ms = delay_ms
        self.volume_boost = volume_boost  # 额外音量增强
        
        self.p = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        self.is_running = False
        
        # 音频参数
        self.format = pyaudio.paFloat32
        self.channels = 1
        self.rate = 24000
        
        # 音频缓冲队列
        self.audio_buffer = deque()
        self.buffer_lock = threading.Lock()
        
        # 自动增益控制参数
        self.current_gain = 1.0
        self.target_level = 0.9  # 目标音量水平（90%）- 提高目标音量
        self.max_gain = 50.0     # 最大增益倍数 - 增加最大增益
        self.min_gain = 0.1      # 最小增益倍数
        self.gain_attack = 0.99  # 增益下降速度（防止破音）
        self.gain_release = 1.001 # 增益上升速度（缓慢增加）
        
        # 音频限制器参数
        self.limiter_threshold = 0.98  # 限制器阈值 - 提高阈值允许更大音量
        self.limiter_ratio = 5.0       # 压缩比 - 降低压缩比保留更多动态
        self.limiter_attack = 0.95     # 限制器快速响应
        
        # 音量历史记录（用于平滑处理）
        self.volume_history = deque(maxlen=10)
        self.peak_history = deque(maxlen=50)
        
        # 统计信息
        self.input_volume = 0
        self.output_volume = 0
        self.buffer_length = 0
        self.current_peak = 0
        self.gain_reduction = 0
        
    def get_device_by_name(self, name: str, is_input: bool = True) -> int:
        """根据名称查找音频设备"""
        for i in range(self.p.get_device_count()):
            try:
                dev_info = self.p.get_device_info_by_index(i)
                if name in dev_info['name']:
                    # 检查设备是否支持所需的输入/输出
                    if is_input and dev_info['maxInputChannels'] > 0:
                        return i
                    elif not is_input and dev_info['maxOutputChannels'] > 0:
                        return i
            except Exception as e:
                logger.error(f"检查设备 {i} 时出错: {e}")
        return -1
    
    def test_sample_rate(self, device_id, is_input=True, test_rates=None):
        """测试设备支持的采样率"""
        if test_rates is None:
            test_rates = [44100, 48000, 22050, 24000, 16000, 8000]
        
        for rate in test_rates:
            try:
                if is_input:
                    test_stream = self.p.open(
                        format=self.format,
                        channels=self.channels,
                        rate=rate,
                        input=True,
                        input_device_index=device_id,
                        frames_per_buffer=self.buffer_size
                    )
                else:
                    test_stream = self.p.open(
                        format=self.format,
                        channels=self.channels,
                        rate=rate,
                        output=True,
                        output_device_index=device_id,
                        frames_per_buffer=self.buffer_size
                    )
                test_stream.close()
                return rate
            except Exception as e:
                continue
        return None

    def setup_devices(self):
        """设置录音和播放设备"""
        # 查找录音设备
        input_device_id = self.get_device_by_name(self.input_device_name, True)
        if input_device_id == -1:
            raise ValueError(f"未找到录音设备: {self.input_device_name}")
        
        # 查找播放设备
        output_device_id = self.get_device_by_name(self.output_device_name, False)
        if output_device_id == -1:
            raise ValueError(f"未找到播放设备: {self.output_device_name}")
        
        input_info = self.p.get_device_info_by_index(input_device_id)
        output_info = self.p.get_device_info_by_index(output_device_id)
        
        logger.info(f"录音设备: {input_info['name']} (索引: {input_device_id})")
        logger.info(f"  默认采样率: {input_info['defaultSampleRate']} Hz")
        logger.info(f"  最大输入通道: {input_info['maxInputChannels']}")
        
        logger.info(f"播放设备: {output_info['name']} (索引: {output_device_id})")
        logger.info(f"  默认采样率: {output_info['defaultSampleRate']} Hz")
        logger.info(f"  最大输出通道: {output_info['maxOutputChannels']}")
        
        # 测试录音设备支持的采样率
        logger.info("正在测试录音设备支持的采样率...")
        input_rate = self.test_sample_rate(input_device_id, True)
        if input_rate is None:
            # 尝试使用设备默认采样率
            input_rate = int(input_info['defaultSampleRate'])
            logger.info(f"使用录音设备默认采样率: {input_rate} Hz")
        else:
            logger.info(f"录音设备支持的采样率: {input_rate} Hz")
        
        # 测试播放设备支持的采样率
        logger.info("正在测试播放设备支持的采样率...")
        output_rate = self.test_sample_rate(output_device_id, False)
        if output_rate is None:
            # 尝试使用设备默认采样率
            output_rate = int(output_info['defaultSampleRate'])
            logger.info(f"使用播放设备默认采样率: {output_rate} Hz")
        else:
            logger.info(f"播放设备支持的采样率: {output_rate} Hz")
        
        # 使用两个设备都支持的采样率
        if input_rate == output_rate:
            self.rate = input_rate
        else:
            # 如果不同，选择较低的采样率或常用的44100
            common_rates = [44100, 48000, 22050, 16000]
            for rate in common_rates:
                input_test = self.test_sample_rate(input_device_id, True, [rate])
                output_test = self.test_sample_rate(output_device_id, False, [rate])
                if input_test and output_test:
                    self.rate = rate
                    break
            else:
                # 如果都不支持，使用较低的
                self.rate = min(input_rate, output_rate)
        
        logger.info(f"最终使用采样率: {self.rate} Hz")
        logger.info(f"音频参数: {self.channels}声道, {self.rate}Hz, 缓冲区{self.buffer_size}")
        if self.auto_gain:
            logger.info(f"自动增益控制: 启用 (目标音量: {self.target_level*100:.0f}%, 最大增益: {self.max_gain}x)")
            logger.info(f"音频限制器: 启用 (阈值: {self.limiter_threshold*100:.0f}%, 压缩比: {self.limiter_ratio:.1f}:1)")
        else:
            logger.info(f"自动增益控制: 禁用")
        logger.info(f"音量增强: {self.volume_boost}x")
        logger.info(f"延迟: {self.delay_ms}ms")
        
        return input_device_id, output_device_id
    
    def apply_auto_gain_control(self, audio_data):
        """应用自动增益控制"""
        if not self.auto_gain:
            return audio_data
        
        # 计算当前音量（RMS）
        rms = np.sqrt(np.mean(audio_data**2))
        
        # 计算峰值
        peak = np.max(np.abs(audio_data))
        self.current_peak = peak
        
        # 记录音量历史
        self.volume_history.append(rms)
        self.peak_history.append(peak)
        
        # 计算平均音量（平滑处理）
        avg_volume = np.mean(self.volume_history) if self.volume_history else rms
        avg_peak = np.mean(self.peak_history) if self.peak_history else peak
        
        # 自动增益控制
        if avg_volume > 0:
            # 计算理想增益
            ideal_gain = self.target_level / avg_volume
            ideal_gain = np.clip(ideal_gain, self.min_gain, self.max_gain)
            
            # 如果峰值过高，快速降低增益（防止破音）
            if avg_peak * self.current_gain > self.limiter_threshold:
                self.current_gain *= self.gain_attack
            else:
                # 缓慢调整到理想增益
                if self.current_gain < ideal_gain:
                    self.current_gain *= self.gain_release
                elif self.current_gain > ideal_gain:
                    self.current_gain *= self.gain_attack
        
        # 限制增益范围
        self.current_gain = np.clip(self.current_gain, self.min_gain, self.max_gain)
        
        # 应用增益
        gained_audio = audio_data * self.current_gain
        
        return gained_audio
    
    def apply_limiter(self, audio_data):
        """应用音频限制器防止削波"""
        # 计算峰值
        peak = np.max(np.abs(audio_data))
        
        if peak > self.limiter_threshold:
            # 计算压缩比
            excess = peak - self.limiter_threshold
            reduction = excess / self.limiter_ratio
            
            # 计算增益衰减
            gain_reduction = (self.limiter_threshold + reduction) / peak
            self.gain_reduction = (1.0 - gain_reduction) * 100
            
            # 应用限制
            limited_audio = audio_data * gain_reduction
        else:
            limited_audio = audio_data
            self.gain_reduction = 0
        
        # 最终安全限制
        limited_audio = np.clip(limited_audio, -0.99, 0.99)
        
        return limited_audio
    
    def process_audio(self, audio_data):
        """完整的音频处理流程"""
        # 1. 自动增益控制
        gained_audio = self.apply_auto_gain_control(audio_data)
        
        # 2. 应用额外音量增强
        boosted_audio = gained_audio * self.volume_boost
        
        # 3. 音频限制器
        processed_audio = self.apply_limiter(boosted_audio)
        
        return processed_audio
    
    def audio_input_callback(self, in_data, frame_count, time_info, status):
        """录音回调函数"""
        if status:
            logger.info(f"录音状态: {status}")
        
        try:
            # 将字节数据转换为numpy数组
            audio_data = np.frombuffer(in_data, dtype=np.float32)
            
            # 计算输入音量
            self.input_volume = np.sqrt(np.mean(audio_data**2)) * 100
            
            # 应用音频处理（自动增益控制 + 限制器）
            processed_audio = self.process_audio(audio_data)
            
            # 添加到缓冲队列
            with self.buffer_lock:
                self.audio_buffer.append(processed_audio)
                self.buffer_length = len(self.audio_buffer)
                
                # 限制缓冲区大小，防止延迟过大
                max_buffer_size = max(10, int(self.delay_ms * self.rate / 1000 / self.buffer_size))
                while len(self.audio_buffer) > max_buffer_size:
                    self.audio_buffer.popleft()
            
        except Exception as e:
            logger.error(f"录音回调错误: {e}")
        
        return (None, pyaudio.paContinue)
    
    def audio_output_callback(self, in_data, frame_count, time_info, status):
        """播放回调函数"""
        if status:
            logger.info(f"播放状态: {status}")
        
        try:
            with self.buffer_lock:
                if self.audio_buffer:
                    # 从缓冲队列取出音频数据
                    audio_data = self.audio_buffer.popleft()
                    self.buffer_length = len(self.audio_buffer)
                    
                    # 计算输出音量
                    self.output_volume = np.sqrt(np.mean(audio_data**2)) * 100
                    
                    # 确保数据长度匹配
                    if len(audio_data) < frame_count:
                        # 如果数据不够，用零填充
                        padded_data = np.zeros(frame_count, dtype=np.float32)
                        padded_data[:len(audio_data)] = audio_data
                        audio_data = padded_data
                    elif len(audio_data) > frame_count:
                        # 如果数据太多，截取
                        audio_data = audio_data[:frame_count]
                    
                    return (audio_data.tobytes(), pyaudio.paContinue)
                else:
                    # 没有数据时播放静音
                    silence = np.zeros(frame_count, dtype=np.float32)
                    return (silence.tobytes(), pyaudio.paContinue)
        
        except Exception as e:
            logger.error(f"播放回调错误: {e}")
            silence = np.zeros(frame_count, dtype=np.float32)
            return (silence.tobytes(), pyaudio.paContinue)
    
    def start(self):
        """开始实时音频回环"""
        try:
            input_device_id, output_device_id = self.setup_devices()
            
            # 创建录音流
            self.input_stream = self.p.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                input_device_index=input_device_id,
                frames_per_buffer=self.buffer_size,
                stream_callback=self.audio_input_callback
            )
            
            # 创建播放流
            self.output_stream = self.p.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                output=True,
                output_device_index=output_device_id,
                frames_per_buffer=self.buffer_size,
                stream_callback=self.audio_output_callback
            )
            
            # 启动音频流
            self.input_stream.start_stream()
            self.output_stream.start_stream()
            self.is_running = True
            
            logger.info("\n实时音频回环已启动!")
            logger.info("按 Ctrl+C 停止...")
            
            # 显示实时状态
            self.show_status()
            
        except Exception as e:
            logger.error(f"启动音频回环失败: {e}")
            self.stop()
    
    def show_status(self):
        """显示实时状态信息"""
        try:
            while self.is_running:
                delay_ms = self.buffer_length * self.buffer_size / self.rate * 1000 if self.rate > 0 else 0
                
                if self.auto_gain:
                    sys.stdout.write(f"\r输入: {self.input_volume:5.1f}% | "
                                   f"输出: {self.output_volume:5.1f}% | "
                                   f"增益: {self.current_gain:5.2f}x | "
                                   f"峰值: {self.current_peak:4.2f} | "
                                   f"限制: {self.gain_reduction:4.1f}% | "
                                   f"缓冲: {self.buffer_length:2d} | "
                                   f"延迟: {delay_ms:.0f}ms")
                else:
                    sys.stdout.write(f"\r输入音量: {self.input_volume:5.1f}% | "
                                   f"输出音量: {self.output_volume:5.1f}% | "
                                   f"缓冲区: {self.buffer_length:3d} | "
                                   f"延迟: {delay_ms:.0f}ms")
                
                sys.stdout.flush()
                time.sleep(0.1)
        except KeyboardInterrupt:
            logger.info("\n\n收到停止信号...")
            self.stop()
    
    def stop(self):
        """停止音频回环"""
        self.is_running = False
        
        if self.input_stream:
            self.input_stream.stop_stream()
            self.input_stream.close()
        
        if self.output_stream:
            self.output_stream.stop_stream()
            self.output_stream.close()
        
        self.p.terminate()
        logger.info("音频回环已停止")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="实时音频回环程序")
    parser.add_argument("--device_mic", type=str, default="USB", help="录音设备名称关键字")
    parser.add_argument("--device_speaker", type=str, default="USB", help="录音设备名称关键字")
    args = parser.parse_args()
    
    logger.info("实时音频回环程序")
    logger.info("=" * 50)
    
    # 创建音频回环实例
    # 可以调整以下参数：
    # - input_device_name: 录音设备名称关键字
    # - output_device_name: 播放设备名称关键字
    # - buffer_size: 缓冲区大小（影响延迟）
    # - volume_boost: 音量增强倍数
    # - delay_ms: 额外延迟（毫秒）
    
    loopback = RealtimeAudioLoopback(
        input_device_name=args.device_mic,      # 录音设备
        output_device_name=args.device_speaker,     # 播放设备
        buffer_size=512,              # 较小的缓冲区减少延迟
        auto_gain=True,               # 启用自动增益控制
        delay_ms=50,                  # 50ms额外延迟
        volume_boost=4.0              # 2倍音量增强 - 可根据需要调整
    )
    
    try:
        loopback.start()
    except KeyboardInterrupt:
        logger.error("\n程序被用户中断")
    except Exception as e:
        logger.error(f"程序出错: {e}")
    finally:
        loopback.stop()

if __name__ == "__main__":
    main()
