# CSL Multi-Camera Calibration Pipeline

[![Python 3.6+](https://img.shields.io/badge/python-3.6+-blue.svg)](https://www.python.org/downloads/)
[![OpenCV 4.5+](https://img.shields.io/badge/opencv-4.5+-green.svg)](https://opencv.org/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Multi-camera synchronization and calibration pipeline for biomechanics motion capture. Processes **16 GoPro cameras** (60fps, 4K) + **1 PrimeColor OptiTrack camera** (120fps) to produce per-camera extrinsic calibrations and distribute ground truth (GT) data from mocap to each camera view.

**Target Application**: 3D human motion capture with prosthetic subjects (bilateral amputees), tracking skeleton joints, blade edges, and body markers.

---

## 📋 Table of Contents

- [Quick Start](#quick-start)
- [Complete Workflow](#complete-workflow)
- [System Requirements](#system-requirements)
- [Key Features](#key-features)
- [Project Structure](#project-structure)
- [Documentation](#documentation)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## 🚀 Quick Start

### 1. Environment Setup

#### Option A: Automated Setup (Recommended)

```bash
# Clone repository
git clone <repository-url>
cd csl_pipeline

# Initialize multical submodule
git submodule update --init --recursive

# Run automated setup script (Linux/macOS)
./setup_environment.sh

# Activate environment
conda activate camcalib

# Verify installation
python -c "import cv2, numpy, scipy; print('✅ Environment ready!')"
```

#### Option B: Manual Setup

<details>
<summary>Click to expand manual setup instructions</summary>

```bash
# 1. Create conda environment
conda create -n camcalib python=3.8 -y
conda activate camcalib

# 2. Install system dependencies
# Ubuntu/Debian:
sudo apt-get update
sudo apt-get install -y ffmpeg libzbar0 libzbar-dev libsm6 libxext6 libxrender-dev

# macOS (requires Homebrew):
brew install ffmpeg zbar
export DYLD_LIBRARY_PATH="/opt/homebrew/opt/zbar/lib:$DYLD_LIBRARY_PATH"

# 3. Install Python packages
pip install --upgrade pip
pip install -r requirements.txt

# 4. Install multical in development mode
cd multical
pip install -e .
cd ..

# 5. Verify installation
python -c "from pyzbar import pyzbar; print('✅ pyzbar OK')"
python -c "import quaternion; print('✅ numpy-quaternion OK')"
ffmpeg -version | head -1
```

</details>

### 2. Run Your First Pipeline

#### Step 0: Organize GoPro Videos
```bash
# Reorganize from per-camera to per-session structure
python workflow/organize_gopro_videos.py \
    --input /path/to/P7_gopro \
    --output /path/to/organized \
    --participant P7
```

#### Step 1: Process Mocap Data
```bash
# Convert AVI + CSV → GT (skeleton, markers, blade editor)
python workflow/process_mocap_session.py \
    /path/to/P7_mocap \
    -o /path/to/P7_output \
    --batch
```

**Interactive**: Open `blade_editor_*.html` in browser to annotate blade edges.

#### Step 2: Extract Blade Edges + Refine cam19
```bash
# Extract blade 3D trajectories
python workflow/process_blade_session.py \
    /path/to/P7_mocap \
    -o /path/to/P7_output \
    --batch --share_json P7_1

# Refine PrimeColor camera extrinsics (interactive)
python post_calibration/refine_extrinsics.py \
    --markers /path/to/P7_output/P7_4/body_markers.npy \
    --names /path/to/P7_output/P7_4/body_marker_names.json \
    --video /path/to/P7_output/P7_4/video.mp4 \
    --camera /path/to/P7_output/P7_4/cam19_initial.yaml \
    --output /path/to/P7_output/P7_4/cam19_refined.yaml \
    --no-sync
```

#### Step 3: Complete GoPro Pipeline (One Command!)
```bash
# Sync + Calibrate + Distribute GT (all sessions)
python workflow/process_p7_complete.py \
    --organized_dir /path/to/organized \
    --mocap_dir /path/to/P7_output \
    --output_dir /path/to/synced \
    --anchor_video /path/to/organized/qr_sync.mp4 \
    --calibration_session P7_1 \
    --start_time 707 \
    --duration 264 \
    --sessions P7_1 P7_2 P7_3 P7_4 P7_5
```

**⏱️ Total Time**: ~2 hours (including interactive steps)

**📖 For detailed step-by-step instructions, see**:
- **English**: [workflow/P7_complete_workflow_EN.md](workflow/P7_complete_workflow_EN.md) 🇬🇧
- **中文**: [workflow/P7_complete_workflow_CN.md](workflow/P7_complete_workflow_CN.md) 🇨🇳
- **日本語**: [workflow/P7_complete_workflow_JP.md](workflow/P7_complete_workflow_JP.md) 🇯🇵

---

## 📚 Complete Workflow

The pipeline consists of **three major phases**:

| Phase | Description | Time | Output |
|-------|-------------|------|--------|
| **Phase 1** | Mocap data processing | ~40 min | `skeleton_h36m.npy`, `body_markers.npy`, blade HTML editor |
| **Phase 2** | Blade edge extraction + cam19 refinement | ~15 min | `*_edges.npy`, `cam19_refined.yaml` |
| **Phase 3** | GoPro sync + calibration + GT distribution | ~65 min | 17-camera YAMLs, per-camera GT arrays |

**Key Interactive Steps**:
1. **Blade annotation**: Click markers in HTML editor to define edge ordering (~10 min)
2. **cam19 refinement**: Click marker pairs to optimize camera parameters (~10 min)
3. **Optional GT verification**: Adjust temporal offset for each camera (~5 min/camera)

See [workflow documentation](workflow/P7_complete_workflow_EN.md) for detailed instructions.

## System Requirements

- **OS**: Linux (Ubuntu/Debian) or macOS
- **Python**: 3.6+
- **Memory**: 32 GB+ recommended
- **Storage**: ~30-50 GB per session
- **CPU**: Multi-core recommended (parallel processing)

## Key Features

- **Two-phase calibration**: Reuse GoPro rig calibration across sessions, only refine cam19
- **Fast QR synchronization**: ~4-6 minutes per session (optimized with batch processing)
- **Interactive refinement**: Manual marker-based camera optimization
- **Dual blade support**: Automatic detection and processing of multiple prosthetic blades
- **GT distribution**: Automatic temporal mapping from 120fps mocap to 60fps GoPro

## Project Structure

```
csl_pipeline/
├── workflow/           # High-level session processing scripts
├── scripts/            # Core data processing (CSV→H36M, blade edges, GT distribution)
├── sync/               # Video synchronization (QR + time-based)
├── post_calibration/   # Interactive refinement and YAML generation
├── utils/              # Shared utilities (triangulation, I/O, plotting)
├── multical/           # Multi-camera calibration library (submodule)
├── tool_scripts/       # Standalone validation tools
├── requirements.txt    # Python dependencies
└── setup_environment.sh # Automated environment setup
```

## Documentation

- **[CLAUDE.md](CLAUDE.md)**: Project overview and architecture
- **[WORKFLOW.md](WORKFLOW.md)**: Detailed 1400-line pipeline guide
- **[workflow/P7_complete_workflow_EN.md](workflow/P7_complete_workflow_EN.md)**: End-to-end workflow (English)
- **[workflow/P7_complete_workflow_CN.md](workflow/P7_complete_workflow_CN.md)**: 端到端工作流程（中文）
- **[workflow/P7_complete_workflow_JP.md](workflow/P7_complete_workflow_JP.md)**: エンドツーエンドワークフロー（日本語）

## Dependencies

### System Dependencies
- **ffmpeg/ffprobe**: Video processing
- **libzbar**: QR code detection (Linux)

### Python Packages
- **Core**: numpy, scipy, pandas
- **Computer Vision**: opencv-contrib-python (>=4.5.0)
- **3D Geometry**: numpy-quaternion, aniposelib
- **Optimization**: numba
- **Visualization**: matplotlib
- **Configuration**: PyYAML, easydict

See [requirements.txt](requirements.txt) for complete list.

## Hardware Setup

- **16 GoPro cameras**: 60fps, 4K resolution (cam1-cam12, cam15-cam18)
- **1 PrimeColor camera**: 120fps, 1920x1080 (cam19, OptiTrack system)
- **ChArUco calibration board**: 7x9 grid, DICT_5X5_100

## 🔧 Troubleshooting

### Issue 1: `pyzbar` ImportError

**Symptoms**: `ImportError: cannot import name 'pyzbar'`

**Solution**:
```bash
# Linux (Ubuntu/Debian)
sudo apt-get install libzbar0 libzbar-dev
pip install pyzbar

# macOS
brew install zbar
export DYLD_LIBRARY_PATH="/opt/homebrew/opt/zbar/lib:$DYLD_LIBRARY_PATH"
pip install pyzbar
```

### Issue 2: High RMS Calibration Error (>2.5 pixels)

**Symptoms**: `calibration.json` reports RMS > 2.5 pixels

**Causes**:
- ChArUco board moving too fast
- Insufficient stable frames (< 100)
- Poor board detection quality

**Solution**:
1. Re-select time range with stable board: adjust `--start_time` and `--duration`
2. Check frame count in `original_stable/` directory
3. Lower movement threshold: add `--movement_threshold 3.0` to calibration script

### Issue 3: GT Temporal Misalignment

**Symptoms**: Skeleton projection doesn't align with video (delayed or advanced)

**Solution**: Use interactive offset adjustment tool:
```bash
python post_calibration/verify_gt_offset.py \
    --session_dir /path/to/cameras_synced \
    --camera camX \
    --start 60 --duration 10

# Controls: [ ] to adjust offset, 'e' to save, 'q' to quit
```

### Issue 4: `cam19_refined.yaml` Not Found

**Symptoms**: `process_p7_complete.py` reports missing cam19_refined.yaml

**Solution**:
1. Verify refinement was completed: check `/path/to/P7_output/*/cam19_refined.yaml`
2. If missing, run Phase 2 refinement step
3. Or manually specify path: `--cam19_refined /path/to/cam19_refined.yaml`

### Issue 5: ffmpeg Hardware Encoder Not Available (Linux)

**Symptoms**: `Unknown encoder 'h264_videotoolbox'`

**Solution**: The code automatically falls back to `libx264` on Linux. No action needed.

**For more issues**, see the troubleshooting section in [workflow documentation](workflow/P7_complete_workflow_EN.md#troubleshooting).

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Commit** your changes (`git commit -m 'Add amazing feature'`)
4. **Push** to the branch (`git push origin feature/amazing-feature`)
5. **Open** a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 📧 Contact

For questions, issues, or collaboration inquiries:

- **Project Lead**: [Your Name]
- **Email**: [your.email@domain.com]
- **Issues**: [GitHub Issues](https://github.com/your-repo/csl_pipeline/issues)

## 🙏 Acknowledgments

- **multical**: Multi-camera calibration library
- **aniposelib**: Triangulation utilities
- **OpenCV**: Computer vision foundation
- **OptiTrack**: Mocap system support

---

**Made with ❤️ for biomechanics research**
