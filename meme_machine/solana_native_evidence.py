"""Read-only conversion of candidate-specific finalized native evidence.

The caller must obtain a complete filtered block from a FINALIZED subscription.
Block metadata, transaction updates, ACKs and silence cannot call this adapter.
No floats enter monetary authority: token amounts/decimals remain exact strings
and integers; uiAmount is only the provider's legacy display projection.
"""
import math
import struct
import copy
from dataclasses import dataclass
import based58
from .solana_evidence_plane import EvidenceUnavailable


@dataclass(frozen=True)
class NativeFrame:
    update: object
    source_bytes: int
    seen: float


# Bincode enum discriminants from anza-xyz/solana-sdk transaction-error and
# instruction-error. Unknown/malformed variants fail closed; bytes are never
# reinterpreted as a successful transaction. All supported error bytes are exact.
TRANSACTION_ERRORS=tuple('''AccountInUse AccountLoadedTwice AccountNotFound
ProgramAccountNotFound InsufficientFundsForFee InvalidAccountForFee AlreadyProcessed
BlockhashNotFound InstructionError CallChainTooDeep MissingSignatureForFee
InvalidAccountIndex SignatureFailure InvalidProgramForExecution SanitizeFailure
ClusterMaintenance AccountBorrowOutstanding WouldExceedMaxBlockCostLimit
UnsupportedVersion InvalidWritableAccount WouldExceedMaxAccountCostLimit
WouldExceedAccountDataBlockLimit TooManyAccountLocks AddressLookupTableNotFound
InvalidAddressLookupTableOwner InvalidAddressLookupTableData InvalidAddressLookupTableIndex
InvalidRentPayingAccount WouldExceedMaxVoteCostLimit WouldExceedAccountDataTotalLimit
DuplicateInstruction InsufficientFundsForRent MaxLoadedAccountsDataSizeExceeded
InvalidLoadedAccountsDataSizeLimit ResanitizationNeeded ProgramExecutionTemporarilyRestricted
UnbalancedTransaction ProgramCacheHitMaxLimit CommitCancelled BailOut'''.split())
INSTRUCTION_ERRORS=tuple('''GenericError InvalidArgument InvalidInstructionData
InvalidAccountData AccountDataTooSmall InsufficientFunds IncorrectProgramId
MissingRequiredSignature AccountAlreadyInitialized UninitializedAccount
UnbalancedInstruction ModifiedProgramId ExternalAccountLamportSpend
ExternalAccountDataModified ReadonlyLamportChange ReadonlyDataModified DuplicateAccountIndex
ExecutableModified RentEpochModified NotEnoughAccountKeys AccountDataSizeChanged
AccountNotExecutable AccountBorrowFailed AccountBorrowOutstanding DuplicateAccountOutOfSync
Custom InvalidError ExecutableDataModified ExecutableLamportChange ExecutableAccountNotRentExempt
UnsupportedProgramId CallDepth MissingAccount ReentrancyNotAllowed MaxSeedLengthExceeded
InvalidSeeds InvalidRealloc ComputationalBudgetExceeded PrivilegeEscalation
ProgramEnvironmentSetupFailure ProgramFailedToComplete ProgramFailedToCompile Immutable
IncorrectAuthority BorshIoError AccountNotRentExempt InvalidAccountOwner ArithmeticOverflow
UnsupportedSysvar IllegalOwner MaxAccountsDataAllocationsExceeded MaxAccountsExceeded
MaxInstructionTraceLengthExceeded BuiltinProgramsMustConsumeComputeUnits BailOut'''.split())


def transaction_error(raw):
    """Convert supported bincode error bytes into the canonical JSON-RPC shape."""
    try:
        if not isinstance(raw,bytes) or not 4<=len(raw)<=4096:raise ValueError()
        tag=struct.unpack_from('<I',raw)[0];name=TRANSACTION_ERRORS[tag];tail=raw[4:]
        if name=='InstructionError':
            if len(tail)<5:raise ValueError()
            index=tail[0];kind=INSTRUCTION_ERRORS[struct.unpack_from('<I',tail,1)[0]];extra=tail[5:]
            if kind=='Custom':
                if len(extra)!=4:raise ValueError()
                kind={'Custom':struct.unpack('<I',extra)[0]}
            elif kind=='BorshIoError' and extra:
                if len(extra)<8 or struct.unpack_from('<Q',extra)[0]!=len(extra)-8:raise ValueError()
                kind={'BorshIoError':extra[8:].decode('utf-8')}
            elif extra:raise ValueError()
            return {'InstructionError':[index,kind]}
        if name=='DuplicateInstruction':
            if len(tail)!=1:raise ValueError()
            return {name:tail[0]}
        if name in ('InsufficientFundsForRent','ProgramExecutionTemporarilyRestricted'):
            if len(tail)!=1:raise ValueError()
            return {name:{'account_index':tail[0]}}
        if tail:raise ValueError()
        return name
    except (ValueError,IndexError,struct.error,UnicodeError):
        raise EvidenceUnavailable('yellowstone_transaction_error_encoding') from None


def pubkey(raw):
    try:
        if len(raw)!=32:raise ValueError()
        return based58.b58encode(raw).decode('ascii')
    except (ValueError,TypeError):raise EvidenceUnavailable('yellowstone_pubkey_shape') from None


def signature(raw):
    try:
        if len(raw)!=64:raise ValueError()
        return based58.b58encode(raw).decode('ascii')
    except (ValueError,TypeError):raise EvidenceUnavailable('yellowstone_signature_shape') from None


def instruction(item,*,inner=False):
    # Compiled instruction data is base58 in the existing canonical RPC body.
    value=dict(programIdIndex=item.program_id_index,accounts=list(item.accounts),data=based58.b58encode(item.data).decode('ascii'))
    if inner:value['stackHeight']=item.stack_height if item.HasField('stack_height') else None
    return value


def token_balance(item):
    amount=item.ui_token_amount
    if not amount.amount.isdecimal() or not math.isfinite(amount.ui_amount):
        raise EvidenceUnavailable('yellowstone_token_balance_shape')
    value=dict(accountIndex=item.account_index,mint=item.mint,
        uiTokenAmount=dict(amount=amount.amount,decimals=amount.decimals,
            uiAmount=amount.ui_amount,uiAmountString=amount.ui_amount_string))
    if item.owner:value['owner']=item.owner
    if item.program_id:value['programId']=item.program_id
    return value


def normalize_zero_display(body):
    """Compare legacy null/0.0 zero displays; exact native amounts never change.

    Used only to prove compatibility with an already-verified immutable body.
    It never changes newly stored canonical bytes or any strategy input.
    """
    body=copy.deepcopy(body)
    payload=body.get('payload',body);meta=payload.get('meta') or {}
    for family in ('preTokenBalances','postTokenBalances'):
        for item in meta.get(family) or []:
            amount=item.get('uiTokenAmount') or {}
            ui=amount.get('uiAmount')
            if amount.get('amount')=='0' and (ui is None or type(ui) is float and ui==0.):
                amount['uiAmount']=None
    return body


def economic_transaction(item, *, slot, block_time, rich):
    """Normalize only authoritative downstream fields; raw delivery is billed.

    Yellowstone has no transaction-field projection. This function never labels
    its smaller return value as provider bandwidth saved. Pump logs need no
    instruction body; Meteora needs instructions, inner instructions and exact
    token balances. Both preserve the real chain index and normalized keys.
    """
    if not item.HasField('transaction') or not item.HasField('meta'):
        raise EvidenceUnavailable('yellowstone_transaction_shape')
    tx=item.transaction; message=tx.message; meta=item.meta
    signatures=[signature(s) for s in tx.signatures]
    if not signatures or signatures[0]!=signature(item.signature):
        raise EvidenceUnavailable('yellowstone_transaction_signature_mismatch')
    keys=[pubkey(k) for k in message.account_keys]
    keys += [pubkey(k) for k in meta.loaded_writable_addresses]
    keys += [pubkey(k) for k in meta.loaded_readonly_addresses]
    error=transaction_error(meta.err.err) if meta.HasField('err') else None
    if meta.log_messages_none and (error is None or meta.log_messages):
        raise EvidenceUnavailable('incomplete_finalized_logs')
    body=dict(slot=slot,blockTime=block_time,transactionIndex=item.index,
        transaction=dict(signatures=signatures,message=dict(accountKeys=keys)),
        meta=dict(err=error,logMessages=None if meta.log_messages_none else list(meta.log_messages)))
    if rich:
        body['transaction']['message']['instructions']=[instruction(i) for i in message.instructions]
        body['meta'].update(
            innerInstructions=None if meta.inner_instructions_none else [dict(index=i.index,
                instructions=[instruction(x,inner=True) for x in i.instructions]) for i in meta.inner_instructions],
            preTokenBalances=[token_balance(b) for b in meta.pre_token_balances],
            postTokenBalances=[token_balance(b) for b in meta.post_token_balances])
    return normalize_zero_display(body)
