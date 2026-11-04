import os

# Which server version solution_server.py runs:
#   0 = naive broadcast
#   1 = per-client queues (non-naive)
#   2 = per-client queues + ping-based flow control
#   3 = v2 + drop clients lagging more than MAX_LAG_WINDOW seconds
# Override without editing this file: LIVERECALL_VERSION=1 python solution_server.py
VERSION = int(os.environ.get("LIVERECALL_VERSION", 6))
