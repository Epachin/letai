"""Три микросервиса + Windows GUI на одной машине. Требуется запущенный RabbitMQ."""
from pathlib import Path
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
SERVICES = ("serve_flights", "serve_hotels", "serve_payments")


def main():
    from common.db import init
    init()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    processes = []
    try:
        for name in SERVICES:
            proc = subprocess.Popen([sys.executable, "-m", f"services.{name}"],
                                    cwd=ROOT, env=env)
            processes.append(proc)
        time.sleep(1)
        if any(p.poll() is not None for p in processes):
            raise RuntimeError("Не удалось запустить один из микросервисов")
        from desktop.app import main as desktop_main
        return desktop_main()
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
