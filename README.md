# unitree G1 Robot Chat Library
本项目是宇树机器人G1的对话库

## 安装
### 硬件

### 软件
本项目使用asr, llm, tts都是火山引擎的api
```
sudo apt-get install portaudio19-dev
```
#### ASR
获取API KEY, 具体咨询火山引擎
```

```
## 使用
```
# 查看包含`USB`字符串的音频设备名
python -m g1chat.tools.audio_device_list --device USB

# mp3 文件 转成 wav 文件
python -m g1chat.tools.convert_mp3_wav assets/check_speaker.mp3 assets/check_speaker.wav

# 显示wav文件信息
python -m g1chat.tools.wav_info assets/check_speaker.wav

# 实时播放音频
python -m g1chat.tools.check_audio_device

# 测试豆包ASR
python -m g1chat.tools.doubao_asr --mode file --file assets/check_speaker.wav
python -m g1chat.tools.doubao_asr --mode realtime

# 测试豆包TTS
python -m g1chat.tools.doubao_tts

# 测试集合豆包ASR—TTS的类
python -m g1chat.tools.doubao_asrtts_asr
 python -m g1chat.tools.doubao_asrtts_tts --count 10
```
### python 启动

### rosbridge

### ros node