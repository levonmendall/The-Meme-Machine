"""Offline, research-only Fomo intelligence for Solana candidate annotation.

This module is deliberately outside trading authority.  It can normalize bounded,
point-in-time leaderboard evidence, annotate an already discovered candidate, retain
bounded research outcomes, and join that annotation to a *separate* direct-DLMM
economics record.  It never nominates a token, changes continuation-v1, reserves
capital, creates orders, or enables DLMM.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Mapping

from . import pump

FOMOSCAN_BASE_URL = 'https://api.fomoscan.sh'
BOARD_PATHS = {
    'trending': '/v2/leaderboard/tokens/trending',
    'most-held': '/v2/leaderboard/tokens/most-held',
    'graduated': '/v2/leaderboard/tokens/graduated',
}
BOARD_NAMES = tuple(BOARD_PATHS)
SCORE_VERSION = 'fomo-shadow-v1'
ANNOTATION_VERSION = 'fomo-annotation-v1'
RESEARCH_VERSION = 'fomo-incremental-value-v1'
DLMM_BRIDGE_VERSION = 'fomo-dlmm-research-v1'
MAX_RANK = 100
MAX_HISTORY_PER_BOARD = 8
MAX_TOKENS = 256
MAX_SCORE_AGE_SECONDS = 120
MAX_RESEARCH_RECORDS = 512
MAX_REJECTION_REASONS = 8
MAX_TEXT_FIELD = 160


@dataclass(frozen=True)
class TokenBoardObservation:
    mint: str
    board: str
    rank: int
    sampled_at: int
    observed_at: int
    source: str = 'fomoscan-v2'


@dataclass(frozen=True)
class FomoBoardSnapshot:
    board: str
    sampled_at: int
    observed_at: int
    source: str
    ranks: tuple[tuple[str, int], ...]

    def rank_for(self, mint):
        for token, rank in self.ranks:
            if token == mint:
                return rank
        return None

    def canonical(self):
        return dict(
            board=self.board,
            sampled_at=self.sampled_at,
            observed_at=self.observed_at,
            source=self.source,
            ranks=list(self.ranks),
        )


@dataclass(frozen=True)
class FomoPointInTimeAnnotation:
    mint: str
    decision_at: int
    available: bool
    status: str
    freshness: str
    missing_data_status: str
    missing_boards: tuple[str, ...]
    source_timestamp: int | None
    available_at: int | None
    freshest_age_seconds: int | None
    oldest_age_seconds: int | None
    provenance: tuple[str, ...]
    trending_rank: int | None
    trending_present: bool | None
    trending_rank_change: int | None
    trending_strength: int | None
    most_held_rank: int | None
    most_held_strength: int | None
    attention_acceleration: int | None
    most_held_present: bool | None
    graduated_rank: int | None
    graduated_present: bool | None
    directional_attention_score: int | None
    dlmm_flow_score: int | None
    state_id: str
    annotation_version: str = ANNOTATION_VERSION
    research_only: bool = True
    nominates_candidate: bool = False
    suppresses_candidate: bool = False
    directional_authority: bool = False
    sizing_authority: bool = False
    execution_authority: bool = False
    order_authority: bool = False
    dlmm_authority: bool = False
    dlmm_allocation_enabled: bool = False

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class CandidateFomoAnnotation:
    mint: str
    decision_at: int
    fomo: FomoPointInTimeAnnotation
    research_only: bool = True
    candidate_authority: bool = False
    order_authority: bool = False
    dlmm_authority: bool = False

    def to_dict(self):
        return asdict(self)


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
    state_id: str | None = None
    freshness: str = 'unavailable'
    missing_data_status: str = 'unavailable'

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class FomoResearchOutcomeRecord:
    candidate_id: str
    mint: str
    decision_at: int
    fomo_state_id: str
    fomo_state: FomoPointInTimeAnnotation
    qualification_result: str
    rejection_reasons: tuple[str, ...]
    pump_entry: bool
    graduation: bool | None = None
    realized_paper_result_lamports: int | None = None
    mfe_bps: int | None = None
    mae_bps: int | None = None
    time_to_graduation_seconds: int | None = None
    time_to_exit_seconds: int | None = None
    research_version: str = RESEARCH_VERSION
    research_only: bool = True

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class DirectDlmmEconomics:
    """Direct Meteora/DLMM evidence, kept separate from Fomo authority."""
    pool: str
    base_mint: str
    quote_mint: str
    sampled_at: int
    available_at: int
    source: str
    current_price: float | None = None
    active_bin: int | None = None
    liquidity_distribution: tuple[tuple[int, int], ...] = ()
    tvl_lamports: int | None = None
    recent_volume_lamports: int | None = None
    historical_volume_lamports: int | None = None
    fee_rate_bps: int | None = None
    dynamic_fee_bps: int | None = None
    fees_generated_lamports: int | None = None
    volatility_bps: int | None = None
    position_range: tuple[int, int] | None = None
    inventory_exposure_bps: int | None = None
    rebalance_cost_bps: int | None = None
    withdrawal_cost_bps: int | None = None
    executable_lp_pnl_lamports: int | None = None
    direct_economics_authority: bool = True
    allocation_authority: bool = False

    def __post_init__(self):
        _solana_mint(self.pool)
        _solana_mint(self.base_mint)
        _solana_mint(self.quote_mint)
        _provenance(self.source)
        if int(self.sampled_at) > int(self.available_at):
            raise ValueError('future_dlmm_observation')

    @property
    def observation_id(self):
        payload = asdict(self)
        return _stable_id('dlmm-direct-v1', payload)

    def to_dict(self):
        out = asdict(self)
        out['observation_id'] = self.observation_id
        return out


@dataclass(frozen=True)
class FomoDlmmResearchVector:
    mint: str
    decision_at: int
    fomo_state_id: str
    dlmm_observation_id: str
    dlmm_pool: str
    fomo_available: bool
    trending_rank: int | None
    trending_rank_change: int | None
    trending_strength: int | None
    most_held_rank: int | None
    most_held_strength: int | None
    attention_acceleration: int | None
    graduated_present: bool | None
    directional_attention_score: int | None
    dlmm_flow_score: int | None
    bridge_version: str = DLMM_BRIDGE_VERSION
    research_only: bool = True
    direct_dlmm_economics_required: bool = True
    order_authority: bool = False
    dlmm_authority: bool = False
    dlmm_allocation_enabled: bool = False

    def to_dict(self):
        return asdict(self)


def _stable_id(namespace, payload):
    raw = json.dumps(
        dict(namespace=namespace, payload=payload),
        sort_keys=True,
        separators=(',', ':'),
        default=str,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _solana_mint(value):
    if not isinstance(value, str):
        raise ValueError('missing_token_address')
    try:
        raw = pump.un58(value)
    except ValueError:
        raise ValueError('invalid_solana_mint') from None
    if len(raw) != 32:
        raise ValueError('invalid_solana_mint')
    return value


def _provenance(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('missing_fomo_provenance')
    value = value.strip()
    if len(value) > MAX_TEXT_FIELD:
        raise ValueError('invalid_fomo_provenance')
    return value


def _bounded_text(value, reason, allow_empty=False):
    if not isinstance(value, str):
        raise ValueError(reason)
    value = value.strip()
    if (not value and not allow_empty) or len(value) > MAX_TEXT_FIELD:
        raise ValueError(reason)
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
            raise ValueError('invalid_fomo_timestamp')
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


def normalize_token_board(board, payload, observed_at=None, source='fomoscan-v2'):
    """Normalize one provider snapshot without granting any trading authority."""
    if board not in BOARD_PATHS:
        raise ValueError('unsupported_fomo_board')
    source = _provenance(source)
    observed_at = int(time.time() if observed_at is None else observed_at)
    sampled_at = _timestamp(payload, observed_at)
    if sampled_at > observed_at + 5:
        raise ValueError('future_fomo_snapshot')
    out = []
    seen = {}
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
        rank = _positive_int(row.get('rank', index), 'invalid_fomo_rank')
        if mint in seen:
            if seen[mint] != rank:
                raise ValueError('conflicting_fomo_token')
            raise ValueError('duplicate_fomo_token')
        seen[mint] = rank
        out.append(TokenBoardObservation(
            mint=mint,
            board=board,
            rank=rank,
            sampled_at=sampled_at,
            observed_at=observed_at,
            source=source,
        ))
    return out


def _rank_strength(rank):
    if rank is None:
        return 0
    rank = max(1, int(rank))
    return max(0, MAX_RANK + 1 - min(rank, MAX_RANK + 1))


class FomoSignalBook:
    """Bounded point-in-time normalized history; raw provider payloads are discarded."""
    def __init__(self, max_tokens=MAX_TOKENS, history_per_board=MAX_HISTORY_PER_BOARD):
        if not 1 <= int(max_tokens) <= 4096 or not 2 <= int(history_per_board) <= 64:
            raise ValueError('invalid_fomo_book_bounds')
        self.max_tokens = int(max_tokens)
        self.history_per_board = int(history_per_board)
        self.history = {}
        self.snapshots = {board: [] for board in BOARD_NAMES}
        self.ingested = 0
        self.duplicate_snapshots = 0

    def _tracked_mints(self):
        return {
            mint
            for board in BOARD_NAMES
            for snapshot in self.snapshots[board]
            for mint, _ in snapshot.ranks
        }

    def _refresh_history(self):
        history = {}
        for board in BOARD_NAMES:
            for snapshot in self.snapshots[board]:
                for mint, rank in snapshot.ranks:
                    boards = history.setdefault(mint, {})
                    rows = boards.setdefault(board, [])
                    rows.append(TokenBoardObservation(
                        mint=mint,
                        board=board,
                        rank=rank,
                        sampled_at=snapshot.sampled_at,
                        observed_at=snapshot.observed_at,
                        source=snapshot.source,
                    ))
        self.history = history

    def _trim_to_bounds(self):
        for board in BOARD_NAMES:
            del self.snapshots[board][:-self.history_per_board]
        while len(self._tracked_mints()) > self.max_tokens:
            candidates = [
                (rows[0].observed_at, board)
                for board, rows in self.snapshots.items()
                if len(rows) > 1
            ]
            if not candidates:
                raise ValueError('fomo_token_capacity')
            _, board = min(candidates)
            del self.snapshots[board][0]
        self._refresh_history()

    def ingest(self, board, payload, observed_at=None, source='fomoscan-v2'):
        source = _provenance(source)
        observed_at = int(time.time() if observed_at is None else observed_at)
        observations = normalize_token_board(board, payload, observed_at, source)
        if len(observations) > self.max_tokens:
            raise ValueError('fomo_snapshot_capacity')
        sampled_at = observations[0].sampled_at if observations else _timestamp(payload, observed_at)
        if sampled_at > observed_at + 5:
            raise ValueError('future_fomo_snapshot')
        ranks = tuple((row.mint, row.rank) for row in observations)
        snapshot = FomoBoardSnapshot(
            board=board,
            sampled_at=sampled_at,
            observed_at=observed_at,
            source=source,
            ranks=ranks,
        )
        rows = self.snapshots[board]
        if rows:
            prior = rows[-1]
            if sampled_at < prior.sampled_at or observed_at < prior.observed_at:
                raise ValueError('fomo_time_regression')
            if sampled_at == prior.sampled_at:
                if (
                    prior.ranks == snapshot.ranks and
                    prior.source == snapshot.source
                ):
                    self.duplicate_snapshots += 1
                    return observations
                raise ValueError('fomo_conflicting_duplicate')
        rows.append(snapshot)
        self.ingested += len(observations)
        try:
            self._trim_to_bounds()
        except Exception:
            rows.pop()
            self._refresh_history()
            raise
        return observations

    def replay(self, frames):
        """Replay captured/provider-shaped frames in supplied availability order."""
        count = 0
        for frame in frames:
            if not isinstance(frame, dict):
                raise ValueError('invalid_fomo_replay_frame')
            self.ingest(
                frame.get('board'),
                frame.get('payload'),
                observed_at=frame.get('observed_at'),
                source=frame.get('source'),
            )
            count += 1
        return count

    def _snapshots_as_of(self, board, decision_at):
        return [
            row for row in self.snapshots.get(board, ())
            if row.observed_at <= decision_at and row.sampled_at <= decision_at
        ]

    def _annotation_state_id(self, mint, decision_at, selected, prior_trending):
        payload = dict(
            mint=mint,
            decision_at=decision_at,
            selected={
                board: None if selected.get(board) is None else selected[board].canonical()
                for board in BOARD_NAMES
            },
            prior_trending=None if prior_trending is None else prior_trending.canonical(),
        )
        return _stable_id(ANNOTATION_VERSION, payload)

    def annotate(self, mint, decision_at, max_age_seconds=MAX_SCORE_AGE_SECONDS):
        mint = _solana_mint(mint)
        decision_at = int(decision_at)
        max_age_seconds = int(max_age_seconds)
        if max_age_seconds < 0:
            raise ValueError('invalid_fomo_max_age')

        selected = {}
        historical = {}
        missing = []
        ages = []
        for board in BOARD_NAMES:
            as_of = self._snapshots_as_of(board, decision_at)
            historical[board] = as_of[-1] if as_of else None
            if not as_of:
                selected[board] = None
                missing.append(board)
                continue
            latest = as_of[-1]
            age = decision_at - latest.observed_at
            if age > max_age_seconds:
                selected[board] = None
                missing.append(board)
                continue
            selected[board] = latest
            ages.append(age)

        fresh_count = sum(value is not None for value in selected.values())
        had_history = any(value is not None for value in historical.values())
        if not fresh_count:
            status = 'stale' if had_history else 'unavailable'
            freshness = status
            missing_data_status = status
        else:
            status = 'available'
            freshness = 'fresh'
            missing_data_status = 'complete' if fresh_count == len(BOARD_NAMES) else 'partial'

        trending = selected['trending']
        held = selected['most-held']
        graduated = selected['graduated']

        trending_rank = None if trending is None else trending.rank_for(mint)
        held_rank = None if held is None else held.rank_for(mint)
        graduated_rank = None if graduated is None else graduated.rank_for(mint)

        prior_trending = None
        trend_as_of = self._snapshots_as_of('trending', decision_at)
        if trending is not None:
            fresh_trend = [
                row for row in trend_as_of
                if decision_at - row.observed_at <= max_age_seconds
            ]
            if len(fresh_trend) >= 2:
                prior_trending = fresh_trend[-2]
        prior_rank = None if prior_trending is None else prior_trending.rank_for(mint)
        trend_change = None
        if trending_rank is not None and prior_rank is not None:
            trend_change = prior_rank - trending_rank

        trend_strength = _rank_strength(trending_rank)
        held_strength = _rank_strength(held_rank)
        attention_acceleration = (
            None if trend_change is None else max(-100, min(100, trend_change * 10))
        )
        improvement_strength = 0 if attention_acceleration is None else max(0, attention_acceleration)
        graduated_strength = 100 if graduated_rank is not None else 0

        directional = None
        dlmm = None
        if fresh_count:
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

        source_timestamp = max(
            (row.sampled_at for row in selected.values() if row is not None),
            default=None,
        )
        available_at = max(
            (row.observed_at for row in selected.values() if row is not None),
            default=None,
        )
        provenance = tuple(sorted({
            row.source for row in selected.values() if row is not None
        }))
        state_id = self._annotation_state_id(
            mint, decision_at, selected, prior_trending
        )
        return FomoPointInTimeAnnotation(
            mint=mint,
            decision_at=decision_at,
            available=bool(fresh_count),
            status=status,
            freshness=freshness,
            missing_data_status=missing_data_status,
            missing_boards=tuple(missing),
            source_timestamp=source_timestamp,
            available_at=available_at,
            freshest_age_seconds=min(ages) if ages else None,
            oldest_age_seconds=max(ages) if ages else None,
            provenance=provenance,
            trending_rank=trending_rank,
            trending_present=None if trending is None else trending_rank is not None,
            trending_rank_change=trend_change,
            trending_strength=trend_strength if trending is not None else None,
            most_held_rank=held_rank,
            most_held_strength=held_strength if held is not None else None,
            attention_acceleration=attention_acceleration,
            most_held_present=None if held is None else held_rank is not None,
            graduated_rank=graduated_rank,
            graduated_present=None if graduated is None else graduated_rank is not None,
            directional_attention_score=directional,
            dlmm_flow_score=dlmm,
            state_id=state_id,
        )

    def score(self, mint, now=None, max_age_seconds=MAX_SCORE_AGE_SECONDS):
        now = int(time.time() if now is None else now)
        annotation = self.annotate(mint, now, max_age_seconds)
        return FomoShadowScore(
            mint=annotation.mint,
            available=annotation.available,
            directional_attention_score=annotation.directional_attention_score,
            dlmm_flow_score=annotation.dlmm_flow_score,
            trending_rank=annotation.trending_rank,
            most_held_rank=annotation.most_held_rank,
            graduated_rank=annotation.graduated_rank,
            trending_rank_improvement=annotation.trending_rank_change,
            sampled_at=annotation.source_timestamp,
            observed_at=annotation.available_at,
            state_id=annotation.state_id,
            freshness=annotation.freshness,
            missing_data_status=annotation.missing_data_status,
        )

    def status(self):
        retained_snapshots = sum(len(rows) for rows in self.snapshots.values())
        retained_observations = sum(
            len(snapshot.ranks)
            for rows in self.snapshots.values()
            for snapshot in rows
        )
        return dict(
            enabled=False,
            source='provider-neutral/fomoscan-v2-compatible',
            score_version=SCORE_VERSION,
            annotation_version=ANNOTATION_VERSION,
            tracked_tokens=len(self._tracked_mints()),
            retained_snapshots=retained_snapshots,
            retained_observations=retained_observations,
            max_tokens=self.max_tokens,
            history_per_board=self.history_per_board,
            max_retained_snapshots=len(BOARD_NAMES) * self.history_per_board,
            max_retained_observations=(
                len(BOARD_NAMES) * self.history_per_board * self.max_tokens
            ),
            ingested_observations=self.ingested,
            duplicate_snapshots=self.duplicate_snapshots,
            raw_provider_payloads_retained=False,
            persistent_storage='none',
            directional_authority=False,
            dlmm_authority=False,
            order_authority=False,
            production_integration=False,
        )


class FomoCandidateAnnotator:
    """Read-only candidate annotation boundary.  Candidate objects are never mutated."""
    def __init__(self, book, max_age_seconds=MAX_SCORE_AGE_SECONDS):
        if not isinstance(book, FomoSignalBook):
            raise TypeError('invalid_fomo_book')
        self.book = book
        self.max_age_seconds = int(max_age_seconds)

    def annotate_mint(self, mint, decision_at):
        fomo = self.book.annotate(mint, decision_at, self.max_age_seconds)
        return CandidateFomoAnnotation(
            mint=fomo.mint,
            decision_at=int(decision_at),
            fomo=fomo,
        )

    def annotate_candidate(self, candidate, decision_at):
        if not isinstance(candidate, Mapping):
            raise TypeError('invalid_market_candidate')
        if 'mint' not in candidate:
            raise ValueError('missing_candidate_mint')
        return self.annotate_mint(candidate['mint'], decision_at)


class FomoResearchLedger:
    """Bounded summary-only incremental-value records with bounded snapshot persistence."""
    def __init__(self, max_records=MAX_RESEARCH_RECORDS):
        if not 1 <= int(max_records) <= 4096:
            raise ValueError('invalid_fomo_research_bound')
        self.max_records = int(max_records)
        self.records = {}

    def _prune(self):
        while len(self.records) > self.max_records:
            first = next(iter(self.records))
            del self.records[first]

    def capture_decision(
        self,
        candidate_id,
        annotation,
        qualification_result,
        rejection_reasons=(),
        pump_entry=False,
    ):
        candidate_id = _bounded_text(candidate_id, 'invalid_candidate_id')
        qualification_result = _bounded_text(
            qualification_result, 'invalid_qualification_result'
        )
        if not isinstance(annotation, FomoPointInTimeAnnotation):
            raise TypeError('invalid_fomo_annotation')
        reasons = tuple(rejection_reasons or ())
        if len(reasons) > MAX_REJECTION_REASONS:
            raise ValueError('too_many_rejection_reasons')
        reasons = tuple(
            _bounded_text(reason, 'invalid_rejection_reason') for reason in reasons
        )
        record = FomoResearchOutcomeRecord(
            candidate_id=candidate_id,
            mint=annotation.mint,
            decision_at=annotation.decision_at,
            fomo_state_id=annotation.state_id,
            fomo_state=annotation,
            qualification_result=qualification_result,
            rejection_reasons=reasons,
            pump_entry=bool(pump_entry),
        )
        prior = self.records.get(candidate_id)
        if prior is not None:
            if prior == record:
                return prior
            raise ValueError('conflicting_fomo_research_record')
        self.records[candidate_id] = record
        self._prune()
        return record

    def finalize_outcome(
        self,
        candidate_id,
        *,
        graduation=None,
        realized_paper_result_lamports=None,
        mfe_bps=None,
        mae_bps=None,
        time_to_graduation_seconds=None,
        time_to_exit_seconds=None,
    ):
        candidate_id = _bounded_text(candidate_id, 'invalid_candidate_id')
        if candidate_id not in self.records:
            raise KeyError('unknown_fomo_research_candidate')
        for name, value in (
            ('time_to_graduation_seconds', time_to_graduation_seconds),
            ('time_to_exit_seconds', time_to_exit_seconds),
        ):
            if value is not None and int(value) < 0:
                raise ValueError(f'invalid_{name}')
        record = replace(
            self.records[candidate_id],
            graduation=None if graduation is None else bool(graduation),
            realized_paper_result_lamports=(
                None if realized_paper_result_lamports is None
                else int(realized_paper_result_lamports)
            ),
            mfe_bps=None if mfe_bps is None else int(mfe_bps),
            mae_bps=None if mae_bps is None else int(mae_bps),
            time_to_graduation_seconds=(
                None if time_to_graduation_seconds is None
                else int(time_to_graduation_seconds)
            ),
            time_to_exit_seconds=(
                None if time_to_exit_seconds is None else int(time_to_exit_seconds)
            ),
        )
        self.records[candidate_id] = record
        return record

    def save(self, path):
        """Atomically rewrite only the bounded summary snapshot; never append raw feeds."""
        path = Path(path)
        payload = dict(
            schema=RESEARCH_VERSION,
            max_records=self.max_records,
            records=[record.to_dict() for record in self.records.values()],
        )
        raw = json.dumps(
            payload, sort_keys=True, separators=(',', ':')
        ).encode()
        max_bytes = 2048 + self.max_records * 8192
        if len(raw) > max_bytes:
            raise ValueError('fomo_research_snapshot_size')
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + '.tmp')
        with open(tmp, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        return len(raw)

    def status(self):
        return dict(
            research_version=RESEARCH_VERSION,
            retained_records=len(self.records),
            max_records=self.max_records,
            persistence='bounded_atomic_snapshot',
            raw_provider_payloads_retained=False,
            optimization_enabled=False,
            directional_authority=False,
            order_authority=False,
            dlmm_authority=False,
        )


def build_dlmm_research_vector(annotation, dlmm, decision_at=None):
    """Join by identity/time for research while keeping direct DLMM economics separate."""
    if not isinstance(annotation, FomoPointInTimeAnnotation):
        raise TypeError('invalid_fomo_annotation')
    if not isinstance(dlmm, DirectDlmmEconomics):
        raise TypeError('direct_dlmm_economics_required')
    decision_at = annotation.decision_at if decision_at is None else int(decision_at)
    if decision_at != annotation.decision_at:
        raise ValueError('fomo_dlmm_decision_mismatch')
    if dlmm.available_at > decision_at or dlmm.sampled_at > decision_at:
        raise ValueError('future_dlmm_observation')
    if annotation.mint not in (dlmm.base_mint, dlmm.quote_mint):
        raise ValueError('fomo_dlmm_mint_mismatch')
    return FomoDlmmResearchVector(
        mint=annotation.mint,
        decision_at=decision_at,
        fomo_state_id=annotation.state_id,
        dlmm_observation_id=dlmm.observation_id,
        dlmm_pool=dlmm.pool,
        fomo_available=annotation.available,
        trending_rank=annotation.trending_rank,
        trending_rank_change=annotation.trending_rank_change,
        trending_strength=annotation.trending_strength,
        most_held_rank=annotation.most_held_rank,
        most_held_strength=annotation.most_held_strength,
        attention_acceleration=annotation.attention_acceleration,
        graduated_present=annotation.graduated_present,
        directional_attention_score=annotation.directional_attention_score,
        dlmm_flow_score=annotation.dlmm_flow_score,
    )


class FomoScanClient:
    """Explicitly inactive read-only adapter for a separately authorized research run."""
    def __init__(
        self,
        api_key='',
        enabled=False,
        provider_spend_authorized=False,
        base_url=FOMOSCAN_BASE_URL,
        timeout=8,
    ):
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
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Accept': 'application/json',
            },
        )
        self.requests += 1
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise RuntimeError('fomo_response_size_limit')
        return json.loads(raw)

    def capture_board(self, book, board, observed_at=None, source='fomoscan-v2'):
        if not isinstance(book, FomoSignalBook):
            raise TypeError('invalid_fomo_book')
        payload = self.fetch_board(board)
        return book.ingest(
            board,
            payload,
            observed_at=observed_at,
            source=source,
        )

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
