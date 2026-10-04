"""Shared read-only Solana ingestion process, launched by the paper supervisor.

Importing this module opens no network. Explicit process startup requires the same
existing authenticated Alchemy endpoint and the unchanged shared governor.
"""
import asyncio
import json
import os
import signal
import urllib.error
import urllib.request
from pathlib import Path
from meme_machine.runtime.governor import Governor
from meme_machine.solana_evidence_transport import alchemy_stream_endpoint
from meme_machine.solana_evidence_service import serve

class RepairRPC:
    def __init__(self,endpoint,governor):
        from meme_machine.solana_provider_config import AlchemyEndpoint
        from collections import Counter
        import threading
        self.config=AlchemyEndpoint.parse(endpoint)
        self.endpoint=self.config.http_url;self.governor=governor
        self.counts=Counter({k:0 for k in ('physical_requests','logical_calls','repair_calls','identity_calls','failures','429s','unsupported_methods','queue_microseconds','transport_microseconds')});self.lock=threading.Lock()
    def _count(self,key,n=1):
        with self.lock:self.counts[key]+=n
    def telemetry(self):
        from meme_machine.runtime.cu import estimate
        with self.lock:counts=dict(self.counts)
        methods={k.split(':',1)[1]:v for k,v in counts.items() if k.startswith('method:')}
        return dict(counters=counts,estimated_alchemy=estimate(methods),
                    endpoint_identity=self.config.identity,provider=self.config.provider)
    def validate_network(self):
        from meme_machine.solana_provider_config import GENESIS
        if self.call('getGenesisHash',[],False)!=GENESIS:
            raise ValueError('solana_network_identity_mismatch')
    def call(self,method,params,priority=False):
        import time
        if method not in ('getTransactionsForAddress','getGenesisHash'):
            raise ValueError('repair_method_forbidden')
        started=time.monotonic();transport=None
        try:
            self.governor.acquire('solana','evidence',2 if priority else 50,deadline_seconds=8,methods=(method,))
            self._count('queue_microseconds',int((time.monotonic()-started)*1e6))
            transport=time.monotonic()
            self._count('physical_requests');self._count('logical_calls');self._count('method:'+method)
            self._count('repair_calls' if method=='getTransactionsForAddress' else 'identity_calls')
            request=urllib.request.Request(self.endpoint,json.dumps(dict(jsonrpc='2.0',id=1,method=method,params=params)).encode(),{'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=8) as response:raw=response.read(16*1024*1024+1)
            if len(raw)>16*1024*1024:raise ValueError('repair_response_bound')
            value=json.loads(raw)
            code=(value.get('error') or {}).get('code')
            if code in (429,-32005):
                self._count('429s');self.governor.rate_limited('solana',(method,))
            if code==-32601:self._count('unsupported_methods')
            if value.get('id')!=1 or 'error' in value or 'result' not in value:
                raise ValueError('repair_response_unavailable')
            self.config.public(value)
            self.governor.succeeded('solana',(method,))
            return value['result']
        except urllib.error.HTTPError as exc:
            if exc.code==429:
                self._count('429s');self.governor.rate_limited('solana',(method,))
            self._count('failures')
            raise ValueError('repair_http_'+str(int(exc.code))) from None
        except Exception:
            self._count('failures')
            raise ValueError('repair_response_unavailable') from None
        finally:
            if transport is not None:self._count('transport_microseconds',int((time.monotonic()-transport)*1e6))


async def main_async():
    endpoint=os.environ['MM_SOLANA_READ_RPC_URL']
    path=Path(os.environ['MM_SOLANA_EVIDENCE_PLANE_DB'])
    governor=Governor(os.environ['MM_PROVIDER_GOVERNOR_DB'])
    stop=asyncio.Event();loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,stop.set)
    rpc=RepairRPC(endpoint,governor)
    await asyncio.to_thread(rpc.validate_network)
    await serve(path,endpoint,repair_rpc=rpc,stop=stop)

# Only source-defined fixed reason codes may cross the process boundary.
SAFE_EVIDENCE_REASONS=frozenset(('address_history_page_bound', 'address_history_response_shape_unverified', 'admitted_frame_drain_timeout', 'archive_batch_bound', 'archive_manifest_record_count', 'archive_snapshot_bound', 'archive_snapshot_source_changed', 'archive_worker_metric', 'authoritative_alchemy_endpoint_required', 'authoritative_subscription_rejected', 'checkpoint_handoff_owner_thread', 'checkpoint_handoff_token', 'checkpoint_handoff_unavailable', 'checkpoint_inside_source_transaction', 'checkpoint_ticket_owner_thread', 'consumer_command_bound', 'consumer_command_forbidden', 'consumer_counter_bound', 'consumer_cursor_regression', 'decoded_event_address_missing', 'dlmm_local_transaction_identity_or_order', 'dlmm_signature_census_missing_start_boundary', 'evidence_ack_identity', 'evidence_admission_offer_expired', 'evidence_admission_offer_unavailable', 'evidence_background_yield', 'evidence_cold_start', 'evidence_command_envelope', 'evidence_command_expired', 'evidence_command_identity_conflict', 'evidence_command_unacknowledged', 'evidence_control_overloaded', 'evidence_interest_command_bound', 'evidence_owner_shutdown_timeout', 'evidence_owner_unavailable', 'evidence_receipt_capacity', 'evidence_request_identity_conflict', 'evidence_requires_offline_archive_restore', 'evidence_time_boundary_unavailable', 'evidence_writer_already_running', 'exact_finalized_block_time_unavailable', 'filtered_block_bound', 'filtered_block_unavailable', 'filtered_census_shape', 'finalized_block_fence_shape', 'finalized_block_unavailable', 'frozen_log_decoder_required', 'hot_store_capacity', 'hot_store_capacity_bound', 'incomplete_finalized_logs', 'incomplete_interval_proof', 'ingestion_backlog_gap', 'ingestion_batch_bound', 'ingestion_payload_bound', 'ingestion_queue_overflow', 'interest_account_bound', 'interest_address', 'interest_checkpoint_ahead_of_source', 'interest_checkpoint_conflict', 'interest_checkpoint_owner_inactive', 'interest_checkpoint_regression', 'interest_checkpoint_shape', 'interest_checkpoint_unknown_owner', 'interest_owned_by_other_consumer', 'interest_owner_bound', 'interest_owner_capacity', 'invalid_finalized_record', 'invalid_gap', 'invalid_interest', 'invalid_interval_proof', 'invalid_pump_time_window', 'invalid_query_window', 'invalid_subscription_interest', 'lifecycle_evidence_priority', 'lifecycle_interest_downgrade', 'local_evidence_query_bound', 'local_ordered_commit_stalled', 'maintenance_admission_revoked', 'maintenance_archive_concurrency', 'maintenance_archive_slice_exceeds_512', 'maintenance_archive_worker_lease_exceeded', 'maintenance_cannot_reserve_both_sides', 'maintenance_clock_regressed', 'maintenance_clock_relationship_invalid', 'maintenance_completion_identity', 'maintenance_completion_transaction_open', 'maintenance_completion_unavailable', 'maintenance_deadline_invalid', 'maintenance_decision_in_flight', 'maintenance_demand_invalid', 'maintenance_durable_progress_invalid', 'maintenance_episode_bound', 'maintenance_episode_invalid', 'maintenance_execution_lease_exceeded', 'maintenance_finalized_frontier_invalid', 'maintenance_floor_ahead_of_hot_evidence', 'maintenance_floor_contradiction', 'maintenance_generation_changed', 'maintenance_invalid_service_lease', 'maintenance_missing_recovery_clock', 'maintenance_no_two_sided_reservation', 'maintenance_nonrecord_demand_bound', 'maintenance_nonrecord_demand_invalid', 'maintenance_observation_clock', 'maintenance_observation_inside_transaction', 'maintenance_observation_python_bound', 'maintenance_observation_row_bound', 'maintenance_observation_vm_bound', 'maintenance_owner_lease_exceeded', 'maintenance_pin_count_contradiction', 'maintenance_progress_bound', 'maintenance_progress_clock_invalid', 'maintenance_progress_outside_transaction', 'maintenance_progress_regressed', 'maintenance_progress_shape', 'maintenance_readiness_incomplete', 'maintenance_receipt_clock_invalid', 'maintenance_receipt_generation_changed', 'maintenance_recovery_source_unavailable', 'maintenance_scope_bound', 'maintenance_service_deadline_exhausted', 'maintenance_source_clock_invalid', 'maintenance_stale_or_wrong_generation', 'maintenance_storage_failure', 'maintenance_store_poisoned', 'maintenance_synopsis_contradiction', 'maintenance_synopsis_trigger_identity', 'nested_source_frame', 'notification_subscription_mismatch', 'owner_stage_identity', 'prepared_source_identity_mismatch', 'pump_consumer_backlog_archived', 'pump_event_lineage_mismatch', 'pump_local_snapshot_boundary_required', 'pump_normalized_event_missing', 'query_bound', 'reconnect_cursor_regression', 'record_below_hot_retention_floor', 'repair_duplicate_signature', 'repair_not_bounded_or_exhausted', 'repair_order_or_bounds', 'repair_page_budget', 'repair_page_budget_or_state', 'repair_pagination_stalled', 'repair_upper_boundary_not_finalized', 'restored_subscription_capacity', 'retention_batch_bound', 'retention_inside_source_transaction', 'service_draining', 'shared_evidence_plane_required', 'source_block_shape', 'source_message_shape', 'source_message_size_limit', 'source_receive_idle_timeout', 'source_transaction_shape', 'storage_capacity_critical', 'storage_stage_identity', 'stream_commit_batch_bound', 'stream_ordered_drain_incomplete', 'stream_receiver_stopped', 'subscription_capacity', 'unknown_source_subscription', 'unresolved_evidence_gap', 'unresolved_lifecycle_interest', 'unsupported_evidence_class', 'writer_failed', 'writer_start_timeout', 'writer_stop_timeout', 'writer_thread_violation'))

def failure_diagnostic(exc):
    from meme_machine.solana_evidence_plane import EvidenceUnavailable
    result='evidence_worker_failed:'+type(exc).__name__
    if type(exc) is EvidenceUnavailable and len(exc.args)==1:
        reason=exc.args[0]
        if isinstance(reason,str) and reason in SAFE_EVIDENCE_REASONS:
            result+=':'+reason
    return result

if __name__=='__main__':
    # Final process diagnostic never formats third-party exceptions/URLs.
    try:asyncio.run(main_async())
    except Exception as exc:
        raise SystemExit(failure_diagnostic(exc)) from None
