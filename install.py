"""Qwen3-TTS Plugin Installer

Auto-detects GPU, installs the correct PyTorch + CUDA version,
installs plugin dependencies, and optionally installs faster-qwen3-tts.

Usage: Double-click install.bat (or run: python install.py)
"""
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── GPU detection ──

# Maps GPU architecture keywords to recommended CUDA wheel versions
# Format: (name_pattern, cuda_url_suffix, friendly_name)
GPU_CUDA_MAP = [
    # Blackwell (RTX 50xx)
    (r"50[5-9]0|RTX 5\d",  "cu128", "RTX 50-series (Blackwell)"),
    # Ada Lovelace (RTX 40xx)
    (r"40[5-9]0|RTX 4\d",  "cu126", "RTX 40-series (Ada Lovelace)"),
    # Ampere (RTX 30xx, A100, etc.)
    (r"30[5-9]0|RTX 3\d|A100|A6000|A5000|A4000", "cu124", "RTX 30-series / Ampere"),
    # Turing (RTX 20xx, GTX 16xx)
    (r"20[5-9]0|RTX 2\d|GTX 16",  "cu124", "RTX 20-series / Turing"),
    # Older — fallback
    (r"GTX 10|Tesla|Quadro",  "cu124", "Older NVIDIA GPU"),
]

PYTORCH_URLS = {
    "cu128": "https://download.pytorch.org/whl/cu128",
    "cu126": "https://download.pytorch.org/whl/cu126",
    "cu124": "https://download.pytorch.org/whl/cu124",
}


def run(cmd, capture=False):
    """Run a shell command, optionally capturing output."""
    if capture:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip(), result.returncode
    else:
        return subprocess.run(cmd, shell=True).returncode


def detect_gpu():
    """Detect NVIDIA GPU using nvidia-smi."""
    try:
        output, rc = run("nvidia-smi --query-gpu=name --format=csv,noheader,nounits", capture=True)
        if rc != 0 or not output:
            return None, None, None
        gpu_name = output.strip().split("\n")[0].strip()
        for pattern, cuda_ver, friendly in GPU_CUDA_MAP:
            if re.search(pattern, gpu_name, re.IGNORECASE):
                return gpu_name, cuda_ver, friendly
        # Unknown NVIDIA GPU — default to cu124
        return gpu_name, "cu124", "NVIDIA GPU (unknown series)"
    except Exception:
        return None, None, None


def check_pytorch():
    """Check if PyTorch with CUDA is already installed and working."""
    try:
        output, rc = run(f'"{sys.executable}" -c "import torch; print(torch.cuda.is_available()); print(torch.__version__)"', capture=True)
        if rc != 0:
            return False, None
        lines = output.strip().split("\n")
        cuda_ok = lines[0].strip() == "True"
        version = lines[1].strip() if len(lines) > 1 else "unknown"
        return cuda_ok, version
    except Exception:
        return False, None


def check_package(name):
    """Check if a Python package is installed."""
    _, rc = run(f'"{sys.executable}" -c "import {name}"', capture=True)
    return rc == 0


def print_header(text):
    print(f"\n  {'='*50}")
    print(f"  {text}")
    print(f"  {'='*50}\n")


def print_step(num, text):
    print(f"  [{num}] {text}")


def print_ok(text):
    print(f"      [OK] {text}")


def print_warn(text):
    print(f"      [!!] {text}")


def print_fail(text):
    print(f"      [FAIL] {text}")


