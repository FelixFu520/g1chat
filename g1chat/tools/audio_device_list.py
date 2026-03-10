"""
ALSA: https://zhuanlan.zhihu.com/p/813448431
"""
import argparse
from typing import List, Optional

import pyaudio


def list_audio_devices(device: str = "all"):
    """返回匹配的音频设备列表。"""
    device_list = []

    p = pyaudio.PyAudio()
    try:
        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            if device == "all":
                device_list.append(dev)
            elif device in dev["name"]:
                device_list.append(dev)
    finally:
        p.terminate()

    return device_list


def main(argv: Optional[List[str]] = None) -> None:
    """命令行入口，可用于 `python -m g1chat.tools.audio_device_list`。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=str, default="all")
    args = parser.parse_args(argv)

    print(f"正在扫描音频设备: {args.device} ...")
    device_list = list_audio_devices(args.device)

    for dev in device_list:
        print(dev)


if __name__ == "__main__":
    main()

