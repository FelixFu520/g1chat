# unitree G1 Robot Chat Library
本项目是宇树机器人G1的对话库

## 安装
```
sudo apt-get install portaudio19-dev
git clone https://github.com/FelixFu520/g1chat.git
cd g1chat
uv sync -p 3.8
```
## 配置
```
将下面内容导入环境变量, 根据情况修改下面变量值
export G1CHAT_WORK_DIR=/home/drobotics/.g1chat/
export G1CHAT_AUDIO_DEVICE_SPEAKER_NAME=USB
export G1CHAT_AUDIO_DEVICE_MIC_NAME=USB
export G1CHAT_ARK_API_KEY=3e91ddd6aa-646ef-433d6-8de8e-cdssdfsfsa48daac5566
export G1CHAT_ASR_APP_KEY=5919896644
export G1CHAT_ASR_ACCESS_KEY=G-o4lVEbyzsOdav9F6cLud9jYshdkrOegOdjorqUd
export G1CHAT_TTS_APP_KEY=5919896644
export G1CHAT_TTS_ACCESS_KEY=G-o4lVEbyzsOdav9F6cLud9jYshdkrOegOdjorqUd

将assets下的hooks.json, system_prompt_en.txt, system_prompt_zh.txt拷贝到$G1CHAT_WORK_DIR目录下
cp -r assets/* $G1CHAT_WORK_DIR
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
python -m g1chat.tools.doubao_asrtts_asr --simulate-disconnect
python -m g1chat.tools.doubao_asrtts_tts --count 10

# 测试g1chat
python -m g1chat.tools.g1
```
## 发布
```
uv build
把dist目录的whl拷贝出来给别人用
```