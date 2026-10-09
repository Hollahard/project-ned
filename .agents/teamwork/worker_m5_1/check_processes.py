import subprocess
import csv
import io
import sys

output = subprocess.check_output(["tasklist", "/v", "/fo", "csv"], text=True)
reader = csv.DictReader(io.StringIO(output))

orphans = []
other_python = []
for row in reader:
    name = row.get("Image Name", "").lower()
    pid = row.get("PID", "")
    window_title = row.get("Window Title", "")
    mem = row.get("Mem Usage", "")
    if name in ("ping.exe", "pytest.exe"):
        orphans.append((pid, name, window_title, mem))
    elif name == "python.exe":
        other_python.append((pid, name, window_title, mem))

print(f"Total python processes running: {len(other_python)}")
for pid, name, title, mem in other_python:
    print(f"  PID {pid} ({name}, Mem: {mem}): Window Title = '{title}'")

if orphans:
    print(f"ERROR: Found {len(orphans)} orphaned test processes:")
    for pid, name, title, mem in orphans:
        print(f"  PID {pid} ({name}, Mem: {mem}): {title}")
    sys.exit(1)
else:
    print("\nZero orphaned ping.exe or pytest.exe processes found.")
    print("Process check PASSED: Clean system state confirmed.")
    sys.exit(0)
