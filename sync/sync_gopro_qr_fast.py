#!/usr/bin/env python3
"""
GoPro QR码快速同步 (极速优化版)

优化策略:
1. ffmpeg批量提取帧 - 比OpenCV逐帧seek快10倍
2. 多进程并行检测 - 充分利用所有CPU核心
3. 更小分辨率 - 540p足够检测QR码
4. ROI裁剪 - 只检测中心区域(QR码通常在画面中心)
5. 激进采样 - 粗扫描每2秒,精细扫描积累20个即停

预期速度:
- 单相机QR扫描: 15-30秒 (原来2-3分钟)
- 16相机并行: 30-60秒
- SmartCut: 3-5分钟
- 总计: 4-6分钟/组

使用:
    # 单组
    python sync_gopro_qr_fast.py \\
        --input_dir /path/to/P4_1 \\
        --output_dir /path/to/output \\
        --anchor_video /path/to/qr_sync.mp4

    # 批量15组
    python sync_gopro_qr_fast.py \\
        --input_dir /path/to/organized \\
        --output_dir /path/to/output \\
        --anchor_video /path/to/qr_sync.mp4 \\
        --batch
"""

import os
import sys
import json
import argparse
import subprocess
import shutil
import tempfile
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import multiprocessing as mp
from dataclasses import dataclass, field
import time
import re

try:
    from pyzbar import pyzbar
    from pyzbar.pyzbar import ZBarSymbol
    HAS_PYZBAR = True
except ImportError:
    HAS_PYZBAR = False
    print("⚠️ 推荐安装pyzbar加速: pip install pyzbar")

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

import cv2


# =============================================================================
# 配置
# =============================================================================

@dataclass
class ScanConfig:
    """扫描配置"""
    max_scan_duration: float = 240.0   # 最大扫描时长(秒) - 前4分钟
    coarse_interval: float = 1.0       # 粗扫描间隔(秒) - 优化：从0.5s改为1s
    fine_range: float = 10.0           # 精细扫描范围(±秒) - 优化：从5s改为10s
    fine_fps: float = 30.0             # 精细扫描帧率
    target_detections: int = 15        # 目标检测数 - 优化：从30改为15
    frame_width: int = 960             # 提取帧宽度
    roi_ratio: float = 0.6             # ROI区域比例(中心60%)


@dataclass
class DenseScanConfig:
    """密集扫描配置 - 用于重试失败的相机"""
    max_scan_duration: float = 240.0   # 最大扫描时长(秒)
    coarse_interval: float = 0.5       # 更密集的粗扫描间隔(秒) - 从0.25s改为0.5s
    fine_range: float = 10.0           # 精细扫描范围(±秒)
    fine_fps: float = 30.0             # 精细扫描帧率
    target_detections: int = 10        # 更低的目标数（更容易成功）
    frame_width: int = 1280            # 更高分辨率
    roi_ratio: float = 0.8             # 更大的ROI区域


@dataclass
class VerificationResult:
    """Timecode验证结果"""
    passed: bool                                # 验证是否通过
    max_discrepancy_frames: float               # 最大差异(帧)
    camera_results: Dict[str, dict] = field(default_factory=dict)  # 每个相机的结果
    problem_cameras: List[str] = field(default_factory=list)       # 超出阈值的相机


# =============================================================================
# Timecode提取与验证
# =============================================================================

