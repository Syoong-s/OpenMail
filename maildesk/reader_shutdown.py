"""Bounded asynchronous cleanup of this application's owned WebKit processes."""
import os
from pathlib import Path

# ==========================================
# Function: Observe only WebKit descendants of the current application process.
# Method: Follow Linux's per-process children list, excluding exited zombies and unrelated processes.
# ==========================================
def owned_renderers(root=None,web_only=False):
    if os.name=='nt':return set()
    root=root or os.getpid();pending=[root];seen=set();active=set()
    while pending and len(seen)<256:
        pid=pending.pop()
        if pid in seen:continue
        seen.add(pid);base=Path('/proc')/str(pid)
        try:
            for task in (base/'task').iterdir():
                try:pending.extend(int(child) for child in (task/'children').read_text().split())
                except (OSError,ValueError):continue
            status=(base/'status').read_text();name=(base/'comm').read_text().strip()
            if pid!=root and name.startswith(('WebKitWeb',) if web_only else ('WebKitWeb','WebKitNetwork','WebKitGPU')) and '\nState:\tZ' not in status:active.add(pid)
        except (OSError,ValueError):continue
    return active

# ==========================================
# Function: Bound a native renderer drain while allowing IPC and D-Bus cleanup to complete.
# Method: Require a quiet interval after owned renderers disappear, with a two-second hard limit.
# ==========================================
class ReaderDrain:
    # ==========================================
    # Function: Initialize one shutdown deadline.
    # Method: Accept a monotonic timestamp so the policy can be tested without wall-clock sleeps.
    # ==========================================
    def __init__(self,started):
        self.started=started;self.quiet_since=None;self.timed_out=False;self.last_active=set()
    # ==========================================
    # Function: Decide whether renderer cleanup has completed or reached its bounded deadline.
    # Method: Reset the quiet interval whenever any owned renderer remains alive.
    # ==========================================
    def ready(self,now,active):
        self.last_active=set(active)
        if now-self.started>=2:self.timed_out=bool(active);return True
        if active:self.quiet_since=None;return False
        if self.quiet_since is None:self.quiet_since=now
        return now-self.quiet_since>=.2
