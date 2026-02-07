#!/usr/bin/env python3
"""
PrimeColor 精确对齐到 GoPro 时间轴（基于时间的降采样方案）

核心设计:
1. 基于时间（秒）对齐，而非帧号
2. PrimeColor 视频降采样到 GoPro 帧率（如 120fps -> 60fps）
3. CSV 基于 Time(Seconds) 列精确对齐，不依赖 FPS 假设
4. 支持任意帧率比例，不要求整数倍

对齐原理:
    1. 通过 QR 码计算 GoPro 和 PrimeColor 各自相对 anchor 的时间偏移
    2. 相对偏移 offset = gopro_offset - primecolor_offset
    3. PrimeColor 时间轴对齐: gopro_time = primecolor_time + offset
    4. 降采样: 对于每个 GoPro 帧时间点，选择最近的 PrimeColor 帧

使用示例:
    python sync_primecolor_to_gopro_precise.py \\
        --gopro_video /path/to/gopro_synced/cam01/Video.MP4 \\
        --primecolor_video /path/to/primecolor/Video.avi \\
        --anchor_video /path/to/qr_sync.mp4 \\
        --mocap_csv /path/to/motion.csv \\
        --output_dir /path/to/output

输出:
    - primecolor_synced.mp4: 降采样并对齐到 GoPro 时间轴的视频
    - mocap_synced.csv: 降采样并对齐到 GoPro 时间轴的 CSV
    - sync_mapping.json: 同步参数和帧映射信息
"""

import os
import sys
import json
import argparse
import subprocess
import shutil
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from tqdm import tqdm

# 导入已有的 QR 检测函数
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sync_with_qr_anchor import (
    scan_video_qr_segment,
    extract_anchor_metadata_from_video,
    get_anchor_time,
    get_video_info,
    FFMPEG
)


@dataclass
class SyncMapping:
    """同步映射参数"""
    # 时间偏移（秒）: gopro_time = primecolor_time + offset
    offset_seconds: float

    # 各自相对 anchor 的偏移
    gopro_offset_to_anchor: float
    primecolor_offset_to_anchor: float

    # 帧率信息
    gopro_fps: float
    primecolor_fps: float
    target_fps: float  # 输出帧率（通常等于 gopro_fps）

    # 时长信息
    gopro_duration: float
    primecolor_duration: float
    output_duration: float

    # 帧数信息
    gopro_frames: int
    primecolor_frames: int
    output_frames: int

    # QR 码检测统计
    gopro_qr_count: int
    primecolor_qr_count: int
    offset_std: float  # 偏移计算的标准差

    # 帧映射（输出帧号 -> PrimeColor 源帧号）
    # 存储为 JSON 时只保存采样信息，不保存完整映射
    frame_mapping_sample: Dict[int, int] = None


def calculate_time_offset(
    gopro_detections: List[Tuple[float, int]],
    primecolor_detections: List[Tuple[float, int]],
    anchor_map: Dict[int, float],
    anchor_fps: float
) -> Tuple[float, float, float, float]:
    """
    计算 PrimeColor 相对 GoPro 的时间偏移（基于 anchor）

    Returns:
        (offset_seconds, gopro_offset, primecolor_offset, offset_std)
        offset_seconds: 相对偏移，gopro_time = primecolor_time + offset
    """
    if not gopro_detections or not primecolor_detections:
        raise ValueError("至少一个视频没有检测到 QR 码")

    print("\n" + "=" * 80)
    print("计算时间偏移（基于 anchor）")
    print("=" * 80)

    # 计算每个视频相对 anchor 的偏移
    gopro_offsets = []
    for video_time, qr_num in gopro_detections:
        anchor_time = get_anchor_time(qr_num, anchor_map, anchor_fps)
        gopro_offsets.append(video_time - anchor_time)

    primecolor_offsets = []
    for video_time, qr_num in primecolor_detections:
        anchor_time = get_anchor_time(qr_num, anchor_map, anchor_fps)
        primecolor_offsets.append(video_time - anchor_time)

    # 使用中位数（更鲁棒）
    gopro_offset = np.median(gopro_offsets)
    primecolor_offset = np.median(primecolor_offsets)

    # 相对偏移
    offset_seconds = gopro_offset - primecolor_offset

    # 计算标准差（评估一致性）
    gopro_std = np.std(gopro_offsets)
    primecolor_std = np.std(primecolor_offsets)
    combined_std = np.sqrt(gopro_std**2 + primecolor_std**2)

    print(f"  GoPro 相对 anchor 偏移: {gopro_offset:.6f}s (std: {gopro_std:.4f}s)")
    print(f"  PrimeColor 相对 anchor 偏移: {primecolor_offset:.6f}s (std: {primecolor_std:.4f}s)")
    print(f"  相对偏移: {offset_seconds:.6f}s")
    print(f"  综合标准差: {combined_std:.4f}s")

    if combined_std > 0.1:
        print(f"  ⚠️  警告: 标准差较大，可能存在检测错误或时间漂移")

    # 显示 QR 码映射示例
    print(f"\n  QR 码映射示例（前 5 个）:")
    print(f"  GoPro: {[(f'QR#{qr}@{t:.2f}s', f'offset={t-get_anchor_time(qr,anchor_map,anchor_fps):.3f}s') for t, qr in gopro_detections[:5]]}")
    print(f"  PrimeColor: {[(f'QR#{qr}@{t:.2f}s', f'offset={t-get_anchor_time(qr,anchor_map,anchor_fps):.3f}s') for t, qr in primecolor_detections[:5]]}")

    return offset_seconds, gopro_offset, primecolor_offset, combined_std


