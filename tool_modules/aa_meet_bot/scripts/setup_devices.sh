#!/bin/bash
# Meet Bot Virtual Device Setup Script
# Run this script to set up virtual audio and video devices

set -e

echo "=== Meet Bot Virtual Device Setup ==="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root for v4l2loopback
check_root_for_video() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${YELLOW}Note: v4l2loopback setup may require sudo${NC}"
    fi
}

# Setup PulseAudio virtual sink
setup_audio_sink() {
    echo "Setting up virtual audio sink..."

    # Check if PulseAudio is running
    if ! pactl info > /dev/null 2>&1; then
        echo -e "${RED}Error: PulseAudio is not running${NC}"
        return 1
    fi

    # Check if sink already exists
    if pactl list short sinks | grep -q "meet_bot_sink"; then
        echo -e "${GREEN}✓ Virtual sink 'meet_bot_sink' already exists${NC}"
    else
        # Create null sink
        pactl load-module module-null-sink \
            sink_name=meet_bot_sink \
            sink_properties=device.description=MeetBot_Audio_Capture
        echo -e "${GREEN}✓ Created virtual sink 'meet_bot_sink'${NC}"
    fi
}

# Setup PulseAudio virtual source
setup_audio_source() {
    echo "Setting up virtual audio source..."

    # Create pipe directory
    PIPE_DIR="$HOME/.config/aa-workflow/meet_bot/pipes"
    mkdir -p "$PIPE_DIR"

    # Check if source already exists
    if pactl list short sources | grep -q "meet_bot_source"; then
        echo -e "${GREEN}✓ Virtual source 'meet_bot_source' already exists${NC}"
    else
        # Create pipe source
        pactl load-module module-pipe-source \
            source_name=meet_bot_source \
            file="$PIPE_DIR/audio_pipe" \
            rate=16000 \
            channels=1 \
            format=s16le \
            source_properties=device.description=MeetBot_Voice_Output
        echo -e "${GREEN}✓ Created virtual source 'meet_bot_source'${NC}"
    fi
}

# Setup v4l2loopback virtual camera
setup_video() {
    echo "Setting up virtual camera..."

    # Check if v4l2loopback is loaded
    if lsmod | grep -q v4l2loopback; then
        echo -e "${GREEN}✓ v4l2loopback module already loaded${NC}"
    else
        echo "Loading v4l2loopback module..."
        sudo modprobe v4l2loopback \
            devices=1 \
            video_nr=10 \
            card_label="MeetBot_Camera" \
            exclusive_caps=1
        echo -e "${GREEN}✓ Loaded v4l2loopback module${NC}"
    fi

    # Check device exists
    if [ -e /dev/video10 ]; then
        echo -e "${GREEN}✓ Virtual camera available at /dev/video10${NC}"
    else
        echo -e "${YELLOW}Warning: /dev/video10 not found, checking other devices...${NC}"
        v4l2-ctl --list-devices 2>/dev/null || true
    fi
}

# Create data directories
setup_directories() {
    echo "Creating data directories..."

    DIRS=(
        "$HOME/.config/aa-workflow/meet_bot"
        "$HOME/.config/aa-workflow/meet_bot/logs"
        "$HOME/.config/aa-workflow/meet_bot/recordings"
        "$HOME/.config/aa-workflow/meet_bot/clips"
        "$HOME/.config/aa-workflow/meet_bot/models"
        "$HOME/.config/aa-workflow/meet_bot/voice_samples"
    )

    for dir in "${DIRS[@]}"; do
        mkdir -p "$dir"
        echo -e "${GREEN}✓ Created $dir${NC}"
    done
}

# Main
main() {
    check_root_for_video

    echo ""
    echo "1. Setting up directories..."
    setup_directories

    echo ""
    echo "2. Setting up audio devices..."
    setup_audio_sink
    setup_audio_source

    echo ""
    echo "3. Setting up video device..."
    setup_video

    echo ""
    echo "=== Setup Complete ==="
    echo ""
    echo "Next steps:"
    echo "1. Record 10 minutes of voice samples for GPT-SoVITS training"
    echo "2. Place samples in ~/.config/aa-workflow/meet_bot/voice_samples/"
    echo "3. Download Wav2Lip checkpoint to ~/.config/aa-workflow/meet_bot/models/"
    echo "4. Use meet_bot_status() to verify everything is ready"
    echo ""
}

main "$@"
