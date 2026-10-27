"""
Build script for Reycamview
Creates standalone Reycamview.exe using PyInstaller
"""

import subprocess
import sys
import os

def build():
    print("=" * 60)
    print("  Building Reycamview (Virtual Camera: reycam)")
    print("=" * 60)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "Reycamview",
        "--hidden-import", "pyvirtualcam",
        "--hidden-import", "cv2",
        "--hidden-import", "PIL",
        "reycamview.py",
    ]

    print(f"\nRunning: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))

    if result.returncode == 0:
        print("\n" + "=" * 60)
        print("  BUILD SUCCESSFUL!")
        print("  Output: dist/Reycamview.exe")
        print("=" * 60)
    else:
        print("\n  BUILD FAILED!")
        sys.exit(1)

if __name__ == "__main__":
    build()