def extract_video_timecode(video_path: str) -> Optional[str]:
    """
    用ffprobe提取视频的硬件timecode

    Args:
        video_path: 视频文件路径

    Returns:
        timecode字符串 (HH:MM:SS:FF 或 HH:MM:SS;FF) 或 None
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream_tags=timecode",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    tc = result.stdout.strip()

    if tc:
        return tc

    # 尝试从format tags获取
    cmd2 = [
        "ffprobe", "-v", "error",
        "-show_entries", "format_tags=timecode",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    result2 = subprocess.run(cmd2, capture_output=True, text=True)
    tc2 = result2.stdout.strip()

    return tc2 if tc2 else None


def timecode_to_seconds(timecode: str, fps: float) -> float:
    """
    将timecode转换为秒

    Args:
        timecode: HH:MM:SS:FF 或 HH:MM:SS;FF 格式
        fps: 视频帧率

    Returns:
        秒数 (float)
    """
    # 支持 : 和 ; 作为帧分隔符 (drop frame用;)
    tc = timecode.replace(';', ':')
    parts = tc.split(':')

    if len(parts) != 4:
        raise ValueError(f"Invalid timecode format: {timecode}")

    hours, minutes, seconds, frames = map(int, parts)

    total_seconds = hours * 3600 + minutes * 60 + seconds + frames / fps
    return total_seconds


def calculate_timecode_offsets(
    cameras: Dict[str, str],
    fps: float = 60.0
) -> Dict[str, Optional[float]]:
    """
    计算所有相机基于timecode的同步偏移

    偏移定义: 以最晚开始的相机为基准(0), 其他相机的timecode差值

    Args:
        cameras: {cam_name: video_path}
        fps: 视频帧率

    Returns:
        {cam_name: offset_seconds} 或 None如果提取失败
    """
    timecodes = {}
    tc_seconds = {}

    for cam_name, video_path in cameras.items():
        tc = extract_video_timecode(video_path)
        if tc:
            timecodes[cam_name] = tc
            try:
                tc_seconds[cam_name] = timecode_to_seconds(tc, fps)
            except ValueError:
                tc_seconds[cam_name] = None
        else:
            tc_seconds[cam_name] = None

    # 找到最晚的开始时间
    valid_times = [t for t in tc_seconds.values() if t is not None]
    if not valid_times:
        return {cam: None for cam in cameras}

    latest_start = max(valid_times)

    # 计算相对偏移 (相对于anchor的偏移)
    offsets = {}
    for cam_name, tc_sec in tc_seconds.items():
        if tc_sec is not None:
            offsets[cam_name] = tc_sec
        else:
            offsets[cam_name] = None

    return offsets


def verify_qr_vs_timecode(
    qr_offsets: Dict[str, float],
    tc_offsets: Dict[str, Optional[float]],
    fps: float = 60.0,
    threshold_frames: float = 3.0
) -> VerificationResult:
    """
    比较QR偏移与timecode偏移

    Args:
        qr_offsets: QR码计算的anchor偏移 {cam_name: offset_seconds}
        tc_offsets: timecode偏移 {cam_name: offset_seconds}
        fps: 视频帧率
        threshold_frames: 差异阈值(帧)

    Returns:
        VerificationResult
    """
    camera_results = {}
    problem_cameras = []
    max_discrepancy = 0.0

    # 找到同时有QR和TC偏移的相机
    common_cameras = [c for c in qr_offsets if tc_offsets.get(c) is not None]

    if len(common_cameras) < 2:
        return VerificationResult(
            passed=False,
            max_discrepancy_frames=float('inf'),
            camera_results={'error': 'Not enough cameras with timecode'},
            problem_cameras=list(qr_offsets.keys())
        )

    # 计算QR偏移差值 (相机间的相对偏移)
    # 选择第一个相机作为参考
    ref_cam = common_cameras[0]
    qr_ref = qr_offsets[ref_cam]
    tc_ref = tc_offsets[ref_cam]

    for cam in common_cameras:
        qr_diff = qr_offsets[cam] - qr_ref  # QR相对偏移
        tc_diff = tc_offsets[cam] - tc_ref  # TC相对偏移

        # QR和TC的差异 (注意: QR偏移和TC偏移是反向关系)
        # 如果相机A比B早开始录制: A的QR偏移更大, A的TC偏移更小
        # 所以正确的验证是: |qr_diff + tc_diff| 应该接近0
        discrepancy_sec = abs(qr_diff + tc_diff)
        discrepancy_frames = discrepancy_sec * fps

        camera_results[cam] = {
            'qr_offset': qr_offsets[cam],
            'tc_offset': tc_offsets[cam],
            'qr_relative': qr_diff,
            'tc_relative': tc_diff,
            'discrepancy_sec': discrepancy_sec,
            'discrepancy_frames': discrepancy_frames,
            'passed': discrepancy_frames < threshold_frames
        }

        if discrepancy_frames > max_discrepancy:
            max_discrepancy = discrepancy_frames

        if discrepancy_frames >= threshold_frames:
            problem_cameras.append(cam)

    # 添加没有timecode的相机
    for cam in qr_offsets:
        if cam not in common_cameras:
            camera_results[cam] = {
                'qr_offset': qr_offsets[cam],
                'tc_offset': None,
                'discrepancy_sec': None,
                'discrepancy_frames': None,
                'passed': None,
                'note': 'No timecode available'
            }

    passed = len(problem_cameras) == 0 and len(common_cameras) >= 2

    return VerificationResult(
        passed=passed,
        max_discrepancy_frames=max_discrepancy,
        camera_results=camera_results,
        problem_cameras=problem_cameras
    )


def get_directory_size(path: Path) -> int:
    """获取目录大小(字节)"""
    total = 0
    for entry in path.rglob('*'):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def cleanup_originals_if_verified(
    input_dir: Path,
    verification: VerificationResult,
    dry_run: bool = False
) -> Tuple[bool, str]:
    """
    验证通过则删除原始文件夹

    Args:
        input_dir: 原始视频目录
        verification: 验证结果
        dry_run: 如果True，只显示不删除

    Returns:
        (success, message)
    """
    if not verification.passed:
        return False, f"验证未通过，保留原始文件 (问题相机: {', '.join(verification.problem_cameras)})"

    if not input_dir.exists():
        return False, f"目录不存在: {input_dir}"

    # 计算目录大小
    dir_size = get_directory_size(input_dir)
    size_str = format_size(dir_size)

    if dry_run:
        return True, f"[干运行] 将删除 {input_dir} ({size_str})"

    try:
        shutil.rmtree(input_dir)
        return True, f"已删除 {input_dir} ({size_str})"
    except Exception as e:
        return False, f"删除失败: {e}"


# =============================================================================
# QR码检测 (优化版)
# =============================================================================

def detect_qr_pyzbar(image: np.ndarray) -> List[str]:
    """使用pyzbar检测QR码"""
    if not HAS_PYZBAR:
        return []
    try:
        results = pyzbar.decode(image, symbols=[ZBarSymbol.QRCODE])
        return [r.data.decode('utf-8') for r in results]
    except:
        return []


def detect_qr_opencv(image: np.ndarray) -> List[str]:
    """使用OpenCV检测QR码"""
    try:
        detector = cv2.QRCodeDetector()
        data, _, _ = detector.detectAndDecode(image)
        return [data] if data else []
    except:
        return []


def detect_qr(image: np.ndarray) -> List[str]:
    """检测QR码 (优先pyzbar)"""
    # 转灰度
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    # 尝试pyzbar
    results = detect_qr_pyzbar(gray)
    if results:
        return results

    # 回退到OpenCV
    return detect_qr_opencv(gray)


def parse_qr_number(qr_data: str, prefix: str = "") -> Optional[int]:
    """解析QR码数字"""
    try:
        if prefix and qr_data.startswith(prefix):
            qr_data = qr_data[len(prefix):]
        return int(qr_data)
    except:
        return None


# =============================================================================
# 快速帧提取 (ffmpeg)
# =============================================================================

def extract_frames_ffmpeg(
    video_path: str,
    output_dir: str,
    start_time: float,
    duration: float,
    fps: float,
    width: int = 960
) -> List[str]:
    """
    使用ffmpeg批量提取帧 (比OpenCV快10倍)

    Returns: 帧文件路径列表
    """
    os.makedirs(output_dir, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(start_time),
        "-i", video_path,
        "-t", str(duration),
        "-vf", f"fps={fps},scale={width}:-1",
        "-q:v", "2",
        os.path.join(output_dir, "frame_%04d.jpg")
    ]

    subprocess.run(cmd, capture_output=True)

    # 返回生成的帧文件列表
    frames = sorted(Path(output_dir).glob("frame_*.jpg"))
    return [str(f) for f in frames]


def extract_frames_at_times(
    video_path: str,
    times: List[float],
    output_dir: str,
    width: int = 960
) -> Dict[float, str]:
    """
    在指定时间点提取帧（优化版：批量提取而非逐帧调用ffmpeg）

    Returns: {time: frame_path}
    """
    os.makedirs(output_dir, exist_ok=True)
    result = {}

    if not times:
        return result

    # 按时间排序
    sorted_times = sorted(times)

    # 计算采样间隔（假设times是均匀间隔的粗采样）
    if len(sorted_times) > 1:
        avg_interval = (sorted_times[-1] - sorted_times[0]) / (len(sorted_times) - 1)
        fps_extract = 1.0 / avg_interval if avg_interval > 0 else 1.0
        # 限制fps，避免提取过多帧
        fps_extract = min(fps_extract, 2.0)  # 最多2fps
    else:
        fps_extract = 1.0

    # 批量提取：使用fps filter一次性提取所有帧
    start_time = sorted_times[0]
    duration = sorted_times[-1] - start_time + 2.0  # 加2秒缓冲

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(start_time),
        "-i", video_path,
        "-t", str(duration),
        "-vf", f"fps={fps_extract},scale={width}:-1",
        "-q:v", "2",
        os.path.join(output_dir, "frame_%04d.jpg")
    ]

    subprocess.run(cmd, capture_output=True)

    # 匹配提取的帧到请求的时间点
    frame_files = sorted(Path(output_dir).glob("frame_*.jpg"))

    for i, frame_file in enumerate(frame_files):
        # 计算该帧对应的时间
        frame_time = start_time + i / fps_extract

        # 找到最接近的请求时间点
        closest_time = min(sorted_times, key=lambda t: abs(t - frame_time))

        # 如果误差在0.5秒内，认为匹配成功
        if abs(frame_time - closest_time) < 0.5:
            if closest_time not in result:  # 避免重复
                result[closest_time] = str(frame_file)

    return result


# =============================================================================
# 并行QR检测
# =============================================================================

def detect_qr_from_file(args) -> Tuple[str, float, Optional[int]]:
    """从文件检测QR码 (用于并行)"""
    frame_path, frame_time, prefix = args

    try:
        img = cv2.imread(frame_path)
        if img is None:
            return frame_path, frame_time, None

        # ROI: 中心60%区域
        h, w = img.shape[:2]
        margin_y = int(h * 0.2)
        margin_x = int(w * 0.2)
        roi = img[margin_y:h-margin_y, margin_x:w-margin_x]

        qr_codes = detect_qr(roi)
        for qr_data in qr_codes:
            qr_num = parse_qr_number(qr_data, prefix)
            if qr_num is not None:
                return frame_path, frame_time, qr_num

        # ROI没找到，尝试全图
        qr_codes = detect_qr(img)
        for qr_data in qr_codes:
            qr_num = parse_qr_number(qr_data, prefix)
            if qr_num is not None:
                return frame_path, frame_time, qr_num

    except Exception as e:
        pass

    return frame_path, frame_time, None


def parallel_qr_detect(
    frame_files: List[str],
    frame_times: List[float],
    prefix: str = "",
    max_workers: int = None
) -> Dict[int, List[float]]:
    """
    并行检测多个帧的QR码

    Returns: {qr_number: [detection_times]}
    """
    if max_workers is None:
        # 限制每个相机的worker数，避免多相机并行时过度订阅
        max_workers = max(2, mp.cpu_count() // 4)

    args_list = [(f, t, prefix) for f, t in zip(frame_files, frame_times)]

    detections = {}

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(detect_qr_from_file, args) for args in args_list]

        for future in as_completed(futures):
            _, frame_time, qr_num = future.result()
            if qr_num is not None:
                if qr_num not in detections:
                    detections[qr_num] = []
                detections[qr_num].append(frame_time)

    return detections


# =============================================================================
# 两阶段扫描 (优化版)
# =============================================================================

def scan_video_fast(
    video_path: str,
    config: ScanConfig,
    prefix: str = "",
    temp_base: str = None
) -> Tuple[List[Tuple[float, int]], Dict]:
    """
    快速两阶段QR扫描

    阶段1: 粗扫描 - 每2秒一帧，找到QR码位置
    阶段2: 精细扫描 - 在QR位置±5秒内密集扫描
    """
    # 获取视频信息
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,duration",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    info = json.loads(result.stdout)

    fps_str = info['streams'][0].get('r_frame_rate', '60/1')
    num, den = map(int, fps_str.split('/'))
    video_fps = num / den

    duration = float(info['streams'][0].get('duration', 0))
    if duration == 0:
        duration = float(info['format'].get('duration', 0))

    scan_duration = min(config.max_scan_duration, duration)

    cam_name = Path(video_path).parent.name

    stats = {
        'video_path': video_path,
        'fps': video_fps,
        'duration': duration,
        'scan_duration': scan_duration
    }

    # 创建临时目录
    if temp_base:
        temp_dir = os.path.join(temp_base, f"qr_scan_{cam_name}")
    else:
        temp_dir = tempfile.mkdtemp(prefix=f"qr_scan_{cam_name}_")

    try:
        # ===== 阶段1: 增量窗口粗扫描 =====
        # 策略：从小窗口开始，找到QR码后立即停止，避免扫描整个240秒
        window_size = 30.0  # 初始窗口30秒
        window_step = 30.0  # 每次扩展30秒
        coarse_detections = {}
        first_qr_time = None

        coarse_dir = os.path.join(temp_dir, "coarse")

        while True:
            # 当前窗口范围
            window_end = min(window_size, scan_duration)

            # 提取当前窗口的帧
            coarse_times = list(np.arange(0, window_end, config.coarse_interval))

            frame_map = extract_frames_at_times(
                video_path, coarse_times, coarse_dir, config.frame_width
            )

            if frame_map:
                # 并行检测
                frame_files = list(frame_map.values())
                frame_times = list(frame_map.keys())

                coarse_detections = parallel_qr_detect(frame_files, frame_times, prefix)

            # 找到QR码 → 立即停止
            if coarse_detections:
                all_times = []
                for times in coarse_detections.values():
                    all_times.extend(times)
                first_qr_time = min(all_times)
                stats['phase1_found_at'] = first_qr_time
                stats['phase1_window'] = window_end
                break

            # 没找到 → 扩展窗口
            if window_end >= scan_duration:
                # 已经扫描完整个视频，尝试更密集的扫描
                shutil.rmtree(coarse_dir, ignore_errors=True)
                coarse_times = list(np.arange(0, scan_duration, config.coarse_interval / 2))
                frame_map = extract_frames_at_times(
                    video_path, coarse_times, coarse_dir, config.frame_width
                )
                coarse_detections = parallel_qr_detect(
                    list(frame_map.values()), list(frame_map.keys()), prefix
                )
                if coarse_detections:
                    all_times = []
                    for times in coarse_detections.values():
                        all_times.extend(times)
                    first_qr_time = min(all_times)
                    stats['phase1_found_at'] = first_qr_time
                break

            # 扩展窗口
            window_size += window_step

        # 清理粗扫描帧
        shutil.rmtree(coarse_dir, ignore_errors=True)

        if not coarse_detections or first_qr_time is None:
            return [], stats

        # ===== 阶段2: 精细扫描 =====
        fine_start = max(0, first_qr_time - config.fine_range)
        fine_end = min(scan_duration, first_qr_time + config.fine_range)
        fine_duration = fine_end - fine_start

        stats['phase2_range'] = (fine_start, fine_end)

        fine_dir = os.path.join(temp_dir, "fine")
        frame_files = extract_frames_ffmpeg(
            video_path, fine_dir,
            fine_start, fine_duration,
            config.fine_fps, config.frame_width
        )

        if not frame_files:
            return [], stats

        # 计算每帧的时间
        frame_times = [fine_start + i / config.fine_fps for i in range(len(frame_files))]

        # 并行检测
        fine_detections = parallel_qr_detect(frame_files, frame_times, prefix)

        # 清理
        shutil.rmtree(fine_dir, ignore_errors=True)

        # 合并结果
        all_detections = {}
        for qr_num, times in coarse_detections.items():
            if qr_num not in all_detections:
                all_detections[qr_num] = []
            all_detections[qr_num].extend(times)

        for qr_num, times in fine_detections.items():
            if qr_num not in all_detections:
                all_detections[qr_num] = []
            all_detections[qr_num].extend(times)

        # 取中位数并检查是否达到目标检测数
        result = []
        for qr_num, times in sorted(all_detections.items()):
            median_time = float(np.median(times))
            result.append((median_time, qr_num))

        result.sort()
        stats['total_detections'] = len(result)

        # 提前停止：如果已经找到足够的QR码，不继续扫描
        if len(result) >= config.target_detections:
            stats['early_stop'] = True
            print(f"  ✅ {cam_name}: 已找到{len(result)}个QR码，提前停止扫描")

        return result, stats

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def scan_camera_worker(args) -> Tuple[str, List[Tuple[float, int]], Dict]:
    """扫描单个相机 (worker)"""
    cam_name, video_path, config, anchor_map, anchor_fps, prefix, temp_base = args

    detections, stats = scan_video_fast(video_path, config, prefix, temp_base)

    # 计算anchor偏移
    if detections and anchor_map:
        offsets = []
        for video_time, qr_num in detections:
            if qr_num in anchor_map:
                offsets.append(video_time - anchor_map[qr_num])
            else:
                offsets.append(video_time - qr_num / anchor_fps)

        if offsets:
            stats['anchor_offset'] = float(np.median(offsets))
            stats['anchor_offset_std'] = float(np.std(offsets))

    return cam_name, detections, stats


# =============================================================================
# Anchor处理
# =============================================================================

def extract_anchor_fast(
    video_path: str,
    prefix: str = "",
    max_samples: int = 200,
    temp_dir: str = None
) -> Tuple[Dict[int, float], float]:
    """快速提取anchor metadata"""

    # 获取视频信息
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,duration",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    info = json.loads(result.stdout)

    fps_str = info['streams'][0].get('r_frame_rate', '60/1')
    num, den = map(int, fps_str.split('/'))
    fps = num / den

    duration = float(info['streams'][0].get('duration', 0))
    if duration == 0:
        duration = float(info['format'].get('duration', 0))

    # 提取帧
    if temp_dir is None:
        temp_dir = tempfile.mkdtemp(prefix="anchor_")

    try:
        # 每5帧提取一帧
        extract_fps = fps / 5
        frames = extract_frames_ffmpeg(
            video_path, temp_dir,
            0, min(duration, max_samples / extract_fps),
            extract_fps, 960
        )

        if not frames:
            return {}, fps

        frame_times = [i / extract_fps for i in range(len(frames))]

        # 并行检测
        detections = parallel_qr_detect(frames, frame_times, prefix)

        # 构建anchor map
        anchor_map = {}
        for qr_num, times in detections.items():
            anchor_map[qr_num] = float(np.median(times))

        return anchor_map, fps

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# =============================================================================
# Smart Cut
# =============================================================================

def get_video_codec(video_path: str) -> str:
    """获取视频编码"""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip().lower()


def get_video_info(video_path: str) -> Dict:
    """获取视频信息"""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,duration",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    info = json.loads(result.stdout)

    fps_str = info['streams'][0].get('r_frame_rate', '60/1')
    num, den = map(int, fps_str.split('/'))
    fps = num / den

    duration = float(info['streams'][0].get('duration', 0))
    if duration == 0:
        duration = float(info['format'].get('duration', 0))

    return {'fps': fps, 'duration': duration}


def get_hardware_encoder(codec: str) -> List[str]:
    """获取硬件编码器"""
    result = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                          capture_output=True, text=True)
    encoders = result.stdout

    if codec in ['hevc', 'h265']:
        if sys.platform == 'darwin' and 'hevc_videotoolbox' in encoders:
            return ['hevc_videotoolbox', '-q:v', '65']
        elif 'hevc_nvenc' in encoders:
            return ['hevc_nvenc', '-preset', 'p1', '-cq', '18']
        return ['libx265', '-preset', 'ultrafast', '-crf', '18']
    else:
        if sys.platform == 'darwin' and 'h264_videotoolbox' in encoders:
            return ['h264_videotoolbox', '-q:v', '65']
        elif 'h264_nvenc' in encoders:
            return ['h264_nvenc', '-preset', 'p1', '-cq', '18']
        return ['libx264', '-preset', 'ultrafast', '-crf', '18']


def get_keyframes(video_path: str, max_time: float) -> List[float]:
    """获取关键帧"""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_frames", "-show_entries", "frame=pts_time,pict_type",
        "-read_intervals", f"%+{max_time}", "-of", "csv=p=0",
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    keyframes = []
    for line in result.stdout.strip().split('\n'):
        if line:
            parts = line.split(',')
            if len(parts) >= 2 and parts[1].strip().startswith('I'):
                try:
                    keyframes.append(float(parts[0].strip()))
                except:
                    pass
    return sorted(keyframes)


def fix_hevc_tag(video_path: str) -> bool:
    """
    修复 HEVC 视频的 codec tag (hev1 -> hvc1)
    hvc1 是 Apple 兼容的格式，hev1 在 macOS 上无法播放

    返回: 是否成功
    """
    # 检查当前 tag
    cmd_check = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_tag_string",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    result = subprocess.run(cmd_check, capture_output=True, text=True)
    current_tag = result.stdout.strip()

    # 如果已经是 hvc1，无需修复
    if current_tag == "hvc1":
        return True

    # 需要修复：hev1 -> hvc1
    temp_path = video_path + ".tmp.mp4"

    cmd_fix = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", video_path,
        "-c", "copy",
        "-tag:v", "hvc1",
        temp_path
    ]

    result = subprocess.run(cmd_fix, capture_output=True, text=True)

    if result.returncode == 0 and os.path.exists(temp_path):
        # 替换原文件
        os.replace(temp_path, video_path)
        return True
    else:
        # 清理临时文件
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False


# =============================================================================
# Smart Cut - 关键帧检测和智能裁剪
# =============================================================================

def get_keyframe_positions(video_path: str, max_duration: float = 10.0) -> List[float]:
    """
    获取视频开头的关键帧位置（时间戳）
    只扫描前max_duration秒，因为我们只需要开头的关键帧信息
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_frames",
        "-show_entries", "frame=pts_time,pict_type",
        "-read_intervals", f"%+{max_duration}",
        "-of", "csv=p=0",
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    keyframes = []
    for line in result.stdout.strip().split('\n'):
        if not line:
            continue
        parts = line.split(',')
        if len(parts) >= 2:
            pts_time = parts[0].strip()
            pict_type = parts[1].strip()
            # 检查是否是I帧（关键帧）
            if pict_type.startswith('I') and pts_time:
                try:
                    keyframes.append(float(pts_time))
                except ValueError:
                    pass

    return sorted(keyframes)


