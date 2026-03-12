# Sound playback issue in g1chat_ros2
_Exported on 3/12/2026 at 19:45:20 GMT+8 from Cursor (2.5.22)_

---

**User**

在 conda activate g1chat_ros2环境下， 我执行@README.md (104) 是可以播放出声音的，但是执行@README.md (107) 无法实时播放出声音，会卡住，找下原因，并解决


---

**Cursor**

我会先看 `README.md` 中这两条命令的上下文，再去查 `g1chat.tools.play_audio` 和 `g1chat.tools.check_audio_device` 的源码，看看输入输出设备、采样率、阻塞方式等有什么差异，然后再考虑在你当前环境里如何修改或添加参数来避免卡住并实现实时播放。

---

**User**

大概率是设备占用，或者获取不到设备， 你参考/home/unitree/fa.fu/g1chat_ros2/whls/g1chat-0.3.0-py3-none-any.whl中的play_audio.py代码

---

**Cursor**

### 原因分析（结合你这台 Jetson 环境）

- 从 `check_audio_device.py` 可以看到，它的核心逻辑是：

  ```python
  device = AudioDevice(enable_aec=enable_aec)
  device.start_streams()
  while collected_frames < target_frames:
      data = device.get_recorded_data(block=True, timeout=1.0)
      if data:
          ...  # 处理 + 放进播放队列
  ```

- 在你机器上实际运行日志里可以看到：

  - 已经成功找到了 USB 声卡，并且**输入输出都是 index=24**：

    ```text
    根据关键字 'USB' 匹配到 输入 设备: USB Audio Device: - (hw:2,0) (index=24)
    根据关键字 'USB' 匹配到 输出 设备: USB Audio Device: - (hw:2,0) (index=24)
    音频流已启动
    开始录音并实时回放 5.0 秒，请对着麦克风说话...
    ```

  - 之后就再也没有任何 “录音结束”“保存 wav” 的日志了，进程一直在跑，最后被 `conda run` 杀掉（exit 137）。

- 结合 `AudioDevice` 的实现可以确定：
  - 输入流已经打开，但**回调一直拿不到有效数据**（麦克风设备不出数据 / 被 ALSA 搞挂），
  - `get_recorded_data(block=True, timeout=1.0)` 每秒超时一次返回 `None`，`collected_frames` 一直是 0，
  - `while collected_frames < target_frames:` 这个循环就永远转下去，看起来就是“卡住，没有实时声音”。

- 而 `play_audio.py`（你参考的 0.3.0 版本）只做**纯播放**：

  ```python
  stream = p.open(..., output_device_index=args.device_index, output=True)
  while data:
      stream.write(processed_data)
  ```

  不依赖输入设备，所以只要输出设备 24 好用，就一定能正常播放，这就是你 104 行命令能正常出声的原因。

**结论：** `check_audio_device` 在你这台机子上卡住的根本原因是**录音队列一直读不到数据（麦克风/输入设备异常或 ALSA 配置问题）**，导致主循环永远跑不完；而 `play_audio.py` 只用输出设备，所以没问题。

---

### 建议的解决/替代方案

#### 方案一：直接用 0.3.0 里的 `record_audio.py + play_audio.py` 代替 `check_audio_device` 做测试（推荐）

你已经有 `whls/g1chat-0.3.0-py3-none-any.whl`，其中自带的工具更贴近你现在这块板子的情况：

1. 确保用的是 0.3.0：

   ```bash
   conda activate g1chat_ros2
   pip install whls/g1chat-0.3.0-py3-none-any.whl --force-reinstall
   ```

2. 用 USB 声卡（index=24）录一小段音：

   ```bash
   conda activate g1chat_ros2
   python -m g1chat.tools.record_audio \
     --device_index 24 \
     --record_seconds 5 \
     --output /tmp/check_mic.wav
   ```

3. 再用你已经验证过能正常工作的 `play_audio.py` 播放这段录音（同一个设备 index=24）：

   ```bash
   conda activate g1chat_ros2
   python -m g1chat.tools.play_audio \
     --wav_file /tmp/check_mic.wav \
     --device_index 24
   ```

- 如果能听到自己刚才说的话，说明**输入 + 输出链路都没问题**，只是 `check_audio_device` 这套基于队列的“实时回放”逻辑在 Jetson/ALSA 上不太稳定。
- 后续你要检查设备，直接用这两条命令组合就能替代 README 第 107 行的功能，而且更可控，还能把录下来的 wav 留着分析。

#### 方案二：如果一定要用 `check_audio_device`，可以改一下逻辑防止“死等”

如果你愿意改安装好的 `g1chat` 包源码（或基于它再打一个本地 whl），可以在 `record_and_playback` 里给“拿不到数据”的情况加一个**总超时**，避免无限循环，比如：

- 在循环外加一个计数器 `empty_loops = 0`，
- 每次 `data` 为 `None` 时 `empty_loops += 1`，
- 超过一定次数（比如 10 秒）就 `break` 并打日志 “没有收到任何麦克风数据，可能设备被占用或未连接”。

逻辑上就是把现在的“永远等录音”改成“等一会儿，等不到就报错退出”，那样在你这台机器上就不会表现为卡死，而是**几秒后明确告诉你：录音设备没数据**。

---

### 小结

- **原因**：`check_audio_device` 依赖输入设备的实时数据，在你当前 Jetson + USB 声卡环境下，麦克风流没有任何数据，导致主循环永远不结束，看起来就是“卡住不播”；`play_audio.py` 只用输出设备，所以完全正常。
- **建议做法**：实际调试/验机时，直接改用 `record_audio.py + play_audio.py`（都用你已确认可用的 24 号设备）来替代 `check_audio_device`，可以做到“录一段 + 回放验证”，同时避免现在这个死循环问题。

