"""Process supervision only; no implicit startup on import or construction."""
from pathlib import Path
import os
import subprocess
import sys
import time

class EvidenceProcess:
    def __init__(self,run,cwd,env,*,spawn=subprocess.Popen,clock=time.monotonic,wait_ready=True):
        self.run=Path(run);self.cwd=cwd;self.env=env;self.spawn=spawn;self.clock=clock
        self.wait_ready=wait_ready;self.proc=None;self.restarts=0;self.started=0;self.file=None
    def start(self):
        self.file=(self.run/'evidence-process.log').open('ab')
        self.proc=self.spawn([sys.executable,'-m','certification.evidence_worker'],cwd=self.cwd,
            env=self.env,stdout=self.file,stderr=subprocess.STDOUT,start_new_session=True)
        self.started=self.clock()
        if self.wait_ready:
            ready=Path(self.env['MM_SOLANA_EVIDENCE_PLANE_DB']+'.sock')
            while not ready.exists():
                if self.proc.poll() is not None:raise RuntimeError('evidence_service_start_failed')
                if self.clock()-self.started>5:raise RuntimeError('evidence_service_start_timeout')
                time.sleep(.05)
    def check(self):
        if self.proc is None:raise RuntimeError('evidence_service_not_started')
        code=self.proc.poll()
        if code is not None:
            self.file.close()
            if self.restarts>=3:return dict(pid=self.proc.pid,restarts=self.restarts,exit_code=code,health='restart_bound_fail_closed')
            self.restarts+=1;self.start()
        return dict(pid=self.proc.pid,restarts=self.restarts,exit_code=code)
    def close(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait(timeout=5)
        if self.file:self.file.close()