def find_nearest_keyframes(keyframes: List[float], target_time: float) -> Tuple[float, float]:
    """找到目标时间前后最近的关键帧"""
    before = 0.0
    after = keyframes[-1] if keyframes else target_time

    for kf in keyframes:
        if kf <= target_time:
            before = kf
        else:
            after = kf
            break

    return before, after


def get_hardware_encoder(codec: str = 'hevc') -> List[str]:
    """检测并返回可用的硬件编码器"""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True, text=True
    )
    encoders_output = result.stdout

    # 根据原始编码选择对应的硬件编码器
    if codec in ['hevc', 'h265']:
        # HEVC编码器
        if sys.platform == 'darwin' and 'hevc_videotoolbox' in encoders_output:
            return ['hevc_videotoolbox', '-q:v', '65']
        elif 'hevc_nvenc' in encoders_output:
            return ['hevc_nvenc', '-preset', 'p1', '-rc', 'vbr', '-cq', '18']
        else:
            return ['libx265', '-preset', 'ultrafast', '-crf', '18']
    else:
        # H.264编码器
        if sys.platform == 'darwin' and 'h264_videotoolbox' in encoders_output:
            return ['h264_videotoolbox', '-q:v', '65']
        elif 'h264_nvenc' in encoders_output:
            return ['h264_nvenc', '-preset', 'p1', '-rc', 'vbr', '-cq', '18']
        else:
            return ['libx264', '-preset', 'ultrafast', '-crf', '18']


