"""Pinned isolated entrypoint, including both multiprocessing child kinds."""
import os
from pathlib import Path
import re
import sys

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))


def main():
    import bound_runtime as runtime
    if '--multiprocessing' in sys.argv:
        args=sys.argv[sys.argv.index('--multiprocessing')+1:]
        if '-c' not in args:raise ValueError('child_entrypoint_missing')
        code=args[args.index('-c')+1]
        spawn=re.fullmatch(r'from multiprocessing.spawn import spawn_main; spawn_main\(tracker_fd=(\d+), pipe_handle=(\d+)\)',code)
        tracker=re.fullmatch(r'from multiprocessing.resource_tracker import main;main\((\d+)\)',code)
        if spawn:
            runtime.initialize('decoder-spawn')
            sys.argv=[str(Path(__file__).resolve()),'--multiprocessing-fork']
            from multiprocessing.spawn import spawn_main
            spawn_main(tracker_fd=int(spawn[1]),pipe_handle=int(spawn[2]))
        elif tracker:
            runtime.initialize('resource-tracker')
            from multiprocessing.resource_tracker import main
            main(int(tracker[1]))
        else:raise ValueError('unbound_multiprocessing_code')
    elif len(sys.argv)==2 and sys.argv[1]=='--member':
        runtime.initialize('member')
        from workload import main as workload_main
        workload_main()
    elif len(sys.argv)==2 and sys.argv[1]=='--audit':
        runtime.initialize('audit-parent')
        from audit import runtime_proof
        runtime_proof()
    elif len(sys.argv)==2 and sys.argv[1]=='--trial':
        runtime.initialize('trial',project=False)
        from trial import main as trial_main
        trial_main()
    else:raise ValueError('unbound_entrypoint')


if __name__=='__main__':main()
