#!/bin/bash
# CSL Pipeline Environment Setup Script
# Compatible with Ubuntu/Debian Linux and macOS

set -e  # Exit on error

echo "=========================================="
echo "CSL Multi-Camera Calibration Pipeline"
echo "Environment Setup"
echo "=========================================="

# Detect OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
    echo "✓ Detected OS: Linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
    echo "✓ Detected OS: macOS"
else
    echo "✗ Unsupported OS: $OSTYPE"
    exit 1
fi

# Install system dependencies
echo ""
echo "Installing system dependencies..."
if [[ "$OS" == "linux" ]]; then
    echo "Running: sudo apt-get update && sudo apt-get install -y ..."
    sudo apt-get update
    sudo apt-get install -y \
        ffmpeg \
        libzbar0 \
        libzbar-dev \
        libsm6 \
        libxext6 \
        libxrender-dev \
        libgomp1 \
        libglib2.0-0

    echo "✓ System dependencies installed (Linux)"

elif [[ "$OS" == "macos" ]]; then
    # Check if Homebrew is installed
    if ! command -v brew &> /dev/null; then
        echo "✗ Homebrew not found. Please install from https://brew.sh"
        exit 1
    fi

    echo "Running: brew install ffmpeg zbar"
    brew install ffmpeg zbar

    # Set library path for pyzbar
    export DYLD_LIBRARY_PATH="/opt/homebrew/opt/zbar/lib:$DYLD_LIBRARY_PATH"
    echo 'export DYLD_LIBRARY_PATH="/opt/homebrew/opt/zbar/lib:$DYLD_LIBRARY_PATH"' >> ~/.bashrc
    echo 'export DYLD_LIBRARY_PATH="/opt/homebrew/opt/zbar/lib:$DYLD_LIBRARY_PATH"' >> ~/.zshrc

    echo "✓ System dependencies installed (macOS)"
fi

# Check Python version
echo ""
echo "Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [[ $PYTHON_MAJOR -ge 3 ]] && [[ $PYTHON_MINOR -ge 6 ]]; then
    echo "✓ Python $PYTHON_VERSION detected"
else
    echo "✗ Python 3.6+ required, found $PYTHON_VERSION"
    exit 1
fi

# Create/activate conda environment
echo ""
echo "Setting up conda environment..."
ENV_NAME="camcalib"

if conda env list | grep -q "^$ENV_NAME "; then
    echo "✓ Conda environment '$ENV_NAME' already exists"
    read -p "Do you want to recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        conda env remove -n $ENV_NAME -y
        conda create -n $ENV_NAME python=3.8 -y
        echo "✓ Recreated conda environment '$ENV_NAME'"
    fi
else
    conda create -n $ENV_NAME python=3.8 -y
    echo "✓ Created conda environment '$ENV_NAME'"
fi

# Activate environment
echo ""
echo "Activating environment..."
eval "$(conda shell.bash hook)"
conda activate $ENV_NAME

# Install Python dependencies
echo ""
echo "Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "✓ Python dependencies installed"

# Install multical in development mode
echo ""
echo "Installing multical submodule..."
if [ -d "multical" ]; then
    cd multical
    pip install -e .
    cd ..
    echo "✓ multical installed in development mode"
else
    echo "⚠ multical directory not found. Run 'git submodule update --init' if needed"
fi

# Verify installation
echo ""
echo "=========================================="
echo "Verifying installation..."
echo "=========================================="

# Test imports
python3 -c "import numpy; print('✓ numpy:', numpy.__version__)"
python3 -c "import cv2; print('✓ opencv:', cv2.__version__)"
python3 -c "import scipy; print('✓ scipy:', scipy.__version__)"
python3 -c "from pyzbar import pyzbar; print('✓ pyzbar: available')"
python3 -c "import quaternion; print('✓ numpy-quaternion: available')"
python3 -c "import aniposelib; print('✓ aniposelib:', aniposelib.__version__)"

# Test ffmpeg
if command -v ffmpeg &> /dev/null; then
    FFMPEG_VERSION=$(ffmpeg -version | head -n1 | awk '{print $3}')
    echo "✓ ffmpeg: $FFMPEG_VERSION"
else
    echo "✗ ffmpeg not found"
fi

# Test ffprobe
if command -v ffprobe &> /dev/null; then
    echo "✓ ffprobe: available"
else
    echo "✗ ffprobe not found"
fi

echo ""
echo "=========================================="
echo "Setup complete! 🎉"
echo "=========================================="
echo ""
echo "To activate the environment:"
echo "  conda activate $ENV_NAME"
echo ""
echo "To test the pipeline:"
echo "  python workflow/process_mocap_session.py --help"
echo ""

# macOS-specific reminder
if [[ "$OS" == "macos" ]]; then
    echo "macOS users: Remember to set DYLD_LIBRARY_PATH in each session:"
    echo '  export DYLD_LIBRARY_PATH="/opt/homebrew/opt/zbar/lib:$DYLD_LIBRARY_PATH"'
    echo ""
fi

echo "For full workflow documentation, see:"
echo "  workflow/P7_complete_workflow_EN.md"
echo "  workflow/P7_complete_workflow_CN.md"
echo ""