def direct_copy_video(
    input_path: str,
    output_path: str,
    start_time: float,
    duration: float
) -> Tuple[bool, str]:
    """直接copy（当起始点正好在关键帧时）"""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(start_time),
        "-i", input_path,
        "-t", str(duration),
        "-c:v", "copy",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0 and os.path.exists(output_path):
        return True, None
    else:
        return False, result.stderr


def fallback_reencode(
    input_path: str,
    output_path: str,
    start_time: float,
    duration: float,
    use_hardware_accel: bool = True
) -> Tuple[bool, str]:
    """退回到全重编码（使用硬件加速H.264）"""
    cam_name = Path(input_path).parent.name

    if use_hardware_accel:
        encoder = get_hardware_encoder('h264')
    else:
        encoder = ['libx264', '-preset', 'ultrafast', '-crf', '18']

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(start_time),
        "-i", input_path,
        "-t", str(duration),
        "-c:v", encoder[0]
    ]
    if len(encoder) > 1:
        cmd.extend(encoder[1:])
    cmd.extend([
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path
    ])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0 and os.path.exists(output_path):
        return True, None
    else:
        return False, result.stderr


def smart_cut_worker(args) -> Tuple[str, bool, str]:
    """
    Smart Cut worker - Python实现的智能裁剪（不依赖外部smartcut CLI）

    原理:
    1. 找到start_time之前最近的关键帧 (kf_before)
    2. 找到start_time之后最近的关键帧 (kf_after)
    3. 重编码 [kf_before, kf_after) 但只输出 [start_time, kf_after)
    4. Copy [kf_after, end]
    5. Concat拼接
    """
    cam_name, input_path, output_path, start_time, duration, temp_dir = args

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)

    try:
        # 获取视频FPS
        cmd_fps = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=r_frame_rate",
            "-of", "default=noprint_wrappers=1:nokey=1",
            input_path
        ]
        result_fps = subprocess.run(cmd_fps, capture_output=True, text=True)
        fps_str = result_fps.stdout.strip()
        num, den = map(int, fps_str.split('/'))
        fps = num / den

        # 特殊情况：如果start_time接近0，直接用copy
        if start_time < 0.02:
            success, error = direct_copy_video(input_path, output_path, start_time, duration)
            if success:
                fix_hevc_tag(output_path)
                return cam_name, True, "direct_copy"
            else:
                return cam_name, False, error[:200] if error else "copy failed"

        # 步骤1: 获取关键帧位置
        keyframes = get_keyframe_positions(input_path, max_duration=start_time + 5)

        if not keyframes:
            # 没有关键帧，退回到全重编码
            success, error = fallback_reencode(input_path, output_path, start_time, duration)
            if success:
                fix_hevc_tag(output_path)
                return cam_name, True, "full_reencode"
            else:
                return cam_name, False, error[:200] if error else "reencode failed"

        kf_before, kf_after = find_nearest_keyframes(keyframes, start_time)

        # 计算需要跳过的时间
        skip_duration = start_time - kf_before

        # 如果start_time正好在关键帧上，直接用copy
        if skip_duration < 0.001:
            success, error = direct_copy_video(input_path, output_path, start_time, duration)
            if success:
                fix_hevc_tag(output_path)
                return cam_name, True, "keyframe_copy"
            else:
                return cam_name, False, error[:200] if error else "copy failed"

        # 步骤2: Smart Cut
        segment1_duration = kf_after - start_time

        if segment1_duration <= 0:
            # 找下一个关键帧
            for kf in keyframes:
                if kf > start_time:
                    kf_after = kf
                    segment1_duration = kf_after - start_time
                    break

        # 临时文件
        segment1_path = os.path.join(temp_dir, f"{cam_name}_seg1.mp4")
        segment2_path = os.path.join(temp_dir, f"{cam_name}_seg2.mp4")
        concat_list = os.path.join(temp_dir, f"{cam_name}_concat.txt")

        # 段1: 重编码（只有几十帧）
        encoder = get_hardware_encoder('h264')

        cmd1 = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", str(kf_before),
            "-i", input_path,
            "-ss", str(skip_duration),
            "-t", str(segment1_duration),
            "-c:v", encoder[0]
        ]
        if len(encoder) > 1:
            cmd1.extend(encoder[1:])
        cmd1.extend([
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            segment1_path
        ])

        result1 = subprocess.run(cmd1, capture_output=True, text=True)
        if result1.returncode != 0:
            success, error = fallback_reencode(input_path, output_path, start_time, duration)
            return cam_name, success, "seg1_failed->reencode"

        # 段2: 直接copy
        segment2_start = kf_after
        segment2_duration = duration - segment1_duration

        if segment2_duration > 0:
            cmd2 = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-ss", str(segment2_start),
                "-i", input_path,
                "-t", str(segment2_duration),
                "-c:v", "copy",
                "-c:a", "copy",
                "-movflags", "+faststart",
                segment2_path
            ]

            result2 = subprocess.run(cmd2, capture_output=True, text=True)
            if result2.returncode != 0:
                # 段2 copy失败，重编码
                cmd2_reencode = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", str(segment2_start),
                    "-i", input_path,
                    "-t", str(segment2_duration),
                    "-c:v", encoder[0]
                ]
                if len(encoder) > 1:
                    cmd2_reencode.extend(encoder[1:])
                cmd2_reencode.extend(["-c:a", "aac", "-movflags", "+faststart", segment2_path])
                subprocess.run(cmd2_reencode, capture_output=True, text=True)

        # 步骤3: Concat拼接
        with open(concat_list, 'w') as f:
            f.write(f"file '{segment1_path}'\n")
            if segment2_duration > 0 and os.path.exists(segment2_path):
                f.write(f"file '{segment2_path}'\n")

        cmd_concat = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c", "copy",
            "-movflags", "+faststart",
            output_path
        ]

        result_concat = subprocess.run(cmd_concat, capture_output=True, text=True)
        if result_concat.returncode != 0:
            success, error = fallback_reencode(input_path, output_path, start_time, duration)
            return cam_name, success, "concat_failed->reencode"

        # 验证输出
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            fix_hevc_tag(output_path)
            reencode_frames = int(segment1_duration * fps)
            total_frames = int(duration * fps)
            return cam_name, True, f"smartcut ({reencode_frames}/{total_frames}f)"
        else:
            success, error = fallback_reencode(input_path, output_path, start_time, duration)
            return cam_name, success, "verify_failed->reencode"

    except Exception as e:
        return cam_name, False, str(e)[:200]


