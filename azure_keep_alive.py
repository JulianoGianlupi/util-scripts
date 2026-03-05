"""
Azure ML Smart Keep-Alive
=========================
Azure ML idle detection ignores CPU/GPU/RAM — it only checks for active Jupyter
kernels, SSH, or VS Code connections. This script bridges the gap:

  * While CPU/GPU/RAM usage is above threshold → maintain a Jupyter kernel so
    Azure ML sees an "active session" and does NOT shut down the compute.
  * When usage drops below threshold for `--idle-grace` seconds → delete the
    kernel and exit, letting Azure ML's idle timer run normally.

Usage (run in a separate terminal or tmux pane):
    python keepalive.py                    # defaults
    python keepalive.py --cpu-thresh 5     # keep alive if CPU > 5%
    python keepalive.py --idle-grace 600   # wait 10 min of true idle before quitting
    nohup python keepalive.py &            # detach from terminal

Logs to stdout and keepalive.log.
"""

import argparse
import json
import logging
import signal
import subprocess
import sys
import time

import requests

# Optional: psutil for CPU/RAM
try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False
    print("[warn] psutil not found — CPU/RAM monitoring disabled. Install with: pip install psutil")

# Optional: pynvml for GPU
try:
    import pynvml
    pynvml.nvmlInit()
    _GPU = True
except Exception:
    _GPU = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("keepalive.log"),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Resource sampling
# ---------------------------------------------------------------------------


def sample_resources():
    """Return (cpu_pct, gpu_pct, ram_pct, description_string)."""
    cpu, gpu, ram = 0.0, 0.0, 0.0
    parts = []

    if _PSUTIL:
        cpu = psutil.cpu_percent(interval=2, percpu=True)  # 2-sec average
        cpu = sum(cpu)
        mem = psutil.virtual_memory()
        ram = mem.percent
        parts.append(f"CPU {cpu:.0f}%  RAM {ram:.0f}% ({mem.used/1e9:.1f}/{mem.total/1e9:.1f} GB)")

    if _GPU:
        try:
            util_vals = []
            for i in range(pynvml.nvmlDeviceGetCount()):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                util = pynvml.nvmlDeviceGetUtilizationRates(h)
                mem = pynvml.nvmlDeviceGetMemoryInfo(h)
                util_vals.append(util.gpu)
                parts.append(f"GPU{i} {util.gpu}%  {mem.used/1e9:.1f}/{mem.total/1e9:.1f} GB")
            gpu = max(util_vals) if util_vals else 0.0
        except Exception:
            pass

    return cpu, gpu, ram, "  |  ".join(parts) if parts else "no monitors available"


def is_active(cpu, gpu, ram, cpu_thresh, gpu_thresh, ram_thresh):
    return cpu >= cpu_thresh or gpu >= gpu_thresh or ram >= ram_thresh


# ---------------------------------------------------------------------------
# Jupyter helpers
# ---------------------------------------------------------------------------


def _find_jupyter():
    for cmd in (["jupyter", "server", "list", "--json"], ["jupyter", "notebook", "list", "--json"]):
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=10, text=True)
            for line in out.strip().splitlines():
                try:
                    info = json.loads(line)
                    url = info.get("url", "").rstrip("/") + "/"
                    tok = info.get("token", "")
                    if url.startswith("http"):
                        return url, tok
                except json.JSONDecodeError:
                    continue
        except Exception:
            continue

    # Probe common ports
    for port in (8888, 8889, 8890):
        try:
            r = requests.get(f"http://localhost:{port}/api", timeout=3)
            if r.status_code in (200, 403):
                return f"http://localhost:{port}/", ""
        except Exception:
            continue

    return None, None


def _hdrs(token):
    return {"Authorization": f"token {token}"} if token else {}


def create_kernel(base_url, token):
    try:
        r = requests.post(f"{base_url}api/kernels", headers=_hdrs(token), json={"name": "python3"}, timeout=20)
        r.raise_for_status()
        kid = r.json()["id"]
        log.info(f"[keepalive] Kernel created  id={kid[:12]}…")
        return kid
    except Exception as e:
        log.warning(f"[keepalive] Could not create kernel: {e}")
        return None


def ping_kernel(base_url, token, kid):
    try:
        r = requests.get(f"{base_url}api/kernels/{kid}", headers=_hdrs(token), timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def delete_kernel(base_url, token, kid):
    try:
        requests.delete(f"{base_url}api/kernels/{kid}", headers=_hdrs(token), timeout=10)
        log.info(f"[keepalive] Kernel deleted  id={kid[:12]}…")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--cpu-thresh", type=float, default=10.0, help="CPU %% above which compute is considered active (default 10)"
    )
    p.add_argument(
        "--gpu-thresh", type=float, default=5.0, help="GPU %% above which compute is considered active (default 5)"
    )
    p.add_argument(
        "--ram-thresh", type=float, default=80.0, help="RAM %% above which compute is considered active (default 80)"
    )
    p.add_argument("--check-every", type=int, default=60, help="Seconds between resource checks (default 60)")
    p.add_argument(
        "--idle-grace", type=int, default=300, help="Seconds of continuous true-idleness before quitting (default 300)"
    )
    args = p.parse_args()

    log.info("=== Azure ML Smart Keep-Alive ===")
    log.info(f"Thresholds → CPU>{args.cpu_thresh}%  GPU>{args.gpu_thresh}%  RAM>{args.ram_thresh}%")
    log.info(f"Check every {args.check_every}s  |  Quit after {args.idle_grace}s of true idle")

    if not _PSUTIL and not _GPU:
        log.error("No resource monitors available (psutil/pynvml). Install psutil: pip install psutil")
        sys.exit(1)

    base_url, token = _find_jupyter()
    if not base_url:
        log.error("No Jupyter server found. Is this an Azure ML compute instance?")
        sys.exit(1)
    log.info(f"Jupyter server: {base_url}")

    kid = None  # current kernel ID (None = not alive / not needed)
    idle_since = None  # timestamp when idleness started

    def _shutdown(sig=None, frame=None):
        if kid:
            delete_kernel(base_url, token, kid)
        log.info("=== Keep-Alive exiting ===")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while True:
        cpu, gpu, ram, desc = sample_resources()
        active = is_active(cpu, gpu, ram, args.cpu_thresh, args.gpu_thresh, args.ram_thresh)

        if active:
            # ---- ACTIVE: make sure kernel is alive ----
            idle_since = None

            if kid is None:
                log.info(f"[active]  {desc}  → creating kernel")
                kid = create_kernel(base_url, token)
            else:
                alive = ping_kernel(base_url, token, kid)
                if alive:
                    log.info(f"[active]  {desc}  → heartbeat OK")
                else:
                    log.warning("[active] Kernel lost, recreating…")
                    kid = create_kernel(base_url, token)

        else:
            # ---- IDLE: start / continue grace period ----
            if idle_since is None:
                idle_since = time.time()
                log.info(f"[idle]    {desc}  → grace period started ({args.idle_grace}s)")
            else:
                idle_for = time.time() - idle_since
                log.info(f"[idle]    {desc}  → idle for {idle_for:.0f}/{args.idle_grace}s")

                if idle_for >= args.idle_grace:
                    log.info("[idle] Grace period elapsed — releasing kernel, Azure ML may now idle-shutdown.")
                    if kid:
                        delete_kernel(base_url, token, kid)
                        kid = None
                    log.info("=== Keep-Alive exiting (genuine idle) ===")
                    return

        time.sleep(args.check_every)


if __name__ == "__main__":
    main()
