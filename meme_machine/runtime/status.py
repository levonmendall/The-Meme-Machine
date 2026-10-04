"""Process-local bounded health; no execution or permission authority."""
import threading,time
lock=threading.Lock()
state=dict(phase='RECONCILING',reconciled=False)
def update(phase,**fields):
    with lock:
        state.update(phase=phase,progress_at=time.time(),**fields)
def snapshot():
    with lock:return dict(state)
