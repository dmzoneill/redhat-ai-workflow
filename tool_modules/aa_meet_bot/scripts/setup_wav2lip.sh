#!/bin/bash
# Wav2Lip Setup Script
# Sets up Wav2Lip for real-time lip-sync on RTX 4060

set -e

echo "=== Wav2Lip Setup for Meet Bot ==="
echo ""

WAV2LIP_DIR="$HOME/src/Wav2Lip"
CHECKPOINT_DIR="$WAV2LIP_DIR/checkpoints"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check NVIDIA GPU
check_gpu() {
    echo "Checking GPU..."
    if command -v nvidia-smi &> /dev/null; then
        nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
        echo -e "${GREEN}✓ NVIDIA GPU detected${NC}"
    else
        echo -e "${RED}✗ No NVIDIA GPU detected${NC}"
        exit 1
    fi
}

# Clone Wav2Lip
clone_wav2lip() {
    if [ -d "$WAV2LIP_DIR" ]; then
        echo -e "${YELLOW}Wav2Lip already exists at $WAV2LIP_DIR${NC}"
        return 0
    fi

    echo "Cloning Wav2Lip..."
    git clone https://github.com/Rudrabha/Wav2Lip.git "$WAV2LIP_DIR"
    echo -e "${GREEN}✓ Wav2Lip cloned${NC}"
}

# Download models
download_models() {
    mkdir -p "$CHECKPOINT_DIR"

    # wav2lip_gan.pth - Best quality
    if [ ! -f "$CHECKPOINT_DIR/wav2lip_gan.pth" ]; then
        echo "Downloading wav2lip_gan.pth (best quality)..."
        echo -e "${YELLOW}Note: You need to download manually from:${NC}"
        echo "https://github.com/Rudrabha/Wav2Lip#getting-the-weights"
        echo ""
        echo "Download 'wav2lip_gan.pth' and place in:"
        echo "$CHECKPOINT_DIR/wav2lip_gan.pth"
        echo ""
        echo "Or use gdown if you have the Google Drive link:"
        echo "pip install gdown"
        echo "gdown --id <file_id> -O $CHECKPOINT_DIR/wav2lip_gan.pth"
    else
        echo -e "${GREEN}✓ wav2lip_gan.pth already exists${NC}"
    fi

    # Face detection model
    if [ ! -f "$WAV2LIP_DIR/face_detection/detection/sfd/s3fd.pth" ]; then
        echo "Downloading face detection model..."
        mkdir -p "$WAV2LIP_DIR/face_detection/detection/sfd"
        # This is usually auto-downloaded on first run
        echo -e "${YELLOW}Face detection model will be downloaded on first run${NC}"
    else
        echo -e "${GREEN}✓ Face detection model exists${NC}"
    fi
}

# Install dependencies
install_deps() {
    echo "Installing Wav2Lip dependencies..."
    cd "$WAV2LIP_DIR"

    # Create venv if not exists
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi

    source venv/bin/activate

    pip install --upgrade pip
    pip install -r requirements.txt

    # Additional dependencies for our use case
    pip install opencv-python-headless librosa

    echo -e "${GREEN}✓ Dependencies installed${NC}"
}

# Test installation
test_installation() {
    echo "Testing Wav2Lip installation..."
    cd "$WAV2LIP_DIR"
    source venv/bin/activate

    python -c "
import torch
print(f'PyTorch: {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB')
"

    if [ -f "$CHECKPOINT_DIR/wav2lip_gan.pth" ]; then
        echo -e "${GREEN}✓ Wav2Lip ready for use${NC}"
    else
        echo -e "${YELLOW}⚠ Wav2Lip installed but checkpoint missing${NC}"
        echo "Download wav2lip_gan.pth to complete setup"
    fi
}

# Main
main() {
    check_gpu
    clone_wav2lip
    install_deps
    download_models
    test_installation

    echo ""
    echo "=== Setup Complete ==="
    echo ""
    echo "To use Wav2Lip:"
    echo "  cd $WAV2LIP_DIR"
    echo "  source venv/bin/activate"
    echo "  python inference.py --checkpoint_path checkpoints/wav2lip_gan.pth \\"
    echo "    --face /path/to/face.jpg --audio /path/to/audio.wav --outfile output.mp4"
}

main "$@"
