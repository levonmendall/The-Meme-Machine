"""Reuse authenticated native market evidence; never synthesize a USD rate."""
from dataclasses import dataclass
from datetime import datetime,timezone
from decimal import Decimal,localcontext

USDG_BLOCKER='USDG/USD: no authoritative USD conversion or contractual USD parity was found in the pinned operational sources. Existing ETH-to-USDG executable routes do not supply this final USD anchor.'

class ValuationUnavailable(ValueError):pass

def utc(seconds):return datetime.fromtimestamp(seconds,timezone.utc).isoformat().replace('+00:00','Z')

@dataclass(frozen=True)
class USDValue:
    asset: str
    decimals: int
    usd_per_unit: Decimal
    observed_at: int
    valid_until: int
    evidence_id: str
    evidence_hash: str

    def amount(self,raw,at):
        if type(raw) is not int or raw<0 or not self.observed_at<=at<=self.valid_until:
            raise ValuationUnavailable('native_USD_value_missing_or_stale')
        if self.usd_per_unit<=0:raise ValuationUnavailable('invalid_USD_rate')
        with localcontext() as context:
            context.prec=80
            return Decimal(raw)*self.usd_per_unit/(Decimal(10)**self.decimals)

    def evidence(self,at):
        self.amount(0,at)
        from meme_machine.portfolio_lane_integration import usd_evidence
        return usd_evidence(self.evidence_id,self.evidence_hash,utc(self.observed_at),utc(self.valid_until))


def sol_usd(account,*,now,slot,evidence_hash):
    from meme_machine.lanes.pump.pumpswap_survivor_evidence import sol_usd_lower_micros,SOL_USD_ACCOUNT
    micros=sol_usd_lower_micros(account,now=now,slot=slot)
    # The existing decoder checks a <=120s publish age; caller validity never extends it.
    import base64,struct
    published=struct.unpack_from('<q',base64.b64decode(account['data'][0]),93)[0]
    return USDValue('SOL',9,Decimal(micros)/Decimal(1000000),published,published+120,
        'sol-usd:'+str(slot),evidence_hash)


def robinhood_usd(*args,**kwargs):
    # No config number, historical fixed ETH price or USDG symbol can grant a value.
    raise ValuationUnavailable(USDG_BLOCKER)
