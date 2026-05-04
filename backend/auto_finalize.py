"""NIFS 크롤 완료 → 학습 → 기존 서버 종료 → 새 서버 시작 (전 자동)."""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import train_v2

ARTIFACT = Path(__file__).parent / "artifacts"
LABEL = ARTIFACT / "redtide_labels.parquet"
SERVER_PORT = 8000


def wait_for_label(timeout_sec: int = 1800):
    """label parquet 가 우리 의도한 모양 (cod_news unique > 100) 이 될 때까지 대기."""
    import pandas as pd
    t0 = time.time()
    last_size = -1
    last_unique = -1
    while time.time() - t0 < timeout_sec:
        if LABEL.exists():
            try:
                df = pd.read_parquet(LABEL)
                u = df["cod_news"].nunique() if "cod_news" in df.columns else 0
                size = len(df)
                if u > 100 and size != last_size:
                    last_size = size
                    last_unique = u
                # 5초 동안 변화 없으면 완료로 판단
                time.sleep(5)
                df2 = pd.read_parquet(LABEL)
                if len(df2) == size and df2["cod_news"].nunique() == u and u > 100:
                    print(f"[wait] 안정화 감지: rows={size} unique cod={u}", flush=True)
                    return
            except Exception as e:
                print(f"[wait] read err: {e}", flush=True)
        else:
            print(f"[wait] label 미존재 ({int(time.time()-t0)}s)", flush=True)
        time.sleep(15)
    print("[wait] timeout", flush=True)


def kill_existing_server(port: int):
    """포트 점유 PID 종료 (Windows)."""
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             f"Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | "
             f"Select-Object -ExpandProperty OwningProcess"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        for pid_str in out.splitlines():
            pid = int(pid_str)
            print(f"[kill] PID {pid} 종료")
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"[kill] 실패: {e}")


def main():
    print("[1/4] NIFS 크롤 완료 대기")
    wait_for_label()

    print("\n[2/4] 정식 학습")
    train_v2.main(start_year=2010, end_year=2025)

    print("\n[3/4] 기존 서버 종료")
    kill_existing_server(SERVER_PORT)
    time.sleep(2)

    print(f"\n[4/4] 새 서버 시작 (port {SERVER_PORT})")
    venv_py = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"
    log_path = ARTIFACT / "server.log"
    with open(log_path, "wb") as logf:
        proc = subprocess.Popen(
            [str(venv_py), "-m", "uvicorn", "main:app",
             "--host", "127.0.0.1", "--port", str(SERVER_PORT)],
            stdout=logf, stderr=subprocess.STDOUT,
            cwd=str(Path(__file__).parent),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
    print(f"  PID {proc.pid}  log: {log_path}")
    print("DONE")


if __name__ == "__main__":
    main()
