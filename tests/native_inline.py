"""Run isolated native fixture scripts from the committed checkout."""
import os,subprocess,sys
from pathlib import Path

def run_native(script,*,timeout):
    environment={k:v for k,v in os.environ.items() if not k.startswith('MM_')}
    environment['PYTHONPATH']=str(Path(__file__).resolve().parents[1])
    guarded='from operational.tests import network_guard; network_guard()\n'+script
    return subprocess.run([sys.executable,'-c',guarded],cwd=Path(__file__).resolve().parents[1],
        env=environment,capture_output=True,text=True,timeout=timeout)
