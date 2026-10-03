"""Counterfactual dictionaries and opaque bytes, never native workload input."""
from copy import deepcopy
import gzip
from pathlib import Path

from core import MAGIC, S, canonical, sha
from preserve import persist
from tape import LENGTH, Reader
from verify import SCOPES, stress_member_result


def safe_overload_row():
    protected = {k:[] for k in ('interests','service_interests','account_interest_floors','stream_receipts',
                              'interest_checkpoints','interest_owners','consumers')}
    protected['integrity'] = ['ok']
    before = dict(progress=[],episodes=[],records_digest='unit-records',record_count=1,floors={},protected=protected,
        counters=dict(archived_records=1,compacted_records=1,stream_accepted_messages=1),gaps=[],
        health=dict(phase='FAILED',storage_maintenance={'maintenance_arbiter':{'generation':'unit-before'}},
                    owner_scheduler={'owner_admission':{'failed':True,'events':[
            dict(native_refusal=True,maintenance_error_type='EvidenceUnavailable')]}}))
    after = deepcopy(before);after['gaps'] = [['unit-scope',0,0,'service_restart']]
    after['health']['phase'] = 'OFF'
    after['health']['storage_maintenance']['maintenance_arbiter']['generation'] = 'unit-after'
    row = dict(candidate_sha=S,kind='C',member='combined-1',frames=2223,mode='stress',shape=None,
        declaration_sha256='unit',workload_valid=False,observation_valid=False,provider_attempts=[],integrity=['ok'],
        lag_peak=1,oldest_hot_age_peak=181,oldest_retained_age_peak=181,hot_peak=100000,owner={'queue_peak':2},
        ipc={'stream.received_messages':2,'stream.commit_messages':2,'stream.outstanding_frames_peak':1,
             'stream.dispatch_bytes_peak':100,'stream.commit_batch_messages_peak':1,'stream.commit_batch_bytes_peak':100},
        native_restart=dict(before=before,after=after,native_failure='EvidenceUnavailable:maintenance_stalled',
            native_failure_frames=[dict(file='solana_maintenance_runtime.py')],old_generation='unit-before',
            new_generation='unit-after',external_stop_is_native_proof=False,source_frames_released_after_restart=0,
            preserved_original_inventory_sha256='unit-before-copy',
            stale_refusals=[dict(scope=s,reason='evidence_service_unavailable') for s in SCOPES]))
    row.update(failure=row['native_restart']['native_failure'],failure_frames=row['native_restart']['native_failure_frames'])
    row.update(stress_member_result(row))
    return row


def opaque_prefix(root, *, planned_frames=2):
    """Tiny gzip records contain no Solana frame or native source payload."""
    root = Path(root)
    payloads = [b'UNIT OPAQUE A',b'UNIT OPAQUE B']
    data = MAGIC
    decoded = MAGIC
    for raw in payloads:
        compressed = gzip.compress(raw,mtime=0)
        data += LENGTH.pack(len(compressed))+compressed
        decoded += LENGTH.pack(len(raw))+raw
    tape = root/'opaque-tape.bin';tape.write_bytes(data);tape.chmod(0o444)
    expected = dict(id='combined-1',frames=planned_frames,encoded_prefix_bytes=len(data),
                    encoded_prefix_sha256=sha(data),decoded_canonical_sha256=sha(decoded))
    inventory_reader = Reader(tape,dict(expected,frames=2))
    rows = [inventory_reader.next()[1] for _ in payloads];inventory_reader.close()
    frame_inventory = root/'opaque-inventory.json';persist(frame_inventory,rows)
    reader = Reader(tape,expected);reader.next();partial = reader.close(strict=False)
    anchor = 12*10**9
    receipt = dict(member='combined-1',mode='stress',source_frames_released=1,tape=partial,
        first_release_real_monotonic_ns=anchor,last_release_real_monotonic_ns=anchor+1000000,
        immutable_semantic_wall_epoch=1800000000,immutable_semantic_monotonic_epoch=100,
        retiming_calls=0,declaration_sha256='unit',
        raw_release_hashes=[dict(number=0,sha256=sha(payloads[0]),bytes=len(payloads[0]),
                                released_real_monotonic_ns=anchor+1000000)],
        clock_samples=[dict(frames=1,anchor_real_monotonic_ns=anchor,real_monotonic_ns=anchor+2000000,
                            wall=1800000000.002,monotonic=100.002)])
    declaration = dict(tape_binding=dict(members=[expected],physical_bytes=len(data),physical_sha256=sha(data),
                        frame_inventory_sha256=sha(frame_inventory.read_bytes())),
                        paths=dict(tape=str(tape),frame_inventory=str(frame_inventory)))
    return receipt, declaration


def interval():
    return dict(start_real_monotonic_ns=10*10**9,startup_real_monotonic_ns=101*10**8,
        helpers_terminated_real_monotonic_ns=19*10**9,end_real_monotonic_ns=20*10**9,
        start_perf_ns=100*10**9,end_perf_ns=110*10**9,start_clock_read_span_ns=10,end_clock_read_span_ns=10)