# =============================================================================
# 主类
# =============================================================================

class FastQRSync:
    """快速QR码同步器"""

    def __init__(
        self,
        input_dir: str,
        output_dir: str,
        anchor_video: str,
        config: ScanConfig = None,
        prefix: str = "",
        max_workers: int = None,
        verify_with_timecode: bool = True,
        cleanup_threshold_frames: float = 3.0,
        cleanup_on_success: bool = False,
        dry_run_cleanup: bool = False
    ):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.anchor_video = anchor_video
        self.config = config or ScanConfig()
        self.prefix = prefix
        self.max_workers = max_workers or mp.cpu_count()

        # 验证与清理选项
        self.verify_with_timecode = verify_with_timecode
        self.cleanup_threshold_frames = cleanup_threshold_frames
        self.cleanup_on_success = cleanup_on_success
        self.dry_run_cleanup = dry_run_cleanup

        self.cameras = self._detect_cameras()
        self.verification_result: Optional[VerificationResult] = None

    def _detect_cameras(self) -> Dict[str, str]:
        cameras = {}
        for d in sorted(self.input_dir.glob("cam*")):
            if d.is_dir() and d.name != "cam19":
                videos = list(d.glob("*.MP4")) + list(d.glob("*.mp4"))
                if videos:
                    cameras[d.name] = str(videos[0])
        return cameras

    def run(self) -> int:
        t0 = time.time()

        print("\n" + "=" * 70)
        print("快速QR码同步")
        print("=" * 70)
        print(f"输入: {self.input_dir}")
        print(f"相机: {len(self.cameras)}个")
        print(f"CPU: {self.max_workers}核")

        # 1. Anchor
        print("\n[1/3] 提取Anchor...")
        t1 = time.time()
        anchor_map, anchor_fps = extract_anchor_fast(self.anchor_video, self.prefix)
        print(f"  ✅ {len(anchor_map)}个QR码 ({time.time()-t1:.1f}s)")

        if not anchor_map:
            print("  ❌ 无法提取anchor")
            return 1

        # 2. 并行扫描所有相机
        print(f"\n[2/3] 并行扫描 {len(self.cameras)} 个相机...")
        t2 = time.time()

        temp_base = str(self.output_dir / ".temp_scan")
        os.makedirs(temp_base, exist_ok=True)

        tasks = [
            (cam, path, self.config, anchor_map, anchor_fps, self.prefix, temp_base)
            for cam, path in self.cameras.items()
        ]

        camera_stats = {}

        # 使用线程池调度，每个相机内部用进程池
        with ThreadPoolExecutor(max_workers=min(8, len(self.cameras))) as executor:
            futures = {executor.submit(scan_camera_worker, t): t[0] for t in tasks}

            for future in as_completed(futures):
                cam_name, detections, stats = future.result()
                camera_stats[cam_name] = stats

                if 'anchor_offset' in stats:
                    print(f"  ✅ {cam_name}: {stats['total_detections']}个QR, "
                          f"偏移={stats['anchor_offset']:.3f}s")
                else:
                    print(f"  ❌ {cam_name}: 未检测到QR码")

        shutil.rmtree(temp_base, ignore_errors=True)
        print(f"  扫描耗时: {time.time()-t2:.1f}s")

        # 检查失败的相机，用密集扫描重试
        failed_cams = [c for c, s in camera_stats.items() if 'anchor_offset' not in s]
        if failed_cams:
            print(f"\n  🔄 对 {len(failed_cams)} 个失败相机进行密集扫描...")
            dense_config = DenseScanConfig()
            temp_base_retry = str(self.output_dir / ".temp_scan_retry")
            os.makedirs(temp_base_retry, exist_ok=True)

            retry_tasks = [
                (cam, self.cameras[cam], dense_config, anchor_map, anchor_fps, self.prefix, temp_base_retry)
                for cam in failed_cams
            ]

            with ThreadPoolExecutor(max_workers=min(2, len(failed_cams))) as executor:
                futures = {executor.submit(scan_camera_worker, t): t[0] for t in retry_tasks}

                for future in as_completed(futures):
                    cam_name, detections, stats = future.result()
                    camera_stats[cam_name] = stats

                    if 'anchor_offset' in stats:
                        print(f"  ✅ {cam_name}: 密集扫描成功! {stats['total_detections']}个QR, "
                              f"偏移={stats['anchor_offset']:.3f}s")
                    else:
                        print(f"  ❌ {cam_name}: 密集扫描仍失败")

            shutil.rmtree(temp_base_retry, ignore_errors=True)

        # 计算同步参数
        valid_cams = {c: s for c, s in camera_stats.items() if 'anchor_offset' in s}

        if not valid_cams:
            print("❌ 没有有效相机")
            return 1

        anchor_offsets = {c: s['anchor_offset'] for c, s in valid_cams.items()}

        # 获取视频时长
        for cam in valid_cams:
            info = get_video_info(self.cameras[cam])
            valid_cams[cam]['duration'] = info['duration']
            valid_cams[cam]['fps'] = info['fps']

        # 计算同步偏移
        # anchor_offset 大 = 视频开始得早（QR出现晚）= 需要跳过更多
        # anchor_offset 小 = 视频开始得晚（QR出现早）= 参考点
        min_anchor = min(anchor_offsets.values())
        sync_offsets = {c: o - min_anchor for c, o in anchor_offsets.items()}

        # 计算同步后的结束时间（原始时长 - 跳过的部分）
        synced_end_times = {c: s['duration'] - sync_offsets[c] for c, s in valid_cams.items()}
        sync_duration = min(synced_end_times.values())

        print(f"\n  同步时长: {sync_duration:.2f}s")

        # 3. Smart Cut
        print(f"\n[3/3] Smart Cut...")
        t3 = time.time()

        self.output_dir.mkdir(parents=True, exist_ok=True)
        synced_dir = self.output_dir / "cameras_synced"
        synced_dir.mkdir(exist_ok=True)
        temp_dir = str(self.output_dir / ".temp_cut")
        os.makedirs(temp_dir, exist_ok=True)

        cut_tasks = []
        for cam in valid_cams:
            video_path = self.cameras[cam]
            output_path = synced_dir / cam / Path(video_path).name
            cut_tasks.append((
                cam, video_path, str(output_path),
                sync_offsets[cam], sync_duration, temp_dir
            ))

        results = {}
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(smart_cut_worker, t): t[0] for t in cut_tasks}

            for future in as_completed(futures):
                cam, ok, msg = future.result()
                results[cam] = (ok, msg)
                status = "✅" if ok else "❌"
                print(f"  {status} {cam}: {msg}")

        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"  裁剪耗时: {time.time()-t3:.1f}s")

        # 保存meta
        meta = {
            'input_dir': str(self.input_dir),
            'output_dir': str(synced_dir),
            'sync_method': 'qr_fast',
            'sync_duration': sync_duration,
            'cameras': {
                f"{c}/{Path(self.cameras[c]).name}": {
                    'anchor_offset': anchor_offsets[c],
                    'sync_offset': sync_offsets[c],
                    'qr_count': valid_cams[c].get('total_detections', 0)
                }
                for c in valid_cams
            }
        }

        # ===== 验证阶段 =====
        verification_passed = True
        if self.verify_with_timecode:
            print(f"\n[4/4] 验证同步准确性...")
            t4 = time.time()

            # 提取timecode偏移
            tc_offsets = calculate_timecode_offsets(self.cameras, fps=60.0)

            # 验证QR vs TC
            self.verification_result = verify_qr_vs_timecode(
                anchor_offsets,
                tc_offsets,
                fps=60.0,
                threshold_frames=self.cleanup_threshold_frames
            )

            # 打印验证报告
            print("\n  Camera  | QR偏移   | TC偏移   | 差异(s) | 差异(帧) | 状态")
            print("  --------|----------|----------|---------|----------|-----")

            for cam, result in sorted(self.verification_result.camera_results.items()):
                if isinstance(result, dict) and 'qr_offset' in result:
                    qr_off = result.get('qr_offset')
                    tc_off = result.get('tc_offset')
                    disc_s = result.get('discrepancy_sec')
                    disc_f = result.get('discrepancy_frames')
                    passed = result.get('passed')

                    qr_str = f"{qr_off:.3f}s" if qr_off is not None else "N/A"
                    tc_str = f"{tc_off:.3f}s" if tc_off is not None else "N/A"
                    disc_s_str = f"{disc_s:.3f}s" if disc_s is not None else "N/A"
                    disc_f_str = f"{disc_f:.1f}帧" if disc_f is not None else "N/A"

                    if passed is None:
                        status = "⚠️ 无TC"
                    elif passed:
                        status = "✅"
                    else:
                        status = "❌"

                    print(f"  {cam:7} | {qr_str:8} | {tc_str:8} | {disc_s_str:7} | {disc_f_str:8} | {status}")

            print()
            if self.verification_result.passed:
                print(f"  最大差异: {self.verification_result.max_discrepancy_frames:.1f}帧")
                print(f"  验证结果: ✅ 通过（所有相机 < {self.cleanup_threshold_frames}帧）")
            else:
                if self.verification_result.problem_cameras:
                    print(f"  最大差异: {self.verification_result.max_discrepancy_frames:.1f}帧")
                    print(f"  验证结果: ❌ 失败（问题相机: {', '.join(self.verification_result.problem_cameras)}）")
                else:
                    print(f"  验证结果: ❌ 失败（无法获取足够的timecode数据）")

            verification_passed = self.verification_result.passed
            print(f"  验证耗时: {time.time()-t4:.1f}s")

            # 保存验证报告到meta
            meta['verification'] = {
                'passed': self.verification_result.passed,
                'max_discrepancy_frames': self.verification_result.max_discrepancy_frames,
                'threshold_frames': self.cleanup_threshold_frames,
                'problem_cameras': self.verification_result.problem_cameras,
                'camera_results': {
                    cam: {
                        k: v for k, v in res.items()
                        if not isinstance(v, float) or not (v != v)  # exclude NaN
                    } if isinstance(res, dict) else res
                    for cam, res in self.verification_result.camera_results.items()
                }
            }

        with open(synced_dir / 'meta_info.json', 'w') as f:
            json.dump(meta, f, indent=2)

        # 保存单独的验证报告
        if self.verify_with_timecode and self.verification_result:
            report_path = synced_dir / 'verification_report.json'
            with open(report_path, 'w') as f:
                json.dump(meta.get('verification', {}), f, indent=2)

        # ===== 清理阶段 =====
        cleanup_done = False
        if self.cleanup_on_success and self.verify_with_timecode:
            step_num = "5/5" if self.verify_with_timecode else "4/4"
            print(f"\n[{step_num}] 清理原始文件...")

            cleanup_ok, cleanup_msg = cleanup_originals_if_verified(
                self.input_dir,
                self.verification_result,
                dry_run=self.dry_run_cleanup
            )

            if cleanup_ok:
                print(f"  ✅ {cleanup_msg}")
                cleanup_done = True
            else:
                print(f"  ⚠️ {cleanup_msg}")

        elapsed = time.time() - t0
        success = sum(1 for ok, _ in results.values() if ok)

        print("\n" + "=" * 70)
        print(f"完成! {success}/{len(cut_tasks)} 成功")
        if self.verify_with_timecode:
            verify_status = "✅ 验证通过" if verification_passed else "❌ 验证失败"
            print(f"同步验证: {verify_status}")
        if self.cleanup_on_success:
            if cleanup_done:
                print(f"原始文件: {'[干运行] 将被删除' if self.dry_run_cleanup else '已删除'}")
            else:
                print(f"原始文件: 已保留")
        print(f"总耗时: {elapsed:.1f}s ({elapsed/60:.1f}分钟)")
        print("=" * 70)

        return 0 if success == len(cut_tasks) else 1