def build_frame_mapping(
    gopro_fps: float,
    primecolor_fps: float,
    offset_seconds: float,
    output_duration: float,
    primecolor_duration: float
) -> Dict[int, int]:
    """
    构建帧映射表: 输出帧号 -> PrimeColor 源帧号

    原理:
        output_frame_time = output_frame_idx / target_fps
        primecolor_time = output_frame_time - offset_seconds
        primecolor_frame = round(primecolor_time * primecolor_fps)

    Returns:
        {output_frame_idx: primecolor_frame_idx, ...}
    """
    target_fps = gopro_fps  # 输出帧率 = GoPro 帧率
    output_frames = int(output_duration * target_fps)
    primecolor_frames = int(primecolor_duration * primecolor_fps)

    frame_mapping = {}
    valid_frames = 0

    for out_idx in range(output_frames):
        # 输出帧对应的时间
        out_time = out_idx / target_fps

        # 对应的 PrimeColor 时间
        prime_time = out_time - offset_seconds

        # 对应的 PrimeColor 帧号（四舍五入到最近帧）
        prime_frame = round(prime_time * primecolor_fps)

        # 检查是否在有效范围内
        if 0 <= prime_frame < primecolor_frames:
            frame_mapping[out_idx] = prime_frame
            valid_frames += 1
        else:
            # 超出范围，标记为 -1（需要填充黑帧）
            frame_mapping[out_idx] = -1

    print(f"\n  帧映射统计:")
    print(f"    输出总帧数: {output_frames}")
    print(f"    有效映射帧: {valid_frames}")
    print(f"    需填充黑帧: {output_frames - valid_frames}")

    return frame_mapping


