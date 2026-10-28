import os

# Which server version solution_server.py runs:
#   0 = naive broadcast
#   1 = per-client queues (non-naive)
#   2 = per-client queues + ping-based flow control
# Override without editing this file: LIVERECALL_VERSION=1 python solution_server.py
VERSION = int(os.environ.get("LIVERECALL_VERSION", 2))
