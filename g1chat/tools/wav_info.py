import argparse
import wave

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("wav_file", type=str, default="output.wav")
    args = parser.parse_args()

    wave_file = wave.open(args.wav_file, 'rb')

    print(f"  采样率: {wave_file.getframerate()}")
    print(f"  通道数: {wave_file.getnchannels()}")
    print(f"  采样位数: {wave_file.getsampwidth() * 8}")
    print(f"  帧数: {wave_file.getnframes()}")
    print(f"  参数: {wave_file.getparams()}")