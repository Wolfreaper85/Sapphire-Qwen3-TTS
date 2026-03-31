#!/usr/bin/env bash
# Qwen3-TTS Plugin Installer for Sapphire (Linux / macOS)
# Usage: chmod +x install.sh && ./install.sh

set -e

echo ""
echo "  ============================================"
echo "    Qwen3-TTS Plugin Installer for Sapphire"
echo "  ============================================"
echo ""

# Find Python 3
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" --version 2>&1 | grep -oP '\d+\.\d+')
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "  [ERROR] Python 3.10+ not found!"
    echo "  Install it with your package manager:"
    echo "    Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "    Fedora:        sudo dnf install python3 python3-pip"
    echo "    Arch:          sudo pacman -S python python-pip"
    echo "    macOS:         brew install python@3.11"
    echo ""
    exit 1
fi

echo "  Found: $($PYTHON --version)"
echo ""

# Run the Python installer script (same logic as install.bat)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$PYTHON" "$SCRIPT_DIR/install.py"

echo ""
read -p "  Press Enter to close..." _
