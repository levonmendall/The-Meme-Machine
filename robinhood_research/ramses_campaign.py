"""One frozen, asset-separated paper budget for a continuous Ramses campaign.

Budgets are declared once from the first fundable pinned factory screen, before
any outcome. Later candidates cannot mint capital or exchange unlike quote units.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import uuid
from . import BoundaryError
from .ramses_strategy import POLICY_HASH,STRATEGY_DOMAIN
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
            asset=asset.lower();budgets[asset]=max(budgets.get(asset,0),amount)
        return budgets

    def __init__(self,root,screen):
        self.root=Path(root)
        if self.root.exists():raise BoundaryError('ramses_campaign_existing_capital_requires_recovery')
        budgets=self.budgets_from_screen(screen)
        if not budgets:raise BoundaryError('ramses_campaign_initial_funding_unavailable')
        self.root.mkdir(parents=True)
        with (self.root/'initial-screen.json.gz').open('wb') as file:
            with gzip.GzipFile(fileobj=file,mode='wb') as archive:archive.write(canonical(screen).encode())
            file.flush();os.fsync(file.fileno())
        self.run_id=uuid.uuid4().hex;self.books={}
        self.manifest=dict(run_id=self.run_id,policy_hash=POLICY_HASH,paper_only=True,
            source_screen_hash=digest(screen),source_finalized_block=screen.get('finalized_block'),
            source_finalized_hash=screen.get('finalized_hash'),genesis_by_quote_asset=budgets,
            funding_rule='one_maximum_frozen_scanner_size_per_quote_asset_from_first_fundable_pinned_screen',
            later_assets='unfunded_capacity_censoring',cross_asset_conversion=False)
        manifest=self.root/'capital-manifest.json'
        with manifest.open('x') as file:file.write(canonical(self.manifest));file.flush();os.fsync(file.fileno())
        for asset,amount in budgets.items():
            self.books[asset]=RamsesStrategyLedger(str(self.root/(asset+'.sqlite')),
                paper_capital=amount,quote_asset=asset)

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
