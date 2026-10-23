//! Offline-only: executes the pinned Token-2022 compiled SBF ELF via Mollusk.
//! Accounts and authorities are synthetic. No RPC or real keys.
use mollusk_svm::{result::Check, Mollusk};
use solana_account::{Account as SolanaAccount, ReadableAccount};
use solana_address::Address;
use solana_instruction::Instruction;
use solana_rent::Rent;
use solana_sdk_ids::system_program;
use spl_token_2022_interface::{
    extension::{
        transfer_fee::{instruction::{initialize_transfer_fee_config, set_transfer_fee}, TransferFeeConfig},
        BaseStateWithExtensions, ExtensionType, StateWithExtensions,
    },
    instruction::initialize_mint2,
    state::Mint,
};

fn apply(svm: &mut Mollusk, label: &str, ix: Instruction, mint_key: Address,
         mint: SolanaAccount, other: Option<(Address, SolanaAccount)>) -> SolanaAccount {
    let mut accounts = vec![(mint_key, mint)];
    if let Some(v) = other { accounts.push(v); }
    let result = svm.process_and_validate_instruction(&ix, &accounts, &[Check::success()]);
    println!("SVM_INSTRUCTION name={} result={:?} compute_units={} account_count={}",
             label, result.program_result, result.compute_units_consumed, result.resulting_accounts.len());
    result.resulting_accounts.into_iter()
        .find(|(key, _)| *key == mint_key).expect("mint account must survive").1
}

fn fee_at(mint: &SolanaAccount, epoch: u64) -> (u16,u64,u64) {
    let state = StateWithExtensions::<Mint>::unpack(mint.data()).unwrap();
    let cfg = state.get_extension::<TransferFeeConfig>().unwrap();
    let fee = cfg.get_epoch_fee(epoch);
    (u16::from(fee.transfer_fee_basis_points), u64::from(fee.maximum_fee), u64::from(fee.epoch))
}

#[test]
fn compiled_token2022_fee_epoch_state_transitions() {
    let id = spl_token_2022::id();
    let mint_key = Address::new_unique();
    let admin = Address::new_unique();
    let mut svm = Mollusk::new(&id, "spl_token_2022");
    svm.config.panic = true;
    svm.sysvars.rent = Rent::default();
    svm.sysvars.clock.epoch = 10;
    let len = ExtensionType::try_calculate_account_len::<Mint>(&[ExtensionType::TransferFeeConfig]).unwrap();
    let mint = SolanaAccount::new(Rent::default().minimum_balance(len), len, &id);
    println!("SVM_INITIAL minted=false epoch=10 account_bytes={} lamports={}", len, mint.lamports());
    let mint = apply(&mut svm, "initialize_fee_config", initialize_transfer_fee_config(
        &id, &mint_key, Some(&admin), None, 100, 500).unwrap(), mint_key, mint, None);
    let mint = apply(&mut svm, "initialize_mint2", initialize_mint2(
        &id, &mint_key, &admin, None, 6).unwrap(), mint_key, mint, None);
    assert_eq!(fee_at(&mint, 10), (100,500,10));
    println!("SVM_STATE after=initialization fee_epoch10={:?}", fee_at(&mint, 10));
    let auth = SolanaAccount::new(1_000_000, 0, &system_program::id());
    let mint = apply(&mut svm, "authorized_fee_change_epoch10", set_transfer_fee(
        &id, &mint_key, &admin, &[], 300, 900).unwrap(), mint_key, mint, Some((admin, auth.clone())));
    assert_eq!(fee_at(&mint, 10), (100,500,10));
    assert_eq!(fee_at(&mint, 11), (100,500,10));
    assert_eq!(fee_at(&mint, 12), (300,900,12));
    println!("SVM_STATE after=fee_change_epoch10 fee_epoch10={:?} fee_epoch11={:?} fee_epoch12={:?}",
             fee_at(&mint, 10), fee_at(&mint, 11), fee_at(&mint, 12));
    svm.sysvars.clock.epoch = 11;
    let mint = apply(&mut svm, "replace_pending_fee_epoch11", set_transfer_fee(
        &id, &mint_key, &admin, &[], 500, 1200).unwrap(), mint_key, mint, Some((admin, auth)));
    assert_eq!(fee_at(&mint, 11), (100,500,10));
    assert_eq!(fee_at(&mint, 12), (100,500,10));
    assert_eq!(fee_at(&mint, 13), (500,1200,13));
    println!("SVM_STATE after=replacement fee_epoch11={:?} fee_epoch12={:?} fee_epoch13={:?}",
             fee_at(&mint, 11), fee_at(&mint, 12), fee_at(&mint, 13));
    println!("SVM_PASS actual_compiled_sbf=true verified_state_changes=true tested_instructions=4");
}
