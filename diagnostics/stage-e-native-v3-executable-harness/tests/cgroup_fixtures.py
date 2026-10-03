"""Static unit evidence; no live collection, signed allocation or admission credit."""
from copy import deepcopy
import json
from pathlib import Path

from attest import V1_INTERFACES, _parsed_limits


def diagnosed_cgroup():
    path = Path(__file__).parent/'fixtures/diagnosed_host_cgroup_v2.json'
    return json.loads(path.read_bytes())['cgroup']


def interface(row, name, raw=None, *, state='PRESENT'):
    row['interfaces'][name] = dict(state=state, **({'raw':raw} if state == 'PRESENT' else {}))
    row.update(_parsed_limits(row))


def controller_topology(*controllers, stop_after=None):
    """Counterfactual enablement only, preserving the captured true-root evidence."""
    groups = deepcopy(diagnosed_cgroup())
    rows = list(reversed(groups['ancestors']))
    incoming = None
    names = {'cpu':('cpu.max','cpu.weight'), 'cpuset':('cpuset.cpus','cpuset.cpus.effective'),
             'memory':('memory.max','memory.high','memory.swap.max')}
    values = {'cpu.max':'max 100000\n','cpu.weight':'100\n','cpuset.cpus':'\n',
              'cpuset.cpus.effective':'0-1\n','memory.max':'max\n',
              'memory.high':'max\n','memory.swap.max':'max\n'}
    for index, row in enumerate(rows):
        available = set(row['interfaces']['cgroup.controllers']['raw'].split()) if index == 0 else incoming
        enabled = set(row['interfaces']['cgroup.subtree_control']['raw'].split())
        enabled.update(controllers if index < 2 and index != stop_after else ())
        if index == stop_after:
            enabled.difference_update(controllers)
        enabled.intersection_update(available)
        interface(row,'cgroup.controllers',' '.join(sorted(available))+'\n')
        interface(row,'cgroup.subtree_control',' '.join(sorted(enabled))+'\n' if enabled else '')
        if index:
            for controller, fields in names.items():
                for field in fields:
                    interface(row,field,values[field] if controller in available else None,
                              state='PRESENT' if controller in available else 'ABSENT')
        incoming = enabled
    return groups


def legacy_cgroup():
    """Separate synthetic v1 dictionaries for the preserved legacy comparators."""
    groups = diagnosed_cgroup(); groups['ancestors'] = []; groups['memberships'] = []
    values = {'cpu':{'cpu.cfs_quota_us':'-1\n','cpu.cfs_period_us':'100000\n'},
              'cpuset':{'cpuset.cpus':'0-1\n'},
              'memory':{'memory.limit_in_bytes':'8589934592\n',
                        'memory.soft_limit_in_bytes':str(2**60)+'\n'}}
    mountinfo = []; membership = []; pid1_membership = []
    for index, controller in enumerate(values,1):
        root = '/sys/fs/cgroup/'+controller
        groups['memberships'].append([str(index),[controller],'/runner'])
        membership.append(f'{index}:{controller}:/runner\n')
        pid1_membership.append(f'{index}:{controller}:/\n')
        mountinfo.append(f'{40+index} 24 0:{40+index} / {root} rw - cgroup cgroup rw,{controller}\n')
        for name in ('/runner','/'):
            row = dict(version='cgroup',controllers=[controller],membership='/runner',
                path=root+(name if name!='/' else ''),cgroup_path=name,mount_root='/',
                namespace=groups['namespace'],root_exceptions=[],
                directory=dict(state='PRESENT',inode=1 if name=='/' else 2,device=40+index),
                interfaces={f:dict(state='PRESENT',raw=values[controller][f]) if f in values[controller]
                            else dict(state='ABSENT') for f in V1_INTERFACES})
            row.update(_parsed_limits(row)); groups['ancestors'].append(row)
    for key, raw in [('membership',membership),('pid1_membership',pid1_membership),
                     ('mountinfo',mountinfo),('pid1_mountinfo',mountinfo)]:
        groups['visibility_interfaces'][key] = dict(state='PRESENT',raw=''.join(raw))
    return groups
