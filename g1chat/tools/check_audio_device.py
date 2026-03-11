import argparse
from g1chat.audio.misc import record_and_playback


def main() -> None:
    parser = argparse.ArgumentParser(description="测试 AudioDevice: 录音并回放。")
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help="录音时长(秒), 默认 5 秒",
    )
    parser.add_argument(
        "--no-monitor",
        action="store_true",
        help="只录音不实时回放, 避免啸叫/爆破音",
    )
    parser.add_argument(
        "--enable-aec",
        action="store_true",
        help="启用回声消除(默认关闭, 测试麦克风时建议先关)",
    )

    args = parser.parse_args()

    try:
        record_and_playback(
            duration=args.duration,
            enable_aec=args.enable_aec,
        )
    except KeyboardInterrupt:
        print("\n用户中断。")


if __name__ == "__main__":
    main()

