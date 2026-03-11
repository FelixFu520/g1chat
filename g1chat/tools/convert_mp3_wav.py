import argparse
import subprocess
import sys
from pathlib import Path


def convert_mp3_to_wav(src: Path, dst: Path, sample_rate: int = 16000, channels: int = 1) -> None:
    """
    使用系统中的 ffmpeg 将 MP3 转换为 WAV。

    要求本机已安装 `ffmpeg` 命令。
    """
    if not src.exists():
        raise FileNotFoundError(f"输入文件不存在: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",  # 覆盖输出文件
        "-i",
        str(src),
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        str(dst),
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as e:
        raise RuntimeError("未找到 ffmpeg, 请先在系统中安装 ffmpeg") from e
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="ignore") if e.stderr else ""
        raise RuntimeError(f"ffmpeg 转换失败: {stderr}") from e


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将 MP3 文件转换为 WAV 文件的工具（基于 ffmpeg）。"
    )
    parser.add_argument("input", type=str, help="输入 MP3 文件路径")
    parser.add_argument(
        "output",
        type=str,
        nargs="?",
        help="输出 WAV 文件路径（可选，默认与输入同名，仅扩展名改为 .wav）",
    )
    parser.add_argument(
        "--sample-rate",
        "-r",
        type=int,
        default=16000,
        help="输出 WAV 采样率，默认 16000",
    )
    parser.add_argument(
        "--channels",
        "-c",
        type=int,
        default=1,
        help="输出声道数，默认 1（单声道）",
    )
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)

    src = Path(args.input).expanduser().resolve()
    if args.output:
        dst = Path(args.output).expanduser().resolve()
    else:
        dst = src.with_suffix(".wav")

    try:
        convert_mp3_to_wav(src, dst, sample_rate=args.sample_rate, channels=args.channels)
    except Exception as exc:  # noqa: BLE001
        print(f"转换失败: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"转换成功: {src} -> {dst}")


if __name__ == "__main__":
    main()

