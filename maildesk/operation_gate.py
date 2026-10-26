"""Serialized provider access with cooperative background yielding and foreground priority."""
from contextlib import contextmanager
import threading

# ==========================================
# Function: Keep interactive mail/folder mutations ahead of another long background poll.
# Method: Signal queued foreground owners, let sync leave at protocol boundaries and admit waiters before background work.
# ==========================================
class OperationGate:
    # ==========================================
    # Function: Initialize one service-owned serialization gate without a polling thread.
    # Method: Protect ownership and queued foreground count with a native condition variable.
    # ==========================================
    def __init__(self):
        self.condition=threading.Condition();self.busy=False;self.waiters=0

    # ==========================================
    # Function: Acquire exclusive access for an explicit operation.
    # Method: Notify a running sync through the waiter count before waiting for its next checkpoint.
    # ==========================================
    def __enter__(self):
        with self.condition:
            self.waiters+=1
            try:
                while self.busy:self.condition.wait()
                self.busy=True
            finally:self.waiters-=1
        return self

    # ==========================================
    # Function: Release either foreground or background ownership.
    # Method: Wake waiters after the owner has committed its local consequences.
    # ==========================================
    def __exit__(self,*unused):
        with self.condition:self.busy=False;self.condition.notify_all()

    # ==========================================
    # Function: Admit synchronization only after queued user operations finish.
    # Method: Keep the normal ownership semantics while giving foreground waiters preference.
    # ==========================================
    @contextmanager
    def background(self):
        with self.condition:
            while self.busy or self.waiters:self.condition.wait()
            self.busy=True
        try:yield self
        finally:self.__exit__()

    # ==========================================
    # Function: Tell a running background poll to stop before another network request.
    # Method: Read the synchronized foreground waiter count without taking the operation lock.
    # ==========================================
    def interrupted(self):
        with self.condition:return bool(self.waiters)
