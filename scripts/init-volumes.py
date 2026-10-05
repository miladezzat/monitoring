"""Initialize top-level ownership for this project's named volumes only."""
import os

for name, uid in [("alloy", 10001), ("tempo", 10001), ("logs", 1000)]:
    os.chown("/state/" + name, uid, uid)
