from pathlib import Path
import re

DLMM = Path('meme_machine/dlmm.py')
TEST = Path('tests/test_dlmm_tape_extensions.py')


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected one match, found {count}')
    return text.replace(old, new, 1)


text = DLMM.read_text()
text = replace_once(
    text,
    """    The deployed program advances `last_update_timestamp` on the non-high-frequency\n    branch only: authenticated historical and current mainnet intervals both show the\n    field changing to the swap timestamp exactly when\n    `timestamp - last_update >= filter_period`, while higher-frequency swaps preserve\n    the previous value. This is the same branch on which reference volatility/index\n    parameters are refreshed.\n""",
    """    Reference/index decay still depends on time since `last_update`, but the deployed\n    smart-contract mitigation persists `last_update_timestamp` only when a swap crosses\n    at least one bin. Authentic mainnet evidence covers both sides: a same-bin swap more\n    than one filter period after the stored timestamp leaves it unchanged, while the\n    captured 1073->1074 swap advances it to the swap timestamp.\n""",
    'docstring',
)
text = replace_once(
    text,
    """    if elapsed >= s['filter_period']:\n        p['index_reference']=p['active']\n        p['volatility_reference']=(p['volatility_accumulator']*s['reduction_factor']//10000\n                                   if elapsed < s['decay_period'] else 0)\n        p['last_update']=timestamp\n    left=amount; output=fees=protocol=0; traversed=[]\n""",
    """    if elapsed >= s['filter_period']:\n        p['index_reference']=p['active']\n        p['volatility_reference']=(p['volatility_accumulator']*s['reduction_factor']//10000\n                                   if elapsed < s['decay_period'] else 0)\n    left=amount; output=fees=protocol=0; traversed=[]\n""",
    'reference-update branch',
)
text = replace_once(
    text,
    """    p['time']=timestamp\n    return p,dict(input=amount,output=output,fee=fees,protocol_fee=protocol,\n                  start=start,end=p['active'],traversed=traversed)\n""",
    """    # Meteora PR-178 mitigation: only bin traversal advances the persisted variable-\n    # parameter timestamp. Same-bin swaps may refresh references after filter_period,\n    # but they do not move this clock.\n    if p['active'] != start:\n        p['last_update']=timestamp\n    p['time']=timestamp\n    return p,dict(input=amount,output=output,fee=fees,protocol_fee=protocol,\n                  start=start,end=p['active'],traversed=traversed)\n""",
    'swap terminal timestamp',
)
DLMM.write_text(text)

text = TEST.read_text()
pattern = re.compile(
    r"    def test_last_update_changes_only_after_filter_period\(self\):.*?"
    r"(?=    def test_unexplained_terminal_last_update_mutation_still_fails_closed)",
    re.S,
)
replacement = '''    def test_last_update_is_bin_cross_gated_not_filter_gated(self):\n        start_snapshot=snapshot();start_snapshot['kind']='real';start=dlmm.validate(start_snapshot,100)\n        self.assertEqual(start['parameters']['filter_period'],30)\n        same,quote=dlmm.swap(start,1_000_000,True,140)\n        self.assertEqual((quote['start'],quote['end']),(0,0))\n        self.assertEqual(same['last_update'],100)\n        crossed,quote=dlmm.swap(start,250_000_000,True,110)\n        self.assertNotEqual(quote['start'],quote['end'])\n        self.assertEqual(crossed['last_update'],110)\n\n    def test_same_bin_after_filter_period_preserves_last_update_terminal_equality(self):\n        start_snapshot=snapshot();start_snapshot['kind']='real';start=dlmm.validate(start_snapshot,100)\n        post,tx=transaction(start,1_000_000,101,140,'clock-same')\n        self.assertEqual(post['last_update'],100)\n        end=encode_state(start_snapshot,post,102,142)\n        sigs=[dict(signature='clock-same',slot=101,transactionIndex=7,err=None,confirmationStatus='finalized'),dict(signature='anchor',slot=100,transactionIndex=1,err=None,confirmationStatus='finalized')]\n        tape=reconstruct(start,end,sigs,{'clock-same':tx},142,[100,2**31-1,2**31-1])\n        self.assertEqual(tape.terminal_adjustments,())\n        self.assertEqual(tape.terminal['last_update'],100)\n\n    def test_bin_cross_updates_last_update_terminal_equality(self):\n        start_snapshot=snapshot();start_snapshot['kind']='real';start=dlmm.validate(start_snapshot,100)\n        post,tx=transaction(start,250_000_000,101,110,'clock-cross')\n        self.assertNotEqual(start['active'],post['active'])\n        self.assertEqual(post['last_update'],110)\n        end=encode_state(start_snapshot,post,102,112)\n        sigs=[dict(signature='clock-cross',slot=101,transactionIndex=7,err=None,confirmationStatus='finalized'),dict(signature='anchor',slot=100,transactionIndex=1,err=None,confirmationStatus='finalized')]\n        tape=reconstruct(start,end,sigs,{'clock-cross':tx},112,[100,2**31-1,2**31-1])\n        self.assertEqual(tape.terminal_adjustments,())\n        self.assertEqual(tape.terminal['last_update'],110)\n\n'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit(f'test replacement: expected one match, found {count}')
TEST.write_text(text)

print('patched', DLMM, TEST)
