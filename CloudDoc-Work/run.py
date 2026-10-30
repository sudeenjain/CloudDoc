"""Single-command runner for CloudDoc AI.

Starts the FastAPI server (which serves both the API and the modern UI)
and opens the application in your default browser.
"""
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
VENV_PYTHON = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"


def open_browser():
    time.sleep(1.2)
    print("\n[+] Opening CloudDoc AI in your browser: http://127.0.0.1:8000 ...")
    webbrowser.open("http://127.0.0.1:8000")


def main():
    print("=" * 60)
    print("  CloudDoc AI — Complete Application Launcher")
    print("=" * 60)

    # Use virtual environment python if it exists, otherwise current python
    python_bin = str(VENV_PYTHON) if VENV_PYTHON.is_file() else sys.executable
    print(f"[*] Using Python: {python_bin}")
    print("[*] Working Directory:", BACKEND_DIR)
    print("[*] Local URL: http://127.0.0.1:8000")
    print("[*] API Documentation: http://127.0.0.1:8000/docs")
    print("-" * 60)

    # Launch browser thread
    threading.Thread(target=open_browser, daemon=True).start()

    # Launch Uvicorn
    cmd = [
        python_bin,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--reload",
    ]

    try:
        subprocess.run(cmd, cwd=str(BACKEND_DIR))
    except KeyboardInterrupt:
        print("\n[*] CloudDoc AI server stopped.")


if __name__ == "__main__":
    main()