def main():
    parser = argparse.ArgumentParser(
        description='快速QR码同步 (带Timecode验证)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 单组: 同步+验证
  python sync_gopro_qr_fast.py \\
      --input_dir /path/to/P4_1 \\
      --output_dir /path/to/output \\
      --anchor_video /path/to/qr_sync.mp4

  # 单组: 同步+验证+清理原始文件
  python sync_gopro_qr_fast.py \\
      --input_dir /path/to/P4_1 \\
      --output_dir /path/to/output \\
      --anchor_video /path/to/qr_sync.mp4 \\
      --cleanup

  # 批量: 先干运行查看效果
  python sync_gopro_qr_fast.py \\
      --input_dir /path/to/organized \\
      --output_dir /path/to/synced \\
      --anchor_video /path/to/qr_sync.mp4 \\
      --batch --cleanup --dry-run

  # 批量: 确认后真正删除
  python sync_gopro_qr_fast.py \\
      --input_dir /path/to/organized \\
      --output_dir /path/to/synced \\
      --anchor_video /path/to/qr_sync.mp4 \\
      --batch --cleanup
        """
    )
    parser.add_argument('--input_dir', required=True, help='输入目录')
    parser.add_argument('--output_dir', required=True, help='输出目录')
    parser.add_argument('--anchor_video', required=True, help='QR码anchor视频')
    parser.add_argument('--prefix', default='', help='QR码前缀')
    parser.add_argument('--max_workers', type=int, default=None, help='最大并行数')
    parser.add_argument('--batch', action='store_true', help='批量处理子目录')

    # 验证选项
    verify_group = parser.add_argument_group('验证选项')
    verify_group.add_argument('--verify', action='store_true', dest='verify',
                             default=True, help='启用timecode验证 (默认开启)')
    verify_group.add_argument('--no-verify', action='store_false', dest='verify',
                             help='禁用timecode验证')
    verify_group.add_argument('--cleanup-threshold', type=float, default=10.0,
                             help='验证阈值帧数 (默认: 10帧)')

    # 清理选项
    cleanup_group = parser.add_argument_group('清理选项')
    cleanup_group.add_argument('--cleanup', action='store_true',
                              help='验证通过后删除原始视频')
    cleanup_group.add_argument('--dry-run', action='store_true',
                              help='干运行: 显示将删除但不实际删除')

    args = parser.parse_args()

    if args.batch:
        # 批量模式
        input_path = Path(args.input_dir)
        sessions = sorted([d for d in input_path.iterdir()
                          if d.is_dir() and not d.name.startswith('.')
                          and list(d.glob("cam*"))])

        print(f"\n批量处理 {len(sessions)} 个sessions")
        if args.cleanup:
            if args.dry_run:
                print("⚠️ 干运行模式: 将显示删除操作但不实际执行")
            else:
                print("⚠️ 清理模式: 验证通过的原始文件将被删除!")

        total_start = time.time()
        results = []
        verification_summary = []

        for session in sessions:
            print(f"\n{'='*70}")
            print(f"处理 {session.name}")

            t0 = time.time()
            syncer = FastQRSync(
                str(session),
                str(Path(args.output_dir) / f"{session.name}_sync"),
                args.anchor_video,
                prefix=args.prefix,
                max_workers=args.max_workers,
                verify_with_timecode=args.verify,
                cleanup_threshold_frames=args.cleanup_threshold,
                cleanup_on_success=args.cleanup,
                dry_run_cleanup=args.dry_run
            )
            ret = syncer.run()
            elapsed = time.time() - t0

            sync_ok = ret == 0
            verify_ok = syncer.verification_result.passed if syncer.verification_result else None
            results.append((session.name, sync_ok, verify_ok, elapsed))

        print("\n" + "=" * 70)
        print("批量处理完成")
        print("=" * 70)

        print("\n  Session        | 同步 | 验证 | 耗时")
        print("  ----------------|------|------|------")
        for name, sync_ok, verify_ok, t in results:
            sync_status = "✅" if sync_ok else "❌"
            if verify_ok is None:
                verify_status = "跳过"
            elif verify_ok:
                verify_status = "✅"
            else:
                verify_status = "❌"
            print(f"  {name:15} | {sync_status:4} | {verify_status:4} | {t:.1f}s")

        total = time.time() - total_start
        sync_success = sum(1 for _, ok, _, _ in results if ok)
        verify_success = sum(1 for _, _, ok, _ in results if ok is True)
        verify_total = sum(1 for _, _, ok, _ in results if ok is not None)

        print(f"\n同步成功: {sync_success}/{len(results)}")
        if args.verify:
            print(f"验证通过: {verify_success}/{verify_total}")
        print(f"总耗时: {total:.1f}s ({total/60:.1f}分钟)")

        return 0 if all(ok for _, ok, _, _ in results) else 1

    else:
        syncer = FastQRSync(
            args.input_dir,
            args.output_dir,
            args.anchor_video,
            prefix=args.prefix,
            max_workers=args.max_workers,
            verify_with_timecode=args.verify,
            cleanup_threshold_frames=args.cleanup_threshold,
            cleanup_on_success=args.cleanup,
            dry_run_cleanup=args.dry_run
        )
        return syncer.run()


if __name__ == '__main__':
    sys.exit(main())
