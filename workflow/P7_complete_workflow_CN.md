# CSL Pipeline 完整工作流程指南（P7）

完整处理一个 participant 的多相机校准和 GT 分发，从原始数据到最终输出。

---

## 目录

1. [前提条件](#前提条件)
2. [数据准备](#数据准备)
3. [Pipeline 总览](#pipeline-总览)
4. [Pipeline 三大阶段](#pipeline-三大阶段)
5. [验证和优化工具](#验证和优化工具)
6. [输出目录结构](#输出目录结构)
7. [故障排除](#故障排除)

---

## 前提条件

### 软件环境

```bash
# Conda 环境
conda activate camcalib

# 确认 pyzbar 加速可用
python -c "from pyzbar import pyzbar; print('✅ pyzbar 已安装')"
export DYLD_LIBRARY_PATH="/opt/homebrew/opt/zbar/lib:$DYLD_LIBRARY_PATH"
```

### 硬件资源

- **存储空间**：每个 session 约 30-50 GB (GoPro 4K 视频 + 处理输出)
- **内存**：建议 32 GB 以上（多相机并行处理）
- **外接存储**：
  - FastACIS: GoPro 原始数据 + 同步输出 + 校准结果
  - T7/KINGSTON: Mocap 原始数据 + GT 输出

---

## 数据准备

### 1. Mocap 原始数据放置

**位置**: `/Volumes/KINGSTON/P7_mocap/`

**目录结构**:
```
P7_mocap/
├── P7_1/
│   ├── session1-Camera 13 (C11764).avi       # PrimeColor 视频（可能有多个段）
│   ├── session1-Camera 13 (C11764) (1).avi   # 续段
│   └── Take 2024-11-05 03.50.49 PM.csv       # Motive 导出的 CSV
├── P7_2/
│   ├── session2-Camera 13 (C11764).avi
│   └── Take 2024-11-05 04.10.22 PM.csv
├── P7_3/, P7_4/, P7_5/
└── Cal_2026-02-01.mcal                        # OptiTrack 校准文件（可选，放在父目录）
```

**关键文件**:
- **AVI 视频**: PrimeColor 相机（120fps, 1920x1080）的原始录制
- **CSV 文件**: Motive 导出的骨架和 marker 数据
- **.mcal 文件**: OptiTrack 系统校准（包含 cam19 初始外参）

---

### 2. GoPro 原始数据放置

**位置**: `/Volumes/FastACIS/csl_11_5/P7_gopro/`

**原始结构**（per-camera）:
```
P7_gopro/
├── cam1/
│   ├── GX010279.MP4  # Session 1
│   ├── GX010280.MP4  # Session 2
│   ├── GX010281.MP4  # Session 3
│   └── ...
├── cam2/
│   ├── GX010276.MP4  # Session 1
│   ├── GX010277.MP4  # Session 2
│   └── ...
├── cam3/, ..., cam18/
└── qr_sync.mp4        # QR anchor 视频（用于同步）
```

**注意**:
- GoPro 命名按 **时间顺序** 自动编号，需根据实际录制顺序对应 session
- 确保每个相机的视频数量一致（通常 5 个 session = 5 个视频）

---

### 3. 组织 GoPro 数据（per-session 结构）

**为什么需要**：原始数据是 per-camera 结构，pipeline 需要 per-session 结构。

**工作原理**：
- 扫描每个 `cam*/` 目录下的 MP4 文件
- 按文件名编号排序（GoPro 自动递增编号 = 录制时间顺序）
- 假设每个相机的**第 N 个视频 = 第 N 个 session**
- `--participant P7` 用于生成输出目录名（P7_1, P7_2, ...）
- 同时复制 `qr_sync.mp4` 到输出目录根部

**前提**：所有 GoPro 在每次 session 中同时开始/停止录制，确保文件编号对应关系正确。

```bash
# 预览（dry-run）
python workflow/organize_gopro_videos.py \
    --input /Volumes/FastACIS/csl_11_5/P7_gopro \
    --output /Volumes/FastACIS/csl_11_5/organized \
    --participant P7 \
    --dry-run

# 确认无误后，实际执行
python workflow/organize_gopro_videos.py \
    --input /Volumes/FastACIS/csl_11_5/P7_gopro \
    --output /Volumes/FastACIS/csl_11_5/organized \
    --participant P7
```

**输出结构**:
```
organized/
├── qr_sync.mp4           # 复制的 QR anchor 视频
├── P7_1/
│   ├── cam1/GX010279.MP4
│   ├── cam2/GX010276.MP4
│   └── ... (16 cameras)
├── P7_2/, P7_3/, P7_4/, P7_5/
```

---

## Pipeline 总览

### 依赖流程图

```
数据准备
├── 放置 Mocap 原始数据 (AVI + CSV + .mcal)
└── 组织 GoPro 原始数据 (per-camera → per-session)
    ↓
Phase 1: Mocap 数据处理 (自动)
├── 输出: video.mp4, skeleton_h36m.npy, body_markers.npy, blade_editor_*.html
└── ⚠️ 手动: 打开 HTML 编辑器，标注 blade 边缘 → blade_polygon_order_*.json
    ↓
Phase 2: Blade 边缘提取 + cam19 Refinement
├── 输出: *_edges.npy (blade 3D 轨迹)
└── ⚠️ 手动: 运行 refine_extrinsics.py 优化 cam19 → cam19_refined.yaml
    ↓
Phase 3: GoPro 完整 Pipeline (自动)
├── 3.1 GoPro QR 同步
├── 3.2 PrimeColor 同步
├── 3.3 17 相机联合校准 (仅 calibration session)
├── 3.4 生成每相机 YAML
└── 3.5 GT 分发 → cam*/gt/skeleton.npy, blade_edges.npy, valid_mask.npy
    ↓
验证 (可选手动)
├── verify_gt_offset.py → 检查时间对齐
├── verify_cam19_gt.py → 可视化投影质量
└── refine_extrinsics.py → 单独优化某个 GoPro (如需)
    ↓
完成: cam*/gt/ 可用于训练
```

---

## Pipeline 三大阶段

### Phase 1: Mocap 数据处理

**目的**: AVI 视频合并 + CSV 转 GT + 生成 blade 标注工具

#### 输入

| 文件 | 来源 | 说明 |
|------|------|------|
| `P7_X/*.avi` | Motive 录制 | PrimeColor 120fps 视频（可能多段） |
| `P7_X/*.csv` | Motive 导出 | 骨架 + marker 3D 坐标 |
| `*.mcal` | OptiTrack 校准 | 包含 cam19 初始内外参 |

#### 命令

```bash
# 批量处理所有 sessions
python workflow/process_mocap_session.py \
    /Volumes/KINGSTON/P7_mocap \
    -o /Volumes/KINGSTON/P7_output \
    --batch
```

#### 输出（每个 session）

| 文件 | Shape / 格式 | 说明 |
|------|-------------|------|
| `video.mp4` | 120fps, 1920x1080 | PrimeColor 视频（多段已合并，已去水印） |
| `cam19_initial.yaml` | YAML (K, D, R, t) | 从 .mcal 提取的初始内外参 |
| `skeleton_h36m.npy` | `(N, 17, 3)` | H36M 格式骨架，17 关节，世界坐标系 |
| `body_markers.npy` | `(N, 27, 3)` | Plug-in Gait markers（用于 cam19 refinement） |
| `leg_markers.npy` | `(N, 8, 3)` | 截肢侧 markers L1-L4, R1-R4 |
| `blade_editor_*.html` | HTML | 交互式 3D blade 标注工具 |

```
P7_output/P7_1/
├── video.mp4
├── cam19_initial.yaml
├── skeleton_h36m.npy
├── body_markers.npy, body_marker_names.json
├── leg_markers.npy, leg_marker_names.json
├── blade_editor_Rblade.html
├── blade_editor_lblade2.html
└── ...
```

#### 🔧 交互步骤：Blade 边缘标注

**必须手动完成**（每个 blade 只需标注一次，所有 session 共享）

1. **打开 HTML 编辑器**:
   ```bash
   open /Volumes/KINGSTON/P7_output/P7_1/blade_editor_Rblade.html
   ```

2. **标注边缘顺序**:
   - 选择 **Edge 1**，按顺序点击 blade 第一边缘的 markers（从尖端到根部，或反之）
   - 切换到 **Edge 2**，按 **相同方向** 点击 blade 第二边缘的 markers
   - 确保两条边方向一致（都是 tip→base 或都是 base→tip）

3. **导出 JSON**:
   - 点击 **Export JSON**
   - 保存为 `blade_polygon_order_Rblade.json`
   - 放到 `/Volumes/KINGSTON/P7_output/P7_1/` 目录

4. **重复其他 blade**:
   - 如果有 lblade2，重复上述步骤生成 `blade_polygon_order_lblade2.json`

**快捷键**:
- `1` / `2`: 切换 Edge 1/2
- `Z`: 撤销
- `R`: 重置视角
- 左键拖拽: 旋转，右键拖拽: 平移，滚轮: 缩放

---

### Phase 2: Blade 边缘提取 + cam19 Refinement

**目的**: 从 CSV 提取 blade 3D 轨迹 + 优化 cam19 外参

#### 输入（前置依赖）

| 文件 | 来源 | 说明 |
|------|------|------|
| `P7_X/*.csv` | Mocap 原始数据 | 包含 blade rigid body 的 marker 坐标 |
| `blade_polygon_order_*.json` | **Phase 1 手动标注** | 定义 blade 两条边的 marker 顺序 |
| `body_markers.npy` | Phase 1 输出 | 用于 cam19 refinement 的 marker 对应 |
| `video.mp4` | Phase 1 输出 | 用于 cam19 refinement 的视频 |
| `cam19_initial.yaml` | Phase 1 输出 | cam19 初始参数（refinement 起点） |

#### 命令

```bash
# 共享 P7_1 的 JSON 到其他 sessions，然后批量提取
python workflow/process_blade_session.py \
    /Volumes/KINGSTON/P7_mocap \
    -o /Volumes/KINGSTON/P7_output \
    --batch \
    --share_json P7_1
```

#### 输出（每个 session）

| 文件 | Shape | 说明 |
|------|-------|------|
| `Rblade_edge1.npy` | `(N, M, 3)` | Edge 1 原始 marker 轨迹 |
| `Rblade_edge2.npy` | `(N, M, 3)` | Edge 2 原始 marker 轨迹 |
| `Rblade_edges.npy` | `(N, K, 2, 3)` | 弧长重采样后的两条边缘对 |
| `Rblade_marker_names.json` | JSON | 记录 rigid body 名和 marker 分组 |

> 同理 `lblade2_*` 文件，如果存在第二个 blade。

**关键**: `*_edges.npy` shape 中 `K` = 两条边 marker 数的最大值（弧长重采样后等间距），`2` = 两条边，`3` = xyz 世界坐标

#### 🔧 交互步骤：cam19 外参优化

**目的**: 优化 PrimeColor 相机的外参（内参 + 外参），使 mocap markers 投影到视频帧上精确对齐

**选择 session**: 选择 **motion range 最大** 的 session（例如 P7_4），优化一次后应用到所有 sessions

```bash
# cam19 直接模式（使用显式路径，因为文件在 P7_output 而非 synced 目录）
python post_calibration/refine_extrinsics.py \
    --markers /Volumes/KINGSTON/P7_output/P7_4/body_markers.npy \
    --video /Volumes/KINGSTON/P7_output/P7_4/video.mp4 \
    --camera /Volumes/KINGSTON/P7_output/P7_4/cam19_initial.yaml \
    --output /Volumes/KINGSTON/P7_output/P7_4/cam19_refined.yaml
```

**操作步骤**:
1. **找到清晰帧**: 按 `f` 自动查找 markers 清晰且静止的帧
2. **标注 marker pairs**:
   - 左键点击 3D marker（左侧列表）
   - 右键点击视频中对应的真实位置
   - 重复至少 **6 个 marker pairs**（越多越好，建议 8-10 个）
3. **优化参数**:
   - 按 `O`: 使用 scipy 优化（14 参数：内参 fx,fy,cx,cy + 畸变 k1-k6 + 外参 rvec,tvec）
   - 按 `P`: 使用 solvePnP（仅外参，需要 4+ pairs）
4. **验证投影**:
   - 用 `[` / `]` 切换前后帧，检查投影是否一直对齐
   - 如果误差大，添加更多 marker pairs 或重新优化
5. **导出**: 按 `e` 保存 `cam19_refined.yaml`

**快捷键总结**:
- `f`: 自动查找稳定帧
- `Space`: 播放/暂停
- `[` / `]`: 前/后一帧
- `,` / `.`: 前/后 10 帧
- `O`: scipy 优化（推荐）
- `P`: solvePnP 优化
- `u`: 撤销最后一个 marker pair
- `c`: 清除所有 pairs
- `e`: 导出 YAML
- `q`: 退出

**目标**: Reprojection error < 2.0 pixels（理想 < 1.5 pixels）

---

### Phase 3: GoPro 完整 Pipeline

**目的**: GoPro 同步 + PrimeColor 同步 + 17 相机联合校准 + YAML 生成 + GT 分发

#### 输入（前置依赖）

| 文件 | 来源 | 说明 |
|------|------|------|
| `organized/P7_X/cam*/*.MP4` | 数据准备 step 3 | 按 session 组织好的 GoPro 视频 |
| `organized/qr_sync.mp4` | 数据准备 step 3 | QR anchor 视频 |
| `cam19_refined.yaml` | **Phase 2 手动优化** | participant 级别的 cam19 优化参数 |
| `skeleton_h36m.npy` | Phase 1 输出 | 用于 GT 分发 |
| `*_edges.npy` | Phase 2 输出 | 用于 GT 分发（blade 轨迹） |

#### 命令

```bash
python workflow/process_p7_complete.py \
    --organized_dir /Volumes/FastACIS/csl_11_5/organized \
    --mocap_dir /Volumes/KINGSTON/P7_output \
    --output_dir /Volumes/FastACIS/csl_11_5/synced \
    --anchor_video /Volumes/FastACIS/csl_11_5/organized/qr_sync.mp4 \
    --calibration_session P7_1 \
    --start_time 707 \
    --duration 264 \
    --sessions P7_1 P7_2 P7_3 P7_4 P7_5
```

**注意**:
- `--cam19_refined` 参数可选（自动搜索 `P7_output/*/cam19_refined.yaml`）

#### 如何确定 `--calibration_session` 和 `--start_time` / `--duration`

校准需要 ChArUco board 在画面中**静止且清晰**。确定方法：

1. **选择 calibration session**: 打开每个 session 的某个 GoPro 视频（同步前的原始视频即可），找到 ChArUco board 出现且长时间静止的 session。通常是录制开始或结束时放置 board 的阶段
2. **确定 start_time**: 找到 board 开始静止的大致秒数。可以用视频播放器拖动时间轴查看
3. **确定 duration**: board 静止持续的时长（秒）。建议至少 60 秒，越长越好（更多稳定帧 → 更低 RMS）
4. **验证**: Pipeline 会在 `original_stable/` 中保存检测到的稳定帧。如果稳定帧 < 100 个，考虑扩大时间范围或换 session

**示例**: 如果 P7_1 的 GoPro 视频中，ChArUco board 在第 707 秒到 971 秒之间静止放置，则 `--start_time 707 --duration 264`

#### Pipeline 自动执行的步骤

**Phase 3.1: GoPro QR 同步** (~5 分钟/session)
- 使用 QR anchor 视频对所有 16 个 GoPro 进行时间同步
- 输出：`P7_X_sync/cameras_synced/cam1-18/*.MP4` (已同步，60fps)
- 跳过逻辑：如果 `meta_info.json` 存在则跳过

**Phase 3.2: PrimeColor 同步** (~2 分钟/session)
- 基于 GoPro 时间轴，将 PrimeColor 120fps 视频重采样到 60fps
- 输出：
  - `cam19/primecolor_synced.mp4` (60fps)
  - `cam19/sync_mapping.json` (时间映射)
- 跳过逻辑：如果输出文件存在则跳过

**Phase 3.3: 17 相机联合校准** (~15 分钟，仅 calibration_session)
- 提取帧 (5 fps, 指定时间范围)
- 检测 ChArUco board 静止帧
- 运行 `multical` 联合优化，生成 `calibration.json`
- **目标 RMS**: < 1.6 pixels (excellent), < 2.5 pixels (acceptable)
- 跳过逻辑：如果 `calibration.json` 存在则跳过

**Phase 3.4: 生成 Individual YAMLs** (~1 分钟)
- 组合：
  - `calibration.json` (GoPro 间的外参，共享给所有 sessions)
  - `cam19_refined.yaml` (Mocap → cam19，participant-wide)
- 生成 17 个相机 YAML: `cam1.yaml`, ..., `cam18.yaml`, `cam19.yaml`
- 输出位置：`individual_cam_params/`

**Phase 3.5: GT 分发** (~1 分钟/session)
- 创建 symlinks 到 cam19/ 目录:
  - `skeleton_h36m.npy` → mocap 输出的骨架数据
  - `Rblade_edges.npy`, `lblade2_edges.npy` → 每个 blade 的边缘数据
  - `aligned_edges.npy` → **主 blade 的 symlink**（优先级: Rblade > lblade2 > 第一个找到的 blade）
- `aligned_edges.npy` 说明：这是一个便捷 symlink，`distribute_gt.py` 读取它来生成各相机的 `blade_edges.npy`。对于双侧截肢（有 Rblade 和 lblade2），**只有主 blade 会被分发为通用的 `blade_edges.npy`**。各 blade 的原始文件仍可通过 cam19/ 中的命名 symlink 单独访问
- 调用 `distribute_gt.py` 将 120fps mocap 数据重采样到每个 GoPro 60fps 时间轴
- 输出：`cam*/gt/skeleton.npy`, `cam*/gt/blade_edges.npy`, `cam*/gt/valid_mask.npy`

---

## 验证和优化工具

### 1. GT 时间对齐验证

**目的**: 检查 skeleton 投影是否与视频帧精确对齐（时间同步是否正确）

```bash
python post_calibration/verify_gt_offset.py \
    --session_dir /Volumes/FastACIS/csl_11_5/synced/P7_1_sync/cameras_synced \
    --camera cam1 \
    --start 60 \
    --duration 10
```

**操作**:
- `Space`: 播放/重播
- `[` / `]`: 调整 offset ±1 帧
- `,` / `.`: 调整 offset ±0.5 帧
- `e`: 保存 offset 到 `camera_offsets.json` 并自动重新分发 GT
- `q`: 退出

**目标**: 骨架关节点始终覆盖在运动员身体上，无明显延迟或提前

---

### 2. cam19 可视化验证

**目的**: 验证 cam19 refinement 效果，查看 skeleton + blade edges 投影质量

```bash
python post_calibration/verify_cam19_gt.py \
    --video /Volumes/KINGSTON/P7_output/P7_1/video.mp4 \
    --camera_yaml /Volumes/KINGSTON/P7_output/P7_4/cam19_refined.yaml \
    --gt_dir /Volumes/KINGSTON/P7_output/P7_1/ \
    --start 30 \
    --duration 10 \
    --scale 0.5 \
    --output cam19_P7_1_vis.mp4
```

**输出**: 带骨架 + blade 投影的视频（自动检测所有 blade）

**特性**:
- 自动检测 `Rblade_edges.npy`, `lblade2_edges.npy` 等
- 不同 blade 用不同颜色
- 120fps 原始视频，完整帧率输出

---

### 3. 单独 GoPro 外参优化（可选）

**目的**: 如果某个 GoPro 投影质量不佳，可单独优化其外参

```bash
# 便捷模式：只需 session + cam + 两个 base 路径
python post_calibration/refine_extrinsics.py \
    --session P7_1 --cam cam3 \
    --markers-base /Volumes/KINGSTON/P7_output \
    --synced-base /Volumes/FastACIS/csl_11_5/synced
```

**操作步骤同 cam19 refinement**

---

## 输出目录结构

### Mocap 输出

```
/Volumes/KINGSTON/P7_output/
├── P7_1/
│   ├── video.mp4                      # 120fps PrimeColor
│   ├── cam19_initial.yaml
│   ├── skeleton_h36m.npy
│   ├── body_markers.npy
│   ├── leg_markers.npy
│   ├── Rblade_edges.npy               # (N, K, 2, 3)
│   ├── lblade2_edges.npy
│   └── blade_polygon_order_*.json
├── P7_2/, P7_3/, P7_4/, P7_5/
└── P7_4/
    └── cam19_refined.yaml             # 优化后的 cam19（应用到所有 sessions）
```

### GoPro + Calibration 输出

```
/Volumes/FastACIS/csl_11_5/
├── organized/                         # Phase 0: 组织后的原始数据
│   ├── qr_sync.mp4
│   └── P7_X/cam*/video.MP4
└── synced/
    └── P7_X_sync/cameras_synced/
        ├── meta_info.json             # GoPro sync 元数据
        ├── cam1/, ..., cam18/         # Synced GoPro videos
        ├── cam19/
        │   ├── primecolor_synced.mp4  # 60fps
        │   ├── sync_mapping.json
        │   ├── skeleton_h36m.npy      # Symlink
        │   ├── Rblade_edges.npy       # Symlink
        │   ├── lblade2_edges.npy      # Symlink
        │   └── aligned_edges.npy      # Symlink → 主 blade
        ├── original/                  # 提取的帧（用于校准）
        ├── original_stable/           # 稳定帧
        │   └── calibration.json       # 仅在 calibration_session (P7_1)
        ├── individual_cam_params/     # 每个相机的 YAML
        │   ├── cam1.yaml
        │   ├── ...
        │   └── cam19.yaml
        ├── camera_offsets.json        # Per-camera 时间 offset（可选）
        └── cam*/gt/                   # 分发的 GT 数据
            ├── skeleton.npy           # (N_gopro, 17, 3)
            ├── blade_edges.npy        # (N_gopro, K, 2, 3)
            ├── valid_mask.npy         # (N_gopro,) bool
            └── gt_info.json
```

---

## 故障排除

### 1. pyzbar 警告

**问题**: `⚠️ 推荐安装pyzbar加速`

**解决**:
```bash
pip install pyzbar
export DYLD_LIBRARY_PATH="/opt/homebrew/opt/zbar/lib:$DYLD_LIBRARY_PATH"
```

### 2. RMS error 过高

**问题**: `calibration.json` RMS > 2.5 pixels

**原因**:
- ChArUco board 检测质量差
- 稳定帧数量不足（< 100 帧）
- 选择的时间范围 board 运动太快

**解决**:
1. 重新选择时间范围（`--start_time` / `--duration`），确保 board 长时间静止
2. 检查 `original_stable/` 中的帧数量
3. 降低 `find_stable_boards.py` 的 `--movement_threshold`（默认 5.0）

### 3. GT temporal misalignment

**问题**: 骨架投影不对齐，延迟或提前

**解决**:
```bash
python post_calibration/verify_gt_offset.py \
    --session_dir /path/to/cameras_synced \
    --camera camX
```
调整 offset 后按 `e` 保存并重新分发 GT

### 4. cam19 refinement 失败

**问题**: 投影误差始终很大

**原因**:
- body_markers.npy 不存在（某些 session 缺失）
- 选择的帧 markers 不清晰或被遮挡
- 标注的 marker pairs 太少（< 6 个）

**解决**:
1. 确保 `body_markers.npy` 存在
2. 按 `f` 多次查找不同的清晰帧
3. 标注 8-10 个清晰的 marker pairs
4. 使用 `O` (scipy) 而不是 `P` (solvePnP)

### 5. 找不到 cam19_refined.yaml

**问题**: `process_p7_complete.py` 报错找不到 cam19_refined.yaml

**原因**: 未运行 Phase 2 或 refinement 未导出

**解决**:
1. 确认 `/Volumes/KINGSTON/P7_output/` 下至少有一个 session 包含 `cam19_refined.yaml`
2. 如果没有，运行 Phase 2 的交互 refinement 步骤
3. 手动指定路径：`--cam19_refined /path/to/cam19_refined.yaml`

---

## 完整时间估计

| 阶段 | 时间 | 说明 |
|-----|------|------|
| **数据准备** | | |
| 组织 GoPro 视频 | ~5 min | 文件复制/移动 |
| **Phase 1: Mocap 处理** | | |
| AVI→MP4 + CSV→GT | ~30 min | 5 sessions 串行 |
| Blade HTML 标注 | ~10 min | 每个 blade 一次（手动） |
| **Phase 2: Blade 提取 + cam19 Refine** | | |
| Blade edges 提取 | ~5 min | 批量自动 |
| cam19 refinement | ~10 min | 一次（手动） |
| **Phase 3: GoPro Pipeline** | | |
| GoPro QR sync | ~25 min | 5 sessions × 5 min |
| PrimeColor sync | ~10 min | 5 sessions × 2 min |
| Calibration (P7_1) | ~15 min | 一次 |
| Generate YAMLs | ~5 min | 所有 sessions |
| Distribute GT | ~5 min | 所有 sessions |
| **总计** | **~2 小时** | 含交互时间 |

---

## 下一步

完成 pipeline 后：

1. ✅ **验证投影质量**: 使用 `verify_gt_offset.py` 检查每个 camera 的时间对齐
2. ✅ **可视化检查**: 使用 `verify_cam19_gt.py` 查看 skeleton + blade 投影效果
3. ✅ **开始训练/推理**: 使用 `cam*/gt/` 中的数据进行模型训练

祝顺利！🚀