def create_synced_video_precise(
    primecolor_video_path: str,
    output_path: str,
    mapping: SyncMapping,
    use_gpu: bool = False
) -> bool:
    """
    创建精确对齐的降采样视频

    方法: 使用 ffmpeg 的 fps filter + trim/pad
    输出视频与 GoPro 等长，PrimeColor 内容对齐到正确位置，其余用黑帧填充
    """
    print("\n" + "=" * 80)
    print("创建精确对齐的视频")
    print("=" * 80)

    offset = mapping.offset_seconds
    target_fps = mapping.target_fps
    output_duration = mapping.output_duration
    gopro_duration = mapping.gopro_duration

    print(f"  源视频: {mapping.primecolor_fps:.2f}fps, {mapping.primecolor_duration:.2f}s")
    print(f"  目标: {target_fps:.2f}fps, {output_duration:.2f}s (与 GoPro 等长)")
    print(f"  时间偏移: {offset:.6f}s")

    # 获取源视频信息
    prime_info = get_video_info(primecolor_video_path)

    # 计算 PrimeColor 内容在输出中的位置
    # offset > 0: PrimeColor 在 GoPro 时间轴上延迟（前面需要黑帧）
    # offset < 0: PrimeColor 在 GoPro 时间轴上提前（需要裁剪开头）

    if offset >= 0:
        # PrimeColor 需要延迟
        black_before = offset  # 前置黑帧时长
        trim_start = 0  # 从 PrimeColor 开头开始
        # PrimeColor 内容可用时长
        content_duration = min(mapping.primecolor_duration, gopro_duration - offset)
        # 后置黑帧时长
        black_after = max(0, gopro_duration - offset - mapping.primecolor_duration)
    else:
        # PrimeColor 需要提前（裁剪开头）
        black_before = 0  # 无前置黑帧
        trim_start = abs(offset)  # 裁剪 PrimeColor 开头
        # PrimeColor 内容可用时长
        content_duration = min(mapping.primecolor_duration - trim_start, gopro_duration)
        # 后置黑帧时长
        black_after = max(0, gopro_duration - content_duration)

    print(f"  方案: 前置 {black_before:.4f}s 黑帧 + {content_duration:.4f}s 内容 + 后置 {black_after:.4f}s 黑帧")
    print(f"  PrimeColor 裁剪起点: {trim_start:.4f}s")

    # 构建 ffmpeg filter_complex
    # 根据需要的黑帧情况构建不同的 filter
    filter_parts = []
    concat_inputs = []
    stream_idx = 0

    # 前置黑帧
    if black_before > 0.01:  # 避免极小值
        filter_parts.append(
            f"color=c=black:s={prime_info['width']}x{prime_info['height']}:r={target_fps}:d={black_before}[black_before]"
        )
        concat_inputs.append("[black_before]")
        stream_idx += 1

    # 内容
    if content_duration > 0.01:
        if trim_start > 0:
            filter_parts.append(
                f"[0:v]fps={target_fps},trim=start={trim_start}:duration={content_duration},setpts=PTS-STARTPTS[content]"
            )
        else:
            filter_parts.append(
                f"[0:v]fps={target_fps},trim=duration={content_duration},setpts=PTS-STARTPTS[content]"
            )
        concat_inputs.append("[content]")
        stream_idx += 1

    # 后置黑帧
    if black_after > 0.01:  # 避免极小值
        filter_parts.append(
            f"color=c=black:s={prime_info['width']}x{prime_info['height']}:r={target_fps}:d={black_after}[black_after]"
        )
        concat_inputs.append("[black_after]")
        stream_idx += 1

    # 拼接
    if len(concat_inputs) > 1:
        filter_parts.append(
            f"{''.join(concat_inputs)}concat=n={len(concat_inputs)}:v=1:a=0[outv]"
        )
        filter_complex = ";".join(filter_parts)
    elif len(concat_inputs) == 1:
        # 只有一个输入，直接输出
        if concat_inputs[0] == "[content]":
            filter_complex = filter_parts[0].replace("[content]", "[outv]")
        else:
            filter_complex = filter_parts[0].replace(concat_inputs[0][1:-1], "outv")
    else:
        print(f"  ❌ 错误: 没有有效内容")
        return False

    # 编码参数
    encoder = 'h264_videotoolbox' if use_gpu and sys.platform == 'darwin' else 'libx264'
    preset = 'fast' if encoder == 'libx264' else None

    cmd = [
        FFMPEG, '-y',
        '-i', primecolor_video_path,
        '-filter_complex', filter_complex,
        '-map', '[outv]',
        '-c:v', encoder,
        '-crf', '18',
        '-pix_fmt', 'yuv420p',
    ]

    if preset:
        cmd.extend(['-preset', preset])

    cmd.append(output_path)

    print(f"  编码中...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  ❌ 编码失败")
        print(f"  错误: {result.stderr[:500] if result.stderr else 'Unknown'}")
        return False

    # 验证输出
    if os.path.exists(output_path):
        output_info = get_video_info(output_path)
        print(f"  ✅ 完成: {output_info['fps']:.2f}fps, {output_info['duration']:.2f}s, {output_info['frame_count']} 帧")

        # 检查时长误差
        duration_error = abs(output_info['duration'] - output_duration)
        if duration_error > 0.1:
            print(f"  ⚠️  时长误差: {duration_error:.3f}s")

        return True
    else:
        print(f"  ❌ 输出文件不存在")
        return False


