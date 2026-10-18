"""Offline USDG oracle and native quote composition; no market transport."""
import ast
from contextlib import closing
from decimal import Decimal
from pathlib import Path
import subprocess
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch
from tests.test_pump_restore_source_guard import pump_restore_predecessor

from meme_machine.lanes.ramses.abi import calldata
from meme_machine.lanes.ramses.identity import load
from meme_machine.runtime.usd_valuation import (
    USDG_ASSET,USDG_FEED,USDG_HEARTBEAT,NativeValueReader,
    ValuationUnavailable,robinhood_usd,sol_usd,
)

ROOT=Path(__file__).resolve().parents[1]
BASE='f05dcf09ebbded45e09aa7a95bfbe82c07b4fd38'
NOW=1791077122
ROUND=(1<<64)+121
UPDATED=1791042001
AGGREGATOR='0x8beee3503f6860d5dac4ce26b5eee92982951c2e'
WNATIVE='0x'+'a1'*20
POOL='0x'+'a2'*20


def baseline(path):
    try:
        return subprocess.check_output(['git','show',BASE+':'+path],cwd=ROOT,stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        # Normal CI uses a shallow checkout. No historical/network fetch belongs
        # to a deterministic unit suite; full source comparisons run locally.
        raise unittest.SkipTest('Historical source comparison needs the existing baseline commit') from None


# Explicit owner-approved removal of holding-age sales. Every other economic
# node stays pinned to the original nine-change source. These reviewed methods
# have their own exact AST identities; valuation cannot change them implicitly.
# The later owner directive also requires adverse flow for Pons's legacy
# stale-thesis helper. Its exact two-node delta from fe752458 is independently
# derived by SourceDeltaTests; constants, interfaces and siblings remain pinned.
HOLDING_DELTAS = {'meme_machine/lanes/pump/pump_acceleration_strategy.py': {'exit_decision': 'a2c3d9c0755ac779dc77298eda3a0b88b33eb1e4e3ebada5b34b93dea1dd1535'}, 'meme_machine/lanes/pump/pump_acceleration_paper.py': {'PumpAccelerationPaperLifecycle.mark': '094bb23a9533d1f96183d0239482d3a49afeb55b29567268bc8c6493e87ba671', 'PumpAccelerationPaperLifecycle.exceptional_exit_intent': '6e31ca62cbc145ec2ad27a9cd46cde386772a4cf7f1a6753a171833929534e23', 'PumpAccelerationPaperLifecycle.restore': '0c4afd4cd3497e47a452baf809face20a756d114eb90b8c05c093f229b1a9065'}, 'meme_machine/lanes/pump/runner.py': {'_monitor_positions': '9ff7f86373d2598cf6a9fa0130822ba4aafb9a6b8bfce504e0d80e998b794ba1'}, 'meme_machine/lanes/pump/pumpswap_survivor_runtime.py': {'Runtime._position': 'eb6a182cd92506c80c0506dcef8894a7c14bdd698bbf7eec63a35fe39038dcf2'}, 'meme_machine/lanes/pons/pons_selective_continuation.py': {'pregraduation_action': '123c3c69fcb29d907ea62109e7b7fb96793470439114279ce6a74b791f253ee2'}, 'meme_machine/lanes/pons/pons_postgrad_survivor.py': {'exit_action': 'a7418d0279afe5c8a1ff6e08b3fd48b1a995b81509cb6bf0cd6ef477b7a6e463'}, 'meme_machine/runtime/directional_continuation.py': {'bridge_state': 'ef830dabb4491bd7be1ed77599060e0e0d0b496a3655111b97deb330e6b16763'}, 'meme_machine/runtime/survivor_risk.py': {'mark': 'f3b06981eddd1e839624db849fe8c80fbfa2d520f0c17ed73f37922ce8581d19'}, 'tests/test_operational_nine.py': {'NineChanges.test_bridge_exact_age_and_all_required_evidence': 'd7890408ef6ac990d22ab3afafe32a4c68ecfbb82f5cff033ceae3dce4d92553'}}

# Owner-approved continuous discovery removes only main's engineering clocks.
# Keep an exact AST identity for the entire updated runtime loop, while the
# comparison below still pins all economic helpers, interfaces and siblings.
HOLDING_DELTAS['meme_machine/lanes/pump/runner.py']['main']='5dd3dbdffec0db1d2b51465298d5e3c70732c3fdee84b3297cbd8f6fb2259686'

# Separately authorized volume-quality-attention-v1. Pin the complete reviewed
# functions, including their existing economics; only candidate attention and
# fresh requalification changed. A different body still fails this source guard.
# New helpers have an exact identity too. No quote, stop, sizing or exit method
# receives a blanket exemption, and all remaining nodes/interfaces still pin.
ATTENTION_DELTAS = {
    'meme_machine/lanes/pump/runner.py': {
        # d6059e48 removes only the unused duplicate observer. Original
        # qualification/quotes/exits and the canonical LocalPumpTape remain.
        'main': '7677550cab1f9d4bb10836e1dfd77e79c55d20f3ae3e510cebc11c34b38aba79',
        '_confirmation_meta': '1cc0f6803425581dd6dd91fcd4b037142764d23ae5fbc5a855914ea5f346c000',
        '_volume_quality_attention': 'a4e73e44c66164b18aadd8102d53d86f7483573fec8d9af8c611fae230cec6ab',
        '_late_signal': '2ed9c66d2dbbb1fdbbb7f1317d40ed65eeb1cea2fd923545016b38d74c5b6e6f',
        '_volume_price_signal': 'ca32e28c8363e5ceba28b67fc7edf6d0e3ac98820bf3a06d3234522495ac4b9a',
        '_record_attempt': 'e0d61bb5bda067f4b12274a946a93af485d03a43ca394938dc38f8754ae5bb6e',
    },
    'meme_machine/lanes/pump/pumpswap_survivor_runtime.py': {
        'Runtime.__init__': 'ea88001e5397533149a47b438dddf56a57babb6bb167c768e809c43e36e90cc7',
        'Runtime._quality_rank': '503bd866a7a3a660a7710386918f292c9e7b7f444e6a4aeecd1326dfdd6338fd',
        'Runtime.reconstruct': 'bac6cac5d29640d85e3e21bc217b58ca99d0fee696598aa37a6791c0ae9a9176',
        'Runtime.step': 'aeca30c345bd2d1955a268853b43a3787dea93fac9fc20441c1d37dd9507622f',
    },
    'meme_machine/lanes/pons/pons_history.py': {
        'PonsHistory.__init__': '499d6eed49f38ff1477e1d28873b8bb8a9bd4b57e41019899f58684caa70be50',
        'PonsHistory._quality_rank': '503bd866a7a3a660a7710386918f292c9e7b7f444e6a4aeecd1326dfdd6338fd',
        'PonsHistory.qualification_turn': 'a7ade8682f589a00202bb292fda823c4357d7c0f32ebd12a719a8ed0bf17c3a4',
    },
    'meme_machine/lanes/pons/pons_survivor_runtime.py': {
        'Runtime._watch_due': '53d9f1504e9eb48459179e76cd43df6e0e0d229b4f8a22f4f857387e7bc64987',
        'Runtime._schedule_watch': '9c5959d7e61c6dd69fc1079f928e260b5b34dbcf2dede8aec156055585552b8a',
        'Runtime.reconstruct': '29f6151b8ebbe4ff385ce4388de3932735e8c01d4f3a411a271cae75a05562ee',
    },
}

# Reviewed operational contention repairs retain the same candidate history,
# graduation horizon and 8,192-entry cache. Pin only their exact changed nodes;
# every other economic function and interface remains compared to the baseline.
OPERATION_DELTAS = {
    'meme_machine/lanes/pump/pumpswap_survivor_runtime.py': {
        # Owner-authorized history separation: exact retained reset-prefix
        # reuse and window reads. All economics and maintenance remain pinned;
        # HistoryCalculationTests compares the two changed acquisition nodes.
        'Runtime.reconstruct': 'debef54d753279920b6ec5c0619edd984bee44ad536a5897eea3be954e99f8d8',
    },
    'meme_machine/lanes/pump/solana_evidence_health.py': {
        # Restore the maintained indexed and verified-volume health path in
        # the actual Pump worker; all freshness and coverage checks stay pinned.
        'evidence_health': '3473d68023a84021ec718f2a7d7a92fe10dee7ef4b7ed4958ed21c382cfed011',
    },
    'meme_machine/lanes/pump/solana_evidence_plane.py': {
        # Only the existing coverage_end_hint access path differs. Gap,
        # availability, interval ordering and membership checks remain pinned.
        'EvidenceReader.covered': '06b4169316bc8f6410235f947719956dce7eb731f03c2dbb788784a7b2556626',
    },
    'meme_machine/lanes/pump/runner.py': {
        '_retain_tape_history': '7e2546ac6ea91029b22809fd3b95fa3ff20a891ad1095a1fd1a39f853e3a6cbd',
        '_observed_creation': '45a63d1aec238ecd9c13498b4bace0ccf532d757b2866fd215c2c1fa1940f5ec',
        # The retained-data comparison proves identical restoration outputs.
        # Pin this exact read-only predicate pushdown; the regression below
        # derives its only two AST changes from the reviewed e398 source.
        '_restore_observed_pump_candidates': '5d3e675caf380ccf2743e3e2bcaa3eb37dbc14f7555210eec14db84ab20482b6',
    },
    'meme_machine/lanes/pons/immutable_rpc.py': {
        'EvidenceStore.__init__': 'e6558c2232a88f43b6ac74805395343768cfbbfdd453390ba28cf6f4fb16aa3e',
        'EvidenceStore.put': '28b55b13579655f0aebcc2b45de5c55404d4a1cdf495a62de0f47189adc4a2de',
    },
    'meme_machine/lanes/pump/solana_evidence_runtime.py': {
        # 5ec6a2b6 keeps creation lookup and its bounded per-poll attention
        # cache separate. Missing lineage is forgotten on the next poll.
        'LocalPumpTape.creation': 'a233fc5649ccc393970f4de814b3462884155a0daf3618a9e608b2990624f0d7',
        # O5 cancellation was inside rich-body fetchall. Exact authenticated
        # rolling-origin lookup and cooperative legacy streaming preserve
        # availability, hash/lineage validation and all economic siblings.
        'LocalPumpTape._creation': 'a833703cf88891ed985af14d213c0ca2b9437002925fca278fadadc93b1cd51a',
        'LocalPumpTape.events_since': 'ba20cb5653544e5ae46696fbc47bf95c684b4e0042df9f76c52c09cca981e631',
    },
}

# cf443e86 is the reviewed acquisition-only Pons wider-window integration;
# the subsequent explicit owner directive removes only mandatory team_id.
# Freeze that complete file byte-for-byte, rather than exempting it as generic
# infrastructure. The source before this exact transition stays pinned too;
# strategy economics, constants and the nine-change tests retain their guards.
ACQUISITION_SOURCE_DELTAS = {
    'meme_machine/lanes/pons/log_windows.py': {
        'reference': 'cf443e860ee21795453fd7b6311732267562bf1a',
        'before_sha256': 'bba8cfafcedb7223c4259d2c2a509ec8cb786307cea24ac6ffcbf2b241bf3e84',
        'reviewed_sha256': '7cc289d0041c21b7758fa0a742e1b792ff96d5049954a063d823556088e8db48',
    },
}

# The owner explicitly approved the completed lifecycle/reporting package at
# 9cdc1b54. Its three previously protected files remain pinned byte-for-byte;
# first validate the exact prior source with the original economic guard. This
# permits only that published package, including the reviewed readonly keyword
# interface and canonical confirmation fields, rather than exempting Pons code.
LIFECYCLE_PACKAGE_BASE = 'e8f7d2ec8ccc0d530c94171390e1966d5c42a70f'
LIFECYCLE_PACKAGE_REFERENCE = '9cdc1b5428f8ebf0bfcc6206cb8122b354654d9d'
LIFECYCLE_SOURCE_DELTAS = {
    'meme_machine/lanes/pons/pons_selective_continuation.py': {
        'before_sha256': '1461b456fba76e3e27674eb3cd626f856176d4ba9fdc00c3907fc75b350da0ed',
        'reviewed_sha256': 'e25cd6074cb283dd0924c942094877ff79ed0a21f613ea0974fe16424007e145',
    },
    'meme_machine/lanes/pons/pons_selective_capital.py': {
        'before_sha256': 'c16fc1d787692997222e1fa7003f04d52242d31385efa707d91ee98edefec2f2',
        'reviewed_sha256': '54f9621fed567b8e68b2e18dddc10eb0f0e7db5b4bfb243d434f173d8a5d5716',
    },
    'meme_machine/lanes/pons/pons_selective_recovery.py': {
        'before_sha256': '037a5c21aead51273bbe6d150ed6f2b608d7cee92bd0c8919c3f08374e03c753',
        'reviewed_sha256': '700a09510f2e1eda0f9ea5ef552561d3b13827078c6797dd5ba765e08ec06226',
    },
}

# Explicit owner-selected PAPER opportunity revision. Every changed node is
# pinned against the latest engineering predecessor; historical protections are
# still checked on that predecessor rather than exempting entire strategy files.
OPPORTUNITY_BASE='b1ece095231f156eaf1d9d61bfd2f9d959558c54'
OPPORTUNITY_STRATEGY_BASE='a048ee8cbeb87bff9c589a0b6f587fd909c23ed5'
OPPORTUNITY_REFERENCE='5f94eb0b7c286ec2d763ab274784ebbb89b2baaa'
OPPORTUNITY_ORIGINAL_MANIFEST_SHA256='80ccc48ff5bedf7fb7612c9a586b1533fa3f93e5df745e13af324293d9c60210'
OPPORTUNITY_MANIFEST=ROOT/'tests/fixtures/paper_opportunity_access_source_delta.json'
OPPORTUNITY_ADDED_SOURCES=(
    'meme_machine/paper_policy_revision.py',
    'meme_machine/lanes/pump/pump_attempt_reference.py',
    'meme_machine/runtime/policy_compatibility.py',
    'meme_machine/policy_history/pre_opportunity_access_v1.json',
)


# Issue #138 explicitly authorizes executable PAPER bridge/re-entry economics.
# This is a new exact layer above the already-reviewed source, never a broad
# strategy exemption. Its complete byte pins and individual method/statement
# deltas must reverse to main 950852cb before every original guard runs.
# Its contained-observation layer then reverses independently to its own exact
# predecessor; neither authorization absorbs the other's source delta.
RALLY_BASE='950852cb87516cd1c94f6762ec178b17232c346f'
RALLY_MANIFEST=ROOT/'tests/fixtures/paper_postgrad_rally_source_delta.json'
RALLY_SCHEMA='owner-selected-paper-postgrad-rally-source-delta-v1'
RALLY_MANIFEST_SHA256='c99d39c2e542538271c8b1db9a995ab76d6801d16ade1e0d7689baaf10e90302'
RALLY_CHANGED_SOURCES=('meme_machine/lanes/pons/pons_postgrad_survivor.py', 'meme_machine/lanes/pons/pons_survivor_runtime.py', 'meme_machine/lanes/pump/pump_acceleration_strategy.py', 'meme_machine/lanes/pump/pumpswap_survivor.py', 'meme_machine/lanes/pump/pumpswap_survivor_runtime.py', 'meme_machine/lanes/pump/runner.py', 'meme_machine/operational/supervisor.py', 'meme_machine/paper_policy_revision.py', 'meme_machine/runtime/directional_continuation.py', 'meme_machine/runtime/native_boundary.py', 'meme_machine/runtime/opportunity_telemetry.py', 'meme_machine/runtime/policy_compatibility.py', 'meme_machine/runtime/robinhood/pons.py', 'meme_machine/runtime/sleeve_reservations.py', 'meme_machine/runtime/survivor_commit.py', 'meme_machine/runtime/survivor_history.py', 'meme_machine/runtime/survivor_paper_book.py', 'meme_machine/runtime/survivor_risk.py', 'meme_machine/runtime/survivor_terminal_archive.py', 'meme_machine/shared_capital/native_sleeve.py', 'meme_machine/shared_capital/runtime.py', 'operational/strategy-change-audit.py')
RALLY_ADDED_SOURCES=('meme_machine/policy_history/opportunity_access_v1.json', 'meme_machine/runtime/rally_cycle.py')


# Opt-in source costs use an independent process recorder publication rather
# than waiting for the canonical health queue. This exact transport delta grants
# no readiness, continuity, accounting or lease authority.
SOURCE_RECORDER_PUBLICATION_REFERENCE='6681087c643a205cf1448f4eabcc984ed31906ac'
SOURCE_RECORDER_PUBLICATION_DELTAS={
    'meme_machine/solana_evidence_service.py':(
        '717a471a0451085b1de27a1927f44aedde5a1acd7253bfdbb217800a07e0a15c',
        'b1f0e8d9aaa5db37e73ea544be47725f04f7b97f6e6ad12613c8012770bc5e72',
        'serve','publish_operation_costs',(
            b'        from .runtime.operation_costs import enabled as costs_enabled\n'
            b'        cost_publisher=(asyncio.create_task(publish_operation_costs(path,owner,stop))\n'
            b"            if costs_enabled() and os.environ.get('MM_SQLITE_DIAGNOSTIC_REQUIRED')=='1' else None)\n",
            b'        if cost_publisher is not None:tasks.append(cost_publisher)\n')),
    'engineering/diagnostics/current_combined_observation_20261014.py':(
        'b81d8edb46593777851d42f8b8c84519dc1217119efba23adc5274ae47119b84',
        '5a3adec8c1e28069a43cd521551e7aa7f886260390dbd36e82ce0d3d0a2b0ba2',
        'pipeline_sample','source_operation_costs',(
            b"            if (os.environ.get('MM_OPERATION_COST_DIAGNOSTICS')=='1'\n"
            b"                    and os.environ.get('MM_SQLITE_DIAGNOSTIC_REQUIRED')=='1'):\n"
            b'                telemetry=source_operation_costs(root,expected_pid)\n'
            b"                result['required_counters']['operation_costs']=telemetry.pop('operation_costs')\n"
            b"                result['source_operation_telemetry']=telemetry\n",)),
}
SOURCE_RECORDER_TEST_BODY_BEFORE='9dd30c77c952f1c516b4f2a1f5f2a76220394e1b209f2c71fb9d0f0742a09ad6'
SOURCE_RECORDER_TEST_READ_OLD=b'            current=(ROOT/relative).read_bytes()\n'
SOURCE_RECORDER_TEST_READ_NEW=(b'            current=source_recorder_publication_predecessor('
    b'self,relative,(ROOT/relative).read_bytes())\n')


def source_recorder_publication_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    reviewed=SOURCE_RECORDER_PUBLICATION_DELTAS.get(relative)
    if reviewed is None:return current
    before,after,changed,added,blocks=reviewed
    prior=subprocess.check_output(['git','show',SOURCE_RECORDER_PUBLICATION_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),before,relative+':exact source recorder predecessor')
    if current==prior:return prior
    test.assertEqual(hashlib.sha256(current).hexdigest(),after,relative+':exact independent recorder successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def node(root,name):
        return next(n for n in root.body
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    def source(body,selected):
        return b''.join(body.splitlines(keepends=True)[selected.lineno-1:selected.end_lineno])
    selected=node(tree,changed);original=node(old,changed);helper=node(tree,added)
    with test.assertRaises(StopIteration):node(old,added)
    test.assertEqual(ast.dump(selected.args),ast.dump(original.args),relative+':unchanged original runtime interface')
    restored_node=source(current,selected)
    for block in blocks:
        test.assertEqual(restored_node.count(block),1,relative+':one fixed opt-in lifecycle or cost-only injection')
        restored_node=restored_node.replace(block,b'',1)
    test.assertEqual(restored_node,source(prior,original),
        relative+':all original startup, shutdown, canonical health, financial and cursor statements retained')
    restored=current
    for block in blocks:restored=restored.replace(block,b'',1)
    helper_bytes=source(current,helper)+b'\n\n'
    test.assertEqual(restored.count(helper_bytes),1,relative+':one explicitly added complete helper')
    restored=restored.replace(helper_bytes,b'',1)
    test.assertEqual(restored,prior,relative+':every other source byte and original guard retained')
    tree.body[tree.body.index(selected)]=deepcopy(original);tree.body.remove(helper)
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':only the declared helper and task/injection node change')
    return prior


# The serialized maintenance callback owns one actual entry timestamp. Reusing
# it removes the duplicate queue-clock decision without renewing execution,
# worker, source or drought deadlines. Pin these complete mandatory owner files
# and reverse only the reviewed callback/lease nodes to their exact predecessor.
MAINTENANCE_ENTRY_CLOCK_REFERENCE='76741b3c56b3892d372c5fb2953cf2fdbd53404a'
MAINTENANCE_ENTRY_CLOCK_DELTAS={
    'meme_machine/solana_evidence_service.py':(
        '61c04418d465c1b419b2b88123c37678794ab50dd42fc78c16a3ff20a6845482',
        '717a471a0451085b1de27a1927f44aedde5a1acd7253bfdbb217800a07e0a15c',
        ('serve.maintenance.turn',)),
    'meme_machine/solana_maintenance_runtime.py':(
        'bbedbfb392506ce3b2f05f7473b88234182c6261410217ed56fdcca4c2b6dab6',
        '3c9fbb12f6e5b0a53a73fc014c70a0b68ba836feb8b8c17f810bba9e384f24ff',
        ('MaintenanceRuntime.turn','MaintenanceRuntime.execution_lease')),
}


def maintenance_entry_clock_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    reviewed=MAINTENANCE_ENTRY_CLOCK_DELTAS.get(relative)
    if reviewed is None:return current
    before,after,changed=reviewed
    prior=subprocess.check_output(['git','show',MAINTENANCE_ENTRY_CLOCK_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),before,relative+':exact maintenance-entry predecessor')
    if current==prior:return prior
    current=source_recorder_publication_predecessor(test,relative,current)
    test.assertEqual(hashlib.sha256(current).hexdigest(),after,relative+':exact maintenance-entry successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def node(root,name):
        parent=root
        for part in name.split('.'):
            matches=[n for n in ast.walk(parent) if n is not parent
                and isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==part]
            test.assertEqual(len(matches),1,relative+':one explicit qualified node '+name)
            parent=matches[0]
        return parent
    for name in changed:
        selected=node(tree,name);original=node(old,name)
        test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':explicit entry-clock node '+name)
        owners=[(body,index) for parent in ast.walk(tree) for _,body in ast.iter_fields(parent)
            if isinstance(body,list) for index,child in enumerate(body) if child is selected]
        test.assertEqual(len(owners),1,relative+':one exact named-node owner')
        body,index=owners[0];body[index]=deepcopy(original)
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':all other native, source and economic authority nodes retained')
    return prior


# An incremental Survivor checkpoint cannot seal its earlier required history
# against a later gap. Pin only the fresh full-window continuity precheck before
# the shortcut or any history write; retain every original strategy/exit byte.
SURVIVOR_INCREMENT_CONTINUITY_REFERENCE='1c69c4f23c9f5094d5ee15a02d066820c3517c02'
SURVIVOR_INCREMENT_CONTINUITY_SOURCE='meme_machine/lanes/pump/pumpswap_survivor_runtime.py'
SURVIVOR_INCREMENT_CONTINUITY_BEFORE='a57f3f2b8f44c611b38e02c4bbf648198d1229cab77f2d8c135b3e195f202a46'
SURVIVOR_INCREMENT_CONTINUITY_AFTER='9239b836e24163f9df91f24ac7f7ea48bb31ff98f19367f84bfe702a742320ae'
SURVIVOR_INCREMENT_CONTINUITY_PRIORS={
    '8790ad97bc5dea4b579e65b017e96b8fa38ee1c2fc56ca70c9bb34564b56c090':
        '950852cb87516cd1c94f6762ec178b17232c346f',
    'ade9b157ca2dccd5e12108e10291963c6d1eedb853e37b8bef76d33402c136ae':
        'b1ece095231f156eaf1d9d61bfd2f9d959558c54',
}
SURVIVOR_INCREMENT_CONTINUITY_BLOCK=(
    b'        from meme_machine.solana_evidence_plane import EvidenceUnavailable\n'
    b'        from meme_machine.solana_selective_history import ConsumerReader\n'
    b'        reader=self.plane._selective_reader()\n'
    b'        db=reader.original.db if isinstance(reader,ConsumerReader) else reader.db\n'
    b'        # A durable incremental checkpoint does not seal its retained prefix\n'
    b'        # against a subsequently observed gap. Recheck the exact required\n'
    b'        # history without hydrating it or changing its historical observations.\n'
    b"        db.execute('BEGIN')\n"
    b'        try:\n'
    b"            graduation=row['graduation'];lower=graduation.get('slot');upper=slot\n"
    b'            if lower is None:\n'
    b"                lower,_=self.plane.bounds(SWAP_SCOPE,graduation['at'],at,upper_slot=slot)\n"
    b'            elif type(lower) is not int or lower<0:\n'
    b"                raise EvidenceUnavailable('survivor_graduation_slot_unverified')\n"
    b"            candidate=reader.candidate('pumpswap',row['graduation']['pool']) if isinstance(reader,ConsumerReader) else reader\n"
    b'            scope=candidate.scope if isinstance(reader,ConsumerReader) else SWAP_SCOPE\n'
    b'            if not candidate.covered(scope,lower,upper,as_of=time.time()):\n'
    b"                raise EvidenceUnavailable('unresolved_evidence_gap')\n"
    b"        finally:db.execute('ROLLBACK')\n"
)


def survivor_increment_continuity_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=SURVIVOR_INCREMENT_CONTINUITY_SOURCE:return current
    prior=subprocess.check_output(['git','show',SURVIVOR_INCREMENT_CONTINUITY_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),SURVIVOR_INCREMENT_CONTINUITY_BEFORE,
        relative+':exact Survivor full-window continuity predecessor')
    if current==prior:return prior
    checksum=hashlib.sha256(current).hexdigest()
    if checksum in SURVIVOR_INCREMENT_CONTINUITY_PRIORS:
        earlier=subprocess.check_output(['git','show',SURVIVOR_INCREMENT_CONTINUITY_PRIORS[checksum]+':'+relative],cwd=ROOT)
        test.assertEqual(current,earlier,relative+':exact older strategy comparison source')
        return current
    test.assertEqual(checksum,SURVIVOR_INCREMENT_CONTINUITY_AFTER,
        relative+':exact Survivor full-window continuity successor')
    test.assertEqual(current.count(SURVIVOR_INCREMENT_CONTINUITY_BLOCK),1,
        relative+':one exact required-window precheck')
    restored=current.replace(SURVIVOR_INCREMENT_CONTINUITY_BLOCK,b'',1)
    test.assertEqual(restored,prior,relative+':all other economics, held exits and history bytes retained')
    tree=ast.parse(current);old=ast.parse(prior)
    def method(root):
        parent=next(n for n in root.body if isinstance(n,ast.ClassDef) and n.name=='Runtime')
        return parent,next(n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name=='_increment')
    parent,selected=method(tree);_,original=method(old)
    test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':only Runtime._increment changed')
    parent.body[parent.body.index(selected)]=deepcopy(original)
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':all other source nodes retained')
    return prior


# An empty hot sleeve prefix needs no optional backup/compaction. The positive
# read-only precheck changes scheduling only: the original open, full replay,
# native authority and reconciliation remain exact before older strategy guards.
SLEEVE_EMPTY_PREFIX_REFERENCE='446dba55a81a851252ef4253bb9f62f5c25ed80b'
SLEEVE_EMPTY_PREFIX_SOURCE='meme_machine/runtime/sleeve_reservations.py'
SLEEVE_EMPTY_PREFIX_BEFORE='489bedd30cb1018cc7e61e8b9c0b93ecd663b9f47fad9c3a2230bc3fdce6bb3f'
SLEEVE_EMPTY_PREFIX_AFTER='928a4e250221c3638efbadc52efa6f6718df0c275c7c112882ae90663d356fe7'
SLEEVE_EMPTY_PREFIX_IMPORT_OLD=b'from contextlib import contextmanager\n'
SLEEVE_EMPTY_PREFIX_IMPORT_NEW=b'from contextlib import closing, contextmanager, nullcontext\n'


def sleeve_empty_prefix_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=SLEEVE_EMPTY_PREFIX_SOURCE:return current
    prior=subprocess.check_output(['git','show',SLEEVE_EMPTY_PREFIX_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),SLEEVE_EMPTY_PREFIX_BEFORE,
        relative+':exact original complete sleeve source')
    if current==prior:return prior
    test.assertEqual(hashlib.sha256(current).hexdigest(),SLEEVE_EMPTY_PREFIX_AFTER,
        relative+':exact empty-prefix optional compaction scheduling successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def method(root,name):
        parent=next(n for n in root.body if isinstance(n,ast.ClassDef) and n.name=='SleeveReservations')
        return parent,next(n for n in parent.body
            if isinstance(n,ast.FunctionDef) and n.name==name)
    def source(body,selected):
        first=min(selected.lineno,*(n.lineno for n in selected.decorator_list)) if selected.decorator_list else selected.lineno
        return b''.join(body.splitlines(keepends=True)[first-1:selected.end_lineno])
    parent,selected=method(tree,'__init__');_,original=method(old,'__init__')
    test.assertEqual(ast.dump(selected.args),ast.dump(original.args),relative+':unchanged sleeve constructor interface')
    test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':only the declared constructor changes')
    test.assertIsInstance(selected.body[-1],ast.With)
    test.assertIsInstance(original.body[-1],ast.With)
    test.assertEqual([ast.dump(n) for n in selected.body[-1].body],
        [ast.dump(n) for n in original.body[-1].body],
        relative+':original open, optional compaction and exception cleanup still run in the same order')
    for name in ('_open','_compact_preserved','reconcile','reserve','release','commit_fence'):
        _,node=method(tree,name);_,previous=method(old,name)
        test.assertEqual(source(current,node),source(prior,previous),
            relative+':original financial and recovery method retained '+name)
    before=source(prior,original);after=source(current,selected)
    test.assertEqual(current.count(after),1,relative+':one exact constructor delta')
    test.assertEqual(current.count(SLEEVE_EMPTY_PREFIX_IMPORT_NEW),1,relative+':one exact contextlib import delta')
    restored=current.replace(after,before,1).replace(SLEEVE_EMPTY_PREFIX_IMPORT_NEW,SLEEVE_EMPTY_PREFIX_IMPORT_OLD,1)
    test.assertEqual(restored,prior,relative+':every other source, replay, protection and financial byte retained')
    parent.body[parent.body.index(selected)]=deepcopy(original)
    imported=ast.parse(SLEEVE_EMPTY_PREFIX_IMPORT_NEW).body[0]
    matches=[n for n in tree.body if ast.dump(n)==ast.dump(imported)]
    test.assertEqual(len(matches),1,relative+':one contextlib AST delta')
    tree.body[tree.body.index(matches[0])]=deepcopy(ast.parse(SLEEVE_EMPTY_PREFIX_IMPORT_OLD).body[0])
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':only the reviewed constructor and import nodes change')
    return prior


# The retained provider may omit lines between post-marker observations. Match
# their exact sequence at distinct positions beyond the verified prefix, while
# retaining the complete authenticated log array and every earlier source pin.
ARCHIVE_LOG_ORDER_REFERENCE='2b8c8b12c4d265df846de6bf7c6c904720f2e739'
ARCHIVE_LOG_ORDER_SOURCE='meme_machine/solana_selective_history.py'
ARCHIVE_LOG_ORDER_BEFORE='16587a4779d8b60a67b994489c7367336131a874082397327c33677bff91ae8b'
ARCHIVE_LOG_ORDER_AFTER='d7b79f1a25b687cadc0ebe16f81ddc1ffba222402c3433378658ba39a5734ae3'
ARCHIVE_LOG_ORDER_OLD=(
    b'        # The archive may retain lines after its truncation marker. Preserve\n'
    b'        # their complete order as one contiguous segment, without reusing any\n'
    b'        # prefix lines. The full response may also contain a later suffix.\n'
    b'        if suffix and sum(complete[start:start+len(suffix)]==suffix\n'
    b'                for start in range(len(prefix),len(complete)-len(suffix)+1))<1:\n'
    b'            raise KeyError()\n')
ARCHIVE_LOG_ORDER_NEW=(
    b'        # The archive may retain sparse lines after its truncation marker.\n'
    b'        # Match every line in order at a distinct position beyond the prefix;\n'
    b'        # only the entire complete response supplies decoded event indices.\n'
    b'        position=len(prefix)\n'
    b'        for line in suffix:\n'
    b'            while position<len(complete) and complete[position]!=line:position+=1\n'
    b'            if position==len(complete):raise KeyError()\n'
    b'            position+=1\n')


def archive_log_order_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=ARCHIVE_LOG_ORDER_SOURCE:return current
    prior=subprocess.check_output(['git','show',ARCHIVE_LOG_ORDER_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),ARCHIVE_LOG_ORDER_BEFORE,
        relative+':exact contiguous retained-log predecessor')
    if current==prior:return prior
    test.assertEqual(hashlib.sha256(current).hexdigest(),ARCHIVE_LOG_ORDER_AFTER,
        relative+':exact ordered-distinct retained-log successor')
    test.assertEqual(prior.count(ARCHIVE_LOG_ORDER_OLD),1,relative+':one original contiguous search')
    test.assertEqual(current.count(ARCHIVE_LOG_ORDER_NEW),1,relative+':one exact ordered-distinct search')
    restored=current.replace(ARCHIVE_LOG_ORDER_NEW,ARCHIVE_LOG_ORDER_OLD,1)
    test.assertEqual(restored,prior,
        relative+':all identity, marker, prefix, complete-output, index and receipt bytes retained')
    tree=ast.parse(current);old=ast.parse(prior)
    def function(root):
        return next(n for n in root.body if isinstance(n,ast.FunctionDef) and n.name=='_archive_log_join')
    selected=function(tree);original=function(old)
    test.assertEqual(ast.dump(selected.args),ast.dump(original.args),relative+':unchanged strict join interface')
    test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':only the declared retained-log join changes')
    tree.body[tree.body.index(selected)]=deepcopy(original)
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':every other economic and recovery node retained')
    return prior


# Repeated known suffix placements cannot select or change authoritative logs:
# the output remains the entire authenticated full transaction. Reverse exactly
# the one reviewed zero-match predicate before the retained-log source guards.
ARCHIVE_LOG_CONSISTENCY_REFERENCE='a8f8edebaecf83df0d767e7fba1fd530f378c7af'
ARCHIVE_LOG_CONSISTENCY_SOURCE='meme_machine/solana_selective_history.py'
ARCHIVE_LOG_CONSISTENCY_BEFORE='18575b7a64fc122ae56a770c97a9dc9e60b7b437ffcce792f0e310f1853f62b5'
ARCHIVE_LOG_CONSISTENCY_AFTER='16587a4779d8b60a67b994489c7367336131a874082397327c33677bff91ae8b'
ARCHIVE_LOG_CONSISTENCY_OLD=b'for start in range(len(prefix),len(complete)-len(suffix)+1))!=1:'
ARCHIVE_LOG_CONSISTENCY_NEW=b'for start in range(len(prefix),len(complete)-len(suffix)+1))<1:'


def archive_log_consistency_predecessor(test,relative,current):
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=ARCHIVE_LOG_CONSISTENCY_SOURCE:return current
    prior=subprocess.check_output(['git','show',ARCHIVE_LOG_CONSISTENCY_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),ARCHIVE_LOG_CONSISTENCY_BEFORE,
        relative+':exact complete-log-consistency predecessor')
    if current==prior:return prior
    current=archive_log_order_predecessor(test,relative,current)
    test.assertEqual(hashlib.sha256(current).hexdigest(),ARCHIVE_LOG_CONSISTENCY_AFTER,
        relative+':exact complete-log-consistency successor')
    def function(content):
        return next(n for n in ast.parse(content).body if isinstance(n,ast.FunctionDef) and n.name=='_archive_log_join')
    test.assertNotEqual(ast.dump(function(current)),ast.dump(function(prior)),
        relative+':explicit known-content existence predicate')
    test.assertEqual(current.count(ARCHIVE_LOG_CONSISTENCY_NEW),1,relative+':one exact zero-match rejection')
    restored=current.replace(ARCHIVE_LOG_CONSISTENCY_NEW,ARCHIVE_LOG_CONSISTENCY_OLD,1)
    test.assertEqual(restored,prior,relative+':all other identity, complete-output and receipt source bytes retained')
    return prior


# A finalized archive can retain known lines after its one truncation marker.
# Pin exact transaction joining and receipt metadata, then restore both named
# nodes before the complete-log and original economic/recovery source guards.
RETAINED_ARCHIVE_LOG_SHAPE_REFERENCE='72351d004da308eada224b787aadda0dfdddb283'
RETAINED_ARCHIVE_LOG_SHAPE_SOURCE='meme_machine/solana_selective_history.py'
RETAINED_ARCHIVE_LOG_SHAPE_BEFORE='ea09e4c74ca85302157631303d928b65e656b8c01df6ffaf6193b3efe1ab211f'
RETAINED_ARCHIVE_LOG_SHAPE_AFTER='18575b7a64fc122ae56a770c97a9dc9e60b7b437ffcce792f0e310f1853f62b5'


def retained_archive_log_shape_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=RETAINED_ARCHIVE_LOG_SHAPE_SOURCE:return current
    prior=subprocess.check_output(['git','show',RETAINED_ARCHIVE_LOG_SHAPE_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),RETAINED_ARCHIVE_LOG_SHAPE_BEFORE,
        relative+':exact retained-archive-log predecessor')
    if current==prior:return prior
    current=archive_log_consistency_predecessor(test,relative,current)
    test.assertEqual(hashlib.sha256(current).hexdigest(),RETAINED_ARCHIVE_LOG_SHAPE_AFTER,
        relative+':exact retained-archive-log successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def function(root,name):
        return next(n for n in root.body if isinstance(n,ast.FunctionDef) and n.name==name)
    for name in ('_archive_log_join','archive_page_evidence'):
        selected=function(tree,name);original=function(old,name)
        test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':explicit retained-log node '+name)
        tree.body[tree.body.index(selected)]=deepcopy(original)
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':all other identity, financial and recovery source retained')
    return prior


# Finalized archive rows may contain an explicitly truncated log suffix. The
# separately fetched complete logs must retain the original native order,
# transaction identity and prefix. Pin both complete sources and reverse only
# these reviewed acquisition/proof nodes to 1b77 before the original guards.
# This adds no economic, financial or recovery-authority exemption.
ARCHIVE_COMPLETE_LOGS_REFERENCE='1b77970042697224af3993f564c1d9e06b81ce0a'
ARCHIVE_COMPLETE_LOGS_DELTAS={
    'meme_machine/solana_selective_history.py':(
        '1f267926b9c60d2f4c0f46fb3352cbfe845ae64e4564a2cb7dce6746b11c04cf',
        'ea09e4c74ca85302157631303d928b65e656b8c01df6ffaf6193b3efe1ab211f',
        ('SelectiveHistory.commit_page',),
        ('ArchiveLogSupplement','_archive_log_join','join_archive_log_supplement',
         'complete_archive_transaction','missing_archive_log_transactions',
         'archive_interval_witness','archive_page_evidence','SelectiveHistory.has_archive_log_supplements'),
        (('from dataclasses import replace','from dataclasses import dataclass,replace'),)),
    'meme_machine/solana_selective_source.py':(
        'c21a5e26373b39165194ad5475364494560883c2c7b45b25bd095f68eb451df6',
        'f3391d7aca7c1f185131fabe51edfb0e5bf37a79a35046449b06e3d5c916030e',
        ('SelectiveSource.acquire',),(),()),
}


def archive_complete_logs_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    reviewed=ARCHIVE_COMPLETE_LOGS_DELTAS.get(relative)
    if reviewed is None:return current
    before,after,changed,added,imports=reviewed
    prior=subprocess.check_output(['git','show',ARCHIVE_COMPLETE_LOGS_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),before,relative+':exact complete-log predecessor')
    if current==prior:return prior
    current=retained_archive_log_shape_predecessor(test,relative,current)
    test.assertEqual(hashlib.sha256(current).hexdigest(),after,relative+':exact complete-log successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def node(root,name):
        parent=root
        for part in name.split('.')[:-1]:
            parent=next(n for n in parent.body if isinstance(n,ast.ClassDef) and n.name==part)
        return parent,next(n for n in parent.body
            if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name.split('.')[-1])
    for name in changed:
        parent,selected=node(tree,name);_,original=node(old,name)
        test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':explicit archive node '+name)
        parent.body[parent.body.index(selected)]=deepcopy(original)
    for name in added:
        parent,selected=node(tree,name);parent.body.remove(selected)
        with test.assertRaises(StopIteration):node(old,name)
    for previous,successor in imports:
        original=ast.parse(previous).body[0];replacement=ast.parse(successor).body[0]
        matches=[n for n in tree.body if ast.dump(n)==ast.dump(replacement)]
        test.assertEqual(len(matches),1,relative+':one exact archive import delta')
        test.assertEqual(sum(ast.dump(n)==ast.dump(original) for n in old.body),1,
            relative+':one exact predecessor import')
        tree.body[tree.body.index(matches[0])]=deepcopy(original)
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':all other economic and authority source retained')
    return prior


# Push phase selection into the existing provider-ledger read without changing
# its selected-state comprehension or any quota, reservation or usage writer.
# Non-text keys still reach the original predicate; unused foreign TEXT is no
# longer decoded. Pin only this exact SQL read delta and retain every other byte.
PROVIDER_NAMESPACE_READ_REFERENCE='c69e45adb8f67a9e451aa4e5f7b62a8d8d0e465d'
PROVIDER_NAMESPACE_READ_SOURCE='meme_machine/operational/bounded_provider.py'
PROVIDER_NAMESPACE_READ_BEFORE='af31c335de6ad22e52f7c69a399c4088bd616e6ac925f97a3a8e40265664c383'
PROVIDER_NAMESPACE_READ_AFTER='da18972da976617132d08b475ea24cbb4fbd5556d394dba6e21d038c314bbd45'


def provider_namespace_read_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=PROVIDER_NAMESPACE_READ_SOURCE:return current
    prior=subprocess.check_output(['git','show',PROVIDER_NAMESPACE_READ_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),PROVIDER_NAMESPACE_READ_BEFORE,
        relative+':exact original provider-ledger source')
    if current==prior:return prior
    test.assertEqual(hashlib.sha256(current).hexdigest(),PROVIDER_NAMESPACE_READ_AFTER,
        relative+':exact namespace SQL pushdown successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def read(root):
        parent=next(n for n in root.body if isinstance(n,ast.ClassDef) and n.name=='Budget')
        return parent,next(n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name=='read')
    def source(body,selected):
        return b''.join(body.splitlines(keepends=True)[selected.lineno-1:selected.end_lineno])
    parent,selected=read(tree);_,original=read(old)
    test.assertEqual(ast.dump(selected.args),ast.dump(original.args),relative+':unchanged provider read interface')
    test.assertEqual(len(original.body),1,relative+':original read is only the selected-state comprehension')
    test.assertEqual(len(selected.body),2,relative+':only SQL selection precedes the original comprehension')
    test.assertIsInstance(selected.body[0],ast.If)
    test.assertIsInstance(selected.body[-1],ast.Return)
    projected=deepcopy(selected.body[-1]);previous=original.body[-1]
    test.assertEqual(len(projected.value.generators),1,relative+':one original namespace iterator')
    projected.value.generators[0].iter=deepcopy(previous.value.generators[0].iter)
    test.assertEqual(ast.dump(projected),ast.dump(previous),
        relative+':exact original key stripping, selected values and Python namespace defense retained')
    before=source(prior,original);after=source(current,selected)
    test.assertEqual(current.count(after),1,relative+':one exact changed Budget.read node')
    restored=current.replace(after,before,1)
    test.assertEqual(restored,prior,
        relative+':all other quota, pacing, hourly usage, reservation and cancellation bytes retained')
    parent.body[parent.body.index(selected)]=deepcopy(original)
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':no other provider or financial authority node changes')
    return prior


# The two fixed Pump recorder scopes were reached with diagnostics disabled:
# Supervisor forwarded the opt-in flag only to Pons and the source. Extend
# that exact existing tuple; every other environment, source and economic byte
# remains pinned before the original cooperative-drain/source guard chain.
PUMP_COST_ENVIRONMENT_REFERENCE='c69e45adb8f67a9e451aa4e5f7b62a8d8d0e465d'
PUMP_COST_ENVIRONMENT_SOURCE='meme_machine/operational/supervisor.py'
PUMP_COST_ENVIRONMENT_BEFORE='94c744ca18d83b4cacea3c4c7983369578184edfc6409df3f496c0b4a187a76c'
PUMP_COST_ENVIRONMENT_AFTER='63658a7ed37f03fa9ead8af863ead8d0f442f4356b8ec33c0c9a0571b1a1cb82'
PUMP_COST_ENVIRONMENT_OLD=(
    b"        if lane in ('pons','solana'):\n"
    b"            env['MM_OPERATION_COST_DIAGNOSTICS']='1' if os.environ.get('MM_OPERATION_COST_DIAGNOSTICS')=='1' else '0'\n")
PUMP_COST_ENVIRONMENT_NEW=(
    b"        if lane in ('pump','pons','solana'):\n"
    b"            env['MM_OPERATION_COST_DIAGNOSTICS']='1' if os.environ.get('MM_OPERATION_COST_DIAGNOSTICS')=='1' else '0'\n")


def pump_cost_environment_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=PUMP_COST_ENVIRONMENT_SOURCE:return current
    prior=subprocess.check_output(['git','show',PUMP_COST_ENVIRONMENT_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),PUMP_COST_ENVIRONMENT_BEFORE,
        relative+':exact pre-Pump diagnostic environment source')
    if current==prior:return prior
    test.assertEqual(hashlib.sha256(current).hexdigest(),PUMP_COST_ENVIRONMENT_AFTER,
        relative+':exact single-tuple Pump diagnostic environment successor')
    test.assertEqual(prior.count(PUMP_COST_ENVIRONMENT_OLD),1,relative+':one original fixed opt-in scope')
    test.assertEqual(current.count(PUMP_COST_ENVIRONMENT_NEW),1,relative+':one exact expanded fixed opt-in scope')
    restored=current.replace(PUMP_COST_ENVIRONMENT_NEW,PUMP_COST_ENVIRONMENT_OLD,1)
    test.assertEqual(restored,prior,
        relative+':all original opt-in semantics, environment, authority and lifecycle bytes retained')
    tree=ast.parse(current);old=ast.parse(prior)
    def environment(root):
        parent=next(n for n in root.body if isinstance(n,ast.ClassDef) and n.name=='Supervisor')
        return parent,next(n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name=='environment')
    parent,selected=environment(tree);_,original=environment(old)
    test.assertEqual(ast.dump(selected.args),ast.dump(original.args),relative+':unchanged environment interface')
    test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':only the declared environment node changes')
    parent.body[parent.body.index(selected)]=deepcopy(original)
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':all other source, financial and protection nodes retained')
    return prior


# TERM belongs to the source parent while it drains accepted decoder work.
# Pin the bounded, identity-checked descendant cleanup separately from every
# existing lane timeout, source drain, financial and strategy implementation.
SOURCE_PARENT_DRAIN_REFERENCE='80446ba3918b7ac820cde773bfcd72a8ef23466e'
SOURCE_PARENT_DRAIN_SOURCE='meme_machine/operational/supervisor.py'
SOURCE_PARENT_DRAIN_BEFORE='4aa0f4eec6aa02514c223d13211bd2b211f0985f7a462baa50a15ceb82771033'
SOURCE_PARENT_DRAIN_AFTER='94c744ca18d83b4cacea3c4c7983369578184edfc6409df3f496c0b4a187a76c'
SOURCE_PARENT_DRAIN_CHANGED=('start_services','recover_evidence','run','stop_process')


def source_parent_drain_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=SOURCE_PARENT_DRAIN_SOURCE:return current
    prior=subprocess.check_output(['git','show',SOURCE_PARENT_DRAIN_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),SOURCE_PARENT_DRAIN_BEFORE,
        relative+':exact source-parent drain predecessor')
    if current==prior:return prior
    current=pump_cost_environment_predecessor(test,relative,current)
    test.assertEqual(hashlib.sha256(current).hexdigest(),SOURCE_PARENT_DRAIN_AFTER,
        relative+':exact cooperative source-parent drain successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def method(root,name):
        parent=next(n for n in root.body if isinstance(n,ast.ClassDef) and n.name=='Supervisor')
        return parent,next(n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name==name)
    def source(body,selected):
        first=min(selected.lineno,*(n.lineno for n in selected.decorator_list)) if selected.decorator_list else selected.lineno
        return b''.join(body.splitlines(keepends=True)[first-1:selected.end_lineno])
    for name in ('stop_lanes','start_lane','environment','continuation_health','publish'):
        _,selected=method(tree,name);_,original=method(old,name)
        test.assertEqual(source(current,selected),source(prior,original),
            relative+':unchanged lane, protection or financial source '+name)
    restored=current
    for name in SOURCE_PARENT_DRAIN_CHANGED:
        parent,selected=method(tree,name);_,original=method(old,name)
        test.assertNotEqual(ast.dump(selected),ast.dump(original),
            relative+':explicit cooperative source lifecycle node '+name)
        selected_bytes=source(current,selected)
        test.assertEqual(restored.count(selected_bytes),1,relative+':one exact lifecycle node '+name)
        restored=restored.replace(selected_bytes,source(prior,original),1)
        parent.body[parent.body.index(selected)]=deepcopy(original)
    parent,added=method(tree,'_source_start_ticks')
    with test.assertRaises(StopIteration):method(old,'_source_start_ticks')
    test.assertEqual([ast.dump(n) for n in added.decorator_list],
        [ast.dump(ast.Name(id='staticmethod',ctx=ast.Load()))],
        relative+':source identity proof is a pure static process read')
    addition=source(current,added)+b'\n'
    test.assertEqual(restored.count(addition),1,relative+':one exact source process identity helper')
    restored=restored.replace(addition,b'',1);parent.body.remove(added)
    test.assertEqual(ast.dump(tree),ast.dump(old),
        relative+':all other source, strategy and accounting nodes retained')
    test.assertEqual(restored,prior,
        relative+':all other original bytes, timeouts, containment and financial safeguards retained')
    return prior


# Accounting and its dependent publication use one existing priority-2 owner
# turn. Accepted work keeps its cancellation ownership and one committed delta;
# ACK remains separate. Two fixed Pump costs only describe complete restoration.
# Pin each full source and reverse its exact named-node/constant delta before
# all previous strategy, financial, recovery and source assertions.
PUBLICATION_ACCOUNTING_REFERENCE='9ca64c5c46f666f9e95c80c41a7beb9d7e7a86a8'
PUBLICATION_ACCOUNTING_DELTAS={
    'meme_machine/solana_selective_source.py':(
        'f3391d7aca7c1f185131fabe51edfb0e5bf37a79a35046449b06e3d5c916030e',
        'c21b570ff602dd190ea8e305776dbbefeffc50f214bff4a92beb43374aa8aa4c',
        ('SelectiveSource.flush_delivery','SelectiveSource.publish_history',
         'SelectiveSource._complete_history_delivery')),
    'meme_machine/lanes/pump/runner.py':(
        'eaf902b1894232403bfb2715bf9a0b78bfc9d8b6635c3a796cd9f122c7aca5c5',
        '43fcb7e3608d67b20a0e4a02b5da74fbe8bac712e5ed0b60e46bdc3a3464356c',
        ('_startup_work',)),
    'meme_machine/runtime/operation_costs.py':(
        '510d3036869548e1284c625fa848da17d253633ccef050456f5ae3b73b757768',
        '27f1471a2465e30cda4b9906b37f75818d83df34027a2c7ebeeaa45e166e7b96',()),
}


def publication_accounting_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    reviewed=PUBLICATION_ACCOUNTING_DELTAS.get(relative)
    if reviewed is None:return current
    before,after,changed=reviewed
    prior=subprocess.check_output(['git','show',PUBLICATION_ACCOUNTING_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),before,
        relative+':exact integrated buffered-recovery predecessor')
    if current==prior:return prior
    current=cross_candidate_cold_predecessor(test,relative,current)
    test.assertEqual(hashlib.sha256(current).hexdigest(),after,
        relative+':exact accounting-publication turn and Pump-cost successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def node(root,name):
        parent=root
        for part in name.split('.')[:-1]:
            parent=next(n for n in parent.body if isinstance(n,ast.ClassDef) and n.name==part)
        return parent,next(n for n in parent.body
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name.split('.')[-1])
    def source(body,selected):
        return b''.join(body.splitlines(keepends=True)[selected.lineno-1:selected.end_lineno])
    restored=current
    if relative=='meme_machine/runtime/operation_costs.py':
        def names(root):
            return next(n for n in root.body if isinstance(n,ast.Assign) and len(n.targets)==1
                and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='NAMES')
        selected=names(tree);original=names(old)
        test.assertEqual([ast.literal_eval(n) for n in selected.value.elts[-2:]],
            ['pump.observed_candidates_restore','pump.observed_candidate_events'],
            relative+':only two fixed Pump diagnostic identities appended')
        normalized=deepcopy(selected);del normalized.value.elts[-2:]
        test.assertEqual(ast.dump(normalized),ast.dump(original),
            relative+':all original identifiers and ordering retained')
        addition=b"    'pump.observed_candidates_restore', 'pump.observed_candidate_events',\n"
        test.assertEqual(restored.count(addition),1,relative+':one exact constant-only addition')
        restored=restored.replace(addition,b'',1)
        tree.body[tree.body.index(selected)]=deepcopy(original)
    for name in changed:
        parent,selected=node(tree,name);_,original=node(old,name)
        selected_bytes=source(current,selected)
        test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':explicit reviewed node '+name)
        signature=deepcopy(selected.args)
        if name=='SelectiveSource.flush_delivery':
            test.assertEqual(signature.args[-1].arg,'after')
            test.assertEqual([ast.dump(n) for n in signature.defaults],[ast.dump(ast.Constant(value=None))],
                relative+':standalone delivery retains its absent publication default')
            del signature.args[-1];del signature.defaults[-1]
            commit=next(n for n in ast.walk(selected) if isinstance(n,ast.FunctionDef) and n.name=='commit')
            previous_commit=next(n for n in ast.walk(original) if isinstance(n,ast.FunctionDef) and n.name=='commit')
            conditional=commit.body[1]
            test.assertIsInstance(commit.body[0],ast.Nonlocal)
            test.assertEqual(commit.body[0].names,['committed'])
            test.assertEqual(ast.dump(conditional.test),ast.dump(ast.parse('pending and not committed',mode='eval').body))
            test.assertEqual([ast.dump(n) for n in conditional.body[:-1]],
                [ast.dump(n) for n in previous_commit.body],
                relative+':original delivery transaction and every charge remain unchanged')
            test.assertEqual(ast.dump(conditional.body[-1]),ast.dump(ast.parse('committed=True').body[0]),
                relative+':mark only after the original transaction COMMIT returns')
        test.assertEqual(ast.dump(signature),ast.dump(original.args),relative+':all original call interfaces retained '+name)
        if name=='_startup_work':
            normalized=selected_bytes.replace(b'    with operation(identity), ExitStack() as costs:\n',
                b'    with operation(identity):\n',1)
            addition=(b"        if identity in ('pump.observed_candidates_restore','pump.observed_candidate_events'):\n"
                b'            from meme_machine.runtime.operation_costs import operation as cost_operation\n'
                b'            costs.enter_context(cost_operation(identity))\n')
            test.assertEqual(normalized.count(addition),1,relative+':one two-identity cost scope')
            normalized=normalized.replace(addition,b'',1)
            test.assertEqual(normalized,source(prior,original),
                relative+':all calls, arguments, accounting replay and ownership bytes unchanged')
        elif name=='SelectiveSource.publish_history':
            normalized=selected_bytes.replace(b'                ready=time.monotonic();timing={}\n',
                b'                await self.flush_delivery() # Preserve the original accounting-before-publication fence.\n'
                b'                ready=time.monotonic();timing={}\n',1)
            normalized=normalized.replace(b'                more,startup,retry_at,published=await self.flush_delivery(publish)\n',
                b"                more,startup,retry_at,published=await self.work(publish,2,label='source_commit',component='history_publication')\n",1)
            test.assertEqual(normalized,source(prior,original),
                relative+':all background publication, timing and notification bytes unchanged')
        elif name=='SelectiveSource._complete_history_delivery':
            normalized=selected_bytes.replace(b'            def publish_exact(state):\n',
                b'            await self.flush_delivery()\n            def publish_exact(state):\n',1)
            normalized=normalized.replace(b'            published=await self.flush_delivery(publish_exact)\n',
                b"            published=await self.work(publish_exact,2,label='source_commit',component='history_publication')\n",1)
            test.assertEqual(normalized,source(prior,original),
                relative+':original exact-batch ACK, identities and publication predicates unchanged')
        test.assertEqual(restored.count(selected_bytes),1,relative+':one exact changed named node '+name)
        restored=restored.replace(selected_bytes,source(prior,original),1)
        parent.body[parent.body.index(selected)]=deepcopy(original)
    test.assertEqual(ast.dump(tree),ast.dump(old),
        relative+':every other source, economic, cancellation and scheduling node retained')
    test.assertEqual(restored,prior,
        relative+':every other original byte, priority, lease and authority predicate retained')
    return prior


# All-committed queues do not settle interrupted pre-feed buffered callbacks.
# Derive their observed interval from original closed/joined records and use
# the existing archive/FULL/ACK verifier. Earlier and future subscription gaps
# remain independently partitioned; no callback, drain or normal authority is
# inferred from completion of that bounded economic interval.
BUFFERED_PREJOIN_REFERENCE='eb94217fb64a69f5a889b23ba1f7c464a883f812'
BUFFERED_PREJOIN_SOURCE='meme_machine/solana_source_drain.py'
BUFFERED_PREJOIN_BEFORE='2c7d4a25f3220c75a1d249de8810eef0d96409bf9f35f62c478768b3c07329be'
BUFFERED_PREJOIN_AFTER='c908beab9e6b797a86674ed3035ecf1e9dda8b3c0cfb6d8a42366d7fe9839900'
BUFFERED_PREJOIN_CHANGED=('_economic_recovery_inputs','current_economic_recovery_descriptor',
    'verify_economic_recovery_descriptor')
BUFFERED_PREJOIN_ADDED=('_buffered_log_inputs','_buffered_log_partition')


BUFFERED_ORIGIN_REFERENCE='c159b290d57efae348dd235b052abb3101ae3f5a'
BUFFERED_ORIGIN_AFTER='c16a8f96c3688822735d113ba709b038d53ba9f9e1ca615e0ab5e6c2749eed7d'


def buffered_origin_predecessor(test,relative,current):
    """Reverse only the exact origin geometry; every old guard still runs."""
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=BUFFERED_PREJOIN_SOURCE:return current
    prior=subprocess.check_output(['git','show',BUFFERED_ORIGIN_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),BUFFERED_PREJOIN_AFTER)
    if current==prior:return prior
    test.assertEqual(hashlib.sha256(current).hexdigest(),BUFFERED_ORIGIN_AFTER)
    comment=(b'            # Published prefixes may add same-floor residuals beside the audit\n'
        b'            # origin. Only a row spanning the whole obligation can be its origin.\n')
    before=(b"                WHERE scope=? AND lo=? AND created<=? AND reason='candidate_live_disconnect_or_filter_rebuild'\n"
        b"                ORDER BY id DESC LIMIT 2''',(scope,floor,selected[2])).fetchall()\n")
    after=(b'                WHERE scope=? AND lo=? AND (hi IS NULL OR hi>=?) AND created<=?\n'
        b"                    AND reason='candidate_live_disconnect_or_filter_rebuild'\n"
        b"                ORDER BY id DESC LIMIT 2''',(scope,floor,hi,selected[2])).fetchall()\n")
    test.assertEqual(current.count(comment),1)
    test.assertEqual(current.count(after),1)
    restored=current.replace(comment,b'',1).replace(after,before,1)
    test.assertEqual(restored,prior,
        relative+':all uniqueness, original-handler, financial, cursor, FULL/ACK and partition bytes retained')
    return prior


def buffered_prejoin_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=BUFFERED_PREJOIN_SOURCE:return current
    prior=subprocess.check_output(['git','show',BUFFERED_PREJOIN_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),BUFFERED_PREJOIN_BEFORE,
        relative+':exact original queue/preparation recovery predecessor')
    if current==prior:return prior
    current=buffered_origin_predecessor(test,relative,current)
    test.assertEqual(hashlib.sha256(current).hexdigest(),BUFFERED_PREJOIN_AFTER,
        relative+':exact all-committed buffered observation recovery successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def function(root,name):
        return next(n for n in root.body if isinstance(n,ast.FunctionDef) and n.name==name)
    def source(body,selected):
        return b''.join(body.splitlines(keepends=True)[selected.lineno-1:selected.end_lineno])
    for name in ('_economic_failed_inputs','_preparation_failed_inputs','_economic_descriptor',
            '_economic_descriptor_rows','preserve_economic_recovery_descriptor',
            '_session_economic_boundaries','_preserved_program_gap_observation',
            '_preserved_economic_replay_observation','_preserved_prejoin_observation',
            '_historical_observation_record','_require_observation_funding_closed',
            'retained_source_drain','begin_source_observation','publish_source_drain'):
        test.assertEqual(source(current,function(tree,name)),source(prior,function(old,name)),
            relative+':unchanged original recovery, startup or financial authority '+name)
    reversals={
        '_economic_recovery_inputs':((
            b'    if validator is _economic_failed_inputs and isinstance(raw,str) and _committed_census(_retained_census(raw)):\n'
            b'        validator=_buffered_log_inputs\n',b''),),
        'current_economic_recovery_descriptor':((
            b"        if descriptor.get('input_class')=='COMMITTED_BUFFERED_LOGS':\n"
            b"            actual=_economic_recovery_inputs(db,raw,handlers,descriptor['session_observation_id'],\n"
            b"                expected_origins=descriptor['gap_origins'])\n"
            b"        else:actual=_economic_recovery_inputs(db,raw,handlers,descriptor['session_observation_id'])\n",
            b"        actual=_economic_recovery_inputs(db,raw,handlers,descriptor['session_observation_id'])\n"),),
        'verify_economic_recovery_descriptor':(
            (b'    buffered_partitions={}\n',b''),
            (b"            if descriptor.get('input_class')=='COMMITTED_BUFFERED_LOGS':\n"
             b'                buffered_partitions[family]=_buffered_log_partition(db,shared,descriptor,family,full,points_cover)\n',b''),
            (b'    result=dict(reference=reference,descriptor=descriptor,economic_interval_recovered=True,\n',
             b'    return dict(reference=reference,descriptor=descriptor,economic_interval_recovered=True,\n'),
            (b'    if buffered_partitions:\n'
             b"        result.update(input_class='COMMITTED_BUFFERED_LOGS',scope='OBSERVED_BUFFERED_INTERVAL_ONLY',\n"
             b"            economic_tail_scope='OBSERVED_INTERVAL_AFTER_ARCHIVE_UPPER_ONLY',\n"
             b'            full_subscription_completeness_claim=False,retained_partitions=buffered_partitions)\n'
             b'    return result\n',b'')),
    }
    restored=current
    for name in BUFFERED_PREJOIN_CHANGED:
        selected=function(tree,name);original=function(old,name)
        selected_bytes=source(current,selected);normalized=selected_bytes
        test.assertNotEqual(ast.dump(selected),ast.dump(original),
            relative+':explicit bounded buffered-input integration '+name)
        for reviewed,previous in reversals[name]:
            test.assertEqual(normalized.count(reviewed),1,relative+':one exact approved byte delta '+name)
            normalized=normalized.replace(reviewed,previous,1)
        test.assertEqual(normalized,source(prior,original),
            relative+':every original descriptor, archive, FULL, ACK and false-completion predicate retained '+name)
        test.assertEqual(restored.count(selected_bytes),1,relative+':one exact changed named node '+name)
        restored=restored.replace(selected_bytes,normalized,1)
        tree.body[tree.body.index(selected)]=deepcopy(original)
    additions=[]
    for name in BUFFERED_PREJOIN_ADDED:
        selected=function(tree,name);additions.append(selected);tree.body.remove(selected)
        with test.assertRaises(StopIteration):function(old,name)
    first=min(n.lineno for n in additions);last=max(n.end_lineno for n in additions)
    addition=b''.join(current.splitlines(keepends=True)[first-1:last])+b'\n\n'
    test.assertEqual(restored.count(addition),1,relative+':one exact bounded buffered-input/partition block')
    restored=restored.replace(addition,b'',1)
    test.assertEqual(ast.dump(tree),ast.dump(old),
        relative+':all other financial, historical, cursor and startup nodes retained')
    test.assertEqual(restored,prior,
        relative+':every other original source byte and authority predicate retained')
    return prior


# One authenticated pure-preparation failure has independently closed/joined
# session receipts. Its terminal-unavailable flag stays true; the existing
# archive/FULL/ACK verifier still supplies all economic recovery authority.
PREPARATION_REPLAY_REFERENCE='80446ba3918b7ac820cde773bfcd72a8ef23466e'
PREPARATION_REPLAY_SOURCE='meme_machine/solana_source_drain.py'
PREPARATION_REPLAY_BEFORE='a016bdbe09f2017f19f09126a948a561ab6afb6fcf96898d2ca432a03e59f83e'
PREPARATION_REPLAY_AFTER='2c7d4a25f3220c75a1d249de8810eef0d96409bf9f35f62c478768b3c07329be'
PREPARATION_REPLAY_CHANGED=('current_economic_recovery_descriptor','verify_economic_recovery_descriptor')
PREPARATION_REPLAY_ADDED=('_preparation_failed_inputs','_economic_recovery_inputs')
PREPARATION_REPLAY_CONSTANTS=('PREPARATION_RECOVERY_CENSUS','PREPARATION_RECOVERY_LEDGER',
    'PREPARATION_RECOVERY_SESSION','PREPARATION_RECOVERY_OBSERVATIONS',
    'PREPARATION_RECOVERY_HEADS','PREPARATION_RECOVERY_GAPS')


def preparation_replay_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=PREPARATION_REPLAY_SOURCE:return current
    prior=subprocess.check_output(['git','show',PREPARATION_REPLAY_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),PREPARATION_REPLAY_BEFORE,
        relative+':exact independently closed preparation-failure predecessor')
    if current==prior:return prior
    current=buffered_prejoin_predecessor(test,relative,current)
    test.assertEqual(hashlib.sha256(current).hexdigest(),PREPARATION_REPLAY_AFTER,
        relative+':exact preparation-failure replay-input successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def function(root,name):
        return next(n for n in root.body if isinstance(n,ast.FunctionDef) and n.name==name)
    def source(body,selected):
        return b''.join(body.splitlines(keepends=True)[selected.lineno-1:selected.end_lineno])
    for name in ('_economic_failed_inputs','_economic_descriptor','_economic_descriptor_rows',
            'preserve_economic_recovery_descriptor','_session_economic_boundaries',
            '_preserved_program_gap_observation','_preserved_economic_replay_observation',
            '_preserved_prejoin_observation','_historical_observation_record',
            '_require_observation_funding_closed','retained_source_drain'):
        test.assertEqual(source(current,function(tree,name)),source(prior,function(old,name)),
            relative+':unchanged original recovery or financial authority bytes '+name)
    class OriginalValidator(ast.NodeTransformer):
        def visit_Name(self,value):
            if value.id=='_economic_recovery_inputs':value.id='_economic_failed_inputs'
            return value
    restored=current
    dispatches=0
    for name in PREPARATION_REPLAY_CHANGED:
        selected=function(tree,name);original=function(old,name)
        test.assertNotEqual(ast.dump(selected),ast.dump(original),
            relative+':explicit exact-input validator selection '+name)
        normalization=deepcopy(selected)
        dispatches+=sum(isinstance(n,ast.Name) and n.id=='_economic_recovery_inputs' for n in ast.walk(normalization))
        if name=='current_economic_recovery_descriptor':
            branch=ast.parse("if checksum==PREPARATION_RECOVERY_CENSUS:\n"
                "    return _preparation_failed_inputs(db,raw,handlers,PREPARATION_RECOVERY_OBSERVATIONS['closed'][0])").body[0]
            matches=[n for n in normalization.body if ast.dump(n)==ast.dump(branch)]
            test.assertEqual(len(matches),1,relative+':one fixed authenticated receipt selection before bounded generic search')
            normalization.body.remove(matches[0])
        normalization=OriginalValidator().visit(normalization)
        test.assertEqual(ast.dump(normalization),ast.dump(original),
            relative+':all original FULL, ACK, descriptor and current-incident predicates retained '+name)
        selected_bytes=source(current,selected)
        test.assertEqual(restored.count(selected_bytes),1,relative+':one exact dispatch node '+name)
        restored=restored.replace(selected_bytes,source(prior,original),1)
        tree.body[tree.body.index(selected)]=deepcopy(original)
    test.assertEqual(dispatches,3,relative+':only three existing generic validator call sites dispatched')
    additions=[]
    for name in PREPARATION_REPLAY_CONSTANTS:
        matches=[n for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1
            and isinstance(n.targets[0],ast.Name) and n.targets[0].id==name]
        test.assertEqual(len(matches),1,relative+':one fixed incident constant '+name)
        test.assertFalse(any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name
            for t in n.targets) for n in old.body),relative+':new constant only '+name)
        additions.append(matches[0]);tree.body.remove(matches[0])
    for name in PREPARATION_REPLAY_ADDED:
        selected=function(tree,name);additions.append(selected);tree.body.remove(selected)
        with test.assertRaises(StopIteration):function(old,name)
    first=min(n.lineno for n in additions);last=max(n.end_lineno for n in additions)
    addition=b''.join(current.splitlines(keepends=True)[first-1:last])+b'\n\n'
    test.assertEqual(restored.count(addition),1,relative+':one bounded exact preparation-input implementation')
    restored=restored.replace(addition,b'',1)
    test.assertEqual(ast.dump(tree),ast.dump(old),
        relative+':all other historical, financial, source and cursor authority nodes retained')
    test.assertEqual(restored,prior,
        relative+':every other original byte and safety predicate retained')
    return prior


# The exact cb34 incident interrupted a log callback before economic admission.
# Its original terminal failure flags and unreturned callback remain evidence;
# original same-origin gaps or FULL/ACK coverage partition every required slot.
# Pin this separate observation proof without relaxing lost economic queues,
# ordinary startup, financial authority or the existing funding-closed guard.
PREJOIN_SOURCE_REFERENCE='d66af963d64d3c02099d8e9fe3a94c53ec38c584'
PREJOIN_SOURCE='meme_machine/solana_source_drain.py'
PREJOIN_SOURCE_BEFORE='0cb2fe722ba128506a3355bc88b3c647f4c9a25013bdf260ca6ec0684c3e29d2'
PREJOIN_SOURCE_AFTER='a016bdbe09f2017f19f09126a948a561ab6afb6fcf96898d2ca432a03e59f83e'
PREJOIN_SOURCE_CHANGED=('_session_economic_boundaries','historical_observation_boundary',
    'begin_source_observation','publish_source_drain')
PREJOIN_SOURCE_CONSTANTS=('PREJOIN_OBSERVATION_SHA256','PREJOIN_HANDLER_SHA256',
    'PREJOIN_SESSION_SHA256','PREJOIN_SESSION_OBSERVATION_ID','PREJOIN_SESSION',
    'PREJOIN_GAP_ORIGINS','PREJOIN_NATIVE_HEADS')


def prejoin_source_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=PREJOIN_SOURCE:return current
    prior=subprocess.check_output(['git','show',PREJOIN_SOURCE_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),PREJOIN_SOURCE_BEFORE,
        relative+':exact prejoin-observation predecessor')
    if current==prior:return prior
    current=preparation_replay_predecessor(test,relative,current)
    test.assertEqual(hashlib.sha256(current).hexdigest(),PREJOIN_SOURCE_AFTER,
        relative+':exact prejoin-observation successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def function(root,name):
        return next(n for n in root.body if isinstance(n,ast.FunctionDef) and n.name==name)
    # These authority predicates remain byte-for-byte, including the existing
    # strict CANDIDATE_QUEUE disposition rather than the distinct prejoin case.
    for name in ('_economic_failed_inputs','verify_economic_recovery_descriptor',
            '_preserved_program_gap_observation','_preserved_economic_replay_observation',
            '_historical_observation_record','_require_observation_funding_closed','retained_source_drain'):
        test.assertEqual(ast.get_source_segment(current.decode(),function(tree,name)),
            ast.get_source_segment(prior.decode(),function(old,name)),relative+':unchanged authority bytes '+name)
    for name in PREJOIN_SOURCE_CHANGED:
        selected=function(tree,name);original=function(old,name)
        test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':explicit observation handoff '+name)
        tree.body[tree.body.index(selected)]=deepcopy(original)
    added=function(tree,'_preserved_prejoin_observation');tree.body.remove(added)
    with test.assertRaises(StopIteration):function(old,'_preserved_prejoin_observation')
    for name in PREJOIN_SOURCE_CONSTANTS:
        def matching(root):
            return [n for n in root.body if isinstance(n,ast.Assign) and len(n.targets)==1
                and isinstance(n.targets[0],ast.Name) and n.targets[0].id==name]
        matches=matching(tree)
        test.assertEqual(len(matches),1,relative+':one explicit incident identity '+name)
        test.assertEqual(matching(old),[],relative+':new incident identity only '+name)
        tree.body.remove(matches[0])
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':all other historical, financial and native source retained')
    return prior


# A new interrupted rolling session binds its own immutable census, handler
# ledger, native heads and original session observation before archive work.
# Exact FULL consumer receipts/ACKs and gap-aware coverage can prove recovered
# economics without declaring any interrupted queue or callback completed.
# Reverse only the reviewed session-proof nodes before every older source guard.
SESSION_ECONOMIC_RECOVERY_REFERENCE='2e74c44db35da58cce22038775fb405b7041e168'
SESSION_ECONOMIC_RECOVERY_SOURCE='meme_machine/solana_source_drain.py'
SESSION_ECONOMIC_RECOVERY_BEFORE='b134816293702970d42a93e2108067764c52cd1c4641c292ce7e1c2024d031c1'
SESSION_ECONOMIC_RECOVERY_AFTER='0cb2fe722ba128506a3355bc88b3c647f4c9a25013bdf260ca6ec0684c3e29d2'
SESSION_ECONOMIC_RECOVERY_CHANGED=(
    '_preserved_program_gap_observation','historical_observation_boundary',
    'begin_source_observation','publish_source_drain',
)
SESSION_ECONOMIC_RECOVERY_ADDED=(
    '_economic_db','_economic_require','_economic_descriptor_rows','_economic_descriptor',
    '_economic_failed_inputs','current_economic_recovery_descriptor',
    'preserve_economic_recovery_descriptor','verify_economic_recovery_descriptor',
    '_session_economic_boundaries',
)
SESSION_ECONOMIC_RECOVERY_PRIORS={
    'f23c5307d7340d93187a94543790503c5ce3622a91b684de326c5ba869747da0':
        'c7c1f6bca52e5d53eb49aed75b6e245f7bbbb225',
    'b3b67f0bee582fc0a0054a6b591dd28ddb3b867df4a65b78604675cfb944bfba':
        'd06e37a050847e607db5d5649a00535beb1a58ee',
}


def session_economic_recovery_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=SESSION_ECONOMIC_RECOVERY_SOURCE:return current
    prior=subprocess.check_output(['git','show',SESSION_ECONOMIC_RECOVERY_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),SESSION_ECONOMIC_RECOVERY_BEFORE,
        relative+':exact independent-session recovery predecessor')
    if current==prior:return prior
    checksum=hashlib.sha256(current).hexdigest()
    if checksum in SESSION_ECONOMIC_RECOVERY_PRIORS:
        # Older tests still compare these exact immutable intermediates through
        # their original guards. Unknown source receives no path/name exemption.
        earlier=subprocess.check_output(['git','show',SESSION_ECONOMIC_RECOVERY_PRIORS[checksum]+':'+relative],cwd=ROOT)
        test.assertEqual(current,earlier,relative+':exact older recovery comparison source')
        return current
    current=prejoin_source_predecessor(test,relative,current)
    checksum=hashlib.sha256(current).hexdigest()
    test.assertEqual(checksum,SESSION_ECONOMIC_RECOVERY_AFTER,
        relative+':exact independent-session recovery successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def function(root,name):
        return next(n for n in root.body if isinstance(n,ast.FunctionDef) and n.name==name)
    for name in SESSION_ECONOMIC_RECOVERY_CHANGED:
        selected=function(tree,name);original=function(old,name)
        test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':explicit session-recovery node '+name)
        tree.body[tree.body.index(selected)]=deepcopy(original)
    for name in SESSION_ECONOMIC_RECOVERY_ADDED:
        selected=function(tree,name);tree.body.remove(selected)
        with test.assertRaises(StopIteration):function(old,name)
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':all other historical, financial and native source retained')
    return prior


# The protected preflight already freezes its original SQLite files. The paused
# lane proof may consume that same reader while its ordinary runtime connection,
# integrity, replay and obligation predicates remain unchanged. Pin this newly
# mandatory proof source without granting an economic or authority exemption.
FROZEN_PAUSED_READER_REFERENCE='a3ceb4951d045dc8f5b70dbd12340cfc46d6b8b7'
FROZEN_PAUSED_READER_SOURCE='meme_machine/operational/pause.py'
FROZEN_PAUSED_READER_BEFORE='e4b0edcad894a03e683472d3e40fcb853be45e4e99e2e3b7f22c3a9f5bbc0d08'
FROZEN_PAUSED_READER_AFTER='765516807ded08abc13b23f1e053d7c0198d4708a65d76473521cd7250f76247'


def frozen_paused_reader_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=FROZEN_PAUSED_READER_SOURCE:return current
    prior=subprocess.check_output(['git','show',FROZEN_PAUSED_READER_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),FROZEN_PAUSED_READER_BEFORE,
        relative+':exact protected paused-reader predecessor')
    if current==prior:return prior
    test.assertEqual(hashlib.sha256(current).hexdigest(),FROZEN_PAUSED_READER_AFTER,
        relative+':exact protected paused-reader successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def function(root):
        return next(n for n in root.body if isinstance(n,ast.FunctionDef) and n.name=='assert_clear')
    selected=function(tree);original=function(old)
    test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':explicit frozen-reader injection only')
    tree.body[tree.body.index(selected)]=deepcopy(original)
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':all other financial, replay and paused-lane source retained')
    return prior


# The authenticated AWS timeline located 410 seconds in candidate event reads.
# Reuse only one unchanged cold archive within an explicitly cancellable read;
# fresh canonical/ref hashes, record digests and all ordinary paths stay pinned.
PUMP_RESTORE_ARCHIVE_REUSE_REFERENCE='1c24c2f9c805a5e147660408aeda8fcd668f00c4'
PUMP_RESTORE_ARCHIVE_REUSE_SOURCE='meme_machine/runtime/candidate_history.py'
PUMP_RESTORE_ARCHIVE_REUSE_BEFORE='a2eead063a65bf3e56ca112484a9e8fc452e067d3297060e0916c797015d5010'
PUMP_RESTORE_ARCHIVE_REUSE_AFTER='2b04eeac6590d5aebdf90b3956dde1c283b8a0946365339d45beb7382ae31919'


def pump_restore_archive_reuse_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=PUMP_RESTORE_ARCHIVE_REUSE_SOURCE:return current
    prior=subprocess.check_output(['git','show',PUMP_RESTORE_ARCHIVE_REUSE_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),PUMP_RESTORE_ARCHIVE_REUSE_BEFORE,
        relative+':exact operation-local cold archive predecessor')
    if current==prior:return prior
    current=cross_candidate_cold_predecessor(test,relative,current)
    test.assertEqual(hashlib.sha256(current).hexdigest(),PUMP_RESTORE_ARCHIVE_REUSE_AFTER,
        relative+':exact explicitly cancellable archive-reuse successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def method(root,name):
        parent=next(n for n in root.body if isinstance(n,ast.ClassDef) and n.name=='CandidateHistory')
        return parent,next(n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name==name)
    def source(body,selected):
        return b''.join(body.splitlines(keepends=True)[selected.lineno-1:selected.end_lineno])
    for name in ('_reference_path','_startup_read','candidates','event','observe','append_event',
            'checkpoint','_install_schema','transaction'):
        _,selected=method(tree,name);_,original=method(old,name)
        test.assertEqual(source(current,selected),source(prior,original),
            relative+':unchanged ordinary history or authoritative source '+name)
    restored=current
    for name in ('_reference_body','events'):
        parent,selected=method(tree,name);_,original=method(old,name)
        test.assertNotEqual(ast.dump(selected),ast.dump(original),
            relative+':explicit bounded startup archive-reuse node '+name)
        signature=deepcopy(selected.args)
        if name=='_reference_body':
            test.assertEqual([n.arg for n in signature.kwonlyargs[-2:]],['_archive_cache','_check'],
                relative+':only operation-local private reader context added')
            test.assertEqual([ast.dump(n) for n in signature.kw_defaults[-2:]],
                [ast.dump(ast.Constant(value=None)),ast.dump(ast.Constant(value=None))],
                relative+':ordinary canonical reads retain absent cache and cancellation context')
            del signature.kwonlyargs[-2:];del signature.kw_defaults[-2:]
        test.assertEqual(ast.dump(signature),ast.dump(original.args),
            relative+':all original calling conventions retained '+name)
        selected_bytes=source(current,selected)
        test.assertEqual(restored.count(selected_bytes),1,relative+':one exact reviewed read node '+name)
        restored=restored.replace(selected_bytes,source(prior,original),1)
        parent.body[parent.body.index(selected)]=deepcopy(original)
    test.assertEqual(ast.dump(tree),ast.dump(old),
        relative+':all other financial, locator, event and strategy nodes retained')
    test.assertEqual(restored,prior,
        relative+':every other original source byte, predicate and integrity check retained')
    return prior


# Canonical cold reads must use the same restored-cohort locator validation as
# candidate history. Extract that unchanged reader, bind the actual main SQLite
# file for canonical reads, and reverse exactly those bytes before older guards.
CANONICAL_COLD_REFERENCE='bfcc69b47b98fd10dc2288d7c1c19665a5838d7a'
CANONICAL_COLD_DELTAS={
    'meme_machine/runtime/candidate_history.py':(
        '2ce0a79da9fc1dc571d8331a79c1db3d9ce9d840b480dcb939c16c13b9d157ff',
        'a2eead063a65bf3e56ca112484a9e8fc452e067d3297060e0916c797015d5010'),
    'meme_machine/solana_scoped_retirement.py':(
        '497e00a0b46c7d621c921325fddd2caf928a3a74feb22dbaa4519463e3a5b0c8',
        '51acb532a1c7b11c31f985a86a87e5fbd49d37f44129464acd21cced2f6afa23'),
}
CANONICAL_COLD_MAIN_BINDING=(
    b"        main=[row[2] for row in db.execute('PRAGMA database_list') if row[1]=='main']\n"
    b"        source=Path(main[0]) if len(main)==1 and main[0] else None\n"
    b"        candidate=None if source is None else source.with_name('solana-candidate-history.sqlite')\n"
    b"        packed=retained_reference_path(manifest[0],candidate_path=candidate,cold=True,\n"
    b"            canonical_path=source).read_bytes()\n"
)


def canonical_cold_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    reviewed=CANONICAL_COLD_DELTAS.get(relative)
    if reviewed is None:return current
    before,after=reviewed
    prior=subprocess.check_output(['git','show',CANONICAL_COLD_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),before,
        relative+':exact shared cold-locator predecessor')
    if current==prior:return prior
    current=pump_restore_archive_reuse_predecessor(test,relative,current)
    test.assertEqual(hashlib.sha256(current).hexdigest(),after,
        relative+':exact main-database-bound cold-locator successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def node(root,name):
        parent=root
        for part in name.split('.')[:-1]:
            parent=next(n for n in parent.body if isinstance(n,ast.ClassDef) and n.name==part)
        return parent,next(n for n in parent.body
            if isinstance(n,ast.FunctionDef) and n.name==name.split('.')[-1])
    def source(body,selected):
        return b''.join(body.splitlines(keepends=True)[selected.lineno-1:selected.end_lineno])
    if relative=='meme_machine/runtime/candidate_history.py':
        parent,selected=node(tree,'CandidateHistory._reference_path')
        _,original=node(old,'CandidateHistory._reference_path')
        _,added=node(tree,'retained_reference_path')
        with test.assertRaises(StopIteration):node(old,'retained_reference_path')
        test.assertEqual(ast.dump(selected.args),ast.dump(original.args),
            relative+':original candidate reader calling convention retained')
        test.assertEqual(ast.dump(selected.body[0]),ast.dump(original.body[0]),
            relative+':original candidate reader documentation retained')
        delegate=ast.parse('return retained_reference_path(value,candidate_path=self.path,cold=cold)').body[0]
        test.assertEqual([ast.dump(n) for n in selected.body[1:]],[ast.dump(delegate)],
            relative+':candidate reader delegates with its original context only')
        signature=ast.parse('def retained_reference_path(value,*,candidate_path,cold=False,canonical_path=None):pass').body[0]
        test.assertEqual(ast.dump(added.args),ast.dump(signature.args),
            relative+':canonical main-file binding is explicit and optional only for candidate callers')
        extracted=deepcopy(added.body[1:])
        binding=ast.parse('canonical_path is not None and canonical_path!=source',mode='eval').body
        guards=[n.test for n in extracted if isinstance(n,ast.If)
            and isinstance(n.test,ast.BoolOp) and isinstance(n.test.op,ast.Or)
            and any(ast.dump(value)==ast.dump(binding) for value in n.test.values)]
        test.assertEqual(len(guards),1,relative+':one explicit actual canonical-database predicate')
        guard=guards[0]
        matches=[value for value in guard.values if ast.dump(value)==ast.dump(binding)]
        test.assertEqual(len(matches),1,relative+':actual main-file binding cannot be duplicated or weakened')
        guard.values.remove(matches[0])
        class CandidatePath(ast.NodeTransformer):
            def visit_Attribute(self,value):
                if (isinstance(value.value,ast.Name) and value.value.id=='self'
                        and value.attr=='path'):
                    return ast.Name(id='candidate_path',ctx=ast.Load())
                return self.generic_visit(value)
        original_body=[CandidatePath().visit(deepcopy(n)) for n in original.body[1:]]
        test.assertEqual([ast.dump(n) for n in extracted],[ast.dump(n) for n in original_body],
            relative+':all original mode, cohort, path, symlink and file predicates extracted unchanged')
        added_bytes=source(current,added)+b'\n\n'
        test.assertEqual(current.count(added_bytes),1,relative+':one exact standalone locator helper')
        selected_bytes=source(current,selected);original_bytes=source(prior,original)
        test.assertEqual(current.count(selected_bytes),1,relative+':one exact candidate delegation')
        restored=current.replace(added_bytes,b'',1).replace(selected_bytes,original_bytes,1)
        parent.body[parent.body.index(selected)]=deepcopy(original);tree.body.remove(added)
        test.assertEqual(ast.dump(tree),ast.dump(old),
            relative+':all other candidate, index, event and economic nodes retained')
    else:
        _,selected=node(tree,'cold_record');_,original=node(old,'cold_record')
        test.assertNotEqual(ast.dump(selected),ast.dump(original),
            relative+':canonical cold read changes only its locator acquisition')
        test.assertEqual(current.count(CANONICAL_COLD_MAIN_BINDING),1,
            relative+':one exact main-file and sibling candidate-path binding')
        old_import=b'from .runtime.candidate_history import CandidateHistory\n'
        new_import=b'from .runtime.candidate_history import CandidateHistory,retained_reference_path\n'
        test.assertEqual(current.count(new_import),1,relative+':one exact shared reader import')
        test.assertEqual(prior.count(old_import),1,relative+':original candidate import retained')
        restored=current.replace(new_import,old_import,1).replace(CANONICAL_COLD_MAIN_BINDING,
            b'        packed=Path(manifest[0]).read_bytes()\n',1)
    test.assertEqual(restored,prior,
        relative+':every other original source byte, hash, bound, identity and financial predicate retained')
    return prior


# AWS exhausted the original restore-selection budget before one candidate.
# These three fixed indexes support its unchanged literal predicates/order;
# removing exactly those DDL lines must recover every original source byte.
PUMP_RESTORE_SELECTION_REFERENCE='cc4e0b00fc6d4f6f332bec0b1d646ca4121f11ba'
PUMP_RESTORE_SELECTION_SOURCE='meme_machine/runtime/candidate_history.py'
PUMP_RESTORE_SELECTION_BEFORE='c7afd0898e0582f45d8615bab2524ee0a4bf67f00e71e2b43f57899461b1a8cb'
PUMP_RESTORE_SELECTION_AFTER='2ce0a79da9fc1dc571d8331a79c1db3d9ce9d840b480dcb939c16c13b9d157ff'
PUMP_RESTORE_SELECTION_DDL=(
    b'        CREATE INDEX IF NOT EXISTS candidates_restore_order ON candidates(lane,first_observed,candidate);\n',
    b'        CREATE INDEX IF NOT EXISTS candidate_events_kind ON events(lane,candidate,kind);\n',
    b'        CREATE INDEX IF NOT EXISTS canonical_ref_kind ON canonical_event_refs(lane,candidate,kind);\n',
)


def pump_restore_selection_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=PUMP_RESTORE_SELECTION_SOURCE:return current
    prior=subprocess.check_output(['git','show',PUMP_RESTORE_SELECTION_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),PUMP_RESTORE_SELECTION_BEFORE,
        relative+':exact candidate-selection index predecessor')
    if current==prior:return prior
    current=canonical_cold_predecessor(test,relative,current)
    test.assertEqual(hashlib.sha256(current).hexdigest(),PUMP_RESTORE_SELECTION_AFTER,
        relative+':exact candidate-selection index successor')
    restored=current
    for ddl in PUMP_RESTORE_SELECTION_DDL:
        test.assertEqual(current.count(ddl),1,relative+':one exact restore-selection index')
        test.assertNotIn(ddl,prior,relative+':explicit new index only')
        restored=restored.replace(ddl,b'',1)
    test.assertEqual(restored,prior,relative+':all original selection, event, reference and financial bytes retained')
    tree=ast.parse(current);old=ast.parse(prior)
    def method(root):
        parent=next(n for n in root.body if isinstance(n,ast.ClassDef) and n.name=='CandidateHistory')
        return parent,next(n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name=='_install_schema')
    parent,selected=method(tree);_,original=method(old)
    test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':only schema index declarations differ')
    parent.body[parent.body.index(selected)]=deepcopy(original)
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':all other candidate/source authority nodes retained')
    return prior


# Restored $1,000 candidate references keep their original immutable locators.
# Pin the complete reviewed source and reverse only its known-location reader
# compatibility to cdcc0661 before the existing cancellation/economic guards.
# No history, checkpoint, canonical hash or monetary authority is exempted.
RETAINED_CANONICAL_REFERENCE='cdcc0661f59dc560655f4c09ac401e808b0ed9e2'
RETAINED_CANONICAL_SOURCE='meme_machine/runtime/candidate_history.py'
RETAINED_CANONICAL_BEFORE='99984085df2ceefb8e7a94dfd9eabb85674311fca9d9ae67584dc9415de35d45'
RETAINED_CANONICAL_AFTER='c7afd0898e0582f45d8615bab2524ee0a4bf67f00e71e2b43f57899461b1a8cb'
RETAINED_CANONICAL_ADDITIONS=(
    'import stat',
    "RETAINED_REFERENCE_LEGACY_ROOT=Path('/mnt/volume_nyc1_1790918115030/meme-machine-paper-shared-1000')",
    "RETAINED_REFERENCE_AWS_ROOT=Path('/srv/meme-machine/state/shared-1000')",
    "RETAINED_REFERENCE_EPOCH='paper-shared-1000-20261011T071207Z'",
)


def retained_canonical_predecessor(test,relative,current,*,allow_previous_layers=False):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=RETAINED_CANONICAL_SOURCE:return current
    prior=subprocess.check_output(['git','show',RETAINED_CANONICAL_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),RETAINED_CANONICAL_BEFORE,
        relative+':exact retained-reference predecessor')
    if current==prior:return prior
    if allow_previous_layers:
        # The original cancellation test independently compares its exact
        # 908ce9b7 predecessor too. Permit those immutable bytes only; no unknown
        # intermediate or modified source can bypass this outer reader guard.
        earlier=subprocess.check_output(['git','show',STARTUP_HISTORY_CANCEL_REFERENCE+':'+relative],cwd=ROOT)
        test.assertEqual(hashlib.sha256(earlier).hexdigest(),STARTUP_HISTORY_CANCEL_DELTAS[relative][0],
            relative+':exact older cancellation predecessor')
        if current==earlier:return current
    current=pump_restore_selection_predecessor(test,relative,current)
    test.assertEqual(hashlib.sha256(current).hexdigest(),RETAINED_CANONICAL_AFTER,
        relative+':exact retained-reference successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def method(root,name):
        parent=next(n for n in root.body if isinstance(n,ast.ClassDef) and n.name=='CandidateHistory')
        return parent,next(n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name==name)
    parent,selected=method(tree,'_reference_body');_,original=method(old,'_reference_body')
    test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':explicit reference reader delta')
    parent.body[parent.body.index(selected)]=deepcopy(original)
    parent,added=method(tree,'_reference_path');parent.body.remove(added)
    with test.assertRaises(StopIteration):method(old,'_reference_path')
    for source in RETAINED_CANONICAL_ADDITIONS:
        addition=ast.parse(source).body[0]
        matches=[n for n in tree.body if ast.dump(n)==ast.dump(addition)]
        test.assertEqual(len(matches),1,relative+':one exact retained-reference locator addition')
        test.assertNotIn(ast.dump(addition),[ast.dump(n) for n in old.body])
        tree.body.remove(matches[0])
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':all other canonical, financial and strategy source retained')
    return prior


# Exact first-failure attribution and Pons startup-read cancellation only.
# Reverse these four already-guarded sources to A14 before the previous source
# layers; candidate authority, pruning, accounting and economics remain pinned.
NATIVE_STARTUP_FAILURE_REFERENCE='a14a182221be4dd6abde21081b1a1da40181cdf4'
NATIVE_STARTUP_FAILURE_DELTAS={
    'meme_machine/runtime/status.py':(
        '7c819b3b0c5e3ee56984e021a851466bd12bb7a8ace30ce6d952d12be32575e3',
        'e8c112aa574cbb94a7342b1572af4c6dded71a09117bfb82215ee3c6612835ea',
        ('operation',),('native_failure',),('_FAILURE_CLASSES',)),
    'meme_machine/lanes/pons/pons_selective_cohort.py':(
        '4209107e6eb53bdb32eeb33ae1a3addb47ff4ca5a1ee298d5509fbb46e5d6ad7',
        '4d6851b400f75d760cee7a6954da38917aa3fc879a9ccbe6cbdcf43148c6ed3a',
        ('run',),(),()),
    'meme_machine/runtime/robinhood/pons.py':(
        '3622c77c59aed69fb9358a88a92522b5a7ee53849ec3f6be6f10b119669c8f93',
        '52defbb90f754e7b2ea88e4527bf7bdc30d6251854f89a37f52dabbb70a931f0',
        ('Broker.__init__','Broker._renew_retained_interpretation'),(),()),
    'meme_machine/runtime/storage.py':(
        '0cbe6ea56ed5eba9bc9e2ba895d1dcb0cab569a4c7d13b3f7b5b31f39ee31e9e',
        '847623ca28c595a49431f5c45c1f3de3f15bc16b86d623b52338c04c0097cd18',
        ('audit_ring','_audit_ring'),('_audit_boundary',),('import sqlite3',)),
}


def native_startup_failure_predecessor(test,relative,current,*,allow_previous_layers=False):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    current=session_economic_recovery_predecessor(test,relative,current)
    current=retained_canonical_predecessor(test,relative,current,
        allow_previous_layers=allow_previous_layers)
    reviewed=NATIVE_STARTUP_FAILURE_DELTAS.get(relative)
    if reviewed is None:return current
    before,after,changed,added,top_additions=reviewed
    prior=subprocess.check_output(['git','show',NATIVE_STARTUP_FAILURE_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),before,relative+':exact first-failure repair predecessor')
    if current==prior:return prior
    current_hash=hashlib.sha256(current).hexdigest()
    if allow_previous_layers and current_hash!=after:
        # Only exact immutable predecessors already used by the original guards
        # may pass to their own comparisons. Unknown bytes always fail here.
        references={
            'meme_machine/runtime/status.py':(STARTUP_HISTORY_CANCEL_REFERENCE,),
            'meme_machine/lanes/pons/pons_selective_cohort.py':(
                STARTUP_HISTORY_CANCEL_REFERENCE,PONS_DISCOVERY_REFERENCE,OPERATION_COST_REFERENCE,
                COHORT_AUTHORITY_REFERENCE,OPPORTUNITY_BASE),
            'meme_machine/runtime/robinhood/pons.py':(
                RALLY_BASE,OBSERVATION_FOLLOWUP_REFERENCE,COHORT_AUTHORITY_REFERENCE,OPPORTUNITY_BASE),
            'meme_machine/runtime/storage.py':(OPPORTUNITY_BASE,),
        }
        for reference in references[relative]:
            earlier=subprocess.check_output(['git','show',reference+':'+relative],cwd=ROOT)
            if current==earlier:return current
    test.assertEqual(current_hash,after,relative+':exact first-failure repair successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def node(root,name):
        parent=root
        for part in name.split('.')[:-1]:
            parent=next(n for n in parent.body if isinstance(n,ast.ClassDef) and n.name==part)
        return parent,next(n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name==name.split('.')[-1])
    for name in changed:
        parent,selected=node(tree,name);_,original=node(old,name)
        test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':explicit changed node '+name)
        parent.body[parent.body.index(selected)]=deepcopy(original)
    for name in added:
        parent,selected=node(tree,name);parent.body.remove(selected)
        with test.assertRaises(StopIteration):node(old,name)
    for source in top_additions:
        if source=='_FAILURE_CLASSES':
            matches=[n for n in tree.body if isinstance(n,ast.Assign)
                and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id==source]
            test.assertFalse(any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==source
                for t in n.targets) for n in old.body),relative+':new fixed exception allowlist only')
        else:
            addition=ast.parse(source).body[0]
            matches=[n for n in tree.body if ast.dump(n)==ast.dump(addition)]
            test.assertNotIn(ast.dump(addition),[ast.dump(n) for n in old.body])
        test.assertEqual(len(matches),1,relative+':one explicit top-level addition')
        tree.body.remove(matches[0])
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':all other safety and economic source retained')
    return prior


# A partial harvest's native_sync already performs its fresh monetary replay
# before ACK. Pin only the reviewed removal of the immediately duplicate
# replay; every other monitor, financial, strategy and source byte stays pinned.
SURVIVOR_MONITOR_REPLAY_REFERENCE='be26e3a8793686cec229fb51ddb6314569da7949'
SURVIVOR_MONITOR_REPLAY_SOURCE='meme_machine/runtime/survivor_commit.py'
SURVIVOR_MONITOR_REPLAY_BEFORE='01f8234ee4e039c7661238f604fdcc6cc65512612ccb606af69f9967c6ee9f31'
SURVIVOR_MONITOR_REPLAY_AFTER='68c1256edccacecf35e23afe3ddcc0cd914123dd66e14534eeb3ec6cadd9fcca'
SURVIVOR_MONITOR_REPLAY_OLD_BLOCK=(
    b"    book.replay()\n"
    b"    if native_action=='partial_harvest':native_sync(book,sleeve,identity)\n")
SURVIVOR_MONITOR_REPLAY_NEW_BLOCK=(
    b"    if native_action=='partial_harvest' and sleeve is not None:\n"
    b"        # native_sync independently replays this committed harvest before ACK.\n"
    b"        native_sync(book,sleeve,identity)\n"
    b"    else:book.replay()\n")


def survivor_monitor_replay_predecessor(test,relative,current,*,allow_previous_layers=False):
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=SURVIVOR_MONITOR_REPLAY_SOURCE:return current
    prior=subprocess.check_output(['git','show',SURVIVOR_MONITOR_REPLAY_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),SURVIVOR_MONITOR_REPLAY_BEFORE,
        relative+':exact monitor replay predecessor')
    if current==prior:return prior
    current_hash=hashlib.sha256(current).hexdigest()
    if allow_previous_layers and current_hash==rally_manifest(test)['files'][relative]['before_sha256']:
        earlier=subprocess.check_output(['git','show',RALLY_BASE+':'+relative],cwd=ROOT)
        test.assertEqual(current,earlier,relative+':exact older rally intermediate')
        return current
    test.assertEqual(current_hash,SURVIVOR_MONITOR_REPLAY_AFTER,relative+':exact monitor replay successor')
    test.assertEqual(current.count(SURVIVOR_MONITOR_REPLAY_NEW_BLOCK),1,relative+':one exact post-harvest replay delta')
    restored=current.replace(SURVIVOR_MONITOR_REPLAY_NEW_BLOCK,SURVIVOR_MONITOR_REPLAY_OLD_BLOCK,1)
    test.assertEqual(restored,prior,relative+':all other monitor, financial and strategy bytes retained')
    return prior


# Authenticated archive economics and FULL consumer proofs can establish this
# exact failed session's funding-closed observation boundary. Preserve its false
# queue census, historical callbacks and unavailable tail. Pin the whole source
# and reverse only this reviewed delta before every older recovery guard.
RECOVERED_ECONOMIC_BOUNDARY_REFERENCE='c7c1f6bca52e5d53eb49aed75b6e245f7bbbb225'
RECOVERED_ECONOMIC_BOUNDARY_SOURCE='meme_machine/solana_source_drain.py'
RECOVERED_ECONOMIC_BOUNDARY_BEFORE='f23c5307d7340d93187a94543790503c5ce3622a91b684de326c5ba869747da0'
RECOVERED_ECONOMIC_BOUNDARY_AFTER='b134816293702970d42a93e2108067764c52cd1c4641c292ce7e1c2024d031c1'
RECOVERED_ECONOMIC_BOUNDARY_ASSIGNMENTS=(
    'ECONOMIC_REPLAY_OBSERVATION_SHA256','ECONOMIC_REPLAY_SESSION_SHA256','ECONOMIC_REPLAY_JOBS',
    'ECONOMIC_REPLAY_NATIVE_HASH','ECONOMIC_REPLAY_NATIVE_CENSUS')


def recovered_economic_boundary_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=RECOVERED_ECONOMIC_BOUNDARY_SOURCE:return current
    current=session_economic_recovery_predecessor(test,relative,current)
    prior=subprocess.check_output(['git','show',RECOVERED_ECONOMIC_BOUNDARY_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),RECOVERED_ECONOMIC_BOUNDARY_BEFORE,
        relative+':exact economic-boundary predecessor')
    if current==prior:return prior
    test.assertEqual(hashlib.sha256(current).hexdigest(),RECOVERED_ECONOMIC_BOUNDARY_AFTER,
        relative+':exact economic-boundary successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def function(root,name):
        return next(n for n in root.body if isinstance(n,ast.FunctionDef) and n.name==name)
    for name in ('historical_observation_boundary','begin_source_observation'):
        selected=function(tree,name);original=function(old,name)
        test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':explicit economic-boundary node '+name)
        tree.body[tree.body.index(selected)]=deepcopy(original)
    added=function(tree,'_preserved_economic_replay_observation');tree.body.remove(added)
    with test.assertRaises(StopIteration):function(old,'_preserved_economic_replay_observation')
    for name in RECOVERED_ECONOMIC_BOUNDARY_ASSIGNMENTS:
        def matching(root):
            return [n for n in root.body if isinstance(n,ast.Assign) and len(n.targets)==1
                and isinstance(n.targets[0],ast.Name) and n.targets[0].id==name]
        matches=matching(tree)
        test.assertEqual(len(matches),1,relative+':one exact recovered-session identity '+name)
        test.assertEqual(matching(old),[],relative+':explicit recovered-session addition '+name)
        tree.body.remove(matches[0])
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':all other recovery, financial and strategy source retained')
    return prior


# Preserve the exact failed program-log observation without declaring its
# callback complete. This one-file boundary delta reverses to D06 before any
# earlier guard runs; its entire financial/source mutation surface stays pinned.
PROGRAM_GAP_OBSERVATION_REFERENCE='d06e37a050847e607db5d5649a00535beb1a58ee'
PROGRAM_GAP_OBSERVATION_SOURCE='meme_machine/solana_source_drain.py'
PROGRAM_GAP_OBSERVATION_BEFORE='b3b67f0bee582fc0a0054a6b591dd28ddb3b867df4a65b78604675cfb944bfba'
PROGRAM_GAP_OBSERVATION_AFTER=RECOVERED_ECONOMIC_BOUNDARY_AFTER
PROGRAM_GAP_OBSERVATION_LAYER_AFTER='f23c5307d7340d93187a94543790503c5ce3622a91b684de326c5ba869747da0'
PROGRAM_GAP_OBSERVATION_ADDITIONS=(
    "PROGRAM_GAP_OBSERVATION_SHA256='948743b18d0a33cc85391d07ea4a4ae9dad34110c169ca95945a04473d6db228'",
    "PROGRAM_GAP_HANDLER_SHA256='29f00e3d71c40e1d306f50263b84f1ec25e455e20d112a5f04fdef25293d0fb0'",
    "PROGRAM_GAP_SESSION_SHA256='886dc272c37139e53dac962fda1473fc6eca4e8b2daf462495cb50509a831333'",
)


def program_gap_observation_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=PROGRAM_GAP_OBSERVATION_SOURCE:return current
    current=session_economic_recovery_predecessor(test,relative,current)
    prior=subprocess.check_output(['git','show',PROGRAM_GAP_OBSERVATION_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),PROGRAM_GAP_OBSERVATION_BEFORE,
        relative+':exact preserved-program-gap predecessor')
    if current==prior:return prior
    current=recovered_economic_boundary_predecessor(test,relative,current)
    test.assertEqual(hashlib.sha256(current).hexdigest(),PROGRAM_GAP_OBSERVATION_LAYER_AFTER,
        relative+':exact preserved-program-gap successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def function(root,name):
        return next(n for n in root.body if isinstance(n,ast.FunctionDef) and n.name==name)
    for name in ('historical_observation_boundary','begin_source_observation'):
        selected=function(tree,name);original=function(old,name)
        test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':explicit boundary node '+name)
        tree.body[tree.body.index(selected)]=deepcopy(original)
    added=function(tree,'_preserved_program_gap_observation');tree.body.remove(added)
    with test.assertRaises(StopIteration):function(old,'_preserved_program_gap_observation')
    for source in PROGRAM_GAP_OBSERVATION_ADDITIONS:
        addition=ast.parse(source).body[0]
        matches=[n for n in tree.body if ast.dump(n)==ast.dump(addition)]
        test.assertEqual(len(matches),1,relative+':one exact incident identity')
        test.assertNotIn(ast.dump(addition),[ast.dump(n) for n in old.body])
        tree.body.remove(matches[0])
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':all other recovery and financial source nodes retained')
    return prior


# The measured startup cancellation repair changes only the selected idle
# candidate reads, their Pump caller, Pons's existing startup replay scope and
# one descriptive status identifier. Pin each complete source and reverse only
# these named nodes to 908ce9b7 before every older source/economic comparison.
# CandidateHistory and status gain full-file guards too; no mutation, strategy
# or financial method is exempted by calling the repair infrastructure.
STARTUP_HISTORY_CANCEL_REFERENCE='908ce9b72ec6f7eb9cd4452551c1656b0592a09e'
STARTUP_HISTORY_CANCEL_DELTAS={
    'meme_machine/runtime/candidate_history.py':(
        '359a70e38b2a8e6e015e1dce43e883476228929f3a45791bc05aabfc4e19ffc4',
        '99984085df2ceefb8e7a94dfd9eabb85674311fca9d9ae67584dc9415de35d45',
        ('CandidateHistory.candidates','CandidateHistory.events'),('CandidateHistory._startup_read',)),
    'meme_machine/lanes/pump/runner.py':(
        '148ec23e41195ad1464236873ffe2d1ae6bf96e1ddc5cf401a703703c49ef40e',
        'eaf902b1894232403bfb2715bf9a0b78bfc9d8b6635c3a796cd9f122c7aca5c5',
        ('_restore_observed_pump_candidates',),()),
    'meme_machine/lanes/pons/pons_selective_cohort.py':(
        '62d60f608185713a69542e181cca9302cc9e224e61791bc502d8324e0b79c312',
        '4209107e6eb53bdb32eeb33ae1a3addb47ff4ca5a1ee298d5509fbb46e5d6ad7',
        ('run',),()),
    'meme_machine/runtime/status.py':(
        'fa9fd080bf9c78cb7c844a685b61ebffd281711263c722427d489b6d35e38da7',
        '7c819b3b0c5e3ee56984e021a851466bd12bb7a8ace30ce6d952d12be32575e3',
        ('operation',),()),
}


def startup_history_cancellation_predecessor(test,relative,current,*,allow_previous_layers=False):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    reviewed=STARTUP_HISTORY_CANCEL_DELTAS.get(relative)
    if reviewed is None:return current
    before,after,changed,added=reviewed
    prior=subprocess.check_output(['git','show',STARTUP_HISTORY_CANCEL_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),before,relative+':exact cancellation predecessor')
    if current==prior:return prior
    if allow_previous_layers and hashlib.sha256(current).hexdigest()!=after:
        # Original nested guards already visit their independently pinned older
        # intermediates. Their existing byte/node checks still run unchanged;
        # the active-source test below always requires this exact successor.
        return current
    test.assertEqual(hashlib.sha256(current).hexdigest(),after,relative+':exact startup cancellation successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def node(root,name):
        parent=root
        for part in name.split('.')[:-1]:
            parent=next(n for n in parent.body if isinstance(n,ast.ClassDef) and n.name==part)
        return parent,next(n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name==name.split('.')[-1])
    for name in changed:
        parent,selected=node(tree,name);_,original=node(old,name)
        test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':explicit cancellation node '+name)
        parent.body[parent.body.index(selected)]=deepcopy(original)
    for name in added:
        parent,selected=node(tree,name);parent.body.remove(selected)
        with test.assertRaises(StopIteration):node(old,name)
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':all other source nodes retained')
    return prior


def rally_manifest(test):
    import hashlib,json
    raw=RALLY_MANIFEST.read_bytes()
    test.assertEqual(hashlib.sha256(raw).hexdigest(),RALLY_MANIFEST_SHA256,'exact reviewed rally manifest')
    manifest=json.loads(raw)
    test.assertEqual(manifest['schema'],RALLY_SCHEMA)
    test.assertEqual(manifest['base'],RALLY_BASE)
    test.assertEqual(manifest['revision'],'paper-postgrad-rally-v1')
    test.assertEqual(set(manifest['files']),set(RALLY_CHANGED_SOURCES),'explicit changed rally sources')
    test.assertEqual(set(manifest['added_sources']),set(RALLY_ADDED_SOURCES),'explicit added rally sources')
    return manifest


def rally_nodes(content):
    """Hash every statement/method plus class headers and body ordering."""
    from copy import deepcopy
    import hashlib
    result={};layouts={}
    def walk(body,parent):
        order=[];occurrences={}
        for node in body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                label=type(node).__name__+':'+node.name
            elif isinstance(node,ast.Assign):label='Assign:'+','.join(ast.dump(t) for t in node.targets)
            elif isinstance(node,ast.AnnAssign):label='AnnAssign:'+ast.dump(node.target)
            elif isinstance(node,ast.ImportFrom):label='ImportFrom:'+str(node.level)+':'+str(node.module)
            elif isinstance(node,ast.Import):label='Import:'+','.join(a.name for a in node.names)
            elif isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):
                label='docstring'
            else:label=type(node).__name__+':'+ast.dump(node)
            index=occurrences.get(label,0);occurrences[label]=index+1
            key=parent+'/'+label+('#'+str(index) if index else '')
            order.append(key)
            protected=deepcopy(node)
            if isinstance(node,ast.ClassDef):
                protected.body=[]
                walk(node.body,key)
            result[key]=hashlib.sha256(ast.dump(protected).encode()).hexdigest()
        layouts[parent]=order
    walk(ast.parse(content).body,'module')
    return result,layouts


def rally_delta(before,after):
    old_nodes,old_layouts=rally_nodes(before);new_nodes,new_layouts=rally_nodes(after)
    def changed(old,new):
        return {key:dict(before=old.get(key),after=new.get(key))
            for key in sorted(old.keys()|new.keys()) if old.get(key)!=new.get(key)}
    return dict(nodes=changed(old_nodes,new_nodes),layouts=changed(old_layouts,new_layouts))


# An optional ONE-SLOT cold-cache across the exact Pump startup restoration is
# bounded to that one cancelled/finished pass. Pin BOTH complete runtime files
# at the reviewed implementation commit, reduce them to the prior merged source,
# then execute every previous source/economic guard unchanged.
CROSS_CANDIDATE_COLD_BASE='45185cd007dd0ca17c9cdf2615dde5b551a463cf'
CROSS_CANDIDATE_COLD_REVIEW='409e727f0a14d186378a3e23f0e9669b33aef344'
CROSS_CANDIDATE_COLD_PATHS=frozenset((
    'meme_machine/runtime/candidate_history.py',
    'meme_machine/lanes/pump/runner.py',
))


# The measured successor changes only per-invocation filesystem validation.
# Reduce the exact complete file back to its reviewed predecessor before every
# existing archive, cancellation, accounting and economic source guard.
RETAINED_PATH_FACTOR_REFERENCE='0c8e9beae8eed6e4579f4473c4f449f711fb5691'
RETAINED_PATH_FACTOR_SOURCE='meme_machine/runtime/candidate_history.py'
RETAINED_PATH_FACTOR_BEFORE='bdd6418f6930581e48d887897493d32cb24bd260faf529e4694306e8f389c6c4'
RETAINED_PATH_FACTOR_AFTER='74b40b66a6fd13f7bada63954dfdbb37690bd9c6f3db597a4d3a2182d6ed08cd'


def retained_path_factoring_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=RETAINED_PATH_FACTOR_SOURCE:return current
    prior=subprocess.check_output(['git','show',RETAINED_PATH_FACTOR_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),RETAINED_PATH_FACTOR_BEFORE,
        relative+':exact per-reference filesystem predecessor')
    if current==prior:return prior
    test.assertEqual(hashlib.sha256(current).hexdigest(),RETAINED_PATH_FACTOR_AFTER,
        relative+':exact per-reference filesystem successor')
    tree=ast.parse(current);old=ast.parse(prior)
    selected=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='retained_reference_path')
    original=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name=='retained_reference_path')
    test.assertEqual(ast.dump(selected.args),ast.dump(original.args),relative+':unchanged reader signature')
    new_try=next(n for n in selected.body if isinstance(n,ast.Try))
    old_try=next(n for n in original.body if isinstance(n,ast.Try))
    index=selected.body.index(new_try)
    reduced=deepcopy(selected);reduced.body[index]=deepcopy(old_try)
    test.assertEqual(ast.dump(reduced),ast.dump(original),
        relative+':only within-call filesystem try block changes; original cohort and environment guards retained')
    test.assertEqual([ast.dump(n) for n in new_try.handlers],[ast.dump(n) for n in old_try.handlers],
        relative+':original refusal handling retained')
    tree.body[tree.body.index(selected)]=deepcopy(original)
    test.assertEqual(ast.dump(tree),ast.dump(old),
        relative+':all other source, index, event, hash, transaction and economic nodes unchanged')
    def body(source,node):return b''.join(source.splitlines(keepends=True)[node.lineno-1:node.end_lineno])
    selected_bytes=body(current,selected)
    test.assertEqual(current.count(selected_bytes),1,relative+':one exact filesystem helper')
    restored=current.replace(selected_bytes,body(prior,original),1)
    test.assertEqual(restored,prior,relative+':every source byte outside the one helper unchanged')
    return prior


def cross_candidate_cold_predecessor(test,relative,current):
    if relative not in CROSS_CANDIDATE_COLD_PATHS:return current
    prior=subprocess.check_output(['git','show',CROSS_CANDIDATE_COLD_BASE+':'+relative],cwd=ROOT)
    if current==prior:return prior
    current=retained_path_factoring_predecessor(test,relative,current)
    accepted=subprocess.check_output(['git','show',CROSS_CANDIDATE_COLD_REVIEW+':'+relative],cwd=ROOT)
    test.assertEqual(current,accepted,relative+':exact reviewed Pump startup archive reuse')
    return prior


def rally_predecessor(test,relative,current,*,allow_previous_layers=False):
    import hashlib,json
    if isinstance(current,str):current=current.encode()
    if relative==SLEEVE_EMPTY_PREFIX_SOURCE and hashlib.sha256(current).hexdigest()==SLEEVE_EMPTY_PREFIX_AFTER:
        current=sleeve_empty_prefix_predecessor(test,relative,current)
    current=survivor_increment_continuity_predecessor(test,relative,current)
    current=archive_complete_logs_predecessor(test,relative,current)
    current=native_startup_failure_predecessor(test,relative,current,
        allow_previous_layers=allow_previous_layers)
    current=survivor_monitor_replay_predecessor(test,relative,current,
        allow_previous_layers=allow_previous_layers)
    current=program_gap_observation_predecessor(test,relative,current)
    current=startup_history_cancellation_predecessor(test,relative,current,
        allow_previous_layers=allow_previous_layers)
    current=restored_provider_history_predecessor(test,relative,current)
    manifest=rally_manifest(test)
    record=manifest['files'].get(relative)
    if record is None:return current
    prior=subprocess.check_output(['git','show',RALLY_BASE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),record['before_sha256'],relative+':rally predecessor bytes')
    if current==prior:return prior
    current_hash=hashlib.sha256(current).hexdigest()
    if allow_previous_layers and current_hash!=record['after_sha256']:
        # Existing inner guards also consume their own older intermediate
        # source. They retain their original exact pins and mutation failures.
        return current
    test.assertEqual(current_hash,record['after_sha256'],relative+':exact reviewed rally bytes')
    actual=rally_delta(prior,current)
    test.assertEqual(actual['nodes'],record['nodes'],relative+':exact rally methods/statements')
    test.assertEqual(actual['layouts'],record['layouts'],relative+':exact rally ordering')
    before_nodes,before_layouts=rally_nodes(prior)
    after_nodes,after_layouts=rally_nodes(current)
    for field,restored,original in (('nodes',after_nodes,before_nodes),('layouts',after_layouts,before_layouts)):
        for key,change in record[field].items():
            test.assertEqual(restored.get(key),change['after'],relative+':reviewed successor '+key)
            if change['before'] is None:restored.pop(key,None)
            else:restored[key]=change['before']
        test.assertEqual(restored,original,relative+':all other protected '+field+' preserved')
    return prior


def guarded_source(test,relative):
    """Apply the exact new layer, then let the original economic guards run."""
    current=publication_accounting_predecessor(test,relative,pump_restore_predecessor(test,relative,(ROOT/relative).read_bytes()))
    return rally_predecessor(test,relative,current)


# Fixed, opt-in reached-operation costs are descriptive infrastructure only.
# Pin both complete sources, reverse these exact bytes to the ced262d4 checkpoint,
# then apply every existing startup, opportunity, policy and economic assertion.
# This layer grants no AST exemption to a whole controller or accounting method.
OPERATION_COST_REFERENCE='ced262d4b488059fcc555f7684ec95b86221d546'
OPERATION_COST_DELTAS={'meme_machine/lanes/pons/evidence.py': ('841db7b20c4e563527f30fb8090dabe20ee906c12aa2d6699e3346206e89680e',
                                         '50636a9f0fa360131d62abd6006da152c9fa63c4ffd439decfe5d179f6530939',
                                         ((b'        self.db = sqlite3.connect(path, isolation_level=None)\n',
                                           b'        from meme_machine.runtime.operation_costs import connect'
                                           b'\n        self.db = connect(path, isolation_level=None, diagn'
                                           b"ostic_role='pons_native_store')\n"),)),
 'meme_machine/lanes/pons/pons_selective_capital.py': ('f04dd98eb22d3a6b9eccca284150c81366d6f624b7512dc0c07aaf4d63bf7b43',
                                                       '08b25a29569f08e94a1131dd09f64a642a79814a3b6e8fc8513092ea05a7981f',
                                                       ((b'        db=sqlite3.connect(self.path,timeout=30,'
                                                         b'isolation_level=None)\n',
                                                         b'        from meme_machine.runtime.operation_cost'
                                                         b's import connect\n        db=connect(self.path,ti'
                                                         b"meout=30,isolation_level=None,diagnostic_role='p"
                                                         b"ons_selective_capital')\n"),)),
 'meme_machine/lanes/pons/pons_selective_cohort.py': ('c02656621b57e3c3a2533f79249d012c20ecddbfaf686c21683e989eded3aec8',
                                                      'aa3ccf1884e6e80c274c967def3e481269c68f0c97bcc5bb333abb45ef03182b',
                                                      ((b'',
                                                        b'from meme_machine.runtime import operation_costs'
                                                        b'\n'),
                                                       (b'                discovery_future=discovery_pool.'
                                                        b'submit(_discover_observations,\n',
                                                        b'                discovery_future=operation_costs'
                                                        b".submit(discovery_pool,'pons.current_discovery',"
                                                        b'_discover_observations,\n'),
                                                       (b'                priming_future=discovery_pool.su'
                                                        b'bmit(_prime_current_step,startup_context,queue,s'
                                                        b'tartup_head)\n',
                                                        b'                priming_future=operation_costs.s'
                                                        b"ubmit(discovery_pool,'pons.current_prime',_prime"
                                                        b'_current_step,startup_context,queue,startup_head'
                                                        b')\n'),
                                                       (b'                hydration=hydration_pool.submit(\n',
                                                        b'                hydration=operation_costs.submit'
                                                        b"(hydration_pool,'pons.current_hydration',\n"))),
 'meme_machine/operational/supervisor.py': ('a010ee1daf2e34ab99d371085f674d3984933e8953e430770acfd4697de983a9',
                                            'b2ffa2991607fef15fc1934682018d101a74ba21763702ca5d3757456a132982',
                                            ((b'',
                                              b"        if lane in ('pons','solana'):\n            env['MM_OP"
                                              b"ERATION_COST_DIAGNOSTICS']='1' if os.environ.get('MM_OPERATI"
                                              b"ON_COST_DIAGNOSTICS')=='1' else '0'\n"),)),
 'meme_machine/runtime/survivor_history.py': ('22ab2268bb4b23997314889c7e6936706a7a47a1e3301341e699acc51989ce40',
                                              '5a0e1d111898748014f1412c84ab193ffe4ce5207fbece903613db05faf14350',
                                              ((b'        self.db=sqlite3.connect(path,isolation_level=Non'
                                                b'e)\n',
                                                b'        from meme_machine.runtime.operation_costs import'
                                                b' connect\n        self.db=connect(path,isolation_level=No'
                                                b"ne,diagnostic_role='survivor_history')\n"),
                                               (b'',
                                                b'        from contextlib import nullcontext\n        from '
                                                b'meme_machine.runtime import operation_costs\n        pons'
                                                b"=os.environ.get('MM_RUNTIME_LANE')=='pons'\n        def o"
                                                b'peration(name):return operation_costs.operation(name) if'
                                                b' pons else nullcontext()\n'),
                                               (b'            with native_startup_replay(requested.is_set)'
                                                b':self.service=self.factory()\n',
                                                b"            with operation('pons.survivor_restore'):\n   "
                                                b'             with native_startup_replay(requested.is_set'
                                                b'):self.service=self.factory()\n'),
                                               (b'        if maintenance:\n            from meme_machine.la'
                                                b'nes.pons.provider_admission import position_work\n       '
                                                b'     status=position_work(self.service.step)(admit=False'
                                                b')\n        else:status=self.service.step(admit=admit)\n',
                                                b"        with operation('pons.survivor_step'):\n          "
                                                b'  if maintenance:\n                from meme_machine.lane'
                                                b's.pons.provider_admission import position_work\n         '
                                                b'       status=position_work(self.service.step)(admit=Fal'
                                                b'se)\n            else:status=self.service.step(admit=admi'
                                                b't)\n'),
                                               (b'                telemetry=enrich_service(self.service,no'
                                                b'w=time.time())\n',
                                                b"                with operation('pons.survivor_enrich'):\n"
                                                b'                    telemetry=enrich_service(self.servic'
                                                b'e,now=time.time())\n'))),
 'meme_machine/runtime/survivor_paper_book.py': ('50db696d52f2aafd22259a3aced3223117acf37631a5904b391dfe9edb7c976c',
                                                 '0593b88ab84cb4ce7d9aa2a4f177d42ff933a2950a179cd42e72662ee2c0135d',
                                                 ((b'        self.db = sqlite3.connect(path, isolation_level='
                                                   b'None, timeout=30, check_same_thread=False)\n',
                                                   b'        from meme_machine.runtime.operation_costs import'
                                                   b' connect\n        self.db = connect(path, isolation_l'
                                                   b'evel=None, timeout=30, check_same_thread=False,\n    '
                                                   b"                      diagnostic_role='survivor_paper_bo"
                                                   b"ok')\n"),))}


# The reviewed Pons discovery successor removes duplicate nominations and
# per-event reporting only. Reverse its exact bytes before the original
# complete operation-cost and strategy/economic source checks below.
PONS_DISCOVERY_REFERENCE='f52be1e134b3471470d47c181df63c71192cf50c'
PONS_DISCOVERY_SOURCE='meme_machine/lanes/pons/pons_selective_cohort.py'
PONS_DISCOVERY_BEFORE_SHA256='aa3ccf1884e6e80c274c967def3e481269c68f0c97bcc5bb333abb45ef03182b'
PONS_DISCOVERY_AFTER_SHA256='62d60f608185713a69542e181cca9302cc9e224e61791bc502d8324e0b79c312'
PONS_DISCOVERY_REPLACEMENTS=((b"    return len(result['rows'])-offset\n\n\ndef run(endpoint,*,campaign=False):\n    if type(campaign) is"
  b" not bool:raise BoundaryError('selective_campaign_flag')\n    ROOT.mkdir(parents=True,exist_ok=True)\n",
  b"    return len(result['rows'])-offset\n\n\ndef _collect_observations(*args,queue,scout=None,**kwargs):\n"
  b'    """Nominate once, at the page\'s original receipt time.\n\n    The scout commits each page before n'
  b'otifying Current. Its returned cohort\n    is already durable and can be older than a concurrently accept'
  b'ed page;\n    replaying it here or in the controller adds no evidence or fresh deadline.\n    Standalo'
  b'ne discovery has no page callback and retains its original enqueue.\n    """\n    def nominate(event,o'
  b"bserved):\n        queue.enqueue(event,now=observed,needs_work=event['topics'][0].lower()==scout.curve_to"
  b'pics[0])\n    discovered=_poll(*args,**kwargs,scout=scout,nominate=nominate if scout else None)\n    i'
  b'f scout is None:\n        observed=time.time()\n        for event in discovered[2]:\n            is_buy'
  b"=bool(event.get('topics') and event['topics'][0].lower()==topic(\n                'CurveBuy(address,addre"
  b"ss,uint256,uint256,uint256,uint256)'))\n            queue.enqueue(event,now=observed,needs_work=is_bu"
  b'y)\n    return discovered\n\n\ndef run(endpoint,*,campaign=False):\n    if type(campaign) is not bool:rai'
  b"se BoundaryError('selective_campaign_flag')\n    ROOT.mkdir(parents=True,exist_ok=True)\n"),
 (b'        )\n\n    def _discover_observations(*args,**kwargs):\n        def nominate(event,observed):\n   '
  b"         queue.enqueue(event,now=observed,needs_work=event['topics'][0].lower()==scout.curve_topics[0])\n"
  b'        discovered=_poll(*args,**kwargs,scout=scout,nominate=nominate if scout else None)\n        observ'
  b"ed=time.time()\n        for event in discovered[2]:\n            is_buy=bool(event.get('topics') and e"
  b"vent['topics'][0].lower()==topic(\n                'CurveBuy(address,address,uint256,uint256,uint256,uint"
  b"256)'))\n            queue.enqueue(event,now=observed,needs_work=is_buy)\n        return discovered\n\n "
  b'   pool=None;futures=[]\n    try:\n',
  b'        )\n\n    def _discover_observations(*args,**kwargs):\n        return _collect_observations(*arg'
  b's,**kwargs,queue=queue,scout=scout)\n\n    pool=None;futures=[]\n    try:\n'),
 (b'                identity=(event["transactionHash"],event["logIndex"])\n                is_buy=bool(event.'
  b'get(\'topics\') and event[\'topics\'][0].lower()==topic(\n                    "CurveBuy(address,address,u'
  b'int256,uint256,uint256,uint256)"))\n                # Every newer event updates the durable curve, includ'
  b'ing sells.\n                # Only buys nominate qualification; sells fence an older buy.\n           '
  b'     queue.enqueue(event,now=now,needs_work=is_buy)\n                queue.report_to(pipeline,drain=True)'
  b'\n                current=queue.plane.get(queue.identity(event))\n                if is_buy and curren'
  b"t['latest_id']==event['transactionHash']+':'+event['logIndex']:\n                    pipeline.record(queu"
  b"e.identity(event),'screened',candidate_generation=current['generation'])\n                    pipeline.re"
  b"cord(queue.identity(event),'current_state_queued',candidate_generation=current['generation'],first_obser"
  b'ved_at=now,\n                        original_deadline=now+5,sequencer_last_received_at=getattr(feed.stat'
  b"e,'last_received_at',None))\n\n            coverage()\n            # These retained-history counts are "
  b'reporting, never a readiness\n            # or protection witness. Recompute on real observations and the'
  b'\n            # existing checkpoint cadence, rather than every empty poll.\n',
  b'                identity=(event["transactionHash"],event["logIndex"])\n                is_buy=bool(event.'
  b'get(\'topics\') and event[\'topics\'][0].lower()==topic(\n                    "CurveBuy(address,address,u'
  b'int256,uint256,uint256,uint256)"))\n                # Discovery already committed every buy and sell, inc'
  b'luding\n                # the original observation clock and generation fence.\n                curren'
  b"t=queue.plane.get(queue.identity(event))\n                if is_buy and current['latest_id']==event['tran"
  b"sactionHash']+':'+event['logIndex']:\n                    pipeline.record(queue.identity(event),'screened"
  b"',candidate_generation=current['generation'])\n                    pipeline.record(queue.identity(event),"
  b"'current_state_queued',candidate_generation=current['generation'],first_observed_at=now,\n               "
  b"         original_deadline=now+5,sequencer_last_received_at=getattr(feed.state,'last_received_at',None))"
  b'\n\n            # Project one captured high-water after the complete returned\n            # cohort, be'
  b'fore qualification. Do not repeat full maintenance for\n            # each already-durable event while pe'
  b'er acquisition is committing.\n            coverage(drain=bool(fresh))\n            # These retained-h'
  b'istory counts are reporting, never a readiness\n            # or protection witness. Recompute on real ob'
  b'servations and the\n            # existing checkpoint cadence, rather than every empty poll.\n'))


def pons_discovery_predecessor(test,relative,current):
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!=PONS_DISCOVERY_SOURCE:return current
    prior=subprocess.check_output(['git','show',PONS_DISCOVERY_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),PONS_DISCOVERY_BEFORE_SHA256)
    if current==prior:return prior
    # Nested original guards also receive the exact predecessor after the
    # separately reviewed operation-cost layer has already been reversed.
    # Recognize only those pinned complete bytes, never arbitrary source.
    instrument_prior=subprocess.check_output(['git','show',OPERATION_COST_REFERENCE+':'+relative],cwd=ROOT)
    if current==instrument_prior:return current
    test.assertEqual(hashlib.sha256(current).hexdigest(),PONS_DISCOVERY_AFTER_SHA256,
        relative+':exact reviewed one-nomination discovery successor')
    for old,new in PONS_DISCOVERY_REPLACEMENTS:
        test.assertEqual(current.count(new),1,relative+':one exact discovery delta')
        current=current.replace(new,old,1)
    test.assertEqual(current,prior,relative+':all strategy, execution and recovery bytes preserved')
    return current


# Exact observed DO-to-AWS provider-history compatibility is one additional
# reversible startup delta. Pin its complete helper as well as both Supervisor
# files; then recover every earlier safety/economic source check unchanged.
RESTORED_HISTORY_REFERENCE='cfc25ba8e4378724c29256307af769c9350031bf'
RESTORED_HISTORY_BEFORE='ccf7aba447c254eadea5915cf495560559251966cbc6769be524b37668fcd629'
RESTORED_HISTORY_AFTER='4aa0f4eec6aa02514c223d13211bd2b211f0985f7a462baa50a15ceb82771033'
RESTORED_HISTORY_HELPER='meme_machine/operational/restored_provider_history.py'
RESTORED_HISTORY_HELPER_SHA256='23a9dd86812da4810d1f4abdaea130fbd62ea094a2caaf088179d1430e297684'
RESTORED_HISTORY_OLD_BLOCK=(
    b"            if original_path and (original_path!=str(path) or not path.is_file()):\n"
    b"                raise ValueError('continuous_usage_history_requires_restore_not_reseed')\n"
    b"            self.provider_budget=Budget(path) if path.exists() else Budget.create(path,continuous=envelope)\n")
RESTORED_HISTORY_NEW_BLOCK=(
    b"            if original_path and (original_path!=str(path) or not path.is_file()):\n"
    b"                from .restored_provider_history import require_restored_history\n"
    b"                require_restored_history(self,state,path,envelope)\n"
    b"            self.provider_budget=Budget(path) if original_path or path.exists() else Budget.create(path,continuous=envelope)\n")


def restored_provider_helper(test,current):
    import hashlib
    test.assertEqual(hashlib.sha256(current).hexdigest(),RESTORED_HISTORY_HELPER_SHA256,
        'complete exact fixed-cohort observation compatibility helper')


def restored_provider_history_predecessor(test,relative,current):
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!='meme_machine/operational/supervisor.py' or b'from .restored_provider_history import' not in current:return current
    current=source_parent_drain_predecessor(test,relative,current)
    test.assertEqual(hashlib.sha256(current).hexdigest(),RESTORED_HISTORY_AFTER,
        relative+':exact restored-history successor')
    restored_provider_helper(test,(ROOT/RESTORED_HISTORY_HELPER).read_bytes())
    prior=subprocess.check_output(['git','show',RESTORED_HISTORY_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),RESTORED_HISTORY_BEFORE)
    test.assertEqual(current.count(RESTORED_HISTORY_NEW_BLOCK),1)
    current=current.replace(RESTORED_HISTORY_NEW_BLOCK,RESTORED_HISTORY_OLD_BLOCK,1)
    test.assertEqual(current,prior,relative+':all original startup and economic safeguards preserved')
    return prior


# Explicit host-capacity portability changes only the existing cgroup check.
# Pin both full files and reverse the one reviewed method/import before every
# existing economic/source comparison. No other Supervisor node is exempted.
# The later funding-closed contained observation adds one source-only phase
# binding and authenticates the retained Pump cache against current canonical
# coverage. Reverse only those exact reviewed bytes before the older guards;
# their complete predecessor hashes, economics and negative checks stay pinned.
CONTAINED_OBSERVATION_REFERENCE='738e8b5842ef6f3a27bc4f9e91b8c975d280822f'
CONTAINED_OBSERVATION_DELTAS={
    'meme_machine/operational/supervisor.py':(
        '20fda2428bca7758f2ee4987903c4b346d9b98833472d4d734702cdc8107d646',
        '5c0cd297633ab4575880eb0fdf94d93bfad27ae9575fb569aaebd48e6b9dd98c',
        b"if lane=='solana' and getattr(self,'admission','NORMAL')"),
    'meme_machine/lanes/pump/solana_evidence_runtime.py':(
        '8fa56503e2d5c14c1fea7406a8bba2c4ea4d90380c088efcca60b2c0299a16ba',
        '470f1f610a8a9533bf4fd8218dbcef8e36bbd14dde22ce21f3b88b14e94deca3',
        b'def _cached_window_authority('),
}
CONTAINED_OBSERVATION_PHASE=(
    b"        if lane=='solana' and getattr(self,'admission','NORMAL')=='OBSERVATION':env['MM_OPERATIONAL_PHASE']='OBSERVATION'\n")
CONTAINED_CACHE_WINDOW_BEFORE=(
    b"                with closing(history):rows=history.covered_events(\n"
    b"                    'pump',mint,PUMP_SCOPE,int(now)-60,int(now),upper_slot=max_slot)\n")
CONTAINED_CACHE_WINDOW_AFTER=(
    b"                with closing(history),self._cached_window_authority(\n"
    b"                        mint,int(now)-60,int(now),max_slot) as authority:\n"
    b"                    rows=history.covered_events('pump',mint,PUMP_SCOPE,int(now)-60,int(now),\n"
    b"                        upper_slot=max_slot,source_authority=authority)\n")


def contained_observation_predecessor(test,relative,current):
    import hashlib
    if isinstance(current,str):current=current.encode()
    current=restored_provider_history_predecessor(test,relative,current)
    reviewed=CONTAINED_OBSERVATION_DELTAS.get(relative)
    if reviewed is None or reviewed[2] not in current:return current
    before,after,_=reviewed
    test.assertEqual(hashlib.sha256(current).hexdigest(),after,
        relative+':exact reviewed contained observation successor')
    prior=subprocess.check_output(['git','show',CONTAINED_OBSERVATION_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),before,
        relative+':unchanged contained observation predecessor')
    if relative=='meme_machine/operational/supervisor.py':
        test.assertEqual(current.count(CONTAINED_OBSERVATION_PHASE),1)
        current=current.replace(CONTAINED_OBSERVATION_PHASE,b'',1)
    else:
        test.assertEqual(current.count(b'from contextlib import contextmanager\n'),1)
        current=current.replace(b'from contextlib import contextmanager\n',b'',1)
        parent=next(n for n in ast.parse(current).body if isinstance(n,ast.ClassDef) and n.name=='LocalPumpTape')
        helper=next(n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name=='_cached_window_authority')
        test.assertEqual([ast.dump(n) for n in helper.decorator_list],
            [ast.dump(ast.Name(id='contextmanager',ctx=ast.Load()))])
        lines=current.splitlines(keepends=True)
        del lines[min(helper.lineno,*(n.lineno for n in helper.decorator_list))-1:helper.end_lineno]
        current=b''.join(lines)
        test.assertEqual(current.count(CONTAINED_CACHE_WINDOW_AFTER),1)
        current=current.replace(CONTAINED_CACHE_WINDOW_AFTER,CONTAINED_CACHE_WINDOW_BEFORE,1)
    test.assertEqual(current,prior,relative+':all original source bytes and safeguards preserved')
    return prior


CPU_CAPACITY_REFERENCE='9bc778ff9237c0769aa6a6d2799bf513d677e333'
CPU_CAPACITY_BEFORE='b2ffa2991607fef15fc1934682018d101a74ba21763702ca5d3757456a132982'
CPU_CAPACITY_AFTER='20fda2428bca7758f2ee4987903c4b346d9b98833472d4d734702cdc8107d646'


def cpu_capacity_predecessor(test,relative,current):
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!='meme_machine/operational/supervisor.py':return current
    current=contained_observation_predecessor(test,relative,current)
    if b'configured_cpu=cpu_capacity(budget.envelope)' not in current:return current
    test.assertEqual(hashlib.sha256(current).hexdigest(),CPU_CAPACITY_AFTER,
        relative+':exact reviewed host-capacity successor')
    prior=subprocess.check_output(['git','show',CPU_CAPACITY_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),CPU_CAPACITY_BEFORE)
    def selected(raw):
        tree=ast.parse(raw)
        parent=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Supervisor')
        node=next(n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name=='continuation_health')
        return b''.join(raw.splitlines(keepends=True)[node.lineno-1:node.end_lineno])
    original=selected(prior);reviewed=selected(current)
    test.assertNotEqual(original,reviewed)
    test.assertEqual(current.count(b'import math\n'),1)
    current=current.replace(b'import math\n',b'',1)
    test.assertEqual(current.count(reviewed),1)
    current=current.replace(reviewed,original,1)
    test.assertEqual(current,prior,relative+':all economics, priorities, deadlines and siblings preserved')
    return prior


# Explicit backup-file selection preserves credential redaction and policy
# selection. Reverse the exact capture-only change before the original manifest.
BACKUP_CONFIGURATION_BEFORE='c848672443076ba8f8f4facaf6bfad3a34ee719cb58f05675827e4d5237d0fa7'
BACKUP_CONFIGURATION_AFTER='ce7a78e13e93ff1da76e957c4ff420becb42dc253368bf4d8a17ebe36a10c878'


def backup_configuration_predecessor(test,relative,current):
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!='meme_machine/operational/configuration.py':return current
    if b"env.get('MM_BACKUP_ENV_FILE'" not in current:return current
    test.assertEqual(hashlib.sha256(current).hexdigest(),BACKUP_CONFIGURATION_AFTER)
    prior=subprocess.check_output(['git','show',CPU_CAPACITY_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),BACKUP_CONFIGURATION_BEFORE)
    def capture(raw):
        selected=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='capture')
        return b''.join(raw.splitlines(keepends=True)[selected.lineno-1:selected.end_lineno])
    original=capture(prior);reviewed=capture(current)
    test.assertEqual(current.count(reviewed),1)
    current=current.replace(reviewed,original,1)
    test.assertEqual(current,prior,relative+':all other credential, policy and identity bytes preserved')
    return prior


def operation_cost_predecessor(test,relative,current):
    import hashlib
    if isinstance(current,str):current=current.encode()
    current=cpu_capacity_predecessor(test,relative,current)
    current=pons_discovery_predecessor(test,relative,current)
    reviewed=OPERATION_COST_DELTAS.get(relative)
    if reviewed is None:return current
    before,after,replacements=reviewed
    prior=subprocess.check_output(['git','show',OPERATION_COST_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),before,relative+':reviewed operation-cost predecessor')
    if current==prior:return prior
    test.assertEqual(hashlib.sha256(current).hexdigest(),after,relative+':exact operation-cost successor')
    for old,new in replacements:
        test.assertEqual(current.count(new),1,relative+':one exact operation-cost delta')
        current=current.replace(new,old,1)
    test.assertEqual(current,prior,relative+':all economic and operational bytes preserved')
    return current


def reviewed_operation_costs(test,relative,current):
    import hashlib
    if isinstance(current,str):current=current.encode()
    current=contained_observation_predecessor(test,relative,current)
    current=backup_configuration_predecessor(test,relative,current)
    current=cpu_capacity_predecessor(test,relative,current)
    # Apply this outer layer only while its exact new helper remains present.
    # Original nested guards also visit several older, already-normalized
    # implementations; all their existing guards must run unchanged.
    if relative==PONS_DISCOVERY_SOURCE and b'def _collect_observations(' in current:
        current=pons_discovery_predecessor(test,relative,current)
    reviewed=OPERATION_COST_DELTAS.get(relative)
    if reviewed and hashlib.sha256(current).hexdigest()==reviewed[1]:
        return operation_cost_predecessor(test,relative,current)
    return current


# Reviewed acquisition forwarding after the combined strategy release. Pin the
# complete predecessor and successor, then remove only this exact Pons-only
# environment block before applying the unchanged opportunity/economic guards.
# Neither an arbitrary Supervisor.environment body nor another infrastructure
# edit is exempted. The active-source regression also requires the successor.
OBSERVATION_ROUTE_REFERENCE='4cfe994fdface99e61c33dc534397eff85b5a74b'
OBSERVATION_ROUTE_SOURCE='meme_machine/operational/supervisor.py'
OBSERVATION_ROUTE_BEFORE_SHA256='8c6fc561bbe5dc82bb09d90fc73f8700d01c3dab6e3e9fa007d94c5594961b14'
OBSERVATION_ROUTE_AFTER_SHA256='a010ee1daf2e34ab99d371085f674d3984933e8953e430770acfd4697de983a9'
OBSERVATION_ROUTE_BLOCK=(
    b"            # Forward the existing explicit observation choice to its native\n"
    b"            # consumer only. This grants no provider capability or funding.\n"
    b"            observation_route=os.environ.get('MM_PONS_OBSERVATION_ROUTE') or 'public_existing'\n"
    b"            if observation_route not in ('public_existing','canonical_primary'):\n"
    b"                raise ValueError('invalid_pons_observation_route')\n"
    b"            if not self.offline:env['MM_PONS_OBSERVATION_ROUTE']=observation_route\n"
)


def observation_route_predecessor(test,relative,current):
    import hashlib
    if isinstance(current,str):current=current.encode()
    current=reviewed_operation_costs(test,relative,current)
    if relative!=OBSERVATION_ROUTE_SOURCE:return current
    prior=subprocess.check_output(['git','show',OBSERVATION_ROUTE_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),OBSERVATION_ROUTE_BEFORE_SHA256,
        relative+':reviewed observation-route predecessor')
    if current==prior:return prior
    test.assertEqual(hashlib.sha256(current).hexdigest(),OBSERVATION_ROUTE_AFTER_SHA256,
        relative+':exact reviewed observation-route successor')
    test.assertEqual(current.count(OBSERVATION_ROUTE_BLOCK),1,relative+':one exact acquisition forwarding block')
    stripped=current.replace(OBSERVATION_ROUTE_BLOCK,b'',1)
    test.assertEqual(stripped,prior,relative+':all strategy and operational bytes preserved')
    return stripped


# The observed v1 startup failure demonstrated that canonical candidate cache
# and native capital need not share a parent. Permit only the reviewed explicit
# authority path, with a complete source pin and reversible byte delta. All
# policy, replay, flat-state, release and strategy nodes still pass the existing
# combined package guards below.
COHORT_AUTHORITY_REFERENCE='66f85d61bf4d3ba9a01efdc0e9eb68949419bda8'
COHORT_AUTHORITY_DELTAS={
    # One post-mutation authenticated Survivor reporting population; reverse
    # this exact block before every original strategy/source assertion.
    'meme_machine/lanes/pons/pons_survivor_runtime.py': (
        '2eb7a93827981696edc26115c1c8259d00f30c76a007249ddb8592d03fd3e389',
        'dd126e490b53bba0b414355d12ab617c56b9adc09438457ff630e0ee281202b8',
        ((b"        from meme_machine.runtime.directional_accounting import execution_cost\n        self.attempts.maintain(self.now(),protected=(r['id'] for r in self.history.rows()))\n        return dict(strategy=STRATEGY_VERSION,policy_hash=POLICY_HASH,active=True,paper_only=True,\n                    admission=dict(position_count_limit=None,capital_authority='native_shared_sleeve',\n                        legacy_policy_count_is_not_enforced=True,owner_change='2026-10-09'),\n                    position_safety=[r.get('position_safety',dict(at=0,evidence_current=False,\n                        blocker='pons_survivor_position_not_observed')) for r in self.history.rows() if r.get('position')],\n                    native_execution_cost=execution_cost(self.book),\n                    candidate_count=len(self.history.rows()),last_boundary=self.last_error,\n                    discovery_capacity_deferred=False,\n                    pending_graduations=self.history.pending_graduations(),\n                    deferred_boundaries=errors,\n                    acquisition=getattr(self,'acquisition',None),\n                    historical_readiness=getattr(self,'historical_readiness',None),\n                    qualification_authority='candidate_specific_authenticated_evidence',\n                    accounting=self.book.reconcile(),accounting_replay=self.book.replay(),\n                    policies=self.sleeve.identity['policies'],sleeve=self.sleeve.reconcile(),\n                    durable_handoff=handoff_ready(self.book,self.history.rows()),\n                    held_paper_shadow=(getattr(self,'held_paper_shadow',None).status()\n                        if getattr(self,'held_paper_shadow',None) is not None else\n                        dict(enabled=False,mode='PAPER_SHADOW_ONLY')))\n\n",
          b"        from meme_machine.runtime.directional_accounting import execution_cost\n        # All strategy/history mutations above have finished on this owner.\n        # Authenticate one final population for this report; attempts maintenance\n        # writes the separate candidate plane, never this native history.\n        final_rows=self.history.rows()\n        self.attempts.maintain(self.now(),protected=(r['id'] for r in final_rows))\n        return dict(strategy=STRATEGY_VERSION,policy_hash=POLICY_HASH,active=True,paper_only=True,\n                    admission=dict(position_count_limit=None,capital_authority='native_shared_sleeve',\n                        legacy_policy_count_is_not_enforced=True,owner_change='2026-10-09'),\n                    position_safety=[r.get('position_safety',dict(at=0,evidence_current=False,\n                        blocker='pons_survivor_position_not_observed')) for r in final_rows if r.get('position')],\n                    native_execution_cost=execution_cost(self.book),\n                    candidate_count=len(final_rows),last_boundary=self.last_error,\n                    discovery_capacity_deferred=False,\n                    pending_graduations=self.history.pending_graduations(),\n                    deferred_boundaries=errors,\n                    acquisition=getattr(self,'acquisition',None),\n                    historical_readiness=getattr(self,'historical_readiness',None),\n                    qualification_authority='candidate_specific_authenticated_evidence',\n                    accounting=self.book.reconcile(),accounting_replay=self.book.replay(),\n                    policies=self.sleeve.identity['policies'],sleeve=self.sleeve.reconcile(),\n                    durable_handoff=handoff_ready(self.book,final_rows),\n                    held_paper_shadow=(getattr(self,'held_paper_shadow',None).status()\n                        if getattr(self,'held_paper_shadow',None) is not None else\n                        dict(enabled=False,mode='PAPER_SHADOW_ONLY')))\n\n"),)),
    # Reporting-only reuse: exact bytes reverse to the approved strategy
    # source; no decision, economic or acquisition code is exempted.
    'meme_machine/lanes/pons/pipeline.py': (
        '21ba397b3c695e18b3a22c65b7c0bd0edde2c3b393ee83064c308337851a64e5',
        'e9a848cb9f2b9ea28c8415fc495cc28712dd4de9c18129253ec316ae4195a622',
        (
            (b'        self.last=None;self.write_seconds=0.;self.records=0\n',
             b'        self.last=None;self.write_seconds=0.;self.records=0\n'
             b'        self._policy_count_generation=None;self._policy_counts=None\n'),
            (b'    def snapshot(self):\n',
             b'    def _retained_policy_counts(self):\n'
             b"        # The caller holds this Pipeline's lock. Local writes/retention change\n"
             b'        # total_changes; independent connection commits change data_version.\n'
             b'        # Never save or reuse an aggregate from a caller-owned transaction.\n'
             b"        query='SELECT policy_hash,COUNT(*) FROM progress GROUP BY policy_hash'\n"
             b'        if self.db.in_transaction:return dict(self.db.execute(query))\n'
             b"        generation=(self.db.total_changes,self.db.execute('PRAGMA data_version').fetchone()[0])\n"
             b'        if generation!=self._policy_count_generation:\n'
             b'            counts=dict(self.db.execute(query))\n'
             b'            self._policy_counts=counts;self._policy_count_generation=generation\n'
             b'        return dict(self._policy_counts)\n'
             b'\n'
             b'    def snapshot(self):\n'),
            (b"retained_policy_record_counts=dict(self.db.execute('SELECT policy_hash,COUNT(*) FROM progress GROUP BY policy_hash'))",
             b'retained_policy_record_counts=self._retained_policy_counts()'),
        )),
    'meme_machine/lanes/pons/pons_selective_cohort.py': (
        '01340dc4a2f0994f3c6508f8ab7d8e8e6f25a1a33b4e568b3013418793a34203',
        'c02656621b57e3c3a2533f79249d012c20ecddbfaf686c21683e989eded3aec8',
        ((b'    recovered=(recover_cohort(plane_path(ROOT/"candidate-evidence.sqlite"),POLICY_HASH) if occupied else None)\n',
          b'    recovered=(recover_cohort(plane_path(ROOT/"candidate-evidence.sqlite"),POLICY_HASH,\n'
          b"        capital_path=ROOT/'pons-selective-cohort-capital.sqlite') if occupied else None)\n"),
         # Diagnostic executor names only: identical worker counts, functions,
         # deadlines and economic behavior. Reverse these exact bytes before
         # applying the existing combined-source/economic assertions below.
         (b'hydration_pool=ThreadPoolExecutor(max_workers=1)',
          b"hydration_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='pons-hydration')"),
         (b'discovery_pool=ThreadPoolExecutor(max_workers=2)',
          b"discovery_pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='pons-discovery')"))),
    'meme_machine/runtime/robinhood/pons.py': (
        '530108cf5539890547a5604c855ca49a75ae9a96d6e0c2630041dcb23f613209',
        'ad75892a39a0b6ca898f90a0f698e7eb80ad8c7928820286babc46f5b697028c',
        ((b'def recover_cohort(path,policy):\n',b'def recover_cohort(path,policy,*,capital_path=None):\n'),
         (b"            capital=Path(path).parent/'pons-selective-cohort-capital.sqlite'\n",
          b'            # The shared evidence/cache plane need not be beside native capital.\n'
          b'            # The controller supplies its existing authority; standalone callers\n'
          b'            # retain the original colocated layout.\n'
          b'            capital=(Path(capital_path) if capital_path is not None else\n'
          b"                Path(path).parent/'pons-selective-cohort-capital.sqlite')\n"))),
}


# Startup resource ownership and constructor-only cancellation are explicitly
# reviewed infrastructure changes. Reverse their exact additions to c8 before
# retaining every previous strategy/source assertion. In particular, no part of
# main's economic loop or Survivor's normal step is exempted.
NATIVE_STARTUP_REFERENCE='c8beb2d1317084779f97214b6015b7c345242085'
NATIVE_STARTUP_DELTAS={
    'meme_machine/lanes/pump/runner.py': (
        'f94dc8512ae8e7e0446040db08e4736aad9b32fdb1bd6e65d5d1d7670ec0b884',
        'ca83600f6a54806b52c4f6625d1b30d482e922e82db17d086e1ca055485c6a41'),
    'meme_machine/runtime/survivor_history.py': (
        '69ccc56e918403a2d7939d71c76f84beaa34388f5975be9f5904fdcdd30e7b03',
        '22ab2268bb4b23997314889c7e6936706a7a47a1e3301341e699acc51989ce40'),
}


def native_startup_predecessor(test,relative,current):
    import hashlib
    if isinstance(current,str):current=current.encode()
    current=reviewed_operation_costs(test,relative,current)
    reviewed=NATIVE_STARTUP_DELTAS.get(relative)
    if reviewed is None:return current
    prior=subprocess.check_output(['git','show',NATIVE_STARTUP_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),reviewed[0],relative+':tested lifecycle predecessor')
    if current==prior:return prior
    test.assertEqual(hashlib.sha256(current).hexdigest(),reviewed[1],relative+':exact lifecycle successor')
    if relative=='meme_machine/lanes/pump/runner.py':
        for line in (b'from contextlib import ExitStack\n',b'from contextvars import ContextVar\n',
                     b'from functools import wraps\n',b'@_startup_lifecycle\n'):
            test.assertEqual(current.count(line),1,relative+':one lifecycle addition')
            current=current.replace(line,b'',1)
        first=current.index(b"_STARTUP_RESOURCES=ContextVar('pump_startup_resources',default=None)")
        last=current.index(b'def _startup_work(',first)
        current=current[:first]+b'\n'+current[last:]
        selected=next(n for n in ast.parse(current).body if isinstance(n,ast.FunctionDef) and n.name=='_startup_work')
        original=next(n for n in ast.parse(prior).body if isinstance(n,ast.FunctionDef) and n.name=='_startup_work')
        test.assertEqual(ast.dump(selected.args),ast.dump(original.args),relative+':unchanged startup interface')
        lines=current.splitlines(keepends=True);old=prior.splitlines(keepends=True)
        lines[selected.lineno-1:selected.end_lineno]=old[original.lineno-1:original.end_lineno]
        current=b''.join(lines)
        constructor=(b"            lambda:_startup_work('pump.survivor_runtime_restore',Runtime,\n"
                     b"                REPORT.parent/'pump-survivor',INITIAL_LAMPORTS,run_id,confirmations))\n")
        test.assertEqual(current.count(constructor),1,relative+':one owned factory attribution')
        current=current.replace(constructor,
            b"            lambda:Runtime(REPORT.parent/'pump-survivor',INITIAL_LAMPORTS,run_id,confirmations))\n",1)
        main=next(n for n in ast.parse(current).body if isinstance(n,ast.FunctionDef) and n.name=='main')
        loops=[n for n in main.body if isinstance(n,ast.Try)]
        test.assertEqual(len(loops),1,relative+':one unchanged native loop')
        final=loops[0].finalbody
        test.assertEqual(len(final),2,relative+':only reviewed cleanup wrapper')
        test.assertEqual(ast.dump(final[0]),ast.dump(ast.parse(
            'from meme_machine.runtime.sqlite_failure import preserving_cleanup').body[0]))
        test.assertIsInstance(final[1],ast.With)
        test.assertEqual(ast.dump(final[1].items[0].context_expr),ast.dump(ast.parse(
            'preserving_cleanup()',mode='eval').body))
        test.assertEqual(len(final[1].items),1)
        lines=current.splitlines(keepends=True)
        body=lines[final[1].body[0].lineno-1:final[1].end_lineno]
        test.assertTrue(all(not line.strip() or line.startswith(b'    ') for line in body))
        lines[final[0].lineno-1:final[1].end_lineno]=[line[4:] if line.strip() else line for line in body]
        current=b''.join(lines)
        for identity,value,method in (
            ('survivor_worker_open','survivor','close'),('sessions_open','sessions','finish'),
            ('evidence_broker_open','broker','close'),('runtime_evidence_open','plane','close'),
            ('candidate_history_open','CANDIDATE_HISTORY','close'),
            ('accounting_restore','ACCOUNTING','close'),('pipeline_open','PIPELINE','close')):
            owned=("_close_startup_resource('pump."+identity+"',"+value+")").encode()
            test.assertEqual(current.count(owned),1,relative+':one owned normal cleanup '+identity)
            current=current.replace(owned,(value+'.'+method+'()').encode(),1)
    else:
        addition=(b'        if self.service is None:\n'
            b'            from meme_machine.shared_capital.runtime import native_startup_replay\n'
            b'            from meme_machine.runtime.stop import requested\n'
            b'            # The factory owns its SQLite objects on this executor. Only its\n'
            b'            # initial read-only capital replay may observe startup cancellation;\n'
            b'            # ordinary protection/settlement steps keep their existing behavior.\n'
            b'            with native_startup_replay(requested.is_set):self.service=self.factory()\n')
        test.assertEqual(current.count(addition),1,relative+':one constructor-only scope')
        current=current.replace(addition,b'        if self.service is None:self.service=self.factory()\n',1)
    test.assertEqual(current,prior,relative+':all other economic/source bytes unchanged')
    return prior


def reviewed_native_startup(test,relative,current):
    import hashlib
    if isinstance(current,str):current=current.encode()
    current=reviewed_operation_costs(test,relative,current)
    reviewed=NATIVE_STARTUP_DELTAS.get(relative)
    if reviewed and hashlib.sha256(current).hexdigest()==reviewed[1]:
        return native_startup_predecessor(test,relative,current)
    return current


# Exact infrastructure deltas demonstrated by the 22:40:46 observation and
# disposable crash/cancellation regressions. Reverse only these reviewed nodes
# to the tested 1fe5 source before applying every existing economic/source guard.
OBSERVATION_FOLLOWUP_REFERENCE='1fe5a6f62d37f84ad24f0b7413279c080e3424e5'
OBSERVATION_FOLLOWUP_DELTAS={
    'meme_machine/lanes/pump/runner.py': (
        '0cc465a0a17e88735fc26b3ab43400d68ab38a4ab91358f832fde90597c77f68',
        'f94dc8512ae8e7e0446040db08e4736aad9b32fdb1bd6e65d5d1d7670ec0b884',
        ('_restore_observed_pump_candidates',)),
    'meme_machine/runtime/robinhood/pons.py': (
        'ad75892a39a0b6ca898f90a0f698e7eb80ad8c7928820286babc46f5b697028c',
        '2ca1a6a84f52691e37cb15c7d9c4b574a9b95115492ac874f4710d32ed35d526',
        ('Broker.__init__','Broker._renew_retained_interpretation',
         'Broker._remember_watch','Broker._sync_watch_order','Broker._enqueue',
         # O5 report-only totals now project the same fresh native counters
         # without full endpoint health/CU reporting; every other byte stays.
         'provider_totals')),
}


def observation_followup_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    current=reviewed_native_startup(test,relative,current)
    reviewed=OBSERVATION_FOLLOWUP_DELTAS.get(relative)
    if reviewed is None:return current
    before,after,names=reviewed
    prior=subprocess.check_output(['git','show',OBSERVATION_FOLLOWUP_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),before,relative+':tested observation predecessor')
    if current==prior:return prior
    test.assertEqual(hashlib.sha256(current).hexdigest(),after,relative+':exact reviewed observation repair')
    def selected(content,name):
        parent=ast.parse(content)
        for part in name.split('.')[:-1]:
            parent=next(n for n in parent.body if isinstance(n,ast.ClassDef) and n.name==part)
        return next(n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name==name.split('.')[-1])
    lines=current.splitlines(keepends=True);old_lines=prior.splitlines(keepends=True)
    replacements=[]
    for name in names:
        node=selected(current,name);old=selected(prior,name)
        expected=deepcopy(old.args)
        if name=='Broker._remember_watch':
            # Only the reviewed crash-recovery call may discard an invalidated
            # adapter-bound attention summary. Ordinary callers keep it.
            expected.kwonlyargs.append(ast.arg(arg='reset_quality'))
            expected.kw_defaults.append(ast.Constant(value=False))
        test.assertEqual(ast.dump(node.args),ast.dump(expected),relative+':exact reviewed interface '+name)
        test.assertNotEqual(ast.dump(node),ast.dump(old),relative+':explicit reviewed node '+name)
        replacements.append((node.lineno-1,node.end_lineno,old_lines[old.lineno-1:old.end_lineno]))
    for first,last,body in sorted(replacements,reverse=True):lines[first:last]=body
    test.assertEqual(b''.join(lines),prior,relative+':all other bytes and economic nodes unchanged')
    return prior


def cohort_authority_predecessor(test,relative,current):
    import hashlib
    if isinstance(current,str):current=current.encode()
    current=reviewed_operation_costs(test,relative,current)
    followup=OBSERVATION_FOLLOWUP_DELTAS.get(relative)
    if followup and hashlib.sha256(current).hexdigest()==followup[1]:
        current=observation_followup_predecessor(test,relative,current)
    reviewed=COHORT_AUTHORITY_DELTAS.get(relative)
    if reviewed is None:return current
    before,after,replacements=reviewed
    prior=subprocess.check_output(['git','show',COHORT_AUTHORITY_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),before,relative+':reviewed authority predecessor')
    if current==prior:return current
    test.assertEqual(hashlib.sha256(current).hexdigest(),after,relative+':exact reviewed authority successor')
    for old,new in replacements:
        test.assertEqual(current.count(new),1,relative+':one exact authority delta')
        current=current.replace(new,old,1)
    test.assertEqual(current,prior,relative+':all other source bytes preserved')
    return current


# Constructor cancellation is authorized only for the reproduced native
# startup read. Exact complete-source pins plus reversible named-node checks
# keep every economic sibling, interface and constant in the original guards.
STARTUP_CANCEL_DELTAS={
    'meme_machine/lanes/pump/paper_accounting.py': (
        '5f8107761615f6648fa72e8bc470d3f296af5794255d505427c5a2f77cdd17fe',
        'e40166b342c03ff79121d1cba921f21880f0d639451d89530066c3371178523f',
        ('PaperBook.__init__',),(),()),
    'meme_machine/lanes/pump/runner.py': (
        'd621e3037f769fc9ac8c21c811523097f08b1172552dec9e6324d6d3b2365d32',
        '0cc465a0a17e88735fc26b3ab43400d68ab38a4ab91358f832fde90597c77f68',
        ('_startup_work',),(),()),
    'meme_machine/shared_capital/authority.py': (
        '8bad413009a5f14aa91710b8051d9ae311044400edc12f7bbe6e9f7999c711ef',
        'd31765d115545d30fb4dd0ba9d2523c5e4f5b86365673b4a94a67d45906c1839',
        ('CapitalAuthority.__init__','CapitalAuthority._transaction',
         'CapitalAuthority._verify_replay','CapitalAuthority._authenticated_replay_prefix'),
        ('CapitalAuthority._check_startup_replay_cancel',),()),
    'meme_machine/shared_capital/runtime.py': (
        '313bff34c4ef6f5d9418991fb66039239975a8db629cae576a0771982ea69585',
        'a8905fb779a02c4721b6fa0858eb3716eca2d63e9e407a31f97a1f18c384738a',
        ('connection',),('native_startup_replay',),
        ('from contextvars import ContextVar',
         "_STARTUP_REPLAY_CANCEL=ContextVar('native_startup_replay_cancel',default=None)")),
}


def startup_cancel_predecessor(test,relative,current):
    from copy import deepcopy
    import hashlib
    if isinstance(current,str):current=current.encode()
    current=reviewed_native_startup(test,relative,current)
    followup=OBSERVATION_FOLLOWUP_DELTAS.get(relative)
    if followup and hashlib.sha256(current).hexdigest()==followup[1]:
        current=observation_followup_predecessor(test,relative,current)
    reviewed=STARTUP_CANCEL_DELTAS.get(relative)
    if reviewed is None:return current
    before,after,changed,added,top_additions=reviewed
    prior=subprocess.check_output(['git','show',COHORT_AUTHORITY_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(prior).hexdigest(),before,relative+':reviewed startup predecessor')
    if current==prior:return current
    test.assertEqual(hashlib.sha256(current).hexdigest(),after,relative+':exact reviewed startup successor')
    tree=ast.parse(current);old=ast.parse(prior)
    def node(root,name):
        parent=root
        for part in name.split('.')[:-1]:
            parent=next(n for n in parent.body if isinstance(n,ast.ClassDef) and n.name==part)
        return parent,next(n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name==name.split('.')[-1])
    for name in changed:
        parent,selected=node(tree,name);_,original=node(old,name)
        test.assertNotEqual(ast.dump(selected),ast.dump(original),relative+':explicit changed node '+name)
        parent.body[parent.body.index(selected)]=deepcopy(original)
    for name in added:
        parent,selected=node(tree,name);parent.body.remove(selected)
        with test.assertRaises(StopIteration):node(old,name)
    for source in top_additions:
        addition=ast.parse(source).body[0]
        matches=[n for n in tree.body if ast.dump(n)==ast.dump(addition)]
        test.assertEqual(len(matches),1,relative+':one explicit startup-only top-level addition')
        tree.body.remove(matches[0])
    test.assertEqual(ast.dump(tree),ast.dump(old),relative+':all other source nodes retained')
    return prior


def assert_opportunity_added_source(test,relative,current):
    import hashlib,json
    if isinstance(current,str):current=current.encode()
    current=rally_predecessor(test,relative,current,allow_previous_layers=True)
    manifest=json.loads(OPPORTUNITY_MANIFEST.read_text())
    test.assertEqual(manifest['strategy_implementation'],OPPORTUNITY_REFERENCE)
    test.assertEqual(set(manifest['added_sources']),set(OPPORTUNITY_ADDED_SOURCES))
    test.assertIn(relative,OPPORTUNITY_ADDED_SOURCES)
    published=subprocess.check_output(['git','show',OPPORTUNITY_REFERENCE+':'+relative],cwd=ROOT)
    test.assertEqual(hashlib.sha256(published).hexdigest(),manifest['added_sources'][relative]['sha256'],relative+':published added source')
    test.assertEqual(current,published,relative+':exact approved added source')
    for predecessor in (OPPORTUNITY_BASE,OPPORTUNITY_STRATEGY_BASE):
        test.assertNotEqual(subprocess.run(['git','cat-file','-e',predecessor+':'+relative],cwd=ROOT,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False).returncode,0,
            relative+':must remain an explicit package addition')


def opportunity_predecessor(test,relative,current):
    import hashlib,json
    if isinstance(current,str):current=current.encode()
    current=rally_predecessor(test,relative,current,allow_previous_layers=True)
    if relative=='meme_machine/lanes/pons/evidence.py':
        # The complete lane-tree guard also protects this non-manifest source.
        current=operation_cost_predecessor(test,relative,current)
    current=startup_cancel_predecessor(test,relative,current)
    manifest=json.loads(OPPORTUNITY_MANIFEST.read_text())
    test.assertEqual(manifest['base'],OPPORTUNITY_BASE)
    test.assertEqual(manifest['strategy_base'],OPPORTUNITY_STRATEGY_BASE)
    test.assertEqual(manifest['strategy_implementation'],OPPORTUNITY_REFERENCE)
    test.assertEqual(manifest['original_manifest_sha256'],OPPORTUNITY_ORIGINAL_MANIFEST_SHA256)
    record=manifest['files'].get(relative)
    if record is None:return current
    try:prior=subprocess.check_output(['git','show',OPPORTUNITY_BASE+':'+relative],cwd=ROOT,stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        raise unittest.SkipTest('Historical source comparison needs the existing baseline commit') from None
    test.assertEqual(hashlib.sha256(prior).hexdigest(),record['before_sha256'],relative+':opportunity predecessor')
    if current==prior:return current
    current=cohort_authority_predecessor(test,relative,current)
    current=observation_route_predecessor(test,relative,current)
    test.assertEqual(hashlib.sha256(current).hexdigest(),record['after_sha256'],relative+':approved opportunity source')
    def nodes(content):
        result={}
        for node in ast.parse(content).body:
            if isinstance(node,(ast.FunctionDef,ast.ClassDef)):key=type(node).__name__+':'+node.name
            elif isinstance(node,ast.Assign):key='Assign:'+','.join(ast.dump(t) for t in node.targets)
            elif isinstance(node,ast.AnnAssign):key='AnnAssign:'+ast.dump(node.target)
            elif isinstance(node,ast.ImportFrom):key='ImportFrom:'+str(node.level)+':'+str(node.module)
            elif isinstance(node,ast.Import):key='Import:'+node.names[0].name
            elif isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):key='module_docstring'
            else:key=type(node).__name__+':'+ast.dump(node)
            test.assertNotIn(key,result,relative+':duplicate protected node')
            result[key]=hashlib.sha256(ast.dump(node).encode()).hexdigest()
        return result
    before=nodes(prior);after=nodes(current)
    actual={key:dict(before=before.get(key),after=after.get(key))
        for key in before.keys()|after.keys() if before.get(key)!=after.get(key)}
    test.assertEqual(actual,record['nodes'],relative+':exact authorized node changes')
    def dictionary(content,name):
        assignment=next(n for n in ast.parse(content).body if isinstance(n,ast.Assign)
            and any(isinstance(t,ast.Name) and t.id==name for t in n.targets))
        return eval(compile(ast.Expression(assignment.value),'<reviewed-policy>','eval'),
            {'dict':dict,'ACTIVE_REVISION':'paper-opportunity-access-v1',
             'STRATEGY_ID':'pumpswap-survivor-momentum-v1'})
    if relative.endswith('pons_selective_continuation.py'):
        for name in ('ENTRY_THRESHOLDS','EXIT_POLICY','POST_GRAD_THRESHOLDS','REENTRY_POLICY','BREAKOUT_THRESHOLDS'):
            expected=dictionary(prior,name)
            if name=='ENTRY_THRESHOLDS':expected.update(require_curve_acceleration=False,require_flow_acceleration=False)
            if name=='EXIT_POLICY':expected.update(positive_demand_slowing_exit_authority=False,stale_high_breadth_exit_authority=False)
            test.assertEqual(dictionary(current,name),expected,name+':only C1/C6 metadata deltas')
    elif relative.endswith('pons_postgrad_survivor.py'):
        expected=dictionary(prior,'POLICY');expected['revision']='paper-opportunity-access-v1'
        expected['demand']['require_buy_acceleration']=False
        test.assertEqual(dictionary(current,'POLICY'),expected,'only C5/revision scalar deltas')
    elif relative.endswith('pumpswap_survivor.py'):
        expected=dictionary(prior,'POLICY')
        expected.update(revision='paper-opportunity-access-v1',minimum_reset_bps=300,compression_bps=10000)
        test.assertEqual(dictionary(current,'POLICY'),expected,'only C4/revision scalar deltas')
    elif relative.endswith('pump_acceleration_strategy.py'):
        def scalars(content):
            cls=next(n for n in ast.parse(content).body if isinstance(n,ast.ClassDef) and n.name=='FrozenPolicy')
            return {n.target.id:ast.dump(n.value) for n in cls.body if isinstance(n,ast.AnnAssign)}
        before_scalars=scalars(prior);after_scalars=scalars(current)
        changed={k for k in before_scalars.keys()|after_scalars.keys() if before_scalars.get(k)!=after_scalars.get(k)}
        test.assertEqual(changed,{'version','revision'},'C2 changes no retained numerical threshold')
        test.assertEqual(after_scalars['revision'],ast.dump(ast.Name(id='ACTIVE_REVISION',ctx=ast.Load())))
        def version(content):
            cls=next(n for n in ast.parse(content).body if isinstance(n,ast.ClassDef) and n.name=='FrozenPolicy')
            node=next(n for n in cls.body if isinstance(n,ast.AnnAssign) and n.target.id=='version')
            return eval(compile(ast.Expression(node.value),'<reviewed-version>','eval'),
                {'STRATEGY_ID':'pump-acceleration-independent-v1','ACTIVE_REVISION':'paper-opportunity-access-v1'})
        test.assertEqual(version(current),version(prior)+'-paper-opportunity-access-v1')
        test.assertEqual({k:dict(before=before_scalars.get(k),after=after_scalars.get(k)) for k in before_scalars.keys()|after_scalars.keys()
            if before_scalars.get(k)!=after_scalars.get(k)},record['policy_scalar_deltas'])
    return prior


PUMP_DIAGNOSTIC_REFERENCE = 'ddcee53eb2498b7281820793408abbea71f2e88a'
PUMP_DIAGNOSTIC_NODES = {
    '_startup_work': '40d75f326ff37e06a4bd89390c5f833526ab601cd15aad918841a16e7d90496a',
    '_restore_observed_pump_candidates': '733e3f925b85924f7ec3b98197e41561ca59e93ff854e8cd66a63cb03e59e0ac',
    'main': '985426c540e43cb439a068e52ee3f9b0a7744abd22625cf4d0f99b7a2754de69',
}

# These are exact combined nodes, not broader infrastructure exemptions. The
# reviewed diagnostic layer must strip to the published strategy implementation,
# while its operational predecessor still strips to the original ddcee source.
COMBINED_PUMP_DIAGNOSTIC_NODES = {
    **PUMP_DIAGNOSTIC_NODES,
    'main': '5f27be1968411202d86f00c20d109423ac6399acfbfdd21ab1d457e88d0f423a',
}

class _RemoveReviewedPumpDiagnostics(ast.NodeTransformer):
    """Only used after the complete changed nodes pass their exact AST pins."""
    def visit_FunctionDef(self,node):
        if node.name=='_startup_work':return None
        return self.generic_visit(node)
    def visit_Call(self,node):
        self.generic_visit(node)
        if isinstance(node.func,ast.Name) and node.func.id=='_startup_work':
            return ast.copy_location(ast.Call(func=node.args[1],args=node.args[2:],keywords=node.keywords),node)
        return node
    def visit_ImportFrom(self,node):
        if (node.module=='meme_machine.runtime.status' and
                [(a.name,a.asname) for a in node.names]==[('operation',None)]):return None
        return node
    def visit_With(self,node):
        self.generic_visit(node)
        if (len(node.items)==1 and isinstance(node.items[0].context_expr,ast.Call) and
                isinstance(node.items[0].context_expr.func,ast.Name) and
                node.items[0].context_expr.func.id=='operation'):return node.body
        return node

def pump_economic_tree(test,content,*,combined=False):
    if combined:
        # The separately pinned constructor-cancellation wrapper is reversed
        # before this older attribution layer. Its original exact node guards
        # and all negative mutation checks remain unchanged.
        content=startup_cancel_predecessor(test,'meme_machine/lanes/pump/runner.py',content)
    tree=ast.parse(content)
    nodes={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
    if '_startup_work' not in nodes:return tree
    # Owner-authorized startup attribution only. Every wrapped call, argument,
    # fixed identifier and wrapper body pins before removing passive diagnostics.
    # The resulting entire source must equal the published pre-repair source.
    pins=COMBINED_PUMP_DIAGNOSTIC_NODES if combined else PUMP_DIAGNOSTIC_NODES
    for name,pinned in pins.items():
        test.assertEqual(__import__('hashlib').sha256(ast.dump(nodes[name]).encode()).hexdigest(),pinned,name)
    stripped=_RemoveReviewedPumpDiagnostics().visit(tree)
    reference=OPPORTUNITY_REFERENCE if combined else PUMP_DIAGNOSTIC_REFERENCE
    prior=subprocess.check_output(['git','show',reference+':meme_machine/lanes/pump/runner.py'],cwd=ROOT)
    test.assertEqual(ast.dump(stripped),ast.dump(ast.parse(prior)),'diagnostics cannot change any runtime economics')
    return stripped

def assert_attention_node(test,relative,name,node):
    current=guarded_source(test,relative)
    prior=opportunity_predecessor(test,relative,current)
    if prior!=current:
        selected=ast.parse(current);previous=ast.parse(prior)
        for part in name.split('.'):
            selected=next(n for n in selected.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name==part)
            previous=next(n for n in previous.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name==part)
        test.assertIn(ast.dump(node),(ast.dump(selected),ast.dump(previous)),relative+':'+name+':reviewed current node')
        node=previous
    if relative=='meme_machine/lanes/pump/runner.py' and name in PUMP_DIAGNOSTIC_NODES:
        from copy import deepcopy
        test.assertEqual(__import__('hashlib').sha256(ast.dump(node).encode()).hexdigest(),PUMP_DIAGNOSTIC_NODES[name],name)
        node=_RemoveReviewedPumpDiagnostics().visit(deepcopy(node))
    expected={**ATTENTION_DELTAS.get(relative,{}),**OPERATION_DELTAS.get(relative,{})}[name]
    test.assertEqual(__import__('hashlib').sha256(ast.dump(node).encode()).hexdigest(),expected,relative+':'+name)


def assert_holding_delta(test, relative, original, current, *, reviewed_lifecycle=True,reviewed_opportunity=True):
    if reviewed_opportunity:current=opportunity_predecessor(test,relative,current)
    if reviewed_lifecycle and relative in LIFECYCLE_SOURCE_DELTAS:
        reviewed=LIFECYCLE_SOURCE_DELTAS[relative]
        prior=subprocess.check_output(['git','show',LIFECYCLE_PACKAGE_BASE+':'+relative],cwd=ROOT)
        sha256=__import__('hashlib').sha256
        test.assertEqual(sha256(prior).hexdigest(),reviewed['before_sha256'],relative+':prior lifecycle source')
        test.assertEqual(sha256(current).hexdigest(),reviewed['reviewed_sha256'],relative+':reviewed lifecycle source')
        assert_holding_delta(test,relative,original,prior,reviewed_lifecycle=False,reviewed_opportunity=False)
        return
    if relative in ACQUISITION_SOURCE_DELTAS:
        reviewed=ACQUISITION_SOURCE_DELTAS[relative]
        sha256=__import__('hashlib').sha256
        test.assertEqual(sha256(original).hexdigest(),reviewed['before_sha256'],relative+':original')
        test.assertEqual(sha256(current).hexdigest(),reviewed['reviewed_sha256'],relative+':reviewed acquisition')
        return
    expected=dict(HOLDING_DELTAS.get(relative,{}))
    expected.update(ATTENTION_DELTAS.get(relative,{}))
    expected.update(OPERATION_DELTAS.get(relative,{}))
    old=ast.parse(original)
    new=pump_economic_tree(test,current) if relative=='meme_machine/lanes/pump/runner.py' else ast.parse(current)
    for name,pinned in expected.items():
        before=old;after=new
        for part in name.split('.'):
            before=next((n for n in before.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name==part),None) if before is not None else None
            after=next(n for n in after.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name==part)
        test.assertEqual(__import__('hashlib').sha256(ast.dump(after).encode()).hexdigest(),pinned,relative+':'+name)
        if before is None:
            # Only the explicitly pinned attention helper may be new. Remove
            # that node for the historical sibling/interface comparison.
            test.assertIn(name,('_volume_quality_attention','Runtime._quality_rank','_retain_tape_history','_observed_creation','LocalPumpTape._creation'))
            owner=new
            for part in name.split('.')[:-1]:owner=next(n for n in owner.body if isinstance(n,ast.ClassDef) and n.name==part)
            owner.body.remove(after)
            continue
        # Retain the full function interface/decorators and every sibling node.
        before.body=[ast.Pass()];after.body=[ast.Pass()]
    test.assertEqual(ast.dump(old),ast.dump(new),relative)


def abi(*values):
    return '0x'+''.join(f'{int(v,16) if isinstance(v,str) else v%(1<<256):064x}' for v in values)


def text_abi(value):
    raw=value.encode()
    return abi(32,len(raw))+raw.hex()+('00'*((-len(raw))%32))


class ReadRPC:
    """The real authentication/route decoders consume these synthetic RPC facts."""
    def __init__(self):
        self.now=NOW
        self.answer=100013961
        self.round=[ROUND,self.answer,UPDATED-12,UPDATED,ROUND]
        self.description='USDG / USD'
        self.feed_decimals=8
        self.token_decimals=6
        self.chain=4663
        self.chain_verified=False
        self.feed_code='0x60006000'
        self.failed=False
        self.calls=[]
        self.route_output=2500000  # 0.001 ETH -> 2.5 USDG, including route fee
        self.unfilled=0
        self.hooks=0
        self.no_pairs=False
        self.bad_factory=False
        self.bad_pool=False
        self.router=load('ramses_router')
        self.factory=load('ramses_factory')
        implementation=load('ramses_pool_implementation')['address'][2:]
        self.pool_code=('0x363d3d373d3d3d3d61002c806035363936013d73'+implementation
            +'5af43d3d93803e603357fd5bf3'+WNATIVE[2:]+USDG_ASSET[2:]+'000a002c')

    def verify_chain(self):
        self.call('eth_chainId',[])
        self.chain_verified=True
        return self.chain

    def batch(self,calls,*,scope):
        return [self.call(method,params,scope=scope) for method,params in calls]

    def call(self,method,params,*,scope=None):
        self.calls.append((method,params,scope))
        if self.failed:raise OSError('https://example.invalid/private-provider-secret')
        if method=='eth_chainId':return hex(self.chain)
        if not self.chain_verified:raise AssertionError('provider_chain_identity_unverified')
        if method=='eth_getBlockByNumber':
            return dict(number='0x4bdc170',hash='0x'+'12'*32,timestamp=hex(self.now))
        if method=='eth_getCode':
            address=params[0].lower()
            if address==USDG_FEED.lower():return self.feed_code
            if address==self.router['address'].lower():return self.router['runtimeBytecode']['onchainBytecode']
            if address==self.factory['address'].lower():
                return '0x6000' if self.bad_factory else self.factory['runtimeBytecode']['onchainBytecode']
            if address==POOL:return '0x6000' if self.bad_pool else self.pool_code
            if address in (USDG_ASSET,AGGREGATOR):return '0x6000'
        if method=='eth_call':
            address=params[0]['to'].lower();data=params[0]['data']
            if address==USDG_FEED.lower():
                reads={
                    calldata('description()'):text_abi(self.description),
                    calldata('decimals()'):abi(self.feed_decimals),
                    calldata('latestRoundData()'):abi(*self.round),
                    calldata('aggregator()'):abi(AGGREGATOR),
                    calldata('version()'):abi(6),
                }
                return reads[data]
            if address==USDG_ASSET and data==calldata('decimals()'):return abi(self.token_decimals)
            if address==self.router['address'].lower() and data==calldata('getWNATIVE()'):return abi(WNATIVE)
            if address==self.factory['address'].lower():
                if data!=calldata('getAllLBPairs(address,address)',WNATIVE,USDG_ASSET):raise AssertionError('wrong route tokens')
                return abi(32,0) if self.no_pairs else abi(32,1,10,POOL,1,0)
            if address==POOL:
                if data==calldata('getLBHooksParameters()'):return abi(self.hooks)
                if data==calldata('getSwapOut(uint128,bool)',10**15,1):return abi(self.unfilled,self.route_output,1000)
        raise AssertionError('unexpected read-only RPC call')


class RobinhoodUSDTests(unittest.TestCase):
    def test_cross_candidate_archive_review_keeps_all_previous_source_guards(self):
        import hashlib
        for path in sorted(CROSS_CANDIDATE_COLD_PATHS):
            with self.subTest(path=path):
                current=pump_restore_predecessor(self,path,(ROOT/path).read_bytes())
                old=subprocess.check_output(['git','show',CROSS_CANDIDATE_COLD_BASE+':'+path],cwd=ROOT)
                self.assertNotEqual(current,old)
                self.assertEqual(cross_candidate_cold_predecessor(self,path,current),old)
                # The pre-existing Pump runner guard first reverses its exact
                # publication/accounting layer, then the rally/strategy layers.
                # Retain that original order rather than inventing an earlier
                # direct shortcut through the protected source chain.
                reviewed=publication_accounting_predecessor(self,path,current)
                predecessor=publication_accounting_predecessor(self,path,old)
                self.assertEqual(rally_predecessor(self,path,reviewed),
                                 rally_predecessor(self,path,predecessor))
                self.assertEqual(opportunity_predecessor(self,path,reviewed),
                                 opportunity_predecessor(self,path,predecessor))
                for changed in (current+b'\n# unexpected economic mutation\n',b'',
                        current.replace(b'archives.clear()',b'pass',1),
                        current.replace(b'_archive_cache=archives',b'_archive_cache=None',1)):
                    if changed==current:continue
                    with self.assertRaises(AssertionError):
                        cross_candidate_cold_predecessor(self,path,changed)


    def test_source_recorder_publication_reverses_only_exact_diagnostic_transport_and_test_read(self):
        import hashlib
        mutations={
            'meme_machine/solana_evidence_service.py':(
                (b"if not operation_costs.enabled() or os.environ.get('MM_SQLITE_DIAGNOSTIC_REQUIRED')!='1':return",
                    b'if not operation_costs.enabled():return'),
                (b"if not operation_costs.enabled() or os.environ.get('MM_SQLITE_DIAGNOSTIC_REQUIRED')!='1':return",
                    b'if False:return'),
                (b"if costs_enabled() and os.environ.get('MM_SQLITE_DIAGNOSTIC_REQUIRED')=='1' else None)",
                    b'if costs_enabled() else None)'),
                (b"if costs_enabled() and os.environ.get('MM_SQLITE_DIAGNOSTIC_REQUIRED')=='1' else None)",
                    b"if os.environ.get('MM_SQLITE_DIAGNOSTIC_REQUIRED')=='1' else None)"),
                (b'if cost_publisher is not None:tasks.append(cost_publisher)',b'if False:tasks.append(cost_publisher)'),
                (b"operation_costs=costs,owner_scheduler=owner.telemetry()",
                    b'operation_costs={},owner_scheduler={}'),
                (b'_atomic_json(target,row)',b"owner.submit(lambda state:state.fence.health('ipc',row))"),
                (b'not stat.S_ISREG(info.st_mode) or info.st_nlink!=1',b'False'),
                (b'info.st_uid!=os.getuid()',b'False'),
                (b'stat.S_IMODE(info.st_mode)!=0o600',b'False'),
                (b'if type(ticks) is not int or ticks<=0:',b'if False:'),
                (b"type(costs.get('pid')) is not int or costs['pid']!=pid",b'False'),
                (b"costs.get('enabled') is not True",b'False'),
                (b'type(clock) not in (int,float)',b'False'),
                (b'not 0<=clock<2**64',b'False'),
                (b"clock=costs.get('collected_monotonic')",b'clock=time.monotonic()'),
                (b'try:await asyncio.shield(pending)',b'try:await pending'),
                (b'while not pending.done():',b'if not pending.done():'),
                (b'try:await persist(\'STOPPED\')',b'try:await persist(\'ACTIVE\')'),
                (b'await asyncio.wait_for(stop.wait(),1)',b'await asyncio.wait_for(stop.wait(),2)'),
                (b'if entered-submitted>runtime.leases.owner:',b'if False:'),
                (b'runtime.turn(flight,submitted,owner_entered=entered)',
                    b'runtime.turn(flight,submitted,owner_entered=time.monotonic())')),
            'engineering/diagnostics/current_combined_observation_20261014.py':(
                (b'os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK',b'os.O_RDONLY'),
                (b'stat.S_IMODE(first.st_mode)!=0o600 or first.st_nlink!=1',b'False'),
                (b'Supervisor._source_start_ticks(expected_pid)!=before',b'False'),
                (b"row['pid']!=expected_pid",b'False'),
                (b"row['process_start_ticks']!=before",b'False'),
                (b"row.get('publication_state')!='ACTIVE'",b'False'),
                (b"not finite_number(costs.get('collected_monotonic'))",b'False'),
                (b"costs['collected_monotonic']<0",b'False'),
                (b'reduced=operation_costs(costs,expected_pid)',b'reduced=costs'),
                (b"if (os.environ.get('MM_OPERATION_COST_DIAGNOSTICS')=='1'\n"
                    b"                    and os.environ.get('MM_SQLITE_DIAGNOSTIC_REQUIRED')=='1'):",
                    b"if os.environ.get('MM_OPERATION_COST_DIAGNOSTICS')=='1':"),
                (b"if (os.environ.get('MM_OPERATION_COST_DIAGNOSTICS')=='1'\n"
                    b"                    and os.environ.get('MM_SQLITE_DIAGNOSTIC_REQUIRED')=='1'):",
                    b"if os.environ.get('MM_SQLITE_DIAGNOSTIC_REQUIRED')=='1':"),
                (b"result['source_operation_telemetry']=telemetry",b"result['available']=True"),
                (b'not 0 <= now - sampled <= 15',b'not 0 <= now - sampled <= 30'),
                (b"db.execute('PRAGMA query_only=ON')",b"db.execute('PRAGMA query_only=OFF')")),
        }
        self.assertEqual(set(mutations),set(SOURCE_RECORDER_PUBLICATION_DELTAS))
        for relative,(_,after,_,_,_) in SOURCE_RECORDER_PUBLICATION_DELTAS.items():
            current=pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes())
            self.assertEqual(hashlib.sha256(current).hexdigest(),after,relative+':active exact recorder transport')
            prior=subprocess.check_output(['git','show',SOURCE_RECORDER_PUBLICATION_REFERENCE+':'+relative],cwd=ROOT)
            self.assertEqual(source_recorder_publication_predecessor(self,relative,current),prior)
            self.assertEqual(source_recorder_publication_predecessor(self,relative,prior),prior)
            if relative=='meme_machine/solana_evidence_service.py':
                self.assertEqual(maintenance_entry_clock_predecessor(self,relative,current),
                    maintenance_entry_clock_predecessor(self,relative,prior))
            changes=[current+b'\n# unreviewed source telemetry or authority mutation\n',b'']
            for previous,successor in mutations[relative]:
                self.assertIn(previous,current,relative+':negative mutation target exists')
                changes.append(current.replace(previous,successor,1))
            for changed in changes:
                self.assertNotEqual(changed,current,relative+':negative mutation changes source')
                with self.assertRaises(AssertionError):source_recorder_publication_predecessor(self,relative,changed)
                if relative=='meme_machine/solana_evidence_service.py':
                    with self.assertRaises(AssertionError):maintenance_entry_clock_predecessor(self,relative,changed)
        # Pin the one necessary old79 entry normalization independently. Every
        # original hash, lease assertion, mutation and relative ordering survives.
        relative='tests/test_robinhood_usd_valuation.py'
        current=(ROOT/relative).read_bytes()
        prior=subprocess.check_output(['git','show',SOURCE_RECORDER_PUBLICATION_REFERENCE+':'+relative],cwd=ROOT)
        def old_guard(body):
            parent=next(n for n in ast.parse(body).body if isinstance(n,ast.ClassDef) and n.name=='RobinhoodUSDTests')
            selected=next(n for n in parent.body if isinstance(n,ast.FunctionDef)
                and n.name=='test_maintenance_entry_clock_preserves_exact_original_leases_and_native_guards')
            return b''.join(body.splitlines(keepends=True)[selected.lineno-1:selected.end_lineno])
        before=old_guard(prior);after=old_guard(current)
        self.assertEqual(hashlib.sha256(before).hexdigest(),SOURCE_RECORDER_TEST_BODY_BEFORE)
        self.assertEqual(before.count(SOURCE_RECORDER_TEST_READ_OLD),1)
        self.assertEqual(after.count(SOURCE_RECORDER_TEST_READ_NEW),1)
        restored=after.replace(SOURCE_RECORDER_TEST_READ_NEW,SOURCE_RECORDER_TEST_READ_OLD,1)
        self.assertEqual(restored,before,'only old79 initial source read normalization is approved')
        self.assertEqual(hashlib.sha256(restored).hexdigest(),SOURCE_RECORDER_TEST_BODY_BEFORE)

    def test_sleeve_empty_prefix_reverses_only_exact_optional_compaction_scheduling(self):
        import hashlib
        relative=SLEEVE_EMPTY_PREFIX_SOURCE;current=(ROOT/relative).read_bytes()
        self.assertEqual(hashlib.sha256(current).hexdigest(),SLEEVE_EMPTY_PREFIX_AFTER,
            relative+':active source must use the exact positive empty-prefix scheduling check')
        prior=subprocess.check_output(['git','show',SLEEVE_EMPTY_PREFIX_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(sleeve_empty_prefix_predecessor(self,relative,current),prior)
        self.assertEqual(sleeve_empty_prefix_predecessor(self,relative,prior),prior)
        self.assertEqual(rally_manifest(self)['files'][relative]['after_sha256'],SLEEVE_EMPTY_PREFIX_BEFORE,
            relative+':original rally source pin remains unchanged')
        self.assertEqual(rally_predecessor(self,relative,current),rally_predecessor(self,relative,prior))
        self.assertEqual(opportunity_predecessor(self,relative,current),opportunity_predecessor(self,relative,prior))
        changes=[current+b'\n# unreviewed sleeve financial or compaction change\n',b'']
        for previous,successor in (
                (b'empty=False',b'empty=True'),
                (b"if os.environ.get('MM_PAPER_EPOCH'):",b'if True:'),
                (b'if Path(path).is_file():',b'if True:'),
                (b"+'?mode=ro',uri=True,timeout=0",b"+'?mode=rwc',uri=True,timeout=0"),
                (b"+'?mode=ro',uri=True,timeout=0",b"+'?mode=ro',uri=True,timeout=30"),
                (b'SELECT 1 FROM sleeve_journal LIMIT 1',b'SELECT 1 FROM sleeve_positions LIMIT 1'),
                (b'empty=journal is None',b'empty=not journal'),
                (b'empty=journal is None',b'empty=True'),
                (b'except (OSError,sqlite3.Error):pass',b'except (OSError,sqlite3.Error):empty=True'),
                (b'nullcontext(None) if empty else',b'nullcontext(None) if not empty else'),
                (b'nullcontext(None) if empty else',b'nullcontext(None) if True else'),
                (b'                self._open(path)',b'                if not empty:self._open(path)'),
                (b'if preserved:self._compact_preserved(*preserved)',b'if False:self._compact_preserved(*preserved)'),
                (b"if hasattr(self,'db'):self.db.close()",b"if hasattr(self,'db'):pass"),
                (b"self.db.execute('PRAGMA synchronous=FULL')",b"self.db.execute('PRAGMA synchronous=NORMAL')"),
                (b"raise ValueError('sleeve_archive_integrity')",b'pass'),
                (b"raise ValueError('sleeve_archive_state_changed')",b'pass'),
                (b"raise ValueError('sleeve_capital_exhausted')",b'pass'),
                (b"raise ValueError('native_terminal_required')",b'pass')):
            self.assertIn(previous,current,relative+':negative mutation target exists')
            changes.append(current.replace(previous,successor,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):sleeve_empty_prefix_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):rally_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_archive_log_order_reverses_only_exact_distinct_post_prefix_sequence_match(self):
        import hashlib
        relative=ARCHIVE_LOG_ORDER_SOURCE;current=(ROOT/relative).read_bytes()
        self.assertEqual(hashlib.sha256(current).hexdigest(),ARCHIVE_LOG_ORDER_AFTER,
            relative+':active source must use the exact retained-line order repair')
        self.assertEqual(ARCHIVE_LOG_ORDER_BEFORE,ARCHIVE_LOG_CONSISTENCY_AFTER,
            relative+':all earlier archive source pins remain unchanged')
        prior=subprocess.check_output(['git','show',ARCHIVE_LOG_ORDER_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(archive_log_order_predecessor(self,relative,current),prior)
        self.assertEqual(archive_log_order_predecessor(self,relative,prior),prior)
        for predecessor in (archive_log_consistency_predecessor,retained_archive_log_shape_predecessor,
                archive_complete_logs_predecessor,rally_predecessor,opportunity_predecessor):
            self.assertEqual(predecessor(self,relative,current),predecessor(self,relative,prior),
                relative+':every original archive, economic and recovery guard still applies')
        changes=[current+b'\n# unreviewed retained-log order change\n',b'']
        for previous,successor in (
                (b'position=len(prefix)',b'position=0'),
                (b'for line in suffix:',b'for line in sorted(suffix):'),
                (b'for line in suffix:',b'for line in set(suffix):'),
                (b'for line in suffix:\n',b'for line in suffix:\n            position=len(prefix)\n'),
                (b'complete[position]!=line:position+=1',b'complete[position]==line:position+=1'),
                (b'if position==len(complete):raise KeyError()',b'if position==len(complete):break'),
                (b'            position+=1\n    except',b'            position+=0\n    except'),
                (b'complete[:len(prefix)]!=prefix',b'False'),
                (b'if len(markers)!=1:raise KeyError()',b'if False:raise KeyError()'),
                (b"'truncat' in line.lower() for line in complete",b'False for line in complete'),
                (b"canonical(fetched['transaction'])!=canonical(original['transaction'])",b'False'),
                (b"type(fetched['slot']) is not int or fetched['slot']!=slot",b'False'),
                (b"canonical(fetched['blockTime'])!=canonical(original['blockTime'])",b'False'),
                (b"old['err'] is not None or new['err'] is not None",b'False'),
                (b"fetched['transactionIndex']!=index",b'False'),
                (b"index=original['transactionIndex']",b'index=0'),
                (b"tx['meta']['logMessages']=list(complete)",b"tx['meta']['logMessages']=list(prefix+suffix)"),
                (b'type(supplement) is not ArchiveLogSupplement',b'False'),
                (b'supplement.endpoint_identity!=endpoint_identity',b'False'),
                (b'canonical(original)!=supplement.original_json',b'False')):
            self.assertIn(previous,current,relative+':negative mutation target exists')
            changes.append(current.replace(previous,successor,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):archive_log_order_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):archive_log_consistency_predecessor(self,relative,changed)

    def test_provider_budget_namespace_read_reverses_only_exact_phase_sql_pushdown(self):
        import hashlib
        relative=PROVIDER_NAMESPACE_READ_SOURCE;current=(ROOT/relative).read_bytes()
        self.assertEqual(hashlib.sha256(current).hexdigest(),PROVIDER_NAMESPACE_READ_AFTER,
            relative+':active source must use the exact validated namespace SQL selection')
        prior=subprocess.check_output(['git','show',PROVIDER_NAMESPACE_READ_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(provider_namespace_read_predecessor(self,relative,current),prior)
        self.assertEqual(provider_namespace_read_predecessor(self,relative,prior),prior)
        changes=[current+b'\n# unreviewed provider-ledger authority change\n',b'']
        for previous,successor in (
                (b"typeof(key)<>'text' OR ",b''),
                (b"typeof(key)='text' AND substr(key,1,?)=?",b"typeof(key)='text' AND key LIKE ?"),
                (b"typeof(key)='text' AND instr(key,'.')=0",b"typeof(key)='text' AND instr(key,'.')>0"),
                (b'args=(len(self.prefix),self.prefix)',b'args=(len(self.prefix)+1,self.prefix)'),
                (b'args=(len(self.prefix),self.prefix)',b'args=(len(self.prefix),self.prefix+\'_\')'),
                (b'db.execute(sql,args)',b'db.execute(sql)'),
                (b'if self.prefix:\n            sql=',b'if not self.prefix:\n            sql='),
                (b"            if (key.startswith(self.prefix) if self.prefix else '.' not in key)",b'            if True'),
                (b'key[len(self.prefix):]:value',b'key:value'),
                (b"if int(state[key])>self.limits[key]:",b"if int(state[key])>self.limits[key]+1:"),
                (b"if any(v<0 for v in deltas.values()):",b'if False:'),
                (b"self.change(dict(rpc_cu=cu,",b"self.change(dict(rpc_cu=0,"),
                (b'await asyncio.shield(task)',b'await task'),
                (b'if cancelled:raise asyncio.CancelledError()',b'if cancelled:return')):
            self.assertIn(previous,current,relative+':negative mutation target exists')
            changes.append(current.replace(previous,successor,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):provider_namespace_read_predecessor(self,relative,changed)

    def test_pump_cost_environment_reverses_only_exact_opt_in_lane_tuple(self):
        import hashlib
        relative=PUMP_COST_ENVIRONMENT_SOURCE;current=(ROOT/relative).read_bytes()
        self.assertEqual(hashlib.sha256(current).hexdigest(),PUMP_COST_ENVIRONMENT_AFTER,
            relative+':active source must forward the exact existing opt-in flag to Pump')
        self.assertEqual(PUMP_COST_ENVIRONMENT_BEFORE,SOURCE_PARENT_DRAIN_AFTER,
            relative+':original source-parent lifecycle pin remains unchanged')
        prior=subprocess.check_output(['git','show',PUMP_COST_ENVIRONMENT_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(pump_cost_environment_predecessor(self,relative,current),prior)
        self.assertEqual(pump_cost_environment_predecessor(self,relative,prior),prior)
        for predecessor in (source_parent_drain_predecessor,restored_provider_history_predecessor,
                rally_predecessor,opportunity_predecessor):
            self.assertEqual(predecessor(self,relative,current),predecessor(self,relative,prior),
                relative+':every original environment, strategy and recovery guard still applies')
        changes=[current+b'\n# unreviewed diagnostic environment change\n',b'']
        for previous,successor in (
                (b"if lane in ('pump','pons','solana'):",b'if True:'),
                (b"if lane in ('pump','pons','solana'):",b"if lane in ('pumpswap','pons','solana'):"),
                (b"if lane in ('pump','pons','solana'):",b"if lane in ('pump','pons','solana','ramses','meteora'):"),
                (b"env['MM_OPERATION_COST_DIAGNOSTICS']='1' if os.environ.get('MM_OPERATION_COST_DIAGNOSTICS')=='1' else '0'",
                    b"env['MM_OPERATION_COST_DIAGNOSTICS']='1'"),
                (b"env['MM_OPERATION_COST_DIAGNOSTICS']='1' if os.environ.get('MM_OPERATION_COST_DIAGNOSTICS')=='1' else '0'",
                    b"env['MM_OPERATION_COST_DIAGNOSTICS']='0'"),
                (b"os.environ.get('MM_OPERATION_COST_DIAGNOSTICS')=='1'",b'bool(os.environ.get(\'MM_OPERATION_COST_DIAGNOSTICS\'))'),
                (b"env.update(MM_MODE='PAPER'",b"env.update(MM_MODE='LIVE'"),
                (b'self.stop_process(self.evidence,45,cooperative_parent=True)',
                    b'self.stop_process(self.evidence,46,cooperative_parent=True)')):
            self.assertIn(previous,current,relative+':negative mutation target exists')
            changes.append(current.replace(previous,successor,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):pump_cost_environment_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):source_parent_drain_predecessor(self,relative,changed)

    def test_publication_accounting_turn_preserves_durable_delta_cancellation_and_passive_pump_costs(self):
        import hashlib
        mutations={
            'meme_machine/solana_selective_source.py':(
                ('SelectiveSource.flush_delivery',(
                    (b'async def flush_delivery(self,after=None):',b'async def flush_delivery(self,after=True):'),
                    (b'async with self.delivery_lock:',b'if True:'),
                    (b'pending=dict(self.pending_delivery)',b'pending=self.pending_delivery'),
                    (b'if not pending and after is None:return',b'if not pending:return'),
                    (b'accepted_future=future',b'accepted_future=None'),
                    (b'if pending and not committed:',b'if pending:'),
                    (b'with state.writer.transaction():',b'if True:'),
                    (b'h.delivery(family,transport,raw_bytes=size,seen=seen)',b'h.delivery(family,transport,raw_bytes=size+1,seen=seen)'),
                    (b'committed=True',b'committed=False'),
                    (b'if after is not None:return after(state)',b'if after is not None:return None'),
                    (b"return await self.work(commit,2,label='source_commit',",b"return await self.work(commit,0,label='source_commit',"),
                    (b"component='delivery_accounting' if after is None else 'history_publication',accepted=accepted)",
                     b"component='delivery_accounting' if after is None else 'history_publication')"),
                    (b'if accepted_future is not None:',b'if False:'),
                    (b'waiter=asyncio.wrap_future(accepted_future)',b'waiter=asyncio.wrap_future(self.last_future)'),
                    (b'while not waiter.done():',b'if not waiter.done():'),
                    (b'await asyncio.shield(waiter)',b'await waiter'),
                    (b'except asyncio.CancelledError:pass',b'except asyncio.CancelledError:raise'),
                    (b'try:waiter.result()',b'try:pass'),
                    (b"if str(exc) not in ('evidence_background_yield','evidence_control_overloaded'):raise",b'pass'),
                    (b'if committed:',b'if True:'),
                    (b'remaining=self.pending_delivery[key][0]-size',b'remaining=0'),
                    (b'if remaining:self.pending_delivery[key]=(remaining,self.pending_delivery[key][1])',
                     b'if remaining:self.pending_delivery[key]=(size,seen)'))),
                ('SelectiveSource.publish_history',(
                    (b'more,startup,retry_at,published=await self.flush_delivery(publish)',
                     b'more,startup,retry_at,published=await self.work(publish,0)'),
                    (b'h.lifecycle.publish()',b'h.lifecycle.publish(proof_ids=[])'),
                    (b'startup=h.startup.advance()',b'startup=True'),
                    (b'if published:self.history_changed(publication=False)',b'if True:self.history_changed(publication=False)'))),
                ('SelectiveSource._complete_history_delivery',(
                    (b'accepted=await self.work(lambda state:acknowledge(install(state).lifecycle,snapshot,result),2,',
                     b'accepted=await self.work(lambda state:True,2,'),
                    (b'label=\'candidate_delivery_ack\'',b'label=\'source_commit\''),
                    (b'if accepted and identities:',b'if identities:'),
                    (b'life.publish(proof_ids=identities)',b'life.publish()'),
                    (b'published=await self.flush_delivery(publish_exact)',b'published=True'),
                    (b"snapshot['proof_publication_changed']=bool(published)",b"snapshot['proof_publication_changed']=True"))),
                ('source_work',(
                    (b"if str(exc) not in ('evidence_background_yield','evidence_control_overloaded'):raise",b'pass'),
                    (b'result=await work(fn,priority,**options)',b'result=await work(fn,0,**options)')))),
            'meme_machine/lanes/pump/runner.py':(
                ('_startup_work',(
                    (b"if identity in ('pump.observed_candidates_restore','pump.observed_candidate_events'):",b'if True:'),
                    (b'costs.enter_context(cost_operation(identity))',b'pass'),
                    (b'costs.enter_context(cost_operation(identity))',b"costs.enter_context(cost_operation('pump.observed_candidates_restore'))"),
                    (b'with native_startup_replay(requested.is_set):',b'with native_startup_replay(lambda:False):'),
                    (b'else:value=call(*args,**kwargs)',b'else:value=call()'),
                    (b'return _own_startup_resource(identity,value)',b'return value'))),
                ('_restore_observed_pump_candidates',(
                    (b'if requested.is_set():raise Shutdown()',b'if False:raise Shutdown()'),
                    (b'cancelled=requested.is_set',b'cancelled=lambda:False'),
                    (b'if mint in created:continue',b'if True:continue')))),
            'meme_machine/runtime/operation_costs.py':(),
        }
        self.assertEqual(set(mutations),set(PUBLICATION_ACCOUNTING_DELTAS))
        for relative,(before,after,_) in PUBLICATION_ACCOUNTING_DELTAS.items():
            current=cross_candidate_cold_predecessor(self,relative,pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes()))
            self.assertEqual(hashlib.sha256(current).hexdigest(),after,relative+':active exact integrated successor')
            prior=subprocess.check_output(['git','show',PUBLICATION_ACCOUNTING_REFERENCE+':'+relative],cwd=ROOT)
            self.assertEqual(hashlib.sha256(prior).hexdigest(),before,relative+':immutable exact tested predecessor')
            self.assertEqual(publication_accounting_predecessor(self,relative,current),prior)
            self.assertEqual(publication_accounting_predecessor(self,relative,prior),prior)
            self.assertEqual(guarded_source(self,relative),rally_predecessor(self,relative,prior),
                relative+':mandatory active-source entry still runs every original source guard')
            self.assertEqual(opportunity_predecessor(self,relative,
                publication_accounting_predecessor(self,relative,current)),
                opportunity_predecessor(self,relative,prior),relative+':all original economic and strategy guards retained')
            tree=ast.parse(current)
            changes=[current+b'\n# unreviewed accounting-publication/cost source change\n',b'']
            for name,replacements in mutations[relative]:
                parent=tree
                for part in name.split('.')[:-1]:
                    parent=next(n for n in parent.body if isinstance(n,ast.ClassDef) and n.name==part)
                selected=next(n for n in parent.body
                    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name.split('.')[-1])
                body=ast.get_source_segment(current.decode(),selected).encode()
                self.assertEqual(current.count(body),1,relative+':one node-specific negative mutation body '+name)
                for previous,successor in replacements:
                    self.assertIn(previous,body,relative+':negative mutation target exists '+name)
                    changes.append(current.replace(body,body.replace(previous,successor,1),1))
            if relative=='meme_machine/runtime/operation_costs.py':
                for previous,successor in (
                        (b"'pump.observed_candidates_restore', 'pump.observed_candidate_events'",
                         b"'pump.observed_candidates_restore', 'pump.any_candidate'"),
                        (b"'pump.observed_candidates_restore', 'pump.observed_candidate_events'",
                         b"'pump.observed_candidate_events', 'pump.observed_candidates_restore'"),
                        (b"os.environ.get('MM_OPERATION_COST_DIAGNOSTICS') == '1'",b'True'),
                        (b"row['calls'] += 1",b"row['calls'] += 0"),
                        (b"row['child_unmeasured_calls'] += child_unmeasured",b"row['child_unmeasured_calls'] += 0"),
                        (b"_validate(name)",b'pass'),
                        (b"if not enabled():",b'if False:'),
                        (b"recorder_valid=_recorder_valid",b'recorder_valid=True')):
                    self.assertIn(previous,current,relative+':fixed-ID/coverage mutation target exists')
                    changes.append(current.replace(previous,successor,1))
            for changed in changes:
                self.assertNotEqual(changed,current,relative+':negative mutation changes source')
                with self.assertRaises(AssertionError):publication_accounting_predecessor(self,relative,changed)

    def test_buffered_origin_geometry_preserves_unique_full_obligation_and_original_authority(self):
        relative=BUFFERED_PREJOIN_SOURCE;current=pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes())
        prior=subprocess.check_output(['git','show',BUFFERED_ORIGIN_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(buffered_origin_predecessor(self,relative,current),prior)
        self.assertEqual(buffered_origin_predecessor(self,relative,prior),prior)
        self.assertEqual(buffered_prejoin_predecessor(self,relative,current),
            buffered_prejoin_predecessor(self,relative,prior))
        for before,after in (
                (b'(hi IS NULL OR hi>=?)',b'(hi IS NULL OR hi>=0)'),
                (b'(scope,floor,hi,selected[2])',b'(scope,floor,0,selected[2])'),
                (b'require(len(gaps)==1);gap=gaps[0]',b'gap=gaps[0]'),
                (b'ORDER BY id DESC LIMIT 2',b'ORDER BY id DESC LIMIT 1'),
                (b"record.get('recovery')==dict(kind='CANDIDATE_GAPS',gap_ids=[origins[family]['id']])",b'True'),
                (b"('prefix',descriptor['prefix_lower_slot'],descriptor['prefix_upper_slot'])",b"('prefix',0,-1)")):
            self.assertIn(before,current)
            changed=current.replace(before,after,1)
            with self.assertRaises(AssertionError):buffered_origin_predecessor(self,relative,changed)
        for changed in (current+b'\n# unreviewed origin change\n',b''):
            with self.assertRaises(AssertionError):buffered_origin_predecessor(self,relative,changed)

    def test_buffered_prejoin_replay_preserves_original_partition_and_full_ack_authority(self):
        import hashlib
        relative=BUFFERED_PREJOIN_SOURCE
        current=buffered_origin_predecessor(self,relative,pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes()))
        self.assertEqual(hashlib.sha256(current).hexdigest(),BUFFERED_PREJOIN_AFTER,
            relative+':active exact committed buffered-observation recovery')
        self.assertEqual(BUFFERED_PREJOIN_BEFORE,PREPARATION_REPLAY_AFTER,
            relative+':every prior preparation and queue-recovery source pin remains unchanged')
        prior=subprocess.check_output(['git','show',BUFFERED_PREJOIN_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(buffered_prejoin_predecessor(self,relative,current),prior)
        self.assertEqual(buffered_prejoin_predecessor(self,relative,prior),prior)
        for predecessor in (preparation_replay_predecessor,prejoin_source_predecessor,
                session_economic_recovery_predecessor,native_startup_failure_predecessor,
                recovered_economic_boundary_predecessor,program_gap_observation_predecessor,
                rally_predecessor,opportunity_predecessor):
            self.assertEqual(predecessor(self,relative,current),predecessor(self,relative,prior),
                relative+':complete original financial, retained-incident and strategy guard chain retained')
        tree=ast.parse(current)
        changes=[current+b'\n# unreviewed buffered-log recovery authority change\n',b'']
        for name,mutations in (
                ('_buffered_log_inputs',(
                    (b"body['state']=='RECOVERY_REQUIRED' and _observation_reference(body) and _committed_census(body)",b'True'),
                    (b"body.get('terminal_record_unavailable',False) is False",b'True'),
                    (b"body.get('unexpected_cancellation',False) is False",b'True'),
                    (b"accounting.get('run')==body.get('run_identity')",b'True'),
                    (b"accounting.get('pid')==body.get('source_pid')",b'True'),
                    (b"('active','failed','unresolved')",b"('active','failed')"),
                    (b'control_recovery(_health_from_db(db,CONTROL_RECOVERY_KEY,SOURCE_DRAIN_BYTES)) is None',b'True'),
                    (b"set(row)=={'accepted','committed','pending'}",b'True'),
                    (b"len(current)==len(records)==body['pending_handlers']==accounting.get('recoverable')",b'True'),
                    (b"len(matches)==1 and all(matches[0].get(k)==v for k,v in record.items())",b'True'),
                    (b"len({(r.get('run'),r.get('id')) for r in retained})==len(retained)",b'True'),
                    (b'ORDER BY id LIMIT 257',b'ORDER BY id DESC LIMIT 1'),
                    (b'len(drains)==len(closed)==1 and drains[0][0]==session_id',b'True'),
                    (b'all(k in observed and k in joined and observed[k]==joined[k] for k in fields)',b'True'),
                    (b"observed['drained'] is False and observed.get('complete_history_claim') is False",b'True'),
                    (b"('pending_slots','pending_bytes','oldest_statuses','oldest_bodies','oldest_missing_logs',\n             'accepted_pending','accepted_pending_bytes')",
                     b"('pending_slots','pending_bytes','oldest_statuses','oldest_bodies','oldest_missing_logs')"),
                    (b"type(floor) is int and 0<floor<=lo",b'True'),
                    (b"observed.get('recovery_obligations')==[dict(scope=s,lower_slot=floor,upper_slot=None) for s in scopes]",b'True'),
                    (b"record['source_pid']==body['source_pid'] and record.get('session')==session",b'True'),
                    (b"('state','RECOVERABLE'),('phase','LOG_BUFFER_WAIT')",b"('state','RETURNED'),('phase','CANDIDATE_QUEUE')"),
                    (b"('failure_state','INTERRUPTED'),('error_type','CancelledError'),('scope_count',1)",b"('failure_state','INTERRUPTED'),('error_type','CancelledError'),('scope_count',2)"),
                    (b"record.get('scope_hash') in [HandlerLedger.scope_hash((s,)) for s in scopes]",b'True'),
                    (b"hi=max(b,*(record['slot'] for record in current))",b'hi=b'),
                    (b"head['slot']==lo",b"head['slot']>=lo"),
                    (b"head['session']==session",b'True'),
                    (b"('id','scope','lo','created','reason')",b"('id','scope','lo','reason')"),
                    (b"old['hi']==origin['hi'] or old['hi'] is None and type(origin['hi']) is int and origin['hi']>=hi",b'True'),
                    (b"record.get('recovery')==dict(kind='CANDIDATE_GAPS',gap_ids=[origins[family]['id']])",b'True'),
                    (b"provider.get('network')=='solana-mainnet'",b'True'),
                    (b'failed_census_sha256=hashlib.sha256(raw.encode()).hexdigest()',b"failed_census_sha256='unverified'"),
                    (b'handler_ledger_sha256=hashlib.sha256(handlers.encode()).hexdigest()',b"handler_ledger_sha256='unverified'"),
                    (b'session_sha256=hashlib.sha256(selected[4].encode()).hexdigest()',b"session_sha256='unverified'"),
                    (b'closed_join_sha256=hashlib.sha256(closed_row[4].encode()).hexdigest()',b"closed_join_sha256='unverified'"),
                    (b'lower_slot=lo,upper_slot=hi,prefix_lower_slot=floor,prefix_upper_slot=lo-1',
                     b'lower_slot=lo+1,upper_slot=hi,prefix_lower_slot=lo,prefix_upper_slot=lo-1'),
                    (b'accepted_pending=0,handler_records=current',b'accepted_pending=0,handler_records=[]'))),
                ('_buffered_log_partition',(
                    (b'require(row is not None);end=row[0]',b'end=descriptor[\'upper_slot\']'),
                    (b'if end is None:',b'if False:'),
                    (b'AND repaired IS NULL AND id>=?',b'AND id>=?'),
                    (b"(scope,origin['lo'],origin['created'],origin['reason'],origin['id'])",
                     b"(scope,origin['lo'],origin['created'],'foreign_origin',origin['id'])"),
                    (b'require(len(rows)==1);end=rows[0][0]-1',b'end=start-1'),
                    (b"('prefix',descriptor['prefix_lower_slot'],descriptor['prefix_upper_slot'])",b"('prefix',0,-1)"),
                    (b"('future',start,end)",b"('future',start,start-1)"),
                    (b'missing=rolling.missing(family,scope,a,b);require(len(missing)<=4096)',b'missing=[]'),
                    (b'require(len(rows)==1)',b'require(True)'),
                    (b'require(len(rows)<=4096);published=[]',b'published=[]'),
                    (b'scheduling==digest(dict(scope=scope,lo=x,hi=y,proof_hash=proof))',b'True'),
                    (b'consumer=full(proof,family,x,y)',b"consumer={'observed_at':time.time()}"),
                    (b"require(points_cover(scope,x,y,consumer['observed_at']))",b'require(True)'),
                    (b'require(not _subtract_intervals(covered,published))',b'require(True)'),
                    (b'future_open_tail=end is None,future_unavailable=end is None',b'future_open_tail=False,future_unavailable=False'),
                    (b"facts[label+'_unavailable']=facts[label+'_unavailable'] or bool(missing)",b"facts[label+'_unavailable']=False"))),
                ('_economic_recovery_inputs',(
                    (b'and _committed_census(_retained_census(raw)):',b':'),
                    (b'PREPARATION_RECOVERY_CENSUS else _economic_failed_inputs)',b'PREPARATION_RECOVERY_CENSUS else _buffered_log_inputs)'))),
                ('current_economic_recovery_descriptor',(
                    (b"expected_origins=descriptor['gap_origins']",b'expected_origins=None'),
                    (b'_economic_require(actual==descriptor)',b'_economic_require(True)'))),
                ('verify_economic_recovery_descriptor',(
                    (b"heads=None if direct else descriptor['native_heads']",b'heads=None'),
                    (b"_health_from_db(db,HANDLER_RECOVERY_KEY+'_preserved.'+str(descriptor.get('handler_ledger_sha256')),HandlerLedger.maximum_bytes)",b'ledger'),
                    (b"hashlib.sha256(old_ledger.encode()).hexdigest()==descriptor.get('handler_ledger_sha256')",b'True'),
                    (b"[r for r in live if (r.get('run'),r.get('id'))==(record.get('run'),record.get('id'))]==[record]",b'True'),
                    (b'buffered_partitions[family]=_buffered_log_partition(db,shared,descriptor,family,full,points_cover)',b'buffered_partitions[family]={}'),
                    (b'full_subscription_completeness_claim=False',b'full_subscription_completeness_claim=True'),
                    (b"scope='OBSERVED_BUFFERED_INTERVAL_ONLY'",b"scope='FULL_SUBSCRIPTION_HISTORY'"),
                    (b'original_queue_acknowledgement_verified=False',b'original_queue_acknowledgement_verified=True'),
                    (b'original_source_drain_pass=False',b'original_source_drain_pass=True'),
                    (b'callback_completion_demonstrated=False',b'callback_completion_demonstrated=True')))):
            selected=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
            body=ast.get_source_segment(current.decode(),selected).encode()
            self.assertEqual(current.count(body),1,relative+':one exact node-specific mutation body '+name)
            for previous,successor in mutations:
                self.assertIn(previous,body,relative+':negative mutation target exists '+name)
                changes.append(current.replace(body,body.replace(previous,successor,1),1))
        for previous,successor in (
                (b"require(0<queues['rolling']['pending']<=8)",b'require(True)'),
                (b'life.unconsumed(scope) is None',b'True'),
                (b'rolling.missing(family,scope,lo,hi)==[]',b'True'),
                (b"        _require_observation_funding_closed()\n",b'        pass\n')):
            self.assertIn(previous,current,relative+':original authority mutation target exists')
            changes.append(current.replace(previous,successor,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):buffered_prejoin_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):preparation_replay_predecessor(self,relative,changed)

    def test_retained_path_factoring_preserves_original_source_guards(self):
        import hashlib
        relative=RETAINED_PATH_FACTOR_SOURCE;current=pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes())
        self.assertEqual(hashlib.sha256(current).hexdigest(),RETAINED_PATH_FACTOR_AFTER)
        prior=subprocess.check_output(['git','show',RETAINED_PATH_FACTOR_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(retained_path_factoring_predecessor(self,relative,current),prior)
        self.assertEqual(retained_path_factoring_predecessor(self,relative,prior),prior)
        for predecessor in (cross_candidate_cold_predecessor,canonical_cold_predecessor,
                pump_restore_selection_predecessor,retained_canonical_predecessor,
                native_startup_failure_predecessor,rally_predecessor,opportunity_predecessor):
            self.assertEqual(predecessor(self,relative,current),predecessor(self,relative,prior))
        changes=[current+b'\n# unreviewed filesystem guard change\n',b'']
        for previous,successor in (
                (b'stat.S_ISDIR(os.lstat(directory).st_mode)',b'stat.S_ISREG(os.lstat(directory).st_mode)'),
                (b'stat.S_ISREG(os.lstat(file).st_mode)',b'True'),
                (b'for directory in directories:',b'for directory in ():'),
                (b'for file in files:',b'for file in ():'),
                (b"os.environ.get('MM_PAPER_EPOCH')!=RETAINED_REFERENCE_EPOCH",b'False')):
            self.assertEqual(current.count(previous),1)
            changes.append(current.replace(previous,successor,1))
        for changed in changes:
            with self.assertRaises(AssertionError):retained_path_factoring_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):canonical_cold_predecessor(self,relative,changed)

    def test_pump_restore_archive_reuse_preserves_fresh_authority_and_cancellation(self):
        import hashlib
        relative=PUMP_RESTORE_ARCHIVE_REUSE_SOURCE
        current=cross_candidate_cold_predecessor(self,relative,pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes()))
        self.assertEqual(hashlib.sha256(current).hexdigest(),PUMP_RESTORE_ARCHIVE_REUSE_AFTER,
            relative+':active exact operation-local startup archive reuse')
        self.assertEqual(PUMP_RESTORE_ARCHIVE_REUSE_BEFORE,CANONICAL_COLD_DELTAS[relative][1],
            relative+':all prior canonical cold-reader source pins remain unchanged')
        prior=subprocess.check_output(['git','show',PUMP_RESTORE_ARCHIVE_REUSE_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(pump_restore_archive_reuse_predecessor(self,relative,current),prior)
        self.assertEqual(pump_restore_archive_reuse_predecessor(self,relative,prior),prior)
        for predecessor in (canonical_cold_predecessor,pump_restore_selection_predecessor,
                retained_canonical_predecessor,native_startup_failure_predecessor,
                rally_predecessor,opportunity_predecessor):
            self.assertEqual(predecessor(self,relative,current),predecessor(self,relative,prior),
                relative+':complete original locator, economic and integrity guard chain retained')
        changes=[current+b'\n# unreviewed startup archive reuse change\n',b'']
        for previous,successor in (
                (b'archives={} if cancelled is not None else None',b'archives={}'),
                (b'archives={} if cancelled is not None else None',b'archives=self._archives'),
                (b'if archives is not None:archives.clear()',b'pass'),
                (b'_archive_cache=archives,_check=check',b'_archive_cache=archives'),
                (b'if _check is not None:_check()',b'pass'),
                (b'path=self._reference_path(ref[\'path\'])',b'path=Path(ref[\'path\'])'),
                (b"row=db.execute('SELECT body,hash,archive FROM canonical_evidence WHERE identity=?'",
                    b"row=db.execute('SELECT body,hash,archive FROM records WHERE identity=?'"),
                (b'if prepared is not None and row[0]==prepared[1]:',b'if prepared is not None:'),
                (b"manifest=db.execute('SELECT path,hash FROM scoped_cold_manifests WHERE id=?'",
                    b"manifest=db.execute('SELECT path,hash FROM scoped_cold_manifests WHERE 1=?'"),
                (b'cold_path=self._reference_path(manifest[0],cold=True)',b'cold_path=Path(manifest[0])'),
                (b'info=cold_path.stat()',b'info=path.stat()'),
                (b"('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')",
                    b"('st_dev','st_ino','st_size','st_mtime_ns')"),
                (b'key=(path,row[2],manifest[0],manifest[1],cold_path,fingerprint)',b'key=(row[2],)'),
                (b'if cached is not None and cached[0]==key:records=cached[1]',
                    b'if cached is not None:records=cached[1]'),
                (b'_archive_cache.clear();cached=None',b'cached=None'),
                (b'if hashlib.sha256(packed).hexdigest()!=manifest[1]:',b'if False:'),
                (b'decoder.decompress(packed,32*1024*1024+1)',b'decoder.decompress(packed)'),
                (b'if not decoder.eof or len(raw)>32*1024*1024:',b'if False:'),
                (b'if fingerprint==tuple(getattr(after,k) for k in',b'if tuple(getattr(after,k) for k in'),
                (b"_archive_cache['entry']=(key,records)",b"self._archives={'entry':(key,records)}"),
                (b"for x in records if x['record']['identity']==ref['canonical_identity']",
                    b"for x in reversed(records) if x['record']['identity']==ref['canonical_identity']"),
                (b'r=deepcopy(r)',b'r=r'),
                (b'if fingerprint!=tuple(getattr(after,k) for k in',b'if False and tuple(getattr(after,k) for k in'),
                (b'checksum=None if r is None else digest(r)',b"checksum=ref['canonical_hash']"),
                (b"r.get('identity')!=ref['canonical_identity']",b'False'),
                (b"checksum!=row[1] or row[1]!=ref['canonical_hash']",b'False'),
                (b'if digest(ref)!=checksum:',b'if False:'),
                (b'if digest(body)!=checksum:',b'if False:'),
                (b'if kind_prefix is not None:',b'if False:'),
                (b'if since is not None:',b'if False:'),
                (b'if through is not None:',b'if False:'),
                (b"self.db.set_progress_handler(lambda:int(bool(cancelled())),1000)",
                    b'self.db.set_progress_handler(lambda:0,1000)'),
                (b"os.environ.get('MM_MODE')!='PAPER'",b'False'),
                (b"candidate_path!=root/'shared/solana-candidate-history.sqlite'",b'False'),
                (b'self.db.execute("PRAGMA synchronous=FULL")',b'self.db.execute("PRAGMA synchronous=OFF")')):
            self.assertIn(previous,current,relative+':negative mutation target exists')
            changes.append(current.replace(previous,successor,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):pump_restore_archive_reuse_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):canonical_cold_predecessor(self,relative,changed)

    def test_preparation_replay_preserves_terminal_incident_and_original_full_ack_authority(self):
        import hashlib
        relative=PREPARATION_REPLAY_SOURCE;current=buffered_prejoin_predecessor(self,relative,pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes()))
        self.assertEqual(hashlib.sha256(current).hexdigest(),PREPARATION_REPLAY_AFTER,
            relative+':active exact preparation-failure replay-input proof')
        self.assertEqual(PREPARATION_REPLAY_BEFORE,PREJOIN_SOURCE_AFTER,
            relative+':original prejoin and generic recovery source pins remain unchanged')
        prior=subprocess.check_output(['git','show',PREPARATION_REPLAY_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(preparation_replay_predecessor(self,relative,current),prior)
        self.assertEqual(preparation_replay_predecessor(self,relative,prior),prior)
        predecessors=(prejoin_source_predecessor,session_economic_recovery_predecessor,
            native_startup_failure_predecessor,recovered_economic_boundary_predecessor,
            program_gap_observation_predecessor,rally_predecessor,opportunity_predecessor)
        for predecessor in predecessors:
            self.assertEqual(predecessor(self,relative,current),predecessor(self,relative,prior),
                relative+':complete prior recovery, financial and source guard chain retained')
        changes=[current+b'\n# unreviewed preparation-replay authority change\n',b'']
        tree=ast.parse(current)
        selected=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_preparation_failed_inputs')
        preparation=ast.get_source_segment(current.decode(),selected).encode()
        for previous,successor in (
                (b'hashlib.sha256(raw.encode()).hexdigest()==PREPARATION_RECOVERY_CENSUS',b'True'),
                (b'hashlib.sha256(handlers.encode()).hexdigest()==PREPARATION_RECOVERY_LEDGER',b'True'),
                (b"session_id==PREPARATION_RECOVERY_OBSERVATIONS['closed'][0]",b'True'),
                (b"body.get('terminal_record_unavailable') is True",b"body.get('terminal_record_unavailable') is False"),
                (b"body.get('all_accepted_committed') is False",b"body.get('all_accepted_committed') is True"),
                (b"body.get('unexpected_cancellation',False) is False",b'True'),
                (b"body.get('pending_handlers')==0",b'True'),
                (b"accounting.get('accepted')==body['accepted_handlers']==body['settled_handlers']==accounting.get('returned')",b'True'),
                (b"('active','recoverable','failed','unresolved')",b"('active','recoverable','failed')"),
                (b"row['pending']==(6 if plane=='rolling' else 0)",b'True'),
                (b"require(all(r.get('run')!=body['run_identity'] for r in retained))",b'require(True)'),
                (b'row[:3]==(kind,at,size)',b'True'),
                (b'hashlib.sha256(row[3].encode()).hexdigest()==checksum',b'True'),
                (b"checkpoint_advanced=False",b'checkpoint_advanced=True'),
                (b'all(observed.get(k)==joined.get(k) for k in fields)',b'True'),
                (b"observed.get('drained') is False",b"observed.get('drained') is True"),
                (b"observed.get('complete_history_claim') is False",b'True'),
                (b"observed.get('completed')==457925009",b'True'),
                (b"observed.get('recovery_obligations')==",b"[]=="),
                (b'require(actual==PREPARATION_RECOVERY_HEADS)',b'require(True)'),
                (b"row[0],row[1],row[3],row[4]",b"row[0],row[1],row[3],reason"),
                (b'row[2]==hi or index==1 and hi is None and type(row[2]) is int and row[2]>=457925127',b'True'),
                (b'require(expected_origins is None or expected_origins==origins)',b'require(True)'),
                (b"provider.get('network')=='solana-mainnet'",b'True'),
                (b'lower_slot=457925003,upper_slot=457925009',b'lower_slot=457925009,upper_slot=457925009'),
                (b'tail_lower_slot=457925010,tail_upper_slot=457925127',b'tail_lower_slot=None,tail_upper_slot=None')):
            self.assertIn(previous,preparation,relative+':preparation-specific negative mutation target exists')
            changes.append(current.replace(preparation,preparation.replace(previous,successor,1),1))
        for previous,successor in (
                (b"PREPARATION_RECOVERY_SESSION='fad3c95d2dc54de4aa7594635d06b8d2'",
                    b"PREPARATION_RECOVERY_SESSION='fad3c95d2dc54de4aa7594635d06b8d3'"),
                (b"'failure':(235833,",b"'failure':(235832,"),
                (b"'closed':(235834,",b"'closed':(235835,"),
                (b"'join':(235839,",b"'join':(235840,"),
                (b'if checksum==PREPARATION_RECOVERY_CENSUS:',b'if True:'),
                (b'PREPARATION_RECOVERY_CENSUS else _economic_failed_inputs)',
                    b'PREPARATION_RECOVERY_CENSUS else _preparation_failed_inputs)'),
                (b"require(0<queues['rolling']['pending']<=8)",b'require(True)'),
                (b"row[:6]==(family,PROGRAMS[family],lo,hi,'complete',None)",b'True'),
                (b"result.get('complete') is (index==pages-1)",b'True'),
                (b"hashlib.sha256(row[1].encode()).hexdigest()==row[2]",b'True'),
                (b"SELECT 1 FROM candidate_pending_proofs WHERE id=?",b"SELECT 1 FROM candidate_pending_proofs WHERE id=? AND 0"),
                (b'life.unconsumed(scope) is None',b'True'),
                (b'rolling.missing(family,scope,lo,hi)==[]',b'True'),
                (b'require(not _subtract_intervals(covered,published))',b'require(True)'),
                (b'retained_economic_tail_unavailable=tail_missing',b'retained_economic_tail_unavailable=False'),
                (b'original_queue_acknowledgement_verified=False',b'original_queue_acknowledgement_verified=True'),
                (b'original_source_drain_pass=False',b'original_source_drain_pass=True'),
                (b'callback_completion_demonstrated=False',b'callback_completion_demonstrated=True'),
                (b"        _require_observation_funding_closed()\n",b'        pass\n')):
            self.assertIn(previous,current,relative+':negative mutation target exists')
            changes.append(current.replace(previous,successor,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):preparation_replay_predecessor(self,relative,changed)
            for predecessor in (prejoin_source_predecessor,session_economic_recovery_predecessor,
                    opportunity_predecessor):
                with self.assertRaises(AssertionError):predecessor(self,relative,changed)

    def test_source_parent_drain_preserves_exact_timeouts_identity_and_financial_guards(self):
        import hashlib
        relative=SOURCE_PARENT_DRAIN_SOURCE;current=pump_cost_environment_predecessor(self,relative,(ROOT/relative).read_bytes())
        self.assertEqual(hashlib.sha256(current).hexdigest(),SOURCE_PARENT_DRAIN_AFTER,
            relative+':active exact cooperative source-parent drain repair')
        self.assertEqual(SOURCE_PARENT_DRAIN_BEFORE,RESTORED_HISTORY_AFTER,
            relative+':original restored-history source pin remains unchanged')
        prior=subprocess.check_output(['git','show',SOURCE_PARENT_DRAIN_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(source_parent_drain_predecessor(self,relative,current),prior)
        self.assertEqual(source_parent_drain_predecessor(self,relative,prior),prior)
        predecessors=(restored_provider_history_predecessor,rally_predecessor,opportunity_predecessor)
        for predecessor in predecessors:
            self.assertEqual(predecessor(self,relative,current),predecessor(self,relative,prior),
                relative+':complete previous source and economic guard chain retained')
        # Inner portability/cost guards consume the prior rally layer, exactly
        # as the existing guarded_source helper does for their original tests.
        current_layer=rally_predecessor(self,relative,current)
        prior_layer=rally_predecessor(self,relative,prior)
        for predecessor in (contained_observation_predecessor,cpu_capacity_predecessor,
                operation_cost_predecessor,observation_route_predecessor):
            self.assertEqual(predecessor(self,relative,current_layer),predecessor(self,relative,prior_layer),
                relative+':all original inner source and economic assertions remain effective')
        self.assertEqual(current.count(b'proc._mm_source_group_closed=True'),3,
            relative+':one-use completion recorded only for owned cleanup success, absence or timeout kill')
        self.assertLess(current.index(b"if getattr(proc,'_mm_source_group_closed',False):"),
            current.index(b"source_ticks=getattr(proc,'_mm_source_start_ticks',None)"),
            relative+':repeated cleanup cannot inspect or signal a subsequently reused PID/group')
        changes=[current+b'\n# unreviewed source-parent drain change\n',b'']
        for previous,successor in (
                (b'cooperative_parent=False',b'cooperative_parent=True'),
                (b'def stop_process(proc,timeout=15,',b'def stop_process(proc,timeout=16,'),
                (b'self.stop_process(self.evidence,45,cooperative_parent=True)',
                    b'self.stop_process(self.evidence,45)'),
                (b'self.stop_process(evidence,45,cooperative_parent=True)',
                    b'self.stop_process(evidence,46,cooperative_parent=True)'),
                (b'if cooperative_parent:proc.send_signal(signal.SIGTERM)',
                    b'if cooperative_parent:os.killpg(proc.pid,signal.SIGTERM)'),
                (b'else:os.killpg(proc.pid,signal.SIGTERM)',b'else:proc.send_signal(signal.SIGTERM)'),
                (b'code=proc.wait(timeout=5)',b'code=proc.wait(timeout=50)'),
                (b'os.killpg(proc.pid,signal.SIGKILL)',b'proc.send_signal(signal.SIGKILL)'),
                (b'if cooperative_parent and not escalated:cleanup_descendants()',b'pass'),
                (b'if cooperative_parent:cleanup_descendants()',b'if False:cleanup_descendants()'),
                (b"if getattr(proc,'_mm_source_group_closed',False):",b'if False:'),
                (b'proc._mm_source_group_closed=True',b'proc._mm_source_group_closed=False'),
                (b"note('already_cleaned',exit_code=code)",b"cleanup_descendants()"),
                (b'if current is not None and current!=source_ticks:',b'if False:'),
                (b'if code is not None:raise RuntimeError(\'source_process_identity_unavailable\')',b'if False:pass'),
                (b"self.evidence._mm_source_start_ticks=ticks",b'self.evidence._mm_source_start_ticks=1'),
                (b"proc._mm_source_start_ticks=source_ticks",b'proc._mm_source_start_ticks=1'),
                (b"int(leader.split('(',1)[0])!=pid",b'False'),
                (b'int(fields[2])!=pid',b'False'),
                (b'int(fields[3])!=pid',b'False'),
                (b'int(fields[19])<=0',b'False'),
                (b'return int(fields[19])',b'return 1'),
                (b"if budget and hasattr(budget,'bootstrap'):",b'if False:'),
                (b'maximum_queue_wait_seconds=5',b'maximum_queue_wait_seconds=6'),
                (b'if outstanding(self.shared_capital.ledger()):',b'if False:'),
                (b"require_restored_history(self,state,path,envelope)",b'pass')):
            self.assertIn(previous,current,relative+':negative mutation target exists')
            changes.append(current.replace(previous,successor,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):source_parent_drain_predecessor(self,relative,changed)
            for predecessor in (restored_provider_history_predecessor,rally_predecessor,opportunity_predecessor):
                with self.assertRaises(AssertionError):
                    predecessor(self,relative,source_parent_drain_predecessor(self,relative,changed))

    def test_canonical_cold_reader_preserves_exact_locator_and_authenticated_archive_authority(self):
        import hashlib
        mutations={
            'meme_machine/runtime/candidate_history.py':(
                (b'return retained_reference_path(value,candidate_path=self.path,cold=cold)',
                    b'return retained_reference_path(value,candidate_path=self.path,cold=True)'),
                (b'canonical_path is not None and canonical_path!=source',b'False'),
                (b"candidate_path!=root/'shared/solana-candidate-history.sqlite'",b'False'),
                (b"os.environ.get('MM_MODE')!='PAPER'",b'False'),
                (b"os.environ.get('MM_PAPER_EPOCH')!=RETAINED_REFERENCE_EPOCH",b'False'),
                (b"os.environ.get('MM_STATE_ROOT')!=str(root)",b'False'),
                (b"os.environ.get('MM_STATE_ROOT')==str(RETAINED_REFERENCE_LEGACY_ROOT)",b'True'),
                (b"os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB',str(source))!=str(source)",b'False'),
                (b"path.parent==legacy.with_suffix('.scoped-cold')",b'True'),
                (b'len(name)==69',b'True'),
                (b"all(c in '0123456789abcdef' for c in name[:-5])",b'True'),
                (b'candidate_path.resolve(strict=True)!=candidate_path',b'False'),
                (b'source.resolve(strict=True)!=source',b'False'),
                (b'target.resolve(strict=True)!=target',b'False'),
                (b'not stat.S_ISREG(target.lstat().st_mode)',b'False'),
                (b"checksum!=row[1] or row[1]!=ref['canonical_hash']",b'False'),
                (b"r.get('identity')!=ref['canonical_identity']",b'False'),
                (b'if not decoder.eof or len(raw)>32*1024*1024:',b'if False:'),
                (b'ON canonical_event_refs(lane,candidate,kind)',b'ON canonical_event_refs(lane,kind,candidate)'),
                (b'self.db.execute("PRAGMA synchronous=FULL")',b'self.db.execute("PRAGMA synchronous=OFF")')),
            'meme_machine/solana_scoped_retirement.py':(
                (b'from .runtime.candidate_history import CandidateHistory,retained_reference_path',
                    b'from .runtime.candidate_history import CandidateHistory'),
                (b"db.execute('PRAGMA database_list')",b"db.execute('PRAGMA table_list')"),
                (b"if row[1]=='main'",b"if row[1]=='temp'"),
                (b'len(main)==1 and main[0]',b'len(main)>=1 and main[0]'),
                (b'source=Path(main[0]) if len(main)==1 and main[0] else None',
                    b'source=None'),
                (b"source.with_name('solana-candidate-history.sqlite')",b"source.with_name('foreign.sqlite')"),
                (b'candidate_path=candidate,cold=True',b'candidate_path=candidate,cold=False'),
                (b'canonical_path=source',b'canonical_path=None'),
                (b'if archive not in cache:',b'if False:'),
                (b'if manifest is None:',b'if False:'),
                (b'if hashlib.sha256(packed).hexdigest()!=manifest[1]:',b'if False:'),
                (b'decoder.decompress(packed,32*1024*1024+1)',b'decoder.decompress(packed)'),
                (b'if len(raw)>32*1024*1024 or not decoder.eof:',b'if False:'),
                (b"cache[archive]={x['record']['identity']:x for x in json.loads(raw)}",
                    b"cache[archive]={identity:x for x in json.loads(raw)}"),
                (b'item=cache[archive].get(identity)',b'item=next(iter(cache[archive].values()))'),
                (b'if item is None:',b'if False:')),
        }
        for relative,(before,after) in CANONICAL_COLD_DELTAS.items():
            current=pump_restore_archive_reuse_predecessor(self,relative,pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes()))
            self.assertEqual(hashlib.sha256(current).hexdigest(),after,
                relative+':active exact canonical cold-path repair')
            prior=subprocess.check_output(['git','show',CANONICAL_COLD_REFERENCE+':'+relative],cwd=ROOT)
            self.assertEqual(hashlib.sha256(prior).hexdigest(),before,
                relative+':independently pinned prior runtime')
            self.assertEqual(canonical_cold_predecessor(self,relative,current),prior)
            self.assertEqual(canonical_cold_predecessor(self,relative,prior),prior)
            if relative==PUMP_RESTORE_SELECTION_SOURCE:
                self.assertEqual(before,PUMP_RESTORE_SELECTION_AFTER,
                    relative+':all earlier index and retained-reference pins remain unchanged')
                for predecessor in (pump_restore_selection_predecessor,retained_canonical_predecessor,
                        native_startup_failure_predecessor,rally_predecessor,opportunity_predecessor):
                    self.assertEqual(predecessor(self,relative,current),predecessor(self,relative,prior),
                        relative+':complete previous source/economic guard chain retained')
            changes=[current+b'\n# unreviewed canonical cold-reader change\n',b'']
            for previous,successor in mutations[relative]:
                self.assertIn(previous,current,relative+':negative mutation target exists')
                changes.append(current.replace(previous,successor,1))
            for changed in changes:
                self.assertNotEqual(changed,current,relative+':negative mutation changes source')
                with self.assertRaises(AssertionError):canonical_cold_predecessor(self,relative,changed)
                if relative==PUMP_RESTORE_SELECTION_SOURCE:
                    for predecessor in (pump_restore_selection_predecessor,retained_canonical_predecessor,
                            native_startup_failure_predecessor,rally_predecessor,opportunity_predecessor):
                        with self.assertRaises(AssertionError):predecessor(self,relative,changed)

    def test_pump_restore_selection_reverses_only_three_fixed_index_declarations(self):
        import hashlib
        relative=PUMP_RESTORE_SELECTION_SOURCE;current=canonical_cold_predecessor(self,relative,pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes()))
        self.assertEqual(hashlib.sha256(current).hexdigest(),PUMP_RESTORE_SELECTION_AFTER,
            relative+':active exact restore-selection index repair')
        self.assertEqual(PUMP_RESTORE_SELECTION_BEFORE,RETAINED_CANONICAL_AFTER,
            relative+':existing retained-reference source pin remains unchanged')
        prior=subprocess.check_output(['git','show',PUMP_RESTORE_SELECTION_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(pump_restore_selection_predecessor(self,relative,current),prior)
        self.assertEqual(pump_restore_selection_predecessor(self,relative,prior),prior)
        self.assertEqual(retained_canonical_predecessor(self,relative,current),
            retained_canonical_predecessor(self,relative,prior))
        self.assertEqual(native_startup_failure_predecessor(self,relative,current),
            native_startup_failure_predecessor(self,relative,prior))
        self.assertEqual(rally_predecessor(self,relative,current),rally_predecessor(self,relative,prior))
        self.assertEqual(opportunity_predecessor(self,relative,current),
            opportunity_predecessor(self,relative,prior))
        changes=[current+b'\n# unreviewed restore-selection change\n',b'']
        for ddl in PUMP_RESTORE_SELECTION_DDL:
            changes.extend((current.replace(ddl,b'',1),current.replace(ddl,ddl+ddl,1)))
        for previous,successor in (
                (b'ON candidates(lane,first_observed,candidate)',b'ON candidates(first_observed,lane,candidate)'),
                (b'ON events(lane,candidate,kind)',b'ON events(kind,lane,candidate)'),
                (b'ON canonical_event_refs(lane,candidate,kind)',b'ON canonical_event_refs(lane,kind,candidate)'),
                (b'if event_prefix is not None:',b'if False:'),
                (b'if kind_prefix is not None:',b'if False:'),
                (b"sql+=\" ORDER BY first_observed,lane,candidate\"",b"sql+=\" ORDER BY candidate\""),
                (b"self.db.set_progress_handler(lambda:int(bool(cancelled())),1000)",
                    b'self.db.set_progress_handler(lambda:0,1000)'),
                (b'digest(ref)!=checksum',b'False'),
                (b"row[1]!=ref['canonical_hash']",b'False'),
                (b'self.db.execute("PRAGMA synchronous=FULL")',b'self.db.execute("PRAGMA synchronous=OFF")')):
            self.assertIn(previous,current,relative+':negative mutation target exists')
            changes.append(current.replace(previous,successor,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):pump_restore_selection_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):retained_canonical_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):native_startup_failure_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):rally_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_prejoin_observation_preserves_exact_incident_gaps_and_full_ack_authority(self):
        import hashlib
        relative=PREJOIN_SOURCE;current=preparation_replay_predecessor(self,relative,pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes()))
        self.assertEqual(hashlib.sha256(current).hexdigest(),PREJOIN_SOURCE_AFTER,
            relative+':active exact prejoin-observation proof')
        prior=subprocess.check_output(['git','show',PREJOIN_SOURCE_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(hashlib.sha256(prior).hexdigest(),PREJOIN_SOURCE_BEFORE,
            relative+':independently pinned existing economic-recovery source')
        self.assertEqual(prejoin_source_predecessor(self,relative,current),prior)
        self.assertEqual(prejoin_source_predecessor(self,relative,prior),prior)
        self.assertEqual(session_economic_recovery_predecessor(self,relative,current),
            session_economic_recovery_predecessor(self,relative,prior))
        self.assertEqual(native_startup_failure_predecessor(self,relative,current),
            native_startup_failure_predecessor(self,relative,prior))
        self.assertEqual(recovered_economic_boundary_predecessor(self,relative,current),
            recovered_economic_boundary_predecessor(self,relative,prior))
        self.assertEqual(program_gap_observation_predecessor(self,relative,current),
            program_gap_observation_predecessor(self,relative,prior))
        self.assertEqual(rally_predecessor(self,relative,current),rally_predecessor(self,relative,prior))
        self.assertEqual(opportunity_predecessor(self,relative,current),
            opportunity_predecessor(self,relative,prior))
        changes=[current+b'\n# unreviewed prejoin-observation source change\n',b'']
        for previous,successor in (
                (b'PREJOIN_SESSION_OBSERVATION_ID=234592',b'PREJOIN_SESSION_OBSERVATION_ID=234593'),
                (b"('phase','CANDIDATE_QUEUE')",b"('phase','LOG_BUFFER_WAIT')"),
                (b"        _require_observation_funding_closed()\n",b'        pass\n'),
                (b"if not body['pending_handlers']:return raw",b'if True:return raw'),
                (b"body['state']!='DRAINED'",b'False'),
                (b'prejoin_callback_completion_demonstrated=False',b'prejoin_callback_completion_demonstrated=True'),
                (b'prejoin_original_source_drain_pass=False',b'prejoin_original_source_drain_pass=True'),
                (b'prejoin_unsealed_native_slot=457898776',b'prejoin_unsealed_native_slot=457898777'),
                (b"current['prejoin_observation_reference']=previous['prejoin_observation_reference']",
                    b"current['prejoin_observation_reference']={}"),
                (b"body=dict(body,prejoin_observation_reference=started['prejoin_observation_reference'])",b'body=dict(body)'),
                (b'_preserve_drain_bytes(state,OBSERVATION_DRAIN_KEY,failed,SOURCE_DRAIN_BYTES)',b'pass'),
                (b'_preserve_drain_bytes(state,HANDLER_RECOVERY_KEY,original,HandlerLedger.maximum_bytes)',b'pass')):
            self.assertIn(previous,current,relative+':negative mutation target exists')
            changes.append(current.replace(previous,successor,1))
        selected=next(n for n in ast.parse(current).body
            if isinstance(n,ast.FunctionDef) and n.name=='_preserved_prejoin_observation')
        prejoin=ast.get_source_segment(current.decode(),selected).encode()
        for previous,successor in (
                (b'if not direct and archived is None and session is None and carried is None:return {},None',
                    b'if not direct:return {},None'),
                (b'old=handlers if direct and isinstance(handlers,str)',b'old=handlers if isinstance(handlers,str)'),
                (b'not direct and carried==reference',b'not direct'),
                (b'hashlib.sha256(old.encode()).hexdigest()==PREJOIN_HANDLER_SHA256',b'True'),
                (b'_committed_census(body)',b'True'),
                (b"body.get('terminal_record_unavailable') is True",b"body.get('terminal_record_unavailable') is False"),
                (b"body.get('unexpected_cancellation') is True",b"body.get('unexpected_cancellation') is False"),
                (b"('accepted_pending',0)",b"('accepted_pending',1)"),
                (b"('oldest_meta',False)",b"('oldest_meta',True)"),
                (b'==PREJOIN_NATIVE_HEADS[family]',b'is not None'),
                (b'lo=457897559;hi=457898887',b'lo=457898777;hi=457898887'),
                (b'life.unconsumed(scope) is None',b'True'),
                (b'require(len(residual)==1)',b'require(True)'),
                (b'hashlib.sha256(receipt[1].encode()).hexdigest()==receipt[2]',b'True'),
                (b"SELECT 1 FROM candidate_pending_proofs WHERE id=?",b"SELECT 1 FROM candidate_pending_proofs WHERE id=? AND 0"),
                (b"IntervalProof(scope,a,b,value.get('source'),endpoint,witness,value.get('observed_at',0)).validate()",b'None'),
                (b'require(not _subtract_intervals(covered,published))',b'require(True)'),
                (b'rolling.missing(family,scope,lo,hi)',b'[]'),
                (b'rolling._history_input_byte_limit=16*1024*1024',b'rolling._history_input_byte_limit=160*1024*1024')):
            self.assertIn(previous,prejoin,relative+':prejoin-specific negative mutation target exists')
            changes.append(current.replace(prejoin,prejoin.replace(previous,successor,1),1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):prejoin_source_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):session_economic_recovery_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):rally_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_maintenance_entry_clock_preserves_exact_original_leases_and_native_guards(self):
        import hashlib
        mutations={
            'meme_machine/solana_evidence_service.py':(
                (b'if entered-submitted>runtime.leases.owner:',b'if False:'),
                (b'runtime.turn(flight,submitted,owner_entered=entered)',
                    b'runtime.turn(flight,submitted,owner_entered=time.monotonic())'),
                (b'runtime.turn(flight,submitted,owner_entered=entered)',b'runtime.turn(flight,submitted)'),
                (b'admission.entry(offer)',b'None'),
                (b'accepted=lambda future:admission.accepted(future,offer)',b'accepted=lambda future:None'),
                (b"admit_before=offer.row['deadline'] if offer is not None else None",b'admit_before=None')),
            'meme_machine/solana_maintenance_runtime.py':(
                (b'all(type(at) in (int,float) and math.isfinite(at) for at in clocks)',b'all(True for at in clocks)'),
                (b'0<=submitted<=entered<=current',b'0<=submitted<=entered'),
                (b'start=entered;owner_delay=entered-submitted',b'start=current;owner_delay=entered-submitted'),
                (b'start=entered;owner_delay=entered-submitted',b'start=entered;owner_delay=0'),
                (b'owner_delay>self.leases.owner',b'owner_delay>self.leases.owner+3'),
                (b'with self.execution_lease(start+self.leases.execution):',
                    b'with self.execution_lease(current+self.leases.execution):'),
                (b'elif current-flight.submitted>=self.leases.worker:',b'elif False:'),
                (b"        if self.monotonic() >= deadline:\n            raise EvidenceUnavailable('maintenance_execution_lease_exceeded')\n",
                    b'        pass\n'),
                (b"if self.monotonic() >= deadline and not getattr(self.writer,'_retention_atomic',False):",b'if False:'),
                (b'self.writer.db.set_progress_handler(previous,1000 if previous else 0)',
                    b'self.writer.db.set_progress_handler(None,0)'),
                (b'if end-start>self.leases.execution:',b'if False:'),
                (b'prior = source_now+RECOVERY_SOURCE_SECONDS, wall_now, PIPELINE_SLACK_RECORDS',
                    b'prior = source_now+RECOVERY_SOURCE_SECONDS+1, wall_now, PIPELINE_SLACK_RECORDS'),
                (b'flight.submitted+self.leases.worker+self.leases.drought',
                    b'now+self.leases.worker+self.leases.drought'),
                (b'self.state.archive_commit_slice_and_plan(plan,receipt)',b'(None,None)'),
                (b'self.state.fence.session!=self.generation',b'False')),
        }
        self.assertEqual(set(mutations),set(MAINTENANCE_ENTRY_CLOCK_DELTAS))
        for relative,(_,after,_) in MAINTENANCE_ENTRY_CLOCK_DELTAS.items():
            current=source_recorder_publication_predecessor(self,relative,(ROOT/relative).read_bytes())
            self.assertEqual(hashlib.sha256(current).hexdigest(),after,relative+':active exact maintenance clock repair')
            prior=subprocess.check_output(['git','show',MAINTENANCE_ENTRY_CLOCK_REFERENCE+':'+relative],cwd=ROOT)
            self.assertEqual(maintenance_entry_clock_predecessor(self,relative,current),prior)
            self.assertEqual(maintenance_entry_clock_predecessor(self,relative,prior),prior)
            changes=[current+b'\n# unreviewed maintenance clock source change\n',b'']
            for previous,successor in mutations[relative]:
                self.assertIn(previous,current,relative+':negative mutation target exists')
                changes.append(current.replace(previous,successor,1))
            if relative=='meme_machine/solana_maintenance_runtime.py':
                # Expiry must reject before the first caller/native statement,
                # even when no SQLite progress callback would run at all.
                expiry=(b"        if self.monotonic() >= deadline:\n"
                    b"            raise EvidenceUnavailable('maintenance_execution_lease_exceeded')\n")
                self.assertLess(current.index(expiry),current.index(b'            yield\n'))
                changes.append(current.replace(expiry,b'',1).replace(b'            yield\n',
                    b'            yield\n            if self.monotonic() >= deadline:\n'
                    b"                raise EvidenceUnavailable('maintenance_execution_lease_exceeded')\n",1))
            for changed in changes:
                self.assertNotEqual(changed,current,relative+':negative mutation changes source')
                with self.assertRaises(AssertionError):maintenance_entry_clock_predecessor(self,relative,changed)

    def test_survivor_increment_continuity_reverses_only_exact_required_window_precheck(self):
        import hashlib,json
        relative=SURVIVOR_INCREMENT_CONTINUITY_SOURCE;current=(ROOT/relative).read_bytes()
        self.assertEqual(hashlib.sha256(current).hexdigest(),SURVIVOR_INCREMENT_CONTINUITY_AFTER,
            relative+':active exact Survivor required-window continuity repair')
        prior=subprocess.check_output(['git','show',SURVIVOR_INCREMENT_CONTINUITY_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(hashlib.sha256(prior).hexdigest(),SURVIVOR_INCREMENT_CONTINUITY_BEFORE,
            relative+':independently pinned previous strategy source')
        rally=rally_manifest(self)['files'][relative]
        opportunity=json.loads(OPPORTUNITY_MANIFEST.read_text())['files'][relative]
        self.assertEqual(rally['after_sha256'],SURVIVOR_INCREMENT_CONTINUITY_BEFORE)
        self.assertEqual(set(SURVIVOR_INCREMENT_CONTINUITY_PRIORS),
            {rally['before_sha256'],opportunity['before_sha256']})
        self.assertEqual(survivor_increment_continuity_predecessor(self,relative,current),prior)
        self.assertEqual(survivor_increment_continuity_predecessor(self,relative,prior),prior)
        self.assertEqual(rally_predecessor(self,relative,current),rally_predecessor(self,relative,prior))
        self.assertEqual(opportunity_predecessor(self,relative,current),
            opportunity_predecessor(self,relative,prior))
        checkpoint=b"        checkpoint=row.get('evidence_checkpoint')"
        self.assertLess(current.index(SURVIVOR_INCREMENT_CONTINUITY_BLOCK),current.index(checkpoint))
        changes=[current+b'\n# unreviewed Survivor continuity change\n',b'']
        for previous,successor in (
                (b"lower=graduation.get('slot')",b"lower=row.get('evidence_checkpoint',{}).get('consumed_slot')"),
                (b'upper=slot',b'upper=lower'),
                (b"self.plane.bounds(SWAP_SCOPE,graduation['at'],at,upper_slot=slot)",
                    b"self.plane.bounds(SWAP_SCOPE,row['through'],at,upper_slot=slot)"),
                (b'elif type(lower) is not int or lower<0:',b'elif False:'),
                (b"reader.candidate('pumpswap',row['graduation']['pool'])",b"reader.candidate('pumpswap','unrelated')"),
                (b'scope=candidate.scope if isinstance(reader,ConsumerReader) else SWAP_SCOPE',b'scope=SWAP_SCOPE'),
                (b'if not candidate.covered(scope,lower,upper,as_of=time.time()):',b'if False:'),
                (b"db.execute('BEGIN')",b"db.execute('SELECT 1')"),
                (b"finally:db.execute('ROLLBACK')",b'finally:pass'),
                (b"if quote['quantity']!=qty or not 0<=now-quote['market_time']<=10 or not 0<=now-quote['acquired']<=5:",
                    b'if False:'),
                (b"return POLICY['bridge_exits'] if risk.get('execution_profile')=='pump_postgrad_bridge' else policy",
                    b'return policy')):
            self.assertIn(previous,current,relative+':negative mutation target exists')
            changes.append(current.replace(previous,successor,1))
        # A fresh check after the shortcut would still let an already durable
        # checkpoint acknowledge stale prefix authority, so its ordering pins.
        anchor=b"        grad=row['graduation'];lo,hi="
        self.assertIn(anchor,current)
        changes.append(current.replace(SURVIVOR_INCREMENT_CONTINUITY_BLOCK,b'',1).replace(
            anchor,SURVIVOR_INCREMENT_CONTINUITY_BLOCK+anchor,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):survivor_increment_continuity_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):rally_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_archive_log_consistency_reverses_only_exact_zero_match_rejection(self):
        import hashlib
        relative=ARCHIVE_LOG_CONSISTENCY_SOURCE;current=archive_log_order_predecessor(self,relative,(ROOT/relative).read_bytes())
        self.assertEqual(hashlib.sha256(current).hexdigest(),ARCHIVE_LOG_CONSISTENCY_AFTER,
            relative+':active exact complete-log-consistency repair')
        prior=subprocess.check_output(['git','show',ARCHIVE_LOG_CONSISTENCY_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(hashlib.sha256(prior).hexdigest(),ARCHIVE_LOG_CONSISTENCY_BEFORE,
            relative+':independently pinned retained-log predecessor')
        self.assertEqual(archive_log_consistency_predecessor(self,relative,current),prior)
        self.assertEqual(archive_log_consistency_predecessor(self,relative,prior),prior)
        self.assertEqual(retained_archive_log_shape_predecessor(self,relative,current),
            retained_archive_log_shape_predecessor(self,relative,prior))
        self.assertEqual(archive_complete_logs_predecessor(self,relative,current),
            archive_complete_logs_predecessor(self,relative,prior))
        self.assertEqual(rally_predecessor(self,relative,current),rally_predecessor(self,relative,prior))
        self.assertEqual(opportunity_predecessor(self,relative,current),
            opportunity_predecessor(self,relative,prior))
        changes=[current+b'\n# unreviewed complete-log-consistency change\n',b'']
        for previous,successor in (
                (ARCHIVE_LOG_CONSISTENCY_NEW,ARCHIVE_LOG_CONSISTENCY_NEW.replace(b'<1:',b'<0:')),
                (b'complete[:len(prefix)]!=prefix',b'False'),
                (b'complete[start:start+len(suffix)]==suffix',b'True'),
                (b'for start in range(len(prefix),len(complete)-len(suffix)+1))<1',
                    b'for start in range(0,len(complete)-len(suffix)+1))<1'),
                (b'if len(markers)!=1:raise KeyError()',b'if False:raise KeyError()'),
                (b"'truncat' in line.lower() for line in complete",b'False for line in complete'),
                (b"canonical(fetched['transaction'])!=canonical(original['transaction'])",b'False'),
                (b"type(fetched['slot']) is not int or fetched['slot']!=slot",b'False'),
                (b"canonical(fetched['blockTime'])!=canonical(original['blockTime'])",b'False'),
                (b"old['err'] is not None or new['err'] is not None",b'False'),
                (b"tx['meta']['logMessages']=list(complete)",b"tx['meta']['logMessages']=list(prefix+suffix)"),
                (b'type(supplement) is not ArchiveLogSupplement',b'False'),
                (b'supplement.endpoint_identity!=endpoint_identity',b'False'),
                (b"canonical(original)!=supplement.original_json",b'False')):
            self.assertIn(previous,current,relative+':negative mutation target exists')
            changes.append(current.replace(previous,successor,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):archive_log_consistency_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):retained_archive_log_shape_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):archive_complete_logs_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):rally_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_retained_archive_log_shape_reverses_only_exact_join_and_receipt_metadata(self):
        import hashlib
        relative=RETAINED_ARCHIVE_LOG_SHAPE_SOURCE;current=archive_log_consistency_predecessor(self,relative,(ROOT/relative).read_bytes())
        self.assertEqual(hashlib.sha256(current).hexdigest(),RETAINED_ARCHIVE_LOG_SHAPE_AFTER,
            relative+':active exact retained-archive-log repair')
        prior=subprocess.check_output(['git','show',RETAINED_ARCHIVE_LOG_SHAPE_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(hashlib.sha256(prior).hexdigest(),RETAINED_ARCHIVE_LOG_SHAPE_BEFORE,
            relative+':independently pinned complete-log predecessor')
        self.assertEqual(retained_archive_log_shape_predecessor(self,relative,current),prior)
        self.assertEqual(retained_archive_log_shape_predecessor(self,relative,prior),prior)
        self.assertEqual(archive_complete_logs_predecessor(self,relative,current),
            archive_complete_logs_predecessor(self,relative,prior))
        self.assertEqual(rally_predecessor(self,relative,current),rally_predecessor(self,relative,prior))
        self.assertEqual(opportunity_predecessor(self,relative,current),
            opportunity_predecessor(self,relative,prior))
        changes=[current+b'\n# unreviewed retained-log source change\n',b'']
        for previous,successor in (
                (b'if len(markers)!=1:raise KeyError()',b'if False:raise KeyError()'),
                (b'complete[:len(prefix)]!=prefix',b'False'),
                (b'complete[start:start+len(suffix)]==suffix',b'True'),
                (b'for start in range(len(prefix),len(complete)-len(suffix)+1))!=1',
                    b'for start in range(0,len(complete)-len(suffix)+1))<1'),
                (b'for start in range(len(prefix),len(complete)-len(suffix)+1))!=1',
                    b'for start in range(0,len(complete)-len(suffix)+1))!=1'),
                # The reviewed next layer now admits <1, while <0 would accept
                # zero known-content matches and remains an unsafe mutation.
                (b'for start in range(len(prefix),len(complete)-len(suffix)+1))!=1',
                    b'for start in range(len(prefix),len(complete)-len(suffix)+1))<0'),
                (b"original_prefix_length=next(i for i,line in enumerate(tx['meta']['logMessages'])\n"
                    b"                if 'truncat' in line.lower())",
                    b"original_prefix_length=len(tx['meta']['logMessages'])-1"),
                (b"'truncat' in line.lower() for line in complete",b'False for line in complete'),
                (b"canonical(fetched['transaction'])!=canonical(original['transaction'])",b'False'),
                (b"type(fetched['slot']) is not int or fetched['slot']!=slot",b'False'),
                (b"canonical(fetched['blockTime'])!=canonical(original['blockTime'])",b'False'),
                (b"old['err'] is not None or new['err'] is not None",b'False'),
                (b"fetched['transactionIndex']!=index",b'False'),
                (b'type(supplement) is not ArchiveLogSupplement',b'False'),
                (b'supplement.endpoint_identity!=endpoint_identity',b'False'),
                (b"canonical(original)!=supplement.original_json",b'False'),
                (b'archive_log_supplements=retained_supplements',b'archive_log_supplements=[]')):
            self.assertIn(previous,current,relative+':negative mutation target exists')
            changes.append(current.replace(previous,successor,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):retained_archive_log_shape_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):archive_complete_logs_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):rally_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_session_economic_recovery_preserves_original_incidents_and_exact_full_proofs(self):
        import hashlib
        relative=SESSION_ECONOMIC_RECOVERY_SOURCE;current=prejoin_source_predecessor(self,relative,pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes()))
        self.assertEqual(hashlib.sha256(current).hexdigest(),SESSION_ECONOMIC_RECOVERY_AFTER,
            relative+':active exact independently bound session-recovery source')
        prior=subprocess.check_output(['git','show',SESSION_ECONOMIC_RECOVERY_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(hashlib.sha256(prior).hexdigest(),SESSION_ECONOMIC_RECOVERY_BEFORE,
            relative+':independently pinned previous economic-recovery boundary')
        self.assertEqual(session_economic_recovery_predecessor(self,relative,current),prior)
        self.assertEqual(session_economic_recovery_predecessor(self,relative,prior),prior)
        self.assertEqual(native_startup_failure_predecessor(self,relative,current),prior)
        self.assertEqual(recovered_economic_boundary_predecessor(self,relative,current),
            recovered_economic_boundary_predecessor(self,relative,prior))
        self.assertEqual(program_gap_observation_predecessor(self,relative,current),
            program_gap_observation_predecessor(self,relative,prior))
        self.assertEqual(rally_predecessor(self,relative,current),rally_predecessor(self,relative,prior))
        self.assertEqual(opportunity_predecessor(self,relative,current),
            opportunity_predecessor(self,relative,prior))
        changes=[current+b'\n# unreviewed session-recovery source change\n',b'']
        for previous,successor in (
                (b'!=(564488,564486,2)',b'!=(564488,564488,0)'),
                (b"('id',60266)",b"('id',60267)"),
                (b"accounting.get('returned')==60345",b"accounting.get('returned')==60346"),
                (b"('rolling',191,183)",b"('rolling',191,191)"),
                (b'original_queue_acknowledgement_verified=False',b'original_queue_acknowledgement_verified=True'),
                (b'original_source_drain_pass=False',b'original_source_drain_pass=True'),
                (b'callback_completion_demonstrated=False',b'callback_completion_demonstrated=True'),
                (b'historical_recovery_verified=False',b'historical_recovery_verified=True'),
                (b"        _require_observation_funding_closed()\n",b'        pass\n'),
                (b"hashlib.sha256(row[3].encode()).hexdigest()==reference['sha256']",b'True'),
                (b"descriptor.get('failed_census_sha256')==row[1]",b'True'),
                (b"accounting.get('run')==body.get('run_identity')",b'True'),
                (b"accounting.get('pid')==body.get('source_pid')",b'True'),
                (b"require(0<queues['rolling']['pending']<=8)",b'require(True)'),
                (b"len(matches)==1 and all(matches[0].get(k)==v for k,v in record.items())",b'True'),
                (b"head['session']==observed['session']",b'True'),
                (b"head['slot']<=observed['completed']",b'True'),
                (b'_economic_require(actual==descriptor)',b'_economic_require(True)'),
                (b"and hashlib.sha256(old_ledger.encode()).hexdigest()==descriptor.get('handler_ledger_sha256')",b'and True'),
                (b"row[:6]==(family,PROGRAMS[family],lo,hi,'complete',None)",b'True'),
                (b'require(len(receipts)==pages)',b'require(True)'),
                (b"result.get('complete') is (index==pages-1)",b'True'),
                (b"digest([scope,a,b,body['witness']])==identity",b'True'),
                (b"SELECT 1 FROM candidate_pending_proofs WHERE id=?",b"SELECT 1 FROM candidate_pending_proofs WHERE id=? AND 0"),
                (b'life.unconsumed(scope) is None',b'True'),
                (b'rolling.missing(family,scope,lo,hi)==[]',b'True'),
                (b'require(not _subtract_intervals(covered,published))',b'require(True)'),
                (b"retained_economic_tail_unavailable=tail_missing",b'retained_economic_tail_unavailable=False'),
                (b"_economic_require(carried==references)",b'_economic_require(True)'),
                (b"_economic_require(len(live)==len(expected) and all(expected.get((r.get('run'),r.get('id')))==r for r in live))",
                    b'_economic_require(True)'),
                (b"and not session_current and",b'and'),
                (b"_preserve_drain_bytes(state,HANDLER_RECOVERY_KEY,handler_boundary,HandlerLedger.maximum_bytes)",b'pass'),
                (b"current['session_economic_recovery_references']=previous['session_economic_recovery_references']",
                    b"current['session_economic_recovery_references']=[]")):
            self.assertIn(previous,current,relative+':negative mutation target exists')
            changes.append(current.replace(previous,successor,1))
        # Deleting the durable descriptor reader must not fall back to the old
        # f76 or DRAINED boundary, even though those original proofs still pin.
        lines=current.splitlines(keepends=True)
        descriptor=next(n for n in ast.parse(current).body
            if isinstance(n,ast.FunctionDef) and n.name=='_economic_descriptor_rows')
        changes.append(b''.join(lines[:descriptor.lineno-1]+lines[descriptor.end_lineno:]))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):session_economic_recovery_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):native_startup_failure_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):recovered_economic_boundary_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):program_gap_observation_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):rally_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_frozen_paused_reader_preserves_original_financial_and_native_proof(self):
        import hashlib
        relative=FROZEN_PAUSED_READER_SOURCE;current=(ROOT/relative).read_bytes()
        self.assertEqual(hashlib.sha256(current).hexdigest(),FROZEN_PAUSED_READER_AFTER,
            relative+':active exact protected paused-reader proof')
        prior=subprocess.check_output(['git','show',FROZEN_PAUSED_READER_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(hashlib.sha256(prior).hexdigest(),FROZEN_PAUSED_READER_BEFORE,
            relative+':independently pinned paused-lane proof predecessor')
        self.assertEqual(frozen_paused_reader_predecessor(self,relative,current),prior)
        self.assertEqual(frozen_paused_reader_predecessor(self,relative,prior),prior)
        self.assertEqual(current.count(b"db.execute('PRAGMA query_only=ON')"),2,
            relative+':both original database readers retain query-only protection')
        self.assertEqual(current.count(b"if not db.in_transaction:db.execute('BEGIN')"),2,
            relative+':both readers retain a consistent original or supplied transaction')
        changes=[current+b'\n# unreviewed paused-lane reader change\n',b'']
        for previous,successor in (
                (b'def assert_clear(root, account, *, read_database=None):',
                    b'def assert_clear(root, account, *, read_database=lambda path:None):'),
                (b'if read_database is None:',b'if True:'),
                (b"return closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1))",
                    b"return closing(sqlite3.connect(path.resolve().as_uri()+'?mode=rw',uri=True,timeout=1))"),
                (b'with read_database(shared) as db:',b'with read_database(path) as db:'),
                (b'with read_database(path) as db:',b'with read_database(shared) as db:'),
                (b"db.execute('PRAGMA query_only=ON')",b"db.execute('PRAGMA query_only=OFF')"),
                (b"if not db.in_transaction:db.execute('BEGIN')",b"if db.in_transaction:db.execute('BEGIN')"),
                (b"if shared.is_symlink():raise ValueError('symlink')",b'if False:pass'),
                (b'if path.is_symlink():',b'if False:'),
                (b"for lane in PAUSED_LANES:",b'for lane in ():'),
                (b"if row['lane'] == lane:",b'if False:'),
                (b"SELECT native,body FROM portfolio_native_pending WHERE lane=?",
                    b"SELECT native,body FROM portfolio_native_pending WHERE lane=? AND 0"),
                (b"if db.execute('PRAGMA quick_check(1)').fetchall() != [('ok',)]:",b'if False:'),
                (b'for row in native_positions(db,lane):',b'for row in ():'),
                (b"if row.get('status') not in ('settled','cancelled','written_off') or row.get('held',0):",
                    b'if False:'),
                (b"if value.get('active') or value.get('pending_intent') or value.get('pending'):",b'if False:'),
                (b'if obligations:raise PauseExposure(obligations)',b'if False:raise PauseExposure(obligations)'),
                (b"if _digest(genesis) != checksum:raise ValueError('native_genesis_corrupt')",b'if False:pass'),
                (b"if unknown:raise ValueError('unverified_native_economic_tables:' + ','.join(sorted(unknown)))",
                    b'if False:pass')):
            self.assertIn(previous,current,relative+':negative mutation target exists')
            changes.append(current.replace(previous,successor,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):frozen_paused_reader_predecessor(self,relative,changed)

    def test_retained_canonical_reference_reverses_only_exact_reader_compatibility(self):
        import hashlib
        relative=RETAINED_CANONICAL_SOURCE;current=pump_restore_selection_predecessor(self,relative,pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes()))
        self.assertEqual(hashlib.sha256(current).hexdigest(),RETAINED_CANONICAL_AFTER,
            relative+':active exact retained canonical-reference reader')
        prior=subprocess.check_output(['git','show',RETAINED_CANONICAL_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(hashlib.sha256(prior).hexdigest(),RETAINED_CANONICAL_BEFORE,
            relative+':independently pinned previous cancellation source')
        self.assertEqual(retained_canonical_predecessor(self,relative,current),prior)
        self.assertEqual(retained_canonical_predecessor(self,relative,prior),prior)
        self.assertEqual(native_startup_failure_predecessor(self,relative,current),prior)
        self.assertEqual(rally_predecessor(self,relative,current),rally_predecessor(self,relative,prior))
        self.assertEqual(opportunity_predecessor(self,relative,current),
            opportunity_predecessor(self,relative,prior))
        changes=[current+b'\n# unreviewed retained-reference reader change\n',b'']
        for previous,successor in (
                (b"if os.environ.get('MM_STATE_ROOT')==str(RETAINED_REFERENCE_LEGACY_ROOT):return path",
                    b'if True:return path'),
                (b"os.environ.get('MM_MODE')!='PAPER'",b'False'),
                (b"os.environ.get('MM_PAPER_EPOCH')!=RETAINED_REFERENCE_EPOCH",b'False'),
                (b"self.path!=root/'shared/solana-candidate-history.sqlite'",b'False'),
                (b"os.environ.get('MM_SOLANA_EVIDENCE_PLANE_DB',str(source))!=str(source)",b'False'),
                (b"root.resolve(strict=True)!=root",b'False'),
                (b"source.resolve(strict=True)!=source",b'False'),
                (b"target.resolve(strict=True)!=target",b'False'),
                (b"not stat.S_ISREG(target.lstat().st_mode)",b'False'),
                (b"r.get('identity')!=ref['canonical_identity']",b'False'),
                (b"checksum!=row[1] or row[1]!=ref['canonical_hash']",b'False'),
                (b"hashlib.sha256(packed).hexdigest()!=manifest[1]",b'False'),
                (b'self.db.execute("PRAGMA synchronous=FULL")',b'self.db.execute("PRAGMA synchronous=OFF")'),
                (b'if self.db.in_transaction:',b'if False:')):
            self.assertIn(previous,current,relative+':negative mutation target exists')
            changes.append(current.replace(previous,successor,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):retained_canonical_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):native_startup_failure_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):rally_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_recovered_economic_boundary_preserves_failed_census_and_all_previous_guards(self):
        import hashlib
        relative=RECOVERED_ECONOMIC_BOUNDARY_SOURCE;current=session_economic_recovery_predecessor(self,relative,pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes()))
        self.assertEqual(hashlib.sha256(current).hexdigest(),RECOVERED_ECONOMIC_BOUNDARY_AFTER,
            relative+':active exact recovered-economic boundary source')
        prior=subprocess.check_output(['git','show',RECOVERED_ECONOMIC_BOUNDARY_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(hashlib.sha256(prior).hexdigest(),PROGRAM_GAP_OBSERVATION_LAYER_AFTER,
            relative+':independently pinned previous program-gap source')
        self.assertEqual(recovered_economic_boundary_predecessor(self,relative,current),prior)
        self.assertEqual(recovered_economic_boundary_predecessor(self,relative,prior),prior)
        self.assertEqual(program_gap_observation_predecessor(self,relative,current),
            program_gap_observation_predecessor(self,relative,prior))
        self.assertEqual(rally_predecessor(self,relative,current),rally_predecessor(self,relative,prior))
        self.assertEqual(opportunity_predecessor(self,relative,current),
            opportunity_predecessor(self,relative,prior))
        changes=[current+b'\n# unreviewed economic-boundary change\n',b'']
        for previous,successor in (
                (b"body.get('all_accepted_committed') is False",b"body.get('all_accepted_committed') is True"),
                (b"('rolling',191,183)",b"('rolling',191,191)"),
                (b"original_queue_acknowledgement_verified=False",b"original_queue_acknowledgement_verified=True"),
                (b"original_source_drain_pass=False",b"original_source_drain_pass=True"),
                (b"and lifecycle.unconsumed(scope) is None",b'and True'),
                (b"rolling.missing(family,scope,457828555,457828563)==[]",b'True'),
                (b"retained_economic_tail_unavailable=tail_unavailable",b"retained_economic_tail_unavailable=False"),
                (b"require(not _subtract_intervals(covered_tail,published))",b'require(True)'),
                (b"if economic_current or archived_economic is not None or economic_retained:",
                    b"if economic_current or archived_economic is not None:"),
                (b"SELECT 1 FROM acquisition_observations WHERE id=232141",b"SELECT 1 FROM acquisition_observations WHERE id=0"),
                (b"SELECT 1 FROM acquisition_jobs WHERE id IN (?,?) LIMIT 1",b"SELECT 1 FROM acquisition_jobs WHERE id NOT IN (?,?) LIMIT 1"),
                (b"_preserve_drain_bytes(state,OBSERVATION_DRAIN_KEY,failed,SOURCE_DRAIN_BYTES)",b'pass'),
                (b"        _require_observation_funding_closed()\n",b'        pass\n'),
                (b"historical_recovery_verified=False",b"historical_recovery_verified=True")):
            self.assertIn(previous,current,relative+':negative mutation target exists')
            changes.append(current.replace(previous,successor,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):recovered_economic_boundary_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):program_gap_observation_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):rally_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_archive_complete_logs_reverse_exactly_and_reject_unverified_source(self):
        import hashlib
        mutations={
            'meme_machine/solana_selective_history.py':(
                (b"complete[:len(logs)-1]!=logs[:-1]",b'False'),
                (b"canonical(fetched['transaction'])!=canonical(original['transaction'])",b'False'),
                (b"type(fetched['slot']) is not int or fetched['slot']!=slot",b'False'),
                (b"type(supplement) is not ArchiveLogSupplement",b'False'),
                (b"supplement.endpoint_identity!=endpoint_identity",b'False'),
                (b"old['err'] is not None or new['err'] is not None",b'False'),
                (b"canonical(original)!=supplement.original_json",b'False'),
                (b"archive_log_supplements=retained_supplements",b'archive_log_supplements=[]')),
            'meme_machine/solana_selective_source.py':(
                (b"dict(commitment='finalized',encoding='json',maxSupportedTransactionVersion=1)",
                    b"dict(commitment='processed',encoding='json',maxSupportedTransactionVersion=1)"),
                (b'finalized_through=finalized,supplements=supplements',b'finalized_through=finalized,supplements=()'),
                (b'job[\'family\'],job[\'priority\'])',b'job[\'family\'],4)')),
        }
        self.assertEqual(set(mutations),set(ARCHIVE_COMPLETE_LOGS_DELTAS))
        for relative,(_,after,_,_,_) in ARCHIVE_COMPLETE_LOGS_DELTAS.items():
            current=retained_archive_log_shape_predecessor(self,relative,
                publication_accounting_predecessor(self,relative,(ROOT/relative).read_bytes()))
            self.assertEqual(hashlib.sha256(current).hexdigest(),after,relative+':active exact archive-log correction')
            prior=subprocess.check_output(['git','show',ARCHIVE_COMPLETE_LOGS_REFERENCE+':'+relative],cwd=ROOT)
            self.assertEqual(archive_complete_logs_predecessor(self,relative,current),prior)
            self.assertEqual(archive_complete_logs_predecessor(self,relative,prior),prior)
            self.assertEqual(rally_predecessor(self,relative,current),rally_predecessor(self,relative,prior))
            self.assertEqual(opportunity_predecessor(self,relative,current),
                opportunity_predecessor(self,relative,prior))
            changes=[current+b'\n# unreviewed archive-log change\n',b'']
            for previous,successor in mutations[relative]:
                self.assertIn(previous,current,relative+':negative mutation target exists')
                changes.append(current.replace(previous,successor,1))
            for changed in changes:
                self.assertNotEqual(changed,current,relative+':negative mutation changes source')
                with self.assertRaises(AssertionError):archive_complete_logs_predecessor(self,relative,changed)
                with self.assertRaises(AssertionError):rally_predecessor(self,relative,changed)
                with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_native_startup_failure_delta_preserves_all_prior_authority_and_source_guards(self):
        import hashlib
        mutations={
            'meme_machine/runtime/status.py':(
                (b'kind in _FAILURE_CLASSES',b'True'),
                (b"'pons.candidate_restore'",b"'pons.unreviewed_restore'")),
            'meme_machine/lanes/pons/pons_selective_cohort.py':(
                (b'startup_cancel=requested.is_set',b'startup_cancel=lambda:False'),),
            'meme_machine/runtime/robinhood/pons.py':(
                (b'startup_cancel=startup_cancel',b'startup_cancel=None'),
                (b"if row['interpretation']!=canonical(self.policy):",b'if False:')),
            'meme_machine/runtime/storage.py':(
                (b'lambda:int(bool(startup_cancel()))',b'lambda:0'),
                (b'with preserving_cleanup():db.set_progress_handler(None,0)',b'with preserving_cleanup():pass')),
        }
        self.assertEqual(set(mutations),set(NATIVE_STARTUP_FAILURE_DELTAS))
        for relative,(_,after,_,_,_) in NATIVE_STARTUP_FAILURE_DELTAS.items():
            current=pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes())
            self.assertEqual(hashlib.sha256(current).hexdigest(),after,relative+':active exact first-failure repair source')
            prior=subprocess.check_output(['git','show',NATIVE_STARTUP_FAILURE_REFERENCE+':'+relative],cwd=ROOT)
            self.assertEqual(native_startup_failure_predecessor(self,relative,current),prior)
            self.assertEqual(rally_predecessor(self,relative,current),rally_predecessor(self,relative,prior))
            self.assertEqual(opportunity_predecessor(self,relative,current),
                opportunity_predecessor(self,relative,prior))
            changes=[current+b'\n# unreviewed startup failure repair change\n',b'']
            for old,new in mutations[relative]:
                self.assertIn(old,current,relative+':negative mutation target exists')
                changes.append(current.replace(old,new,1))
            for changed in changes:
                self.assertNotEqual(changed,current,relative+':negative mutation changes source')
                with self.assertRaises(AssertionError):native_startup_failure_predecessor(self,relative,changed)
                with self.assertRaises(AssertionError):rally_predecessor(self,relative,changed)
                with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_survivor_monitor_replay_delta_preserves_fresh_proof_and_exact_prior_economics(self):
        import hashlib
        relative=SURVIVOR_MONITOR_REPLAY_SOURCE;current=(ROOT/relative).read_bytes()
        self.assertEqual(hashlib.sha256(current).hexdigest(),SURVIVOR_MONITOR_REPLAY_AFTER,
            relative+':active exact reviewed post-harvest replay source')
        prior=subprocess.check_output(['git','show',SURVIVOR_MONITOR_REPLAY_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(survivor_monitor_replay_predecessor(self,relative,current),prior)
        self.assertEqual(rally_predecessor(self,relative,current),rally_predecessor(self,relative,prior))
        self.assertEqual(opportunity_predecessor(self,relative,current),
            opportunity_predecessor(self,relative,prior))
        changes=[current+b'\n# unreviewed monetary replay change\n',b'']
        for old,new in (
                (b"if native_action=='partial_harvest' and sleeve is not None:",b"if False:"),
                (SURVIVOR_MONITOR_REPLAY_NEW_BLOCK,SURVIVOR_MONITOR_REPLAY_NEW_BLOCK.replace(
                    b"        native_sync(book,sleeve,identity)\n",b"        pass\n",1)),
                (b"    else:book.replay()\n",b"    else:pass\n"),
                (b"terminal_hash=digest(final),native_verified=True",b"terminal_hash=digest(final),native_verified=False")):
            self.assertIn(old,current,relative+':negative mutation target exists')
            changes.append(current.replace(old,new,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):survivor_monitor_replay_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):rally_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_program_gap_boundary_reverses_exactly_without_weakening_recovery_or_funding(self):
        import hashlib
        relative=PROGRAM_GAP_OBSERVATION_SOURCE;current=session_economic_recovery_predecessor(self,relative,pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes()))
        self.assertEqual(hashlib.sha256(current).hexdigest(),PROGRAM_GAP_OBSERVATION_AFTER,
            relative+':active exact preserved-program-gap source')
        prior=subprocess.check_output(['git','show',PROGRAM_GAP_OBSERVATION_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(program_gap_observation_predecessor(self,relative,current),prior)
        self.assertEqual(guarded_source(self,relative),prior)
        self.assertEqual(opportunity_predecessor(self,relative,current),
            opportunity_predecessor(self,relative,prior))
        changes=[current+b'\n# unreviewed recovery-boundary change\n',b'']
        for old,new in (
                (b"current_handler_disposition_verified=False",b"current_handler_disposition_verified=True"),
                (b"AND created=? AND reason=? AND repaired IS NULL AND id>=?",
                    b"AND created=? AND reason=? AND 1=1 AND id>=?"),
                (b"observed['early_log_max_slot'],created,gap[5],identity)",
                    b"observed['early_log_min_slot'],created,gap[5],identity)"),
                (b"        _require_observation_funding_closed()\n",b"        pass\n"),
                (b"accounting.get('returned')==60345",b"accounting.get('returned')==60346")):
            self.assertIn(old,current,relative+':negative mutation target exists')
            changes.append(current.replace(old,new,1))
        for changed in changes:
            self.assertNotEqual(changed,current,relative+':negative mutation changes source')
            with self.assertRaises(AssertionError):program_gap_observation_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_startup_history_cancellation_reverses_only_exact_reviewed_sources(self):
        import hashlib
        mutations={
            'meme_machine/runtime/candidate_history.py':(
                (b'lambda:int(bool(cancelled()))',b'lambda:0'),
                (b'if self.db.in_transaction:',b'if False:')),
            'meme_machine/lanes/pump/runner.py':(
                (b'cancelled=requested.is_set',b'cancelled=lambda:False'),
                (b'if mint in created:continue',b'if mint not in created:continue')),
            'meme_machine/lanes/pons/pons_selective_cohort.py':(
                (b'if requested.is_set():raise Shutdown()',b'if False:raise Shutdown()'),
                (b'native_startup_replay(requested.is_set)',b'native_startup_replay(lambda:False)')),
            'meme_machine/runtime/status.py':(
                (b"'pons.cohort_recovery'",b"'pons.unreviewed'"),
                (b'len(identity)>80',b'len(identity)>800')),
        }
        self.assertEqual(set(mutations),set(STARTUP_HISTORY_CANCEL_DELTAS))
        for relative,(_,after,_,_) in STARTUP_HISTORY_CANCEL_DELTAS.items():
            current=native_startup_failure_predecessor(self,relative,
                publication_accounting_predecessor(self,relative,pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes())))
            self.assertEqual(hashlib.sha256(current).hexdigest(),after,relative+':active exact reviewed cancellation source')
            prior=subprocess.check_output(['git','show',STARTUP_HISTORY_CANCEL_REFERENCE+':'+relative],cwd=ROOT)
            self.assertEqual(startup_history_cancellation_predecessor(self,relative,current),prior)
            self.assertEqual(opportunity_predecessor(self,relative,current),
                opportunity_predecessor(self,relative,prior))
            changes=[current+b'\n# unreviewed cancellation change\n',b'']
            for old,new in mutations[relative]:
                self.assertIn(old,current,relative+':negative mutation target exists')
                changes.append(current.replace(old,new,1))
            for changed in changes:
                self.assertNotEqual(changed,current,relative+':negative mutation changes source')
                with self.assertRaises(AssertionError):
                    startup_history_cancellation_predecessor(self,relative,changed)
                if relative in ('meme_machine/lanes/pump/runner.py','meme_machine/lanes/pons/pons_selective_cohort.py'):
                    with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_exact_restored_history_delta_preserves_original_supervisor_and_helper(self):
        relative='meme_machine/operational/supervisor.py'
        current=(ROOT/relative).read_bytes()
        prior=subprocess.check_output(['git','show',RESTORED_HISTORY_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(restored_provider_history_predecessor(self,relative,current),prior)
        self.assertEqual(opportunity_predecessor(self,relative,current),
            opportunity_predecessor(self,relative,prior))
        for changed in (current+b'\n# unreviewed provider-history change\n',
                current.replace(b'maximum_queue_wait_seconds=5',b'maximum_queue_wait_seconds=6',1),
                current.replace(b'require_restored_history(self,state,path,envelope)',b'pass',1)):
            self.assertNotEqual(changed,current)
            with self.assertRaises(AssertionError):restored_provider_history_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)
        helper=(ROOT/RESTORED_HISTORY_HELPER).read_bytes()
        restored_provider_helper(self,helper)
        for changed in (helper+b'\n# unreviewed guard change\n',
                helper.replace(b"supervisor.admission != 'OBSERVATION'",b'False',1)):
            self.assertNotEqual(changed,helper)
            with self.assertRaises(AssertionError):restored_provider_helper(self,changed)

    def test_rally_source_layer_reverses_exactly_and_rejects_unreviewed_bytes(self):
        import json
        manifest=rally_manifest(self)
        self.assertTrue(manifest['files'])
        for relative,record in manifest['files'].items():
            source=publication_accounting_predecessor(self,relative,pump_restore_predecessor(self,relative,(ROOT/relative).read_bytes()))
            prior=subprocess.check_output(['git','show',RALLY_BASE+':'+relative],cwd=ROOT)
            self.assertNotEqual(source,prior,relative+':only actual reviewed deltas belong in this layer')
            self.assertEqual(rally_predecessor(self,relative,source),prior)
            self.assertTrue(record['nodes'] or record['layouts'],relative+':named structural delta required')
            for mutation in (source+b'\n# unreviewed rally mutation\n',b''):
                with self.assertRaises(AssertionError):rally_predecessor(self,relative,mutation)

    def test_rally_added_policy_and_cycle_sources_have_exact_identities(self):
        import hashlib,json
        manifest=rally_manifest(self)
        self.assertTrue(manifest['added_sources'])
        for relative,record in manifest['added_sources'].items():
            source=(ROOT/relative).read_bytes()
            self.assertEqual(hashlib.sha256(source).hexdigest(),record['sha256'],relative)
            self.assertNotEqual(subprocess.run(['git','cat-file','-e',RALLY_BASE+':'+relative],cwd=ROOT,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False).returncode,0,
                relative+':explicit new source must be absent from the predecessor')
            for mutation in (source+b'\n',b''):
                self.assertNotEqual(hashlib.sha256(mutation).hexdigest(),record['sha256'],relative)

    def test_contained_observation_reverses_only_exact_reviewed_phase_and_cache_authority(self):
        import hashlib
        for relative,(_,after,_) in CONTAINED_OBSERVATION_DELTAS.items():
            # The exact outer rally layer restores the PR139 source first.
            # Its own full-byte/node guards reject every unreviewed combined edit.
            current=guarded_source(self,relative)
            prior=subprocess.check_output(['git','show',CONTAINED_OBSERVATION_REFERENCE+':'+relative],cwd=ROOT)
            self.assertEqual(hashlib.sha256(current).hexdigest(),after,
                relative+':active source must contain the exact reviewed safety correction')
            self.assertEqual(contained_observation_predecessor(self,relative,current),prior)
            self.assertEqual(opportunity_predecessor(self,relative,current),
                opportunity_predecessor(self,relative,prior))
            if relative=='meme_machine/operational/supervisor.py':
                changes=(current.replace(b"=='OBSERVATION':env['MM_OPERATIONAL_PHASE']",
                        b"=='NORMAL':env['MM_OPERATIONAL_PHASE']",1),
                    current.replace(b'maximum_queue_wait_seconds=5',b'maximum_queue_wait_seconds=6',1))
            else:
                changes=(current.replace(b'if callable(usable):usable(PUMP_SCOPE)',
                        b'if callable(usable):pass',1),
                    current.replace(b'if not candidate.covered(target,lo,hi,as_of=at):',b'if False:',1),
                    current.replace(b'upper_slot=max_slot,source_authority=authority)',b'upper_slot=max_slot)',1))
            for changed in (current+b'\n# unreviewed contained observation change\n',*changes):
                self.assertNotEqual(changed,current,relative+':negative mutation must change source')
                with self.assertRaises(AssertionError):contained_observation_predecessor(self,relative,changed)
                with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_backup_configuration_portability_keeps_exact_policy_and_redaction_guard(self):
        relative='meme_machine/operational/configuration.py'
        current=guarded_source(self,relative)
        prior=subprocess.check_output(['git','show',CPU_CAPACITY_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(backup_configuration_predecessor(self,relative,current),prior)
        self.assertEqual(opportunity_predecessor(self,relative,current),
            opportunity_predecessor(self,relative,prior))
        for changed in (current+b'\n# unreviewed change\n',
                current.replace(b'environment(backup_env_file)',b'backup_env_file.read_text()',1)):
            self.assertNotEqual(changed,current)
            with self.assertRaises(AssertionError):backup_configuration_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_host_cpu_portability_keeps_exact_supervisor_and_economic_guards(self):
        relative='meme_machine/operational/supervisor.py'
        current=guarded_source(self,relative)
        prior=subprocess.check_output(['git','show',CPU_CAPACITY_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(cpu_capacity_predecessor(self,relative,current),prior)
        self.assertEqual(opportunity_predecessor(self,relative,current),
            opportunity_predecessor(self,relative,prior))
        for changed in (current+b'\n# unreviewed change\n',
                current.replace(b'maximum_queue_wait_seconds=5',b'maximum_queue_wait_seconds=6',1),
                current.replace(b"within_cpu_limit",b"ignore_cpu_limit",1)):
            self.assertNotEqual(changed,current)
            with self.assertRaises(AssertionError):cpu_capacity_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_reviewed_discovery_nomination_delta_keeps_complete_strategy_guard(self):
        import hashlib
        relative=PONS_DISCOVERY_SOURCE;current=guarded_source(self,relative)
        self.assertEqual(hashlib.sha256(current).hexdigest(),PONS_DISCOVERY_AFTER_SHA256)
        prior=subprocess.check_output(['git','show',PONS_DISCOVERY_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(pons_discovery_predecessor(self,relative,current),prior)
        self.assertEqual(opportunity_predecessor(self,relative,current),opportunity_predecessor(self,relative,prior))
        for changed in (current+b'\n# unreviewed nomination change\n',b'',
                current.replace(b'if scout is None:',b'if scout is not None:',1),
                current.replace(b'coverage(drain=bool(fresh))',b'coverage()',1)):
            self.assertNotEqual(changed,current)
            with self.assertRaises(AssertionError):pons_discovery_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_reviewed_operation_costs_reverse_exactly_before_all_original_guards(self):
        import hashlib
        for relative,(_,after,_) in OPERATION_COST_DELTAS.items():
            current=guarded_source(self,relative)
            current=cpu_capacity_predecessor(self,relative,current)
            current=pons_discovery_predecessor(self,relative,current)
            self.assertEqual(hashlib.sha256(current).hexdigest(),after,
                relative+':active source must contain exactly the reviewed instrumentation')
            prior=subprocess.check_output(['git','show',OPERATION_COST_REFERENCE+':'+relative],cwd=ROOT)
            self.assertEqual(operation_cost_predecessor(self,relative,current),prior)
            if relative=='meme_machine/lanes/pons/evidence.py':
                # This file is protected by the original complete lane-tree loop,
                # independently of the opportunity manifest; retain that guard.
                original=subprocess.check_output(['git','show',
                    'e1070404849dfa86eb3e47d57cf24263b2fefc25:'+relative],cwd=ROOT)
                assert_holding_delta(self,relative,original,current)
            else:
                self.assertEqual(opportunity_predecessor(self,relative,current),
                    opportunity_predecessor(self,relative,prior))
            token=(b'MM_OPERATION_COST_DIAGNOSTICS' if relative==OBSERVATION_ROUTE_SOURCE
                   else b'operation_costs')
            self.assertTrue(token in current,relative+': mutation token must exist')
            for changed in (current+b'\n# unreviewed operation-cost change\n',b'',
                    current.replace(token,b'unreviewed_costs',1),
                    current.replace(b'pons',b'unreviewed_pons',1)):
                self.assertTrue(changed!=current,relative+': mutation must alter source')
                with self.assertRaises(AssertionError):operation_cost_predecessor(self,relative,changed)
                with self.assertRaises(AssertionError):
                    if relative=='meme_machine/lanes/pons/evidence.py':
                        assert_holding_delta(self,relative,original,changed)
                    else:opportunity_predecessor(self,relative,changed)

    def test_native_startup_lifecycle_preserves_exact_prior_economics_and_rejects_other_changes(self):
        import hashlib
        for relative,(_,after) in NATIVE_STARTUP_DELTAS.items():
            current=guarded_source(self,relative)
            current=operation_cost_predecessor(self,relative,current)
            self.assertEqual(hashlib.sha256(current).hexdigest(),after)
            prior=subprocess.check_output(['git','show',NATIVE_STARTUP_REFERENCE+':'+relative],cwd=ROOT)
            self.assertEqual(native_startup_predecessor(self,relative,current),prior)
            self.assertEqual(opportunity_predecessor(self,relative,current),
                opportunity_predecessor(self,relative,prior))
            for changed in (current+b'\n# unreviewed lifecycle change\n',b'',
                            current.replace(b'close',b'unreviewed_close',1)):
                with self.assertRaises(AssertionError):native_startup_predecessor(self,relative,changed)
                with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_reviewed_observation_repairs_keep_exact_prior_economics_and_reject_other_changes(self):
        import hashlib
        for relative,(_,after,_) in OBSERVATION_FOLLOWUP_DELTAS.items():
            current=guarded_source(self,relative)
            current=reviewed_native_startup(self,relative,current)
            self.assertEqual(hashlib.sha256(current).hexdigest(),after)
            prior=subprocess.check_output(['git','show',OBSERVATION_FOLLOWUP_REFERENCE+':'+relative],cwd=ROOT)
            self.assertEqual(observation_followup_predecessor(self,relative,current),prior)
            self.assertEqual(opportunity_predecessor(self,relative,current),
                opportunity_predecessor(self,relative,prior))
            for changed in (current+b'\n# unreviewed repair change\n',b''):
                with self.assertRaises(AssertionError):observation_followup_predecessor(self,relative,changed)
                with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_reviewed_startup_cancellation_preserves_all_original_economic_source(self):
        import hashlib
        for relative,(_,after,*_) in STARTUP_CANCEL_DELTAS.items():
            current=guarded_source(self,relative)
            current=observation_followup_predecessor(self,relative,current)
            self.assertEqual(hashlib.sha256(current).hexdigest(),after)
            prior=subprocess.check_output(['git','show',COHORT_AUTHORITY_REFERENCE+':'+relative],cwd=ROOT)
            self.assertEqual(startup_cancel_predecessor(self,relative,current),prior)
            self.assertEqual(opportunity_predecessor(self,relative,current),
                opportunity_predecessor(self,relative,prior))
            for changed in (current+b'\n# unreviewed source change\n',b''):
                with self.assertRaises(AssertionError):startup_cancel_predecessor(self,relative,changed)
                with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_reviewed_cohort_authority_path_preserves_exact_combined_economics(self):
        import hashlib
        for relative,(_,after,_) in COHORT_AUTHORITY_DELTAS.items():
            current=guarded_source(self,relative)
            current=observation_followup_predecessor(self,relative,current)
            self.assertEqual(hashlib.sha256(current).hexdigest(),after)
            prior=subprocess.check_output(['git','show',COHORT_AUTHORITY_REFERENCE+':'+relative],cwd=ROOT)
            self.assertEqual(cohort_authority_predecessor(self,relative,current),prior)
            self.assertEqual(opportunity_predecessor(self,relative,current),
                opportunity_predecessor(self,relative,prior))
            mutations=((current.replace(b'GROUP BY policy_hash',b'GROUP BY candidate'),
                        current.replace(b'self.db.total_changes',b'0'))
                       if relative=='meme_machine/lanes/pons/pipeline.py' else
                       (current.replace(b'final_rows=self.history.rows()',b'final_rows=[]'),
                        current.replace(b'handoff_ready(self.book,final_rows)',b'handoff_ready(self.book,[])'))
                       if relative=='meme_machine/lanes/pons/pons_survivor_runtime.py' else
                       (current.replace(b'pons-selective-cohort-capital.sqlite',b'unreviewed-capital.sqlite'),
                        current.replace(b'capital_path',b'unverified_authority_path')))
            for changed in (current+b'\n# unreviewed source change\n',*mutations):
                self.assertNotEqual(changed,current)
                with self.assertRaises(AssertionError):cohort_authority_predecessor(self,relative,changed)
                with self.assertRaises(AssertionError):opportunity_predecessor(self,relative,changed)

    def test_reviewed_observation_route_forwarding_preserves_exact_combined_source(self):
        import hashlib
        relative=OBSERVATION_ROUTE_SOURCE
        current=guarded_source(self,relative)
        current=operation_cost_predecessor(self,relative,current)
        self.assertEqual(hashlib.sha256(current).hexdigest(),OBSERVATION_ROUTE_AFTER_SHA256,
            'the active source must contain the reviewed forwarding correction')
        prior=subprocess.check_output(['git','show',OBSERVATION_ROUTE_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(observation_route_predecessor(self,relative,current),prior)
        self.assertEqual(opportunity_predecessor(self,relative,current),
            opportunity_predecessor(self,relative,prior))
        for changed in (
                current+b'\n# unreviewed source change\n',
                current.replace(b"('public_existing','canonical_primary')",b"('public_existing','unverified_route')"),
                current.replace(b"if not self.offline:env['MM_PONS_OBSERVATION_ROUTE']",b"if True:env['MM_PONS_OBSERVATION_ROUTE']"),
                current.replace(b"raise ValueError('invalid_pons_observation_route')",b"pass"),
                current.replace(b"env['MM_PAPER_POLICY_REVISION']=ACTIVE_REVISION",b"env['MM_PAPER_POLICY_REVISION']='unreviewed-policy'"),
        ):
            self.assertNotEqual(changed,current)
            with self.assertRaises(AssertionError):
                observation_route_predecessor(self,relative,changed)
            with self.assertRaises(AssertionError):
                opportunity_predecessor(self,relative,changed)

    def test_added_opportunity_policy_and_recovery_sources_reject_unapproved_changes(self):
        for relative in OPPORTUNITY_ADDED_SOURCES:
            source=guarded_source(self,relative)
            assert_opportunity_added_source(self,relative,source)
            with self.assertRaises(AssertionError):
                assert_opportunity_added_source(self,relative,source+b'\n')
            with self.assertRaises(AssertionError):
                assert_opportunity_added_source(self,relative,b'')

    def test_combined_manifest_preserves_exact_published_strategy_and_operational_layers(self):
        from copy import deepcopy
        import hashlib,json
        manifest=json.loads(OPPORTUNITY_MANIFEST.read_text())
        original_bytes=subprocess.check_output(['git','show',
            OPPORTUNITY_REFERENCE+':tests/fixtures/paper_opportunity_access_source_delta.json'],cwd=ROOT)
        self.assertEqual(hashlib.sha256(original_bytes).hexdigest(),OPPORTUNITY_ORIGINAL_MANIFEST_SHA256)
        original=json.loads(original_bytes)
        self.assertEqual(original['base'],OPPORTUNITY_STRATEGY_BASE)
        self.assertEqual(set(manifest['files']),set(original['files']))
        overlaps=set()
        for relative in manifest['files']:
            operational=subprocess.check_output(['git','show',OPPORTUNITY_BASE+':'+relative],cwd=ROOT)
            strategy_before=subprocess.check_output(['git','show',OPPORTUNITY_STRATEGY_BASE+':'+relative],cwd=ROOT)
            strategy_after=subprocess.check_output(['git','show',OPPORTUNITY_REFERENCE+':'+relative],cwd=ROOT)
            combined=startup_cancel_predecessor(self,relative,guarded_source(self,relative))
            combined=cohort_authority_predecessor(self,relative,combined)
            combined=observation_route_predecessor(self,relative,combined)
            if operational==strategy_before:
                self.assertEqual(combined,strategy_after,relative+':unchanged published strategy package')
                continue
            overlaps.add(relative)
            if relative=='meme_machine/lanes/pump/runner.py':
                self.assertEqual(ast.dump(pump_economic_tree(self,combined,combined=True)),
                    ast.dump(ast.parse(strategy_after)),relative+':exact strategy under diagnostic wrappers')
            elif relative=='meme_machine/operational/supervisor.py':
                # The package changed only these three already reviewed methods.
                # Their complete bodies/interfaces must equal the strategy source;
                # replacing them with the operational predecessor must recover the
                # entire operational AST, including shutdown and guard diagnostics.
                current=ast.parse(combined);previous=ast.parse(operational);published=ast.parse(strategy_after)
                for name in ('validate_environment','Supervisor.initialize','Supervisor.environment'):
                    parent=current;before=previous;after=published
                    for part in name.split('.')[:-1]:
                        parent=next(n for n in parent.body if isinstance(n,ast.ClassDef) and n.name==part)
                        before=next(n for n in before.body if isinstance(n,ast.ClassDef) and n.name==part)
                        after=next(n for n in after.body if isinstance(n,ast.ClassDef) and n.name==part)
                    selected=next(n for n in parent.body if isinstance(n,ast.FunctionDef) and n.name==name.split('.')[-1])
                    old=next(n for n in before.body if isinstance(n,ast.FunctionDef) and n.name==name.split('.')[-1])
                    approved=next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name==name.split('.')[-1])
                    self.assertEqual(ast.dump(selected),ast.dump(approved),relative+':'+name+':published strategy')
                    parent.body[parent.body.index(selected)]=deepcopy(old)
                self.assertEqual(ast.dump(current),ast.dump(previous),relative+':all operational siblings preserved')
            else:self.fail(relative+':unreviewed package overlap')
        self.assertEqual(overlaps,{'meme_machine/lanes/pump/runner.py','meme_machine/operational/supervisor.py'})

    def test_opportunity_revision_exact_nodes_and_retained_scalar_protections(self):
        import json
        manifest=json.loads(OPPORTUNITY_MANIFEST.read_text())
        for relative in manifest['files']:
            source=guarded_source(self,relative)
            opportunity_predecessor(self,relative,source)
            with self.assertRaises(AssertionError):
                opportunity_predecessor(self,relative,source+b'\n# unapproved source mutation\n')

    def test_pump_restore_delta_only_pushes_existing_literal_read_filter_into_sql(self):
        import hashlib
        relative='meme_machine/lanes/pump/runner.py'
        prior=subprocess.check_output(['git','show',
            'e398ffef5aa351c727c6619ee057bf9ea527781d:'+relative],cwd=ROOT)
        expected=ast.parse(prior)
        function=next(n for n in expected.body if isinstance(n,ast.FunctionDef)
            and n.name=='_restore_observed_pump_candidates')
        self.assertEqual(hashlib.sha256(ast.dump(function).encode()).hexdigest(),
            '55ae523f5cf1e8b49c5f83a0349680ac1f93b75f3a8dbfd1b2b009f94721896e')
        loop=next(n for n in function.body if isinstance(n,ast.For))
        loop.iter.keywords.append(ast.keyword(arg='event_prefix',value=ast.Constant('pump_')))
        economic=next(n for n in loop.body if isinstance(n,ast.Assign)
            and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='economic')
        self.assertIsInstance(economic.value,ast.ListComp)
        exact_read=economic.value.generators[0].iter
        exact_read.keywords.append(ast.keyword(arg='kind_prefix',value=ast.Constant('pump_')))
        economic.value=exact_read
        # All other functions, interfaces, constants, ordering and restoration
        # predicates must be byte-independent AST equivalents to e398.
        self.assertEqual(ast.dump(expected),ast.dump(pump_economic_tree(self,
            opportunity_predecessor(self,relative,guarded_source(self,relative)))))

    def test_reviewed_pump_startup_diagnostics_preserve_all_original_calls_and_reject_changes(self):
        from copy import deepcopy
        relative='meme_machine/lanes/pump/runner.py'
        content=guarded_source(self,relative)
        original=subprocess.check_output(['git','show',OPPORTUNITY_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(ast.dump(pump_economic_tree(self,content,combined=True)),ast.dump(ast.parse(original)))
        predecessor=opportunity_predecessor(self,relative,content)
        original_operational=subprocess.check_output(['git','show',PUMP_DIAGNOSTIC_REFERENCE+':'+relative],cwd=ROOT)
        self.assertEqual(ast.dump(pump_economic_tree(self,predecessor)),ast.dump(ast.parse(original_operational)))
        for name in PUMP_DIAGNOSTIC_NODES:
            changed=ast.parse(content)
            node=next(n for n in changed.body if isinstance(n,ast.FunctionDef) and n.name==name)
            node.body.append(ast.Expr(ast.Constant('unreviewed change')))
            with self.assertRaises(AssertionError):pump_economic_tree(self,ast.unparse(changed),combined=True)
        # Changing a wrapped acquisition argument or callable is not a permitted
        # instrumentation change, even though the wrapper itself remains intact.
        changed=ast.parse(content)
        call=next(n for n in ast.walk(changed) if isinstance(n,ast.Call) and
            isinstance(n.func,ast.Name) and n.func.id=='_startup_work')
        call.args[1]=ast.Name(id='unreviewed_reconciliation',ctx=ast.Load())
        with self.assertRaises(AssertionError):pump_economic_tree(self,ast.unparse(changed),combined=True)

    def setUp(self):
        self.rpc=ReadRPC()
        clock=patch('meme_machine.runtime.usd_valuation.time.time',side_effect=lambda:self.rpc.now)
        clock.start();self.addCleanup(clock.stop)

    def value(self):return robinhood_usd(self.rpc,now=self.rpc.now)

    def unavailable(self,reason=None):
        with self.assertRaisesRegex(ValuationUnavailable,reason or 'VALUATION_UNAVAILABLE:USDG/USD'):
            self.value()

    def test_block_acquired_after_caller_time_succeeds(self):
        self.rpc.now=NOW+3
        self.rpc.round=[ROUND,100000000,NOW+1,NOW+2,ROUND]
        value=robinhood_usd(self.rpc,now=NOW)
        self.assertEqual(value.observed_at,NOW+2)
        self.assertEqual(value.amount(1000000,NOW+3),Decimal('1'))

    def test_future_block_after_completion_fails(self):
        original=self.rpc.call
        def call(method,params,**kw):
            result=original(method,params,**kw)
            if method=='eth_getBlockByNumber':result['timestamp']=hex(NOW+4)
            return result
        with patch.object(self.rpc,'call',side_effect=call):
            self.unavailable('invalid_block_time')

    def test_provider_delay_does_not_refresh_stale_oracle(self):
        self.rpc.now=UPDATED+USDG_HEARTBEAT+3
        with self.assertRaisesRegex(ValuationUnavailable,'stale_round'):
            robinhood_usd(self.rpc,now=UPDATED+USDG_HEARTBEAT-1)

    def test_route_expiring_during_transport_fails_at_completion(self):
        original=self.rpc.call
        def call(method,params,**kw):
            result=original(method,params,**kw)
            if method=='eth_call' and params[0]['data']==calldata('getSwapOut(uint128,bool)',10**15,1):
                self.rpc.now=NOW+6
            return result
        with patch.object(self.rpc,'call',side_effect=call):
            with self.assertRaises(ValuationUnavailable):NativeValueReader('pons',rpc=self.rpc)(NOW)

    def test_verified_readback_decode_and_decimal_normalization(self):
        value=self.value()
        self.assertEqual(value.usd_per_unit,Decimal('1.00013961'))
        self.assertEqual((value.asset,value.decimals),('USDG',6))
        self.assertEqual(value.amount(125000000,NOW),Decimal('125.01745125'))
        self.assertEqual(value.observed_at,UPDATED)
        self.assertEqual(value.valid_until,UPDATED+86400)
        self.assertEqual(len(value.evidence_hash),64)

    def test_positive_sub_parity_answer_reflects_depeg(self):
        self.rpc.round[1]=80000000
        self.assertEqual(self.value().amount(1000000,NOW),Decimal('.8'))

    def test_heartbeat_boundary_is_inclusive_and_never_extended(self):
        self.rpc.now=UPDATED+USDG_HEARTBEAT
        value=self.value()
        self.assertEqual(value.valid_until,self.rpc.now)
        self.rpc.now+=1
        self.unavailable('stale_round')

    def test_zero_and_negative_answer_rejected(self):
        for answer in (0,-1):
            with self.subTest(answer=answer):
                self.rpc.round[1]=answer;self.unavailable('nonpositive_answer')

    def test_incomplete_future_and_older_answered_rounds_rejected(self):
        for fields in (
            [0,100,UPDATED,UPDATED,ROUND],
            [1,100,UPDATED,UPDATED,1],
            [1<<64,100,UPDATED,UPDATED,1<<64],
            [ROUND,100,0,UPDATED,ROUND],
            [ROUND,100,UPDATED,0,ROUND],
            [ROUND,100,UPDATED+1,UPDATED,ROUND],
            [ROUND,100,NOW+1,NOW+1,ROUND],
            [ROUND,100,UPDATED,UPDATED,ROUND-1],
            [ROUND,100,UPDATED,UPDATED,(2<<64)+121],
            [1<<80,100,UPDATED,UPDATED,1<<80],
        ):
            with self.subTest(fields=fields):
                self.rpc.round=fields;self.unavailable()

    def test_malformed_round_length_and_hex_rejected(self):
        original=self.rpc.call
        for raw in ('0x','0xgg',abi(ROUND,1),abi(*self.rpc.round)+'00'):
            with self.subTest(raw=raw):
                def call(method,params,**kw):
                    if method=='eth_call' and params[0]['data']==calldata('latestRoundData()'):return raw
                    return original(method,params,**kw)
                with patch.object(self.rpc,'call',side_effect=call):self.unavailable()

    def test_wrong_feed_description_rejected(self):
        for description in ('USDC / USD','USDG/USD','USDG / EUR'):
            with self.subTest(description=description):
                self.rpc.description=description;self.unavailable('wrong_feed_description')

    def test_wrong_feed_decimals_or_invalid_padding_rejected(self):
        for decimals in (0,6,18,256):
            with self.subTest(decimals=decimals):
                self.rpc.feed_decimals=decimals;self.unavailable()

    def test_missing_contract_code_rejected(self):
        for code in ('0x','0x00','0xxyz'):
            with self.subTest(code=code):self.rpc.feed_code=code;self.unavailable()

    def test_wrong_chain_rejected(self):
        self.rpc.chain=1;self.unavailable('wrong_chain')

    def test_exact_proxy_and_token_addresses_and_read_only_methods(self):
        self.value()
        calls=[params[0]['to'] for method,params,_ in self.rpc.calls if method=='eth_call']
        self.assertTrue(all(address in (USDG_FEED,USDG_ASSET) for address in calls))
        self.assertEqual(USDG_FEED,'0x61B7e5650328764B076A108EFF5fa7282a1B9aD2')
        self.assertLessEqual(set(method for method,_,_ in self.rpc.calls),
            {'eth_chainId','eth_getCode','eth_call','eth_getBlockByNumber'})

    def test_unavailable_rpc_has_no_price_fallback_or_credential_leak(self):
        self.rpc.failed=True
        with self.assertRaises(ValuationUnavailable) as caught:self.value()
        self.assertNotIn('private-provider-secret',str(caught.exception))
        self.assertIn('RPC_unavailable_or_invalid',str(caught.exception))

    def test_missing_config_fails_without_market_io(self):
        with patch.dict('os.environ',{},clear=True),patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            with self.assertRaises(ValuationUnavailable):robinhood_usd(now=NOW)

    def test_cache_reuses_only_within_sixty_seconds(self):
        reader=NativeValueReader('ramses',rpc=self.rpc)
        first=reader(NOW);count=len(self.rpc.calls)
        self.assertIs(reader(NOW+60),first)
        self.assertEqual(len(self.rpc.calls),count)
        self.rpc.now=NOW+61;self.rpc.round[1]=90000000
        self.assertEqual(reader(NOW+61).usd_per_unit,Decimal('.9'))
        self.assertGreater(len(self.rpc.calls),count)

    def test_expired_cache_does_not_fallback_during_outage(self):
        reader=NativeValueReader('ramses',rpc=self.rpc)
        value=reader(NOW);self.rpc.failed=True
        self.assertIs(reader(NOW+59),value)
        with self.assertRaises(ValuationUnavailable):reader(NOW+61)
        from meme_machine.runtime.status import snapshot
        self.assertEqual(snapshot()['phase'],'VALUATION_UNAVAILABLE')

    def test_cache_never_extends_oracle_heartbeat(self):
        self.rpc.now=UPDATED+USDG_HEARTBEAT-1
        reader=NativeValueReader('ramses',rpc=self.rpc)
        reader(self.rpc.now)
        self.rpc.now+=2
        with self.assertRaisesRegex(ValuationUnavailable,'stale_round'):reader(self.rpc.now)

    def test_ramses_usdg_to_usd_and_exact_quote_identity(self):
        book=SimpleNamespace(quote_asset=USDG_ASSET.upper())
        value=NativeValueReader('ramses',book,rpc=self.rpc)(NOW)
        self.assertEqual(value.amount(1000000,NOW),Decimal('1.00013961'))
        book.quote_asset=WNATIVE
        with self.assertRaisesRegex(ValuationUnavailable,'wrong_Ramses_quote_asset'):
            NativeValueReader('ramses',book,rpc=self.rpc)(NOW)

    def test_usdg_token_decimals_must_match_accounting_units(self):
        self.rpc.token_decimals=18;self.unavailable('wrong_USDG_token_decimals')

    def test_wrong_proxy_interface_and_address_padding_rejected(self):
        original=self.rpc.call
        for name,raw in (('aggregator()',abi(0)),('aggregator()',abi(1<<160)),('version()',abi(5))):
            with self.subTest(name=name,raw=raw):
                def call(method,params,**kw):
                    if method=='eth_call' and params[0]['data']==calldata(name):return raw
                    return original(method,params,**kw)
                with patch.object(self.rpc,'call',side_effect=call):self.unavailable()

    def test_round_must_exist_at_pinned_block(self):
        original=self.rpc.call
        def call(method,params,**kw):
            result=original(method,params,**kw)
            if method=='eth_getBlockByNumber':result['timestamp']=hex(UPDATED-1)
            return result
        with patch.object(self.rpc,'call',side_effect=call):self.unavailable('round_after_pinned_block')

    def test_pons_native_to_authenticated_executable_usdg_to_usd(self):
        value=NativeValueReader('pons',rpc=self.rpc)(NOW)
        self.assertEqual((value.asset,value.decimals),('ETH',18))
        self.assertEqual(value.usd_per_unit,Decimal('2500.349025'))
        self.assertEqual(value.amount(10**15,NOW),Decimal('2.500349025'))
        self.assertEqual(value.valid_until,NOW+5)
        self.assertLessEqual(len(value.evidence_id),150)
        # $125 family equity is translated by this live composed rate.
        capital=int(Decimal('125')*Decimal(10**18)/value.usd_per_unit)
        self.assertLessEqual(value.amount(capital,NOW),Decimal('125'))
        self.assertLess(Decimal('125')-value.amount(capital,NOW),value.amount(1,NOW))

    def test_pons_execution_capacity_and_route_identity_fail_closed(self):
        for field,value in (('no_pairs',True),('unfilled',1),('route_output',0),
                ('hooks',1),('bad_factory',True),('bad_pool',True)):
            with self.subTest(field=field):
                rpc=ReadRPC();setattr(rpc,field,value)
                with self.assertRaises(ValuationUnavailable):NativeValueReader('pons',rpc=rpc)(NOW)

    def test_pons_quote_cache_expires_without_extending_five_second_window(self):
        reader=NativeValueReader('pons',rpc=self.rpc)
        first=reader(NOW);count=len(self.rpc.calls)
        self.assertIs(reader(NOW+5),first)
        self.assertEqual(len(self.rpc.calls),count)
        self.rpc.now+=6;self.rpc.route_output=2000000
        self.assertEqual(reader(self.rpc.now).usd_per_unit,Decimal('2000.27922'))
        self.assertGreater(len(self.rpc.calls),count)
        # A fresh production RPC session must verify chain even with a cached oracle.
        self.assertGreaterEqual(sum(1 for method,_,_ in self.rpc.calls if method=='eth_chainId'),2)

    def test_pons_concurrent_use_refreshes_before_original_cache_expiration(self):
        reader=NativeValueReader('pons',rpc=self.rpc)
        first=reader(NOW);count=len(self.rpc.calls)
        self.rpc.now=NOW+4
        refreshed=reader(NOW+4,valid_through=NOW+7)
        self.assertIsNot(refreshed,first)
        self.assertGreater(len(self.rpc.calls),count)
        self.assertEqual(first.valid_until,NOW+5)
        self.assertEqual(refreshed.valid_until,NOW+9)
        self.assertEqual(refreshed.amount(10**15,NOW+7),Decimal('2.500349025'))
        with self.assertRaises(ValuationUnavailable):first.amount(1,NOW+7)

    def test_pons_concurrent_use_reuses_compatible_cache_without_provider_work(self):
        reader=NativeValueReader('pons',rpc=self.rpc)
        first=reader(NOW);count=len(self.rpc.calls)
        self.rpc.now=NOW+2
        self.assertIs(reader(NOW+2,valid_through=NOW+5),first)
        self.assertEqual(len(self.rpc.calls),count)

    def test_pons_consumption_deadline_cannot_extend_quote_or_hide_outage(self):
        reader=NativeValueReader('pons',rpc=self.rpc)
        first=reader(NOW);self.rpc.now=NOW+4;self.rpc.failed=True
        with self.assertRaises(ValuationUnavailable):reader(NOW+4,valid_through=NOW+7)
        self.assertEqual(first.valid_until,NOW+5)
        self.rpc.failed=False
        with self.assertRaises(ValuationUnavailable):reader(NOW+4,valid_through=NOW+20)
        self.assertLessEqual(reader.cached.valid_until,NOW+9)

    def test_invalid_consumption_deadline_fails_before_provider_acquisition(self):
        reader=NativeValueReader('pons',rpc=self.rpc)
        for deadline in (True,NOW-1,Decimal(NOW+3),'later'):
            with self.subTest(deadline=deadline):
                with self.assertRaises(ValuationUnavailable):reader(NOW,valid_through=deadline)
        self.assertEqual(self.rpc.calls,[])

    def test_pons_cached_oracle_refresh_verifies_new_provider_session(self):
        reader=NativeValueReader('pons',rpc=self.rpc)
        reader(NOW)
        fresh=ReadRPC();fresh.now=NOW+6
        reader.rpc=fresh
        self.assertEqual(reader(NOW+6).usd_per_unit,Decimal('2500.349025'))
        self.assertTrue(fresh.chain_verified)
        self.assertNotIn(calldata('latestRoundData()'),
            [params[0]['data'] for method,params,_ in fresh.calls if method=='eth_call'])

    def test_pons_oracle_and_conversion_reuse_one_pinned_block(self):
        NativeValueReader('pons',rpc=self.rpc)(NOW)
        self.assertEqual(sum(method=='eth_getBlockByNumber' and params[0]=='latest'
            for method,params,_ in self.rpc.calls),1)
        self.assertEqual(self.rpc.calls[-1][:2],('eth_getBlockByNumber',['0x4bdc170',False]))
        blocks=[params[1] for method,params,_ in self.rpc.calls if method in ('eth_call','eth_getCode')]
        self.assertEqual(set(blocks),{'0x4bdc170'})

    def test_pons_currency_fence_runs_after_route_state_and_refuses_reorganization(self):
        original=self.rpc.call;fork=[False];reader=NativeValueReader('pons',rpc=self.rpc)
        def call(method,params,**kw):
            result=original(method,params,**kw)
            if method=='eth_call' and params[0]['data']==calldata('getSwapOut(uint128,bool)',10**15,1):
                fork[0]=True
            if method=='eth_getBlockByNumber' and params[0]!='latest' and fork[0]:
                result['hash']='0x'+'34'*32
            return result
        with patch.object(self.rpc,'call',side_effect=call):
            with self.assertRaisesRegex(ValuationUnavailable,'canonical_block_changed'):reader(NOW)
        self.assertIsNone(reader.cached);self.assertIsNone(reader.oracle)
        self.assertIsNone(reader.oracle_block);self.assertFalse(reader.route_state)
        self.assertEqual(self.rpc.calls[-1][0],'eth_getBlockByNumber')
        # Refusal never permanently rejects a future canonical observation.
        self.assertEqual(reader(NOW).usd_per_unit,Decimal('2500.349025'))

    def test_pons_currency_fence_compares_numeric_identity_without_encoding_veto(self):
        original=self.rpc.call
        def call(method,params,**kw):
            result=original(method,params,**kw)
            if method=='eth_getBlockByNumber' and params[0]!='latest':result['number']='0x4BDC170'
            return result
        with patch.object(self.rpc,'call',side_effect=call):
            self.assertEqual(NativeValueReader('pons',rpc=self.rpc)(NOW).usd_per_unit,Decimal('2500.349025'))

    def test_concurrent_pons_currency_consumers_share_one_complete_acquisition(self):
        reader=NativeValueReader('pons',rpc=self.rpc)
        entered=threading.Event();release=threading.Event();values=[];errors=[]
        original=self.rpc.call
        def call(method,params,**kw):
            if method=='eth_getBlockByNumber' and params[0]=='latest':
                entered.set()
                if not release.wait(2):raise AssertionError('fixture_release_missing')
            return original(method,params,**kw)
        def consume():
            try:values.append(reader(NOW))
            except Exception as error:errors.append(error)
        with patch.object(self.rpc,'call',side_effect=call):
            threads=[threading.Thread(target=consume) for _ in range(8)]
            try:
                for thread in threads:thread.start()
                self.assertTrue(entered.wait(2))
            finally:
                release.set()
                for thread in threads:thread.join(3)
        self.assertFalse(errors);self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(len(values),8);self.assertTrue(all(v is values[0] for v in values))
        self.assertEqual(sum(m=='eth_getBlockByNumber' and p[0]=='latest' for m,p,_ in self.rpc.calls),1)
        self.assertEqual(sum(m=='eth_chainId' for m,_,_ in self.rpc.calls),1)
        self.assertEqual(len(self.rpc.calls),19)
        self.assertEqual(values[0].amount(10**15,NOW),Decimal('2.500349025'))
        self.assertEqual(values[1].amount(3*10**15,NOW),Decimal('7.501047075'))

    def test_local_currency_wait_cannot_renew_or_return_expired_evidence(self):
        reader=NativeValueReader('pons',rpc=self.rpc);first=reader(NOW)
        started=threading.Event();values=[]
        def consume():started.set();values.append(reader(NOW))
        with reader._lock:
            thread=threading.Thread(target=consume);thread.start()
            self.assertTrue(started.wait(2))
            self.rpc.now=NOW+6;self.rpc.route_output=2000000
        thread.join(3);self.assertFalse(thread.is_alive())
        self.assertIsNot(values[0],first)
        self.assertEqual(values[0].observed_at,NOW+6);self.assertEqual(values[0].valid_until,NOW+11)
        self.assertEqual(values[0].usd_per_unit,Decimal('2000.27922'))

    def test_pons_cached_oracle_block_remains_an_independent_canonical_obligation(self):
        reader=NativeValueReader('pons',rpc=self.rpc);reader(NOW)
        original=self.rpc.call;self.rpc.now=NOW+6
        def call(method,params,**kw):
            result=original(method,params,**kw)
            if method=='eth_getBlockByNumber':
                result.update(number='0x4bdc171',hash='0x'+'34'*32)
                if params[0]=='0x4bdc170':result.update(number=params[0],hash='0x'+'56'*32)
            return result
        with patch.object(self.rpc,'call',side_effect=call):
            with self.assertRaisesRegex(ValuationUnavailable,'canonical_block_changed'):reader(NOW+6)
            self.assertIsNone(reader.oracle)
            # Fresh oracle and route on the new canonical block restore safely.
            value=reader(NOW+6)
            self.assertEqual(value.valid_until,NOW+11)
            self.assertEqual(reader.oracle_block[0],int('4bdc171',16))

    def test_pons_currency_fence_partial_response_and_delay_cannot_publish_or_refresh(self):
        original=self.rpc.batch
        def partial(calls,**kw):
            result=original(calls,**kw)
            return [] if calls[0][0]=='eth_getBlockByNumber' else result
        reader=NativeValueReader('pons',rpc=self.rpc)
        with patch.object(self.rpc,'batch',side_effect=partial):
            with self.assertRaisesRegex(ValuationUnavailable,'canonical_block_proof_incomplete'):reader(NOW)
        self.assertIsNone(reader.cached)
        def delayed(calls,**kw):
            result=original(calls,**kw)
            if calls[0][0]=='eth_getBlockByNumber':self.rpc.now=NOW+6
            return result
        with patch.object(self.rpc,'batch',side_effect=delayed):
            with self.assertRaises(ValuationUnavailable):reader(NOW)
        self.assertIsNone(reader.cached)

    def test_pons_feed_depeg_is_composed_without_fixed_dollar_fallback(self):
        self.rpc.round[1]=80000000
        self.assertEqual(NativeValueReader('pons',rpc=self.rpc)(NOW).usd_per_unit,Decimal('2000'))

    def test_pons_transport_delay_cannot_extend_execution_freshness(self):
        with patch('meme_machine.runtime.usd_valuation.time.monotonic',side_effect=[0,6]):
            with self.assertRaises(ValuationUnavailable):NativeValueReader('pons',rpc=self.rpc)(NOW)

    def test_outage_preserves_shared_capital_and_existing_positions(self):
        from meme_machine.portfolio_accounting import PortfolioAccounting,inception_receipt,LANES
        from meme_machine.runtime.native_boundary import NativeBoundary
        from meme_machine.runtime.usd_valuation import utc
        from meme_machine.runtime.journal import digest
        ids=dict(source_sha='a'*40,policy_hash='b'*64,config_hash='c'*64)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'offline-fixture.sqlite'
            with closing(PortfolioAccounting(path)) as account:
                account.establish_inception(inception_receipt('offline-usdg-fixture',utc(NOW),'offline-inception'),
                    portfolio_identities=ids,lane_identities={lane:ids for lane in LANES})
                account.configure_family_sleeves()
            reader=NativeValueReader('ramses',rpc=self.rpc)
            boundary=NativeBoundary(path,'ramses',SimpleNamespace(),value_reader=reader)
            value=reader(NOW)
            for key,kind,data in (
                ('reserve','reserve',{'amount':'6.25'}),
                ('enter','enter',{'asset':POOL,'basis':'6.25','fee':'0','strategy_id':'ramses'}),
            ):
                boundary.client.deliver('existing',event_key=key,journal_hash=digest([key,data]),kind=kind,
                    at=utc(NOW),data=data,value_evidence=value.evidence(NOW) if kind=='enter' else None)
            with closing(PortfolioAccounting(path)) as account:before=account.snapshot()
            self.rpc.failed=True
            for native,action in (('new','reserved'),('existing','settled')):
                with self.assertRaises(ValuationUnavailable):
                    boundary.record(native,action,{'reserved':1000000},None,at=NOW+61,checksum='b'*64)
            with closing(PortfolioAccounting(path)) as account:self.assertEqual(account.snapshot(),before)
            self.assertFalse(boundary.prepared)
            self.assertFalse(boundary.client.pending())

    def test_unavailable_robinhood_does_not_affect_solana_reader_or_decoder(self):
        from meme_machine.runtime.usd_valuation import USDValue
        for lane in ('pump','meteora'):
            reader=NativeValueReader(lane)
            reader.cached=USDValue('SOL',9,Decimal('100'),NOW,NOW+120,'offline-sol','a'*64)
            with patch('meme_machine.runtime.usd_valuation.robinhood_usd',side_effect=ValuationUnavailable('offline outage')):
                self.assertEqual(reader(NOW).amount(10**9,NOW),Decimal('100'))
        old=baseline('meme_machine/runtime/usd_valuation.py').decode()
        current=(ROOT/'meme_machine/runtime/usd_valuation.py').read_text()
        def decoder(source):
            node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='sol_usd')
            # The unchanged decoder now runs under the canonical exact-money
            # context. Compare the oracle parsing/finality/conversion body.
            node.decorator_list=[]
            return ast.dump(node)
        self.assertEqual(decoder(old),decoder(current))

    def test_strategy_sources_and_nine_change_tests_byte_unchanged(self):
        # USD valuation originally had no authority to alter trading source.
        # Keep that economic guard and the original nine changes. The owner's
        # PR #129 finalization names e1070404 as the implementation predecessor;
        # later reviewed transport/storage repairs are no longer USD changes.
        assert_holding_delta(self,'tests/test_operational_nine.py',
            baseline('tests/test_operational_nine.py'),(ROOT/'tests/test_operational_nine.py').read_bytes())
        economic_reference='b1f215edd3dc079b623401c7e09e9c91a380e6a0'
        for rel in ('meme_machine/lanes/pump/pump_acceleration_strategy.py',
                    'meme_machine/lanes/pump/pumpswap_survivor.py',
                    'meme_machine/lanes/pons/pons_selective_continuation.py',
                    'meme_machine/runtime/directional_continuation.py',
                    'meme_machine/runtime/survivor_risk.py',
                    'operational/nine-change-implementation.json'):
            original=subprocess.check_output(['git','show',economic_reference+':'+rel],cwd=ROOT)
            assert_holding_delta(self,rel,original,guarded_source(self,rel))
        rel='meme_machine/lanes/pons/pons_postgrad_survivor.py'
        original=subprocess.check_output(['git','show',economic_reference+':'+rel],cwd=ROOT)
        def survivor_economics(content):
            # Explicit owner exception: remove the two-position selection veto.
            # Policy identity and every qualification still pin; the owner's
            # holding-age exit removal is separately pinned below.
            return [ast.dump(n) for n in ast.parse(content).body
                if not isinstance(n,ast.FunctionDef) or n.name not in ('select_entries','exit_action')]
        self.assertEqual(survivor_economics(original),survivor_economics(opportunity_predecessor(self,rel,guarded_source(self,rel))))
        approved=ast.parse(guarded_source(self,rel))
        node=next(n for n in approved.body if isinstance(n,ast.FunctionDef) and n.name=='exit_action')
        self.assertEqual(__import__('hashlib').sha256(ast.dump(node).encode()).hexdigest(),HOLDING_DELTAS[rel]['exit_action'])
        active='e1070404849dfa86eb3e47d57cf24263b2fefc25'
        def source(path):
            return subprocess.check_output(['git','show',active+':'+path],cwd=ROOT)
        paths=subprocess.check_output(['git','ls-tree','-r','--name-only',active,'meme_machine/lanes'],cwd=ROOT,text=True).splitlines()
        infrastructure={'meme_machine/lanes/pons/pons_historical.py',
                        'meme_machine/lanes/pons/pons_history.py',
                        'meme_machine/lanes/pons/pons_survivor_runtime.py',
                        'meme_machine/lanes/pons/pons_natural_observation.py',
                        'meme_machine/lanes/pons/pons_selective_cohort.py',
                        'meme_machine/lanes/pons/pons_selective_v4.py',
                        'meme_machine/lanes/pons/pons_quotes.py',
                        'meme_machine/lanes/pons/pons_selective_paper.py',
                        'meme_machine/lanes/pons/pons_current_workers.py',
                        'meme_machine/lanes/pons/pons_selective_acquisition.py',
                        'meme_machine/lanes/pons/provider_topology.py',
                        'meme_machine/lanes/pons/provider_admission.py',
                        'meme_machine/lanes/pons/provider.py',
                        'meme_machine/lanes/pons/sequencer_feed.py',
                        'meme_machine/lanes/pons/abi.py'}
        for rel in paths:
            if rel not in infrastructure:assert_holding_delta(self,rel,source(rel),guarded_source(self,rel))
        for rel in ('meme_machine/runtime/directional_continuation.py','meme_machine/runtime/survivor_risk.py',
                    'operational/nine-change-implementation.json'):
            assert_holding_delta(self,rel,source(rel),guarded_source(self,rel))
        rel='meme_machine/lanes/pons/pons_history.py'
        # The only history reducer change is transport work order near the
        # original expiry. All native append, recovery and retention math pins.
        def history_methods(content,*,reviewed=False):
            cls=next(n for n in ast.parse(content).body if isinstance(n,ast.ClassDef))
            if reviewed:
                for name in ('__init__','_quality_rank','qualification_turn'):
                    node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
                    assert_attention_node(self,rel,'PonsHistory.'+name,node)
            # The reviewed attention additions do not alter any history reducer.
            next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__').body=[ast.Pass()]
            return {n.name:ast.dump(n) for n in cls.body if isinstance(n,ast.FunctionDef)
                    and n.name not in ('qualification_turn','_quality_rank')}
        self.assertEqual(history_methods(guarded_source(self,rel),reviewed=True),history_methods(source(rel)))
        rel='meme_machine/lanes/pons/pons_survivor_runtime.py'
        original=ast.parse(source(rel));current=ast.parse(opportunity_predecessor(self,rel,guarded_source(self,rel)))
        def functions(tree):
            return {n.name:n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        old=functions(original);new=functions(current)
        for name,node in old.items():
            if name=='Quotes':
                old_quotes=functions(node);new_quotes=functions(new[name])
                for method,value in old_quotes.items():
                    value.decorator_list=[];new_quotes[method].decorator_list=[]
                    self.assertEqual(ast.dump(value),ast.dump(new_quotes[method]),rel+':Quotes.'+method)
            elif name!='Runtime':self.assertEqual(ast.dump(node),ast.dump(new[name]),rel+':'+name)
        old_methods=functions(old['Runtime']);new_methods=functions(new['Runtime'])
        mechanical={'__init__','historical_preparation_step','_provider','discover','_bootstrap_cursor',
                    '_increment_candidates','reconstruct','step','_prepare_held_acquisition','_manage_position',
                    '_position','exit_quote','validate_exit'}
        for name,node in old_methods.items():
            if 'Runtime.'+name in ATTENTION_DELTAS[rel]:
                assert_attention_node(self,rel,'Runtime.'+name,new_methods[name])
                if name!='reconstruct':continue
            if name not in mechanical:
                node.decorator_list=[];new_methods[name].decorator_list=[]
                self.assertEqual(ast.dump(node),ast.dump(new_methods[name]),rel+':'+name)
        # Quote timing and individual completeness authority change. The actual
        # price/buyer reducers, sizing and executable-capacity expression pin.
        before=old_methods['reconstruct'];after=new_methods['reconstruct']
        def facts_keywords(node):
            call=next(n.value for n in ast.walk(node) if isinstance(n,ast.Assign)
                and any(isinstance(t,ast.Attribute) and t.attr=='facts' for t in n.targets))
            return {k.arg:ast.dump(k.value) for k in call.keywords
                    if k.arg not in ('continuity_complete','execution')}
        self.assertEqual(facts_keywords(before),facts_keywords(after))
        def economic_expressions(node):
            assigns={t.id:ast.dump(n.value) for n in ast.walk(node) if isinstance(n,ast.Assign)
                for t in n.targets if isinstance(t,ast.Name) and t.id in ('flow','sizing','cap','capacity')}
            assigns['window']=ast.dump(next(n for n in ast.walk(node) if isinstance(n,ast.FunctionDef) and n.name=='window'))
            return assigns
        self.assertEqual(economic_expressions(before),economic_expressions(after))
        # This release changes acquisition order/reuse, not native settlement
        # arithmetic or its exact-quantity/five-second commit prerequisites.
        def net_expressions(node):
            return {ast.dump(k.value) for n in ast.walk(node) if isinstance(n,ast.Call)
                for k in n.keywords if k.arg in ('net_proceeds','gas')}
        self.assertEqual(net_expressions(old_methods['exit_quote']),net_expressions(new_methods['exit_quote']))
        def stale_expression(node):
            return ast.dump(next(n.test for n in ast.walk(node) if isinstance(n,ast.If)
                and any(isinstance(a,ast.Constant) and a.value=='survivor_exit_quote_stale'
                    for a in ast.walk(n))))
        self.assertEqual(stale_expression(old_methods['validate_exit']),stale_expression(new_methods['validate_exit']))
        def constants(tree):
            return [ast.dump(n) for n in tree.body if isinstance(n,(ast.Assign,ast.AnnAssign))]
        self.assertEqual(constants(original),constants(current))

    def test_reviewed_attention_nodes_reject_unapproved_edits(self):
        from copy import deepcopy
        reviewed={relative:{**ATTENTION_DELTAS.get(relative,{}),**OPERATION_DELTAS.get(relative,{})}
                  for relative in ATTENTION_DELTAS.keys()|OPERATION_DELTAS.keys()}
        for relative,methods in reviewed.items():
            tree=ast.parse(guarded_source(self,relative))
            for name in methods:
                node=tree
                for part in name.split('.'):
                    node=next(n for n in node.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==part)
                assert_attention_node(self,relative,name,node)
                changed=deepcopy(node);changed.body.append(ast.Expr(ast.Constant('unapproved change')))
                with self.assertRaises(AssertionError):assert_attention_node(self,relative,name,changed)

    def test_reviewed_acquisition_source_rejects_any_unapproved_change(self):
        for relative,reviewed in ACQUISITION_SOURCE_DELTAS.items():
            original=subprocess.check_output(['git','show','e1070404849dfa86eb3e47d57cf24263b2fefc25:'+relative],cwd=ROOT)
            approved=subprocess.check_output(['git','show',reviewed['reference']+':'+relative],cwd=ROOT)
            delta=b"and row.get('app_id') and row.get('team_id')"
            self.assertEqual(approved.count(delta),1)
            approved=approved.replace(delta,b"and row.get('app_id')")
            self.assertEqual(approved,guarded_source(self,relative))
            assert_holding_delta(self,relative,original,approved)
            for changed in (approved+b'\n# unreviewed change\n',
                    approved.replace(b'SAFE_BLOCKS = 10',b'SAFE_BLOCKS = 40'),
                    approved.replace(b"and row.get('equal') is True",b"and True")):
                self.assertNotEqual(changed,approved)
                with self.assertRaises(AssertionError):assert_holding_delta(self,relative,original,changed)
            with self.assertRaises(AssertionError):assert_holding_delta(self,relative,original+b'\n',approved)

    def test_reviewed_lifecycle_sources_reject_unapproved_changes_and_preserve_economics(self):
        for relative in LIFECYCLE_SOURCE_DELTAS:
            original=subprocess.check_output(['git','show','e1070404849dfa86eb3e47d57cf24263b2fefc25:'+relative],cwd=ROOT)
            published=subprocess.check_output(['git','show',LIFECYCLE_PACKAGE_REFERENCE+':'+relative],cwd=ROOT)
            self.assertEqual(published,opportunity_predecessor(self,relative,guarded_source(self,relative)))
            assert_holding_delta(self,relative,original,guarded_source(self,relative))
            for changed in (published+b'\n# unreviewed change\n',published.replace(b'False',b'True',1)):
                self.assertNotEqual(changed,published)
                with self.assertRaises(AssertionError):assert_holding_delta(self,relative,original,changed)
        relative='meme_machine/lanes/pons/pons_selective_continuation.py'
        def economic_nodes(content):
            nodes={}
            for node in ast.parse(content).body:
                if isinstance(node,ast.FunctionDef) and node.name=='reentry_regime_reset':
                    nodes[node.name]=ast.dump(node)
                elif isinstance(node,ast.Assign):
                    for target in node.targets:
                        if isinstance(target,ast.Name) and target.id in ('REENTRY_POLICY','ENTRY_THRESHOLDS','EXIT_POLICY','POLICY'):
                            nodes[target.id]=ast.dump(node)
            return nodes
        prior=subprocess.check_output(['git','show',LIFECYCLE_PACKAGE_BASE+':'+relative],cwd=ROOT)
        before=economic_nodes(prior);after=economic_nodes(opportunity_predecessor(self,relative,guarded_source(self,relative)))
        self.assertEqual(set(before),{'reentry_regime_reset','REENTRY_POLICY','ENTRY_THRESHOLDS','EXIT_POLICY','POLICY'})
        self.assertEqual(before,after)

    def test_resolved_startup_check_uses_config_only_no_oracle_calls_or_state(self):
        from meme_machine.operational.supervisor import validate_environment
        env={'MM_ROBINHOOD_READ_RPC_URL':'https://robinhood-mainnet.g.alchemy.com/v2/offline-fixture'}
        with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            self.assertIsNone(validate_environment(environ=env))


if __name__=='__main__':unittest.main()
