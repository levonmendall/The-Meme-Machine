"""One frozen, asset-separated paper budget for a continuous Ramses campaign.

Budgets are declared once from the first genuine qualifier's pinned factory screen,
before outcome. Later candidates cannot mint capital or exchange unlike quote units.
"""
from contextlib import closing
import gzip
import fcntl
import sqlite3
import hashlib
import json
import os
from pathlib import Path
import uuid
from . import BoundaryError
from .ramses_strategy import POLICY,POLICY_HASH,STRATEGY_DOMAIN
from .ramses_strategy_ledger import RamsesStrategyLedger


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'))
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


class CampaignBooks:
    @staticmethod
    def budgets_from_screen(screen):
        if screen.get('policy_hash')!=POLICY_HASH or screen.get('strategy_domain')!=STRATEGY_DOMAIN:
            raise BoundaryError('ramses_campaign_foreign_screen')
        if screen.get('finalized_frontier_source')!='pinned_external_finalized_header':
            raise BoundaryError('ramses_campaign_unpinned_initial_screen')
        budgets={}
        for row in screen.get('rows',[]):
            asset=row.get('token_y');amount=row.get('paper_capital_quote_raw')
            if not isinstance(asset,str) or not asset.startswith('0x') or len(asset)!=42:continue
            if type(amount) is not int or amount<=0:continue
            decision=row.get('decision') or {};freeze=decision.get('freeze') or {}
            proposals=freeze.get('proposals') or []
            employed=(proposals[0].get('capital_employed') if proposals else None)
            position=employed if type(employed) is int and employed>0 else amount
            costs=row.get('gas_costs')
            if isinstance(costs,dict) and costs and all(type(v) is int and v>=0 for v in costs.values()):
                cost_envelope=sum(costs.values())*(1+int(POLICY['controller']['max_rebalances']))
                funding=max(amount,position+cost_envelope)
            else:funding=amount
            asset=asset.lower();budgets[asset]=max(budgets.get(asset,0),funding)
        return budgets

    @staticmethod
    def pending_path(root):
        root=Path(root)
        return root.with_name(root.name+'.funding-pending')

    @staticmethod
    def _sync_directory(path):
        fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)

    @classmethod
    def _publish_funding(cls,root,screen):
        """A campaign becomes usable only after every original book is durable.

        The unpublished directory cannot receive positions. Its exact funding
        intent survives crashes; published missing books remain fail closed.
        """
        root=Path(root);root.parent.mkdir(parents=True,exist_ok=True)
        with root.with_name(root.name+'.funding.lock').open('a+b') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise BoundaryError('ramses_campaign_funding_already_running') from None
            if root.exists():raise BoundaryError('ramses_campaign_existing_capital_requires_recovery')
            pending=cls.pending_path(root)
            if pending.is_symlink():raise BoundaryError('ramses_campaign_pending_identity')
            intent_path=pending/'funding-intent.json'
            if intent_path.exists():
                intent=json.loads(intent_path.read_text())
                if set(intent)!={'manifest','screen','hash'} or digest(dict(
                        manifest=intent['manifest'],screen=intent['screen']))!=intent['hash']:
                    raise BoundaryError('ramses_campaign_pending_identity')
                manifest=intent['manifest'];screen=intent['screen']
                budgets=cls.budgets_from_screen(screen)
                if (manifest['genesis_by_quote_asset']!=budgets
                        or manifest['source_screen_hash']!=digest(screen)
                        or manifest['policy_hash']!=POLICY_HASH or manifest['paper_only'] is not True
                        or manifest['cross_asset_conversion'] is not False):
                    raise BoundaryError('ramses_campaign_pending_identity')
            else:
                # No committed intent means no constructor may have funded a book.
                if pending.exists() and any(pending.glob('*.sqlite*')):
                    raise BoundaryError('ramses_campaign_pending_intent_missing')
                budgets=cls.budgets_from_screen(screen)
                if not budgets:raise BoundaryError('ramses_campaign_initial_funding_unavailable')
                pending.mkdir(exist_ok=True)
                manifest=dict(run_id=uuid.uuid4().hex,policy_hash=POLICY_HASH,paper_only=True,
                    source_screen_hash=digest(screen),source_finalized_block=screen.get('finalized_block'),
                    source_finalized_hash=screen.get('finalized_hash'),genesis_by_quote_asset=budgets,
                    funding_rule='one_maximum_frozen_scanner_size_plus_modeled_execution_cost_envelope_per_quote_asset_from_first_qualified_pinned_screen',
                    later_assets='unfunded_capacity_censoring',cross_asset_conversion=False)
                intent=dict(manifest=manifest,screen=screen);intent['hash']=digest(intent)
                temporary=intent_path.with_suffix('.tmp')
                with temporary.open('w') as file:file.write(canonical(intent));file.flush();os.fsync(file.fileno())
                os.replace(temporary,intent_path);cls._sync_directory(pending)
            if not budgets:raise BoundaryError('ramses_campaign_pending_identity')
            if not {p.name for p in pending.glob('*.sqlite')} <= {asset+'.sqlite' for asset in budgets}:
                raise BoundaryError('ramses_campaign_pending_book_set')
            # Validate every existing journal before any missing genesis is created.
            for path in pending.glob('*.sqlite'):
                if path.is_symlink():raise BoundaryError('ramses_campaign_pending_book_set')
                with closing(sqlite3.connect(path)) as db:
                    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    for table in ('ramses_strategy_position','ramses_strategy_journal'):
                        if table in tables and db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]:
                            raise BoundaryError('ramses_campaign_unpublished_exposure')
            for asset,amount in budgets.items():
                with closing(RamsesStrategyLedger(str(pending/(asset+'.sqlite')),
                        paper_capital=amount,quote_asset=asset)) as book:
                    if book.reconcile()['positions']:raise BoundaryError('ramses_campaign_unpublished_exposure')
            with (pending/'initial-screen.json.gz').open('wb') as file:
                with gzip.GzipFile(fileobj=file,mode='wb') as archive:archive.write(canonical(screen).encode())
                file.flush();os.fsync(file.fileno())
            with (pending/'capital-manifest.json').open('w') as file:
                file.write(canonical(manifest));file.flush();os.fsync(file.fileno())
            cls._sync_directory(pending)
            os.rename(pending,root);cls._sync_directory(root.parent)

    def __init__(self,root,screen):
        self._publish_funding(root,screen)
        restored=type(self).recover(root)
        self.__dict__.update(restored.__dict__)

    @classmethod
    def recover(cls,root):
        """Reopen exactly the funded books; missing files cannot recreate capital."""
        root=Path(root)
        manifest_path=root/'capital-manifest.json';screen_path=root/'initial-screen.json.gz'
        if (not manifest_path.is_file() or manifest_path.is_symlink()
                or not screen_path.is_file() or screen_path.is_symlink()):
            raise BoundaryError('ramses_campaign_recovery_evidence_missing')
        manifest=json.loads(manifest_path.read_text())
        with gzip.open(screen_path,'rt') as stream:screen=json.load(stream)
        budgets=cls.budgets_from_screen(screen)
        if (not budgets or manifest.get('policy_hash')!=POLICY_HASH
                or manifest.get('paper_only') is not True
                or manifest.get('cross_asset_conversion') is not False
                or manifest.get('source_screen_hash')!=digest(screen)
                or manifest.get('source_finalized_block')!=screen.get('finalized_block')
                or manifest.get('source_finalized_hash')!=screen.get('finalized_hash')
                or manifest.get('genesis_by_quote_asset')!=budgets
                or not isinstance(manifest.get('run_id'),str) or not manifest['run_id']):
            raise BoundaryError('ramses_campaign_recovery_identity')
        if set(p.name for p in root.glob('*.sqlite'))!={asset+'.sqlite' for asset in budgets}:
            raise BoundaryError('ramses_campaign_recovery_book_set')
        result=cls.__new__(cls);result.root=root;result.run_id=manifest['run_id']
        result.manifest=manifest;result.books={}
        import sqlite3
        try:
            # Check every existing genesis read-only before any constructor may
            # create schema. A crash during first funding remains fail closed.
            for asset,amount in budgets.items():
                path=root/(asset+'.sqlite')
                if path.is_symlink():raise BoundaryError('ramses_campaign_recovery_book_set')
                with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                    raw,checksum=db.execute("SELECT body,hash FROM ramses_strategy_meta WHERE id='genesis'").fetchone()
                    genesis=json.loads(raw)
                    if (digest(genesis)!=checksum or genesis.get('policy_hash')!=POLICY_HASH
                            or genesis.get('paper_capital')!=amount or genesis.get('quote_asset')!=asset):
                        raise BoundaryError('ramses_campaign_recovery_genesis')
            for asset,amount in budgets.items():
                result.books[asset]=RamsesStrategyLedger(str(root/(asset+'.sqlite')),
                    paper_capital=amount,quote_asset=asset)
            result.reconcile()
            return result
        except BaseException:
            result.close();raise

    def ledger(self,asset):
        book=self.books.get(asset.lower())
        if book is None:raise BoundaryError('ramses_campaign_quote_asset_unfunded')
        if any(x.reconcile()['open_positions'] for x in self.books.values()):
            raise BoundaryError('ramses_campaign_unresolved_exposure')
        return book

    def reconcile(self):
        rows={asset:book.reconcile() for asset,book in self.books.items()}
        for asset,row in rows.items():
            if row['paper_capital']!=self.manifest['genesis_by_quote_asset'][asset]:
                raise BoundaryError('ramses_campaign_genesis_changed')
            if row['paper_capital']+row['realized']!=row['available']+row['committed']:
                raise BoundaryError('ramses_campaign_conservation')
        return dict(manifest=self.manifest,by_quote_asset=rows,
            funding_state='funded_once_from_pinned_screen',
            open_positions=sum(x['open_positions'] for x in rows.values()),
            position_count=sum(x['positions'] for x in rows.values()),
            conservation=True,unlike_quote_units_summed=False)

    def record(self,kind,result):
        path=self.root/'lifecycles.jsonl'
        with path.open('a') as file:
            file.write(canonical(dict(kind=kind,policy_hash=POLICY_HASH,result=result))+'\n')
            file.flush();os.fsync(file.fileno())

    def close(self):
        for book in self.books.values():book.close()