def sync_csv_precise(
    csv_path: str,
    output_path: str,
    mapping: SyncMapping
) -> bool:
    """
    精确同步 CSV 到 GoPro 时间轴

    方法:
        1. 读取 CSV，使用 Time(Seconds) 列
        2. 计算对齐后的时间: aligned_time = original_time + offset
        3. 降采样到目标帧率: 对每个目标帧时间，选择最近的源帧
        4. 输出新的 CSV，帧号从 0 开始，与 GoPro 等长
        5. 无效帧（黑帧对应的时间）用 NaN 填充
    """
    print("\n" + "=" * 80)
    print("精确同步 CSV")
    print("=" * 80)

    offset = mapping.offset_seconds
    target_fps = mapping.target_fps
    output_duration = mapping.output_duration  # 现在等于 GoPro 时长

    print(f"  读取: {csv_path}")

    # 读取 CSV（跳过 Motive 格式的头部）
    # Motive 导出格式: 前 7 行是元数据
    with open(csv_path, 'r') as f:
        first_line = f.readline()

    # 检测是否是 Motive 格式
    if first_line.startswith('Format Version'):
        header_rows = 7
        print(f"  检测到 Motive 格式，跳过 {header_rows} 行头部")
    else:
        header_rows = 0

    # 读取头部元数据（保留）
    header_lines = []
    if header_rows > 0:
        with open(csv_path, 'r') as f:
            for i in range(header_rows):
                header_lines.append(f.readline())

    # 读取数据
    df = pd.read_csv(csv_path, skiprows=header_rows, low_memory=False)

    print(f"  原始数据: {len(df)} 行")

    # 获取 Frame 和 Time 列
    frame_col = df.columns[0]  # 通常是 'Frame'
    time_col = df.columns[1]   # 通常是 'Time (Seconds)'

    print(f"  帧列: {frame_col}, 时间列: {time_col}")

    # 计算对齐后的时间
    # aligned_time = original_time + offset
    # 其中 offset = gopro_offset - primecolor_offset
    # 这意味着: gopro_time = primecolor_time + offset
    df['aligned_time'] = df[time_col] + offset

    # 生成目标帧时间点（与 GoPro 等长）
    output_frames = int(output_duration * target_fps)
    target_times = np.arange(output_frames) / target_fps

    print(f"  目标帧数: {output_frames} @ {target_fps}fps (与 GoPro 等长)")

    # 对每个目标帧，找最近的源帧
    aligned_times = df['aligned_time'].values

    # 创建输出 DataFrame，先用 NaN 填充
    df_output = pd.DataFrame(index=range(output_frames), columns=df.columns.drop('aligned_time') if 'aligned_time' in df.columns else df.columns)
    df_output[frame_col] = range(output_frames)
    df_output[time_col] = target_times

    valid_frames = 0
    invalid_frames = 0

    for out_idx, target_time in enumerate(tqdm(target_times, desc="  降采样", ncols=100)):
        # 找到最近的源帧
        idx = np.searchsorted(aligned_times, target_time)

        # 选择更近的那个
        if idx == 0:
            nearest_idx = 0
        elif idx >= len(aligned_times):
            nearest_idx = len(aligned_times) - 1
        else:
            # 比较 idx-1 和 idx 哪个更近
            if abs(aligned_times[idx-1] - target_time) <= abs(aligned_times[idx] - target_time):
                nearest_idx = idx - 1
            else:
                nearest_idx = idx

        # 检查是否在有效范围
        # 且时间差在允许范围内（防止 clamping）
        # 允许误差: 1.5 帧 (例如 120fps 时约为 12.5ms)
        time_diff = abs(aligned_times[nearest_idx] - target_time)
        max_diff = 1.5 / mapping.primecolor_fps

        # PrimeColor 有效时间范围 (对齐后)
        primecolor_valid_start = offset if offset > 0 else 0
        primecolor_valid_end = mapping.primecolor_duration + offset

        if (primecolor_valid_start <= target_time <= primecolor_valid_end) and (time_diff <= max_diff):
            # 复制有效数据
            for col in df.columns:
                if col != 'aligned_time':
                    df_output.loc[out_idx, col] = df.iloc[nearest_idx][col]
            df_output.loc[out_idx, frame_col] = out_idx
            df_output.loc[out_idx, time_col] = target_time
            valid_frames += 1
        else:
            # 无效帧，保持 NaN（Frame 和 Time 已设置）
            invalid_frames += 1

    print(f"  有效帧: {valid_frames}/{output_frames}")
    print(f"  无效帧（黑帧）: {invalid_frames}/{output_frames}")

    # 保存
    # 先写入头部
    with open(output_path, 'w') as f:
        f.writelines(header_lines)

    # 追加数据
    df_output.to_csv(output_path, mode='a', index=False)

    print(f"  ✅ 保存: {output_path}")
    print(f"     输出帧数: {len(df_output)} (与 GoPro 等长)")

    return True


