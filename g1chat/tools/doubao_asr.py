#!/usr/bin/env python3
"""
豆包ASR测试脚本
测试豆包语音识别服务，支持文件ASR和实时录音ASR两种模式

用法：
    文件ASR: python3 03_doubao_asr.py --mode file --file /path/to/audio.wav
    实时录音ASR: python3 03_doubao_asr.py --mode realtime --duration 100
"""

import argparse
import asyncio

from g1chat.audio.misc import test_file_asr, test_realtime_asr

async def main():
    """
    主函数，解析命令行参数并执行相应的测试模式
    """
    parser = argparse.ArgumentParser(description="豆包ASR WebSocket客户端测试工具")
    
    # 添加命令行参数
    parser.add_argument("--mode", type=str, choices=['file', 'realtime'], default='realtime',
                       help="测试模式: file=文件ASR, realtime=实时录音ASR(默认: realtime)")
    parser.add_argument("--file", type=str, 
                       default="/home/drobotics/projects/robota/assets/xiaozhan_ref_16000_concatenated.wav", 
                       help="音频文件路径(用于file模式)")
    parser.add_argument("--url", type=str, 
                       default="wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async", 
                       help="WebSocket服务器URL")
    parser.add_argument("--seg-duration", type=int, default=200, 
                       help="每个音频包的时长(毫秒), 默认: 200")
    parser.add_argument("--duration", type=int, default=10,
                       help="录音时长(秒), 仅用于realtime模式, 默认: 10")
    
    # 解析命令行参数
    args = parser.parse_args()
    
    # 根据模式执行相应的测试
    if args.mode == 'file':
        await test_file_asr(args.url, args.seg_duration, args.file)
    elif args.mode == 'realtime':
        await test_realtime_asr(args.url, args.seg_duration, args.duration)


if __name__ == "__main__":
    asyncio.run(main())