"""
Score blogs in batches by calling score_blogs.py once per range.

  python run_batches.py                 # all blogs, batches of 5 (1-5, 6-10, ...)
  python run_batches.py 3 5             # start at blog 3, batches of 5 (3-7, 8-12, ...)
  python run_batches.py 3 5 30          # same, but stop after blog 30

Each batch is a fresh browser session. Already-scored blogs are skipped,
so you can stop (Ctrl-C) and re-run safely.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

PAUSE_BETWEEN_BATCHES_S = 60

nums = sorted(int(m.group(1)) for p in Path("blogs").glob("*.txt")
              if (m := re.search(r"(\d+)", p.name)))
if not nums:
    raise SystemExit("No blogs found in blogs/")

start = int(sys.argv[1]) if len(sys.argv) > 1 else nums[0]
size = int(sys.argv[2]) if len(sys.argv) > 2 else 5
stop = int(sys.argv[3]) if len(sys.argv) > 3 else nums[-1]

lo = start
while lo <= stop:
    hi = min(lo + size - 1, stop)
    print(f"\n===== Batch Blog{lo} - Blog{hi} =====", flush=True)
    r = subprocess.run([sys.executable, "score_blogs.py", f"{lo}-{hi}"])
    if r.returncode != 0:
        raise SystemExit(f"Batch {lo}-{hi} stopped (exit {r.returncode}).")
    lo = hi + 1
    if lo <= stop:
        print(f"Pausing {PAUSE_BETWEEN_BATCHES_S}s before the next batch...")
        time.sleep(PAUSE_BETWEEN_BATCHES_S)

print("\nAll batches done.")
