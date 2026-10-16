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
# deltas must reverse to main 893b8dd2 before every original guard runs.
RALLY_BASE='893b8dd281f4282aed82573db8334c25605755c9'
RALLY_MANIFEST=ROOT/'tests/fixtures/paper_postgrad_rally_source_delta.json'
RALLY_SCHEMA='owner-selected-paper-postgrad-rally-source-delta-v1'
RALLY_MANIFEST_SHA256='8855115730a56b6d8f2d3e055d32002fdaa75499aec2414b26efd9cc4b946918'
RALLY_CHANGED_SOURCES=('meme_machine/lanes/pons/pons_postgrad_survivor.py', 'meme_machine/lanes/pons/pons_survivor_runtime.py', 'meme_machine/lanes/pump/pump_acceleration_strategy.py', 'meme_machine/lanes/pump/pumpswap_survivor.py', 'meme_machine/lanes/pump/pumpswap_survivor_runtime.py', 'meme_machine/lanes/pump/runner.py', 'meme_machine/operational/supervisor.py', 'meme_machine/paper_policy_revision.py', 'meme_machine/runtime/directional_continuation.py', 'meme_machine/runtime/native_boundary.py', 'meme_machine/runtime/opportunity_telemetry.py', 'meme_machine/runtime/policy_compatibility.py', 'meme_machine/runtime/robinhood/pons.py', 'meme_machine/runtime/sleeve_reservations.py', 'meme_machine/runtime/survivor_commit.py', 'meme_machine/runtime/survivor_history.py', 'meme_machine/runtime/survivor_paper_book.py', 'meme_machine/runtime/survivor_risk.py', 'meme_machine/runtime/survivor_terminal_archive.py', 'meme_machine/shared_capital/native_sleeve.py', 'meme_machine/shared_capital/runtime.py')
RALLY_ADDED_SOURCES=('meme_machine/policy_history/opportunity_access_v1.json', 'meme_machine/runtime/rally_cycle.py')


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


def rally_predecessor(test,relative,current,*,allow_previous_layers=False):
    import hashlib,json
    if isinstance(current,str):current=current.encode()
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
    return rally_predecessor(test,relative,(ROOT/relative).read_bytes())


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


# Explicit host-capacity portability changes only the existing cgroup check.
# Pin both full files and reverse the one reviewed method/import before every
# existing economic/source comparison. No other Supervisor node is exempted.
CPU_CAPACITY_REFERENCE='9bc778ff9237c0769aa6a6d2799bf513d677e333'
CPU_CAPACITY_BEFORE='b2ffa2991607fef15fc1934682018d101a74ba21763702ca5d3757456a132982'
CPU_CAPACITY_AFTER='20fda2428bca7758f2ee4987903c4b346d9b98833472d4d734702cdc8107d646'


def cpu_capacity_predecessor(test,relative,current):
    import hashlib
    if isinstance(current,str):current=current.encode()
    if relative!='meme_machine/operational/supervisor.py':return current
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
    def test_rally_source_layer_reverses_exactly_and_rejects_unreviewed_bytes(self):
        import json
        manifest=rally_manifest(self)
        self.assertTrue(manifest['files'])
        for relative,record in manifest['files'].items():
            source=(ROOT/relative).read_bytes()
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