def main():
    print_header("Qwen3-TTS Plugin Installer")

    # ── Step 1: Check Python ──
    print_step(1, "Checking Python...")
    py_version = sys.version.split()[0]
    major, minor = sys.version_info[:2]
    if major < 3 or (major == 3 and minor < 10):
        print_fail(f"Python {py_version} is too old. Need 3.10+")
        print("      Download: https://www.python.org/downloads/")
        return False
    print_ok(f"Python {py_version}")

    # ── Step 2: Detect GPU ──
    print_step(2, "Detecting GPU...")
    gpu_name, cuda_ver, gpu_friendly = detect_gpu()
    if not gpu_name:
        print_warn("No NVIDIA GPU detected (nvidia-smi not found)")
        print("      Qwen3-TTS requires an NVIDIA GPU with CUDA support.")
        print("      If you have one, make sure NVIDIA drivers are installed.")
        resp = input("\n      Continue anyway? (y/n): ").strip().lower()
        if resp != 'y':
            return False
        cuda_ver = "cu124"  # fallback
        gpu_friendly = "Unknown"
    else:
        print_ok(f"{gpu_name} -> {gpu_friendly}")
        print(f"      Will use PyTorch with CUDA: {cuda_ver}")

    # ── Step 3: Install PyTorch ──
    print_step(3, "Checking PyTorch...")
    cuda_ok, torch_ver = check_pytorch()
    if cuda_ok:
        print_ok(f"PyTorch {torch_ver} with CUDA already installed")
        resp = input("      Reinstall PyTorch? (y/n, default: n): ").strip().lower()
        install_pytorch = resp == 'y'
    else:
        if torch_ver:
            print_warn(f"PyTorch {torch_ver} installed but CUDA not available")
        else:
            print_warn("PyTorch not installed")
        install_pytorch = True

    if install_pytorch:
        url = PYTORCH_URLS.get(cuda_ver, PYTORCH_URLS["cu124"])
        print(f"      Installing PyTorch with {cuda_ver}...")
        print(f"      This may take a few minutes (downloading ~2-3 GB)...\n")
        rc = run(f'"{sys.executable}" -m pip install torch torchaudio --index-url {url}')
        if rc != 0:
            print_fail("PyTorch installation failed")
            print("      Try manually: pip install torch torchaudio --index-url " + url)
            return False
        # Verify
        cuda_ok, torch_ver = check_pytorch()
        if cuda_ok:
            print_ok(f"PyTorch {torch_ver} with CUDA installed successfully")
        else:
            print_warn(f"PyTorch installed but CUDA test failed. Your GPU may need newer drivers.")

    # ── Step 4: Install plugin dependencies ──
    print_step(4, "Installing plugin dependencies...")
    req_file = os.path.join(SCRIPT_DIR, "requirements.txt")
    if os.path.exists(req_file):
        rc = run(f'"{sys.executable}" -m pip install -r "{req_file}"')
        if rc != 0:
            print_fail("Some dependencies failed to install")
            print(f"      Try manually: pip install -r \"{req_file}\"")
        else:
            print_ok("All dependencies installed")
    else:
        print_warn("requirements.txt not found — skipping")

    # ── Step 5: Optional faster-qwen3-tts ──
    print_step(5, "Optional: faster-qwen3-tts (5-10x speedup with CUDA graphs)")
    if check_package("faster_qwen3_tts"):
        print_ok("faster-qwen3-tts already installed")
    else:
        print("      This is optional but highly recommended for faster generation.")
        print("      It uses CUDA graphs for 5-10x speedup on supported GPUs.")
        resp = input("      Install faster-qwen3-tts? (y/n, default: y): ").strip().lower()
        if resp != 'n':
            rc = run(f'"{sys.executable}" -m pip install faster-qwen3-tts')
            if rc != 0:
                print_warn("faster-qwen3-tts failed to install (non-critical, standard backend will be used)")
            else:
                print_ok("faster-qwen3-tts installed")
        else:
            print("      Skipped — standard backend will be used")

    # ── Step 6: Optional flash-attn ──
    print_step(6, "Optional: flash-attn (faster attention, requires CUDA Toolkit SDK)")
    if check_package("flash_attn"):
        print_ok("flash-attn already installed")
    else:
        print("      Flash Attention can speed up generation but requires the")
        print("      CUDA Toolkit SDK to compile. Skip if you're not sure.")
        resp = input("      Install flash-attn? (y/n, default: n): ").strip().lower()
        if resp == 'y':
            rc = run(f'"{sys.executable}" -m pip install flash-attn --no-build-isolation')
            if rc != 0:
                print_warn("flash-attn failed (needs CUDA Toolkit SDK). This is optional — skipping.")
            else:
                print_ok("flash-attn installed")
        else:
            print("      Skipped")

    # ── Step 7: Verify installation ──
    print_step(7, "Verifying installation...")
    all_ok = True

    checks = [
        ("torch", "PyTorch"),
        ("qwen_tts", "qwen-tts"),
        ("soundfile", "soundfile"),
        ("numpy", "numpy"),
        ("psutil", "psutil"),
        ("requests", "requests"),
    ]
    for mod, name in checks:
        if check_package(mod):
            print_ok(f"{name}")
        else:
            print_fail(f"{name} — not installed")
            all_ok = False

    # Optional packages
    for mod, name in [("faster_qwen3_tts", "faster-qwen3-tts"), ("flash_attn", "flash-attn")]:
        if check_package(mod):
            print_ok(f"{name} (optional)")
        else:
            print(f"      [ ] {name} (optional, not installed)")

    # ── Done ──
    print_header("Installation Complete!")
    if all_ok:
        print("  Next steps:")
        print("  1. Start Sapphire")
        print("  2. Go to Settings > Plugins > Enable Qwen3-TTS")
        print("  3. Set your preferred model size (0.6B recommended for most)")
        print("  4. The TTS server will auto-launch and download models on first use")
        print("  5. Open Settings > Qwen3-TTS to create voices in the Voice Lab")
        print("  6. Assign voices to personas in the Personas page")
        print()
        print("  Models download automatically on first launch (~3 GB for 0.6B).")
        print("  See README.md for full documentation.")
    else:
        print("  Some packages failed to install. Check the errors above")
        print("  and try installing them manually with pip.")
    print()
    return all_ok


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n  Cancelled by user.")
        sys.exit(1)