def main():
    parser = argparse.ArgumentParser(
        description='PrimeColor 精确对齐到 GoPro 时间轴（降采样）',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--gopro_video', required=True,
                       help='GoPro 参考视频路径')
    parser.add_argument('--primecolor_video', required=True,
                       help='PrimeColor 视频路径')
    parser.add_argument('--anchor_video', required=True,
                       help='QR anchor 视频路径')
    parser.add_argument('--mocap_csv', default=None,
                       help='Mocap CSV 路径（可选）')
    parser.add_argument('--output_dir', required=True,
                       help='输出目录')

    parser.add_argument('--scan_duration', type=float, default=120.0,
                       help='QR 扫描时长（秒），默认 60')
    parser.add_argument('--frame_step', type=int, default=5,
                       help='QR 检测帧步长，默认 5')
    parser.add_argument('--prefix', type=str, default='',
                       help='QR 码前缀')
    parser.add_argument('--min_detections', type=int, default=30,
                       help='最少QR检测数量，达到后提前停止（默认30，0=不限制）')
    parser.add_argument('--gpu', action='store_true',
                       help='使用 GPU 加速编码（macOS VideoToolbox）')
    parser.add_argument('--skip_csv', action='store_true',
                       help='跳过 CSV 同步（稍后用 sync_csv_fast.py 处理）')

    args = parser.parse_args()

    # 创建输出目录
    os.makedirs(args.output_dir, exist_ok=True)

    # 步骤 1: 提取 anchor metadata
    print("\n" + "=" * 80)
    print("步骤 1: 提取 QR Anchor Metadata")
    print("=" * 80)
    anchor_map, anchor_fps = extract_anchor_metadata_from_video(
        args.anchor_video,
        prefix=args.prefix,
        sample_frames=200,
        frame_step=5
    )

    # 步骤 2: 扫描 GoPro
    print("\n" + "=" * 80)
    print("步骤 2: 扫描 GoPro 视频")
    print("=" * 80)
    gopro_detections = scan_video_qr_segment(
        args.gopro_video,
        start_time=0.0,
        duration=args.scan_duration,
        frame_step=args.frame_step,
        prefix=args.prefix,
        min_detections=args.min_detections,
        early_stop=True
    )
    gopro_info = get_video_info(args.gopro_video)
    print(f"  检测到 {len(gopro_detections)} 个 QR 码")
    print(f"  视频信息: {gopro_info['fps']:.2f}fps, {gopro_info['duration']:.2f}s")

    # 步骤 3: 扫描 PrimeColor
    print("\n" + "=" * 80)
    print("步骤 3: 扫描 PrimeColor 视频")
    print("=" * 80)
    primecolor_detections = scan_video_qr_segment(
        args.primecolor_video,
        start_time=0.0,
        duration=args.scan_duration,
        frame_step=args.frame_step,
        prefix=args.prefix,
        min_detections=args.min_detections,
        early_stop=True
    )
    primecolor_info = get_video_info(args.primecolor_video)
    print(f"  检测到 {len(primecolor_detections)} 个 QR 码")
    print(f"  视频信息: {primecolor_info['fps']:.2f}fps, {primecolor_info['duration']:.2f}s")

    # 步骤 4: 计算时间偏移
    print("\n" + "=" * 80)
    print("步骤 4: 计算时间偏移")
    print("=" * 80)
    offset_seconds, gopro_offset, primecolor_offset, offset_std = calculate_time_offset(
        gopro_detections,
        primecolor_detections,
        anchor_map,
        anchor_fps
    )

    # 计算输出时长（使用 GoPro 完整时长，确保与 GoPro 对齐）
    # GoPro 时间范围: [0, gopro_duration]
    # PrimeColor 对齐后范围: [offset, primecolor_duration + offset]
    #
    # 输出应该与 GoPro 等长，PrimeColor 内容对齐到正确位置，其余用黑帧填充
    output_duration = gopro_info['duration']

    # 计算 PrimeColor 内容在输出中的有效范围
    primecolor_start_in_output = max(0, offset_seconds)  # PrimeColor 内容开始的时间点
    primecolor_end_in_output = min(output_duration, primecolor_info['duration'] + offset_seconds)  # PrimeColor 内容结束的时间点

    # 检查是否有重叠
    if primecolor_end_in_output <= primecolor_start_in_output:
        print(f"  ❌ 错误: 没有重叠时段，无法同步")
        print(f"     GoPro 范围: [0, {gopro_info['duration']:.2f}]s")
        print(f"     PrimeColor 对齐后范围: [{offset_seconds:.2f}, {primecolor_info['duration'] + offset_seconds:.2f}]s")
        return 1

    print(f"\n  输出时长: {output_duration:.2f}s (与 GoPro 等长)")
    print(f"  PrimeColor 有效范围: [{primecolor_start_in_output:.2f}s, {primecolor_end_in_output:.2f}s]")

    # 构建同步映射
    mapping = SyncMapping(
        offset_seconds=offset_seconds,
        gopro_offset_to_anchor=gopro_offset,
        primecolor_offset_to_anchor=primecolor_offset,
        gopro_fps=gopro_info['fps'],
        primecolor_fps=primecolor_info['fps'],
        target_fps=gopro_info['fps'],  # 输出帧率 = GoPro 帧率
        gopro_duration=gopro_info['duration'],
        primecolor_duration=primecolor_info['duration'],
        output_duration=output_duration,
        gopro_frames=gopro_info['frame_count'],
        primecolor_frames=primecolor_info['frame_count'],
        output_frames=int(output_duration * gopro_info['fps']),
        gopro_qr_count=len(gopro_detections),
        primecolor_qr_count=len(primecolor_detections),
        offset_std=offset_std
    )

    # 构建帧映射（采样）
    frame_mapping = build_frame_mapping(
        mapping.gopro_fps,
        mapping.primecolor_fps,
        mapping.offset_seconds,
        mapping.output_duration,
        mapping.primecolor_duration
    )

    # 保存采样（每 100 帧保存一个）
    mapping.frame_mapping_sample = {k: v for k, v in frame_mapping.items() if k % 100 == 0}

    # 步骤 5: 创建对齐视频
    print("\n" + "=" * 80)
    print("步骤 5: 创建对齐视频")
    print("=" * 80)
    video_output = os.path.join(args.output_dir, 'primecolor_synced.mp4')
    video_success = create_synced_video_precise(
        args.primecolor_video,
        video_output,
        mapping,
        use_gpu=args.gpu
    )

    # 步骤 6: 同步 CSV（如果提供且未跳过）
    csv_success = True
    csv_skipped = False
    if args.mocap_csv:
        if args.skip_csv:
            print("\n" + "=" * 80)
            print("步骤 6: 同步 CSV (跳过)")
            print("=" * 80)
            print("  ⏭️  已跳过，稍后使用 sync_csv_fast.py 处理")
            csv_skipped = True
        else:
            print("\n" + "=" * 80)
            print("步骤 6: 同步 CSV")
            print("=" * 80)
            csv_output = os.path.join(args.output_dir, 'mocap_synced.csv')
            csv_success = sync_csv_precise(
                args.mocap_csv,
                csv_output,
                mapping
            )

    # 保存映射参数
    mapping_json = os.path.join(args.output_dir, 'sync_mapping.json')
    with open(mapping_json, 'w') as f:
        json.dump(asdict(mapping), f, indent=2)
    print(f"\n💾 映射参数已保存: {mapping_json}")

    # 总结
    print("\n" + "=" * 80)
    print("同步完成！")
    print("=" * 80)
    print(f"  输出目录: {args.output_dir}")
    print(f"  视频: {'✅' if video_success else '❌'} primecolor_synced.mp4")
    if args.mocap_csv:
        if csv_skipped:
            print(f"  CSV: ⏭️  跳过 (使用 sync_csv_fast.py 处理)")
        else:
            print(f"  CSV: {'✅' if csv_success else '❌'} mocap_synced.csv")
    print(f"  映射: sync_mapping.json")
    print(f"\n  关键参数:")
    print(f"    时间偏移: {mapping.offset_seconds:.6f}s")
    print(f"    帧率: {mapping.primecolor_fps:.0f}fps -> {mapping.target_fps:.0f}fps")
    print(f"    时长: {mapping.output_duration:.2f}s")
    print(f"    帧数: {mapping.output_frames}")

    return 0 if (video_success and csv_success) else 1


if __name__ == '__main__':
    sys.exit(main())
