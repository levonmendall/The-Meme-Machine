"""Inactive Fomo/FomoScan shadow intelligence scaffold.

This module is research plumbing only. It is not imported by the production engine,
does not nominate candidates, cannot reserve capital, and cannot enable DLMM. The
first version normalizes token leaderboard snapshots into a bounded point-in-time
book and publishes two transparent, deliberately uncalibrated research scores:

- directional_attention_score: whether Fomo attention is concentrated on a token;
- dlmm_flow_score: whether the same attention could merit later liquidity research.

Neither score is an alpha claim or an authorization predicate. Current documented
FomoScan API paths require an API key; live polling is disabled unless a future task
explicitly authorizes both activation and provider spend.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import asdict, dataclass

from . import pump

FOMOSCAN_BASE_URL = 'https://api.fomoscan.sh'
BOARD_PATHS = {
    'trending': '/v2/leaderboard/tokens/trending',
    'most-held': '/v2/leaderboard/tokens/most-held',
    'graduated': '/v2/leaderboard/tokens/graduated',
}
SCORE_VERSION = 'fomo-shadow-v0'
MAX_RANK = 100
MAX_HISTORY_PER_BOARD = 8
MAX_TOKENS = 256
MAX_SCORE_AGE_SECONDS = 120


@dataclass(frozen=True)
class TokenBoardObservation:
    mint: str
    board: str
    rank: int
    sampled_at: int
    observed_at: int
    source: str = 'fomoscan-v2'


@dataclass(frozen=True)
class FomoShadowScore:
    mint: str
    available: bool
    directional_attention_score: int | None
    dlmm_flow_score: int | None
    trending_rank: int | None
    most_held_rank: int | None
    graduated_rank: int | None
    trending_rank_improvement: int | None
    sampled_at: int | None
    observed_at: int | None
    score_version: str = SCORE_VERSION
    research_only: bool = True
    directional_authority: bool = False
    dlmm_authority: bool = False
    order_authority: bool = False

    def to_dict(self):
        return asdict(self)


def _solana_mint(value):
    if not isinstance(value, str):
        raise ValueError('missing_token_address')
    pump.un58(value)
    return value


def _positive_int(value, reason):
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise ValueError(reason) from None
    if out <= 0:
        raise ValueError(reason)
    return out


def _timestamp(payload, observed_at):
    if not isinstance(payload, dict):
        return int(observed_at)
    for key in ('at', 'sampledAt', 'sampled_at', 'timestamp'):
        if key in payload and payload[key] is not None:
            value = payload[key]
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str) and value.isdigit():
                return int(value)
    return int(observed_at)


def _rows(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError('invalid_fomo_payload')
    for key in ('items', 'data', 'results', 'tokens'):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    raise ValueError('missing_fomo_rows')


def normalize_token_board(board, payload, observed_at=None):
    """Normalize one documented Fomo token leaderboard snapshot.

    The adapter accepts a small set of common token-address/rank field spellings so
    vendor envelopes can evolve without coupling the research book to presentation
    fields. Structural ambiguity fails closed rather than guessing token identity.
    """
    if board not in BOARD_PATHS:
        raise ValueError('unsupported_fomo_board')
    observed_at = int(time.time() if observed_at is None else observed_at)
    sampled_at = _timestamp(payload, observed_at)
    if sampled_at > observed_at + 5:
        raise ValueError('future_fomo_snapshot')
    out = []
    seen = set()
    for index, row in enumerate(_rows(payload), start=1):
        if not isinstance(row, dict):
            raise ValueError('invalid_fomo_row')
        mint = None
        for key in ('tokenAddress', 'token_address', 'mint', 'address'):
            if row.get(key):
                mint = _solana_mint(row[key])
                break
        if mint is None:
            raise ValueError('missing_token_address')
        if mint in seen:
            raise ValueError('duplicate_fomo_token')
        seen.add(mint)
        rank = _positive_int(row.get('rank', index), 'invalid_fomo_rank')
        out.append(TokenBoardObservation(
            mint=mint,
            board=board,
            rank=rank,
            sampled_at=sampled_at,
            observed_at=observed_at,
        ))
    return out


def _rank_strength(rank):
    if rank is None:
        return 0
    rank = max(1, int(rank))
    return max(0, MAX_RANK + 1 - min(rank, MAX_RANK + 1))


class FomoSignalBook:
    """Bounded point-in-time store for normalized Fomo token leaderboard snapshots."""
    def __init__(self, max_tokens=MAX_TOKENS, history_per_board=MAX_HISTORY_PER_BOARD):
        if not 1 <= int(max_tokens) <= 4096 or not 2 <= int(history_per_board) <= 64:
            raise ValueError('invalid_fomo_book_bounds')
        self.max_tokens = int(max_tokens)
        self.history_per_board = int(history_per_board)
        self.history = {}
        self.ingested = 0

    def ingest(self, board, payload, observed_at=None):
        observations = normalize_token_board(board, payload, observed_at)
        for obs in observations:
            boards = self.history.setdefault(obs.mint, {})
            rows = boards.setdefault(board, [])
            if rows and obs.sampled_at < rows[-1].sampled_at:
                raise ValueError('fomo_time_regression')
            if rows and obs.sampled_at == rows[-1].sampled_at:
                rows[-1] = obs
            else:
                rows.append(obs)
            del rows[:-self.history_per_board]
            self.ingested += 1
        while len(self.history) > self.max_tokens:
            oldest_mint = min(
                self.history,
                key=lambda mint: max(
                    row[-1].observed_at
                    for row in self.history[mint].values() if row
                ),
            )
            del self.history[oldest_mint]
        return observations

    def _latest(self, mint, board):
        rows = self.history.get(mint, {}).get(board, [])
        return rows[-1] if rows else None

    def _prior(self, mint, board):
        rows = self.history.get(mint, {}).get(board, [])
        return rows[-2] if len(rows) >= 2 else None

    def score(self, mint, now=None, max_age_seconds=MAX_SCORE_AGE_SECONDS):
        pump.un58(mint)
        now = int(time.time() if now is None else now)
        latest = [self._latest(mint, board) for board in BOARD_PATHS]
        latest = [row for row in latest if row is not None]
        if not latest:
            return FomoShadowScore(
                mint=mint, available=False,
                directional_attention_score=None, dlmm_flow_score=None,
                trending_rank=None, most_held_rank=None, graduated_rank=None,
                trending_rank_improvement=None, sampled_at=None, observed_at=None,
            )
        freshest = max(row.observed_at for row in latest)
        sampled = max(row.sampled_at for row in latest)
        if now - freshest > int(max_age_seconds):
            return FomoShadowScore(
                mint=mint, available=False,
                directional_attention_score=None, dlmm_flow_score=None,
                trending_rank=None, most_held_rank=None, graduated_rank=None,
                trending_rank_improvement=None, sampled_at=sampled, observed_at=freshest,
            )

        trending = self._latest(mint, 'trending')
        held = self._latest(mint, 'most-held')
        graduated = self._latest(mint, 'graduated')
        prior_trending = self._prior(mint, 'trending')
        improvement = None
        if trending and prior_trending:
            improvement = prior_trending.rank - trending.rank

        trend_strength = _rank_strength(None if trending is None else trending.rank)
        held_strength = _rank_strength(None if held is None else held.rank)
        improvement_strength = 0 if improvement is None else max(0, min(100, improvement * 10))
        graduated_strength = 100 if graduated is not None else 0

        # Deliberately simple, fixed v0 weights. They are instrumentation, not a
        # fitted model and not a decision threshold.
        directional = (
            6 * trend_strength +
            2 * held_strength +
            2 * improvement_strength
        ) // 10
        dlmm = (
            3 * trend_strength +
            3 * held_strength +
            2 * improvement_strength +
            2 * graduated_strength
        ) // 10

        return FomoShadowScore(
            mint=mint,
            available=True,
            directional_attention_score=directional,
            dlmm_flow_score=dlmm,
            trending_rank=None if trending is None else trending.rank,
            most_held_rank=None if held is None else held.rank,
            graduated_rank=None if graduated is None else graduated.rank,
            trending_rank_improvement=improvement,
            sampled_at=sampled,
            observed_at=freshest,
        )

    def status(self):
        return dict(
            enabled=False,
            source='fomoscan-v2-compatible',
            score_version=SCORE_VERSION,
            tracked_tokens=len(self.history),
            ingested_observations=self.ingested,
            directional_authority=False,
            dlmm_authority=False,
            order_authority=False,
            production_integration=False,
        )


class FomoScanClient:
    """Explicitly inactive read-only client for a future authorized research task."""
    def __init__(self, api_key='', enabled=False, provider_spend_authorized=False,
                 base_url=FOMOSCAN_BASE_URL, timeout=8):
        if base_url.rstrip('/') != FOMOSCAN_BASE_URL:
            raise ValueError('unsupported_fomo_provider')
        self.api_key = api_key
        self.enabled = bool(enabled)
        self.provider_spend_authorized = bool(provider_spend_authorized)
        self.base_url = FOMOSCAN_BASE_URL
        self.timeout = int(timeout)
        self.requests = 0
        if self.enabled and not self.api_key:
            raise ValueError('fomo_api_key_required')
        if self.enabled and not self.provider_spend_authorized:
            raise ValueError('fomo_provider_spend_not_authorized')

    def fetch_board(self, board):
        if board not in BOARD_PATHS:
            raise ValueError('unsupported_fomo_board')
        if not self.enabled:
            raise RuntimeError('fomo_shadow_disabled')
        if not self.provider_spend_authorized:
            raise RuntimeError('fomo_provider_spend_not_authorized')
        request = urllib.request.Request(
            self.base_url + BOARD_PATHS[board],
            headers={'Authorization': f'Bearer {self.api_key}', 'Accept': 'application/json'},
        )
        self.requests += 1
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise RuntimeError('fomo_response_size_limit')
        return json.loads(raw)

    def status(self):
        return dict(
            enabled=self.enabled,
            configured=bool(self.api_key),
            provider_spend_authorized=self.provider_spend_authorized,
            requests=self.requests,
            read_only=True,
            order_authority=False,
            directional_authority=False,
            dlmm_authority=False,
        )
