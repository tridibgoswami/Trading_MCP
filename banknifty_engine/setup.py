#!/usr/bin/env python3
# setup.py
# ─────────────────────────────────────────────
# One-time setup script.
# Run this ONCE before starting the engine.
# python setup.py
# ─────────────────────────────────────────────

import os
import sys
import subprocess
from pathlib import Path


def run(cmd, description):
    print(f"  → {description}...", end="", flush=True)
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        print(" ✓")
    else:
        print(f" ✗\n    Error: {result.stderr[:200]}")
    return result.returncode == 0


def main():
    print("""
╔════════════════════════════════════════════╗
║     BANKNIFTY ENGINE — SETUP               ║
╚════════════════════════════════════════════╝
""")

    # ── Step 1: Install dependencies
    print("📦 Installing Python packages...")
    run("pip install -r requirements.txt", "Installing all packages")

    # ── Step 2: Create .env if not exists
    print("\n🔧 Setting up configuration...")
    if not os.path.exists('.env'):
        if os.path.exists('.env.example'):
            import shutil
            shutil.copy('.env.example', '.env')
            print("  → Created .env from template ✓")
            print("  ⚠️  IMPORTANT: Edit .env and add your credentials!")
        else:
            print("  ✗ .env.example not found")
    else:
        print("  → .env already exists ✓")

    # ── Step 3: Create directories
    print("\n📁 Creating directories...")
    for d in ['data_store', 'logs', 'reports']:
        Path(d).mkdir(exist_ok=True)
        print(f"  → {d}/ ✓")

    # ── Step 4: Create __init__.py files
    for f in ['core/__init__.py', 'intelligence/__init__.py']:
        Path(f).touch()

    # ── Step 5: Test config
    print("\n🔍 Testing configuration...")
    try:
        from config import validate_config
        validate_config()
        print("  → Config valid ✓")
    except EnvironmentError as e:
        print(f"  → Config incomplete: {e}")
        print("  → Please fill in your .env file and run setup again")

    # ── Done
    print("""
╔════════════════════════════════════════════╗
║              SETUP COMPLETE!               ║
╠════════════════════════════════════════════╣
║                                            ║
║  Next steps:                               ║
║  1. Edit .env with your credentials        ║
║  2. python start_engine.py                 ║
║                                            ║
║  Manual commands:                          ║
║  python evolve.py --days 14                ║
║  python evolve.py --days 30                ║
║                                            ║
╚════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    main()
