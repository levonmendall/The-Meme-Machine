import base64
import struct
import unittest

from meme_machine import dlmm,pump
from meme_machine.dlmm_tape import _spl_transfer


def account(owner,raw):
    return dict(
        owner=owner,executable=False,
        data=[base64.b64encode(bytes(raw)).decode(),"base64"],
    )


def classic_mint(mint_authority=0,freeze_authority=0,decimals=6):
    raw=bytearray(82)
    raw[0:4]=int(mint_authority).to_bytes(4,"little")
    raw[36:44]=(1_000_000_000).to_bytes(8,"little")
    raw[44]=decimals;raw[45]=1
    raw[46:50]=int(freeze_authority).to_bytes(4,"little")
    return account(pump.TOKEN_PROGRAM,raw)


def token2022_mint(extensions,decimals=6):
    raw=bytearray(166)
    raw[36:44]=(1_000_000_000).to_bytes(8,"little")
    raw[44]=decimals;raw[45]=1;raw[165]=1
    for kind,size in extensions:
        raw.extend(struct.pack("<HH",kind,size))
        raw.extend(bytes(size))
    return account(pump.TOKEN_2022,raw)


def token_account(program,mint,authority,extensions=()):
    raw=bytearray(166 if program==pump.TOKEN_2022 else 165)
    raw[0:32]=pump.un58(mint)
    raw[32:64]=pump.un58(authority)
    raw[64:72]=(123_456_789).to_bytes(8,"little")
    raw[108]=1
    if program==pump.TOKEN_2022:
        raw[165]=2
        for kind,size in extensions:
            raw.extend(struct.pack("<HH",kind,size))
            raw.extend(bytes(size))
    return account(program,raw)


class SafeToken2022Tests(unittest.TestCase):
    def test_classic_mint_authority_without_freeze_is_supported_and_surfaced(self):
        info=dlmm._dlmm_mint_info(
            classic_mint(mint_authority=1,freeze_authority=0),
            pump.TOKEN_PROGRAM)
        self.assertTrue(info["mint_authority_present"])
        self.assertFalse(info["freeze_authority_present"])

    def test_freeze_authority_remains_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"freeze_authority_unsupported"):
            dlmm._dlmm_mint_info(
                classic_mint(mint_authority=1,freeze_authority=1),
                pump.TOKEN_PROGRAM)

    def test_metadata_only_token2022_mint_is_supported(self):
        info=dlmm._dlmm_mint_info(
            token2022_mint(((18,64),(19,4))),
            pump.TOKEN_2022)
        self.assertEqual(info["extensions"],(18,19))
        self.assertEqual(info["program"],pump.TOKEN_2022)

    def test_transfer_fee_token2022_mint_remains_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"behavioral_extension_unsupported"):
            dlmm._dlmm_mint_info(
                token2022_mint(((18,64),(19,4),(1,108))),
                pump.TOKEN_2022)

    def test_transfer_hook_and_pausable_remain_fail_closed(self):
        for ext in ((14,64),(26,33),(12,32),(4,65)):
            with self.subTest(ext=ext):
                with self.assertRaisesRegex(ValueError,"behavioral_extension_unsupported"):
                    dlmm._dlmm_mint_info(
                        token2022_mint(((18,64),(19,4),ext)),
                        pump.TOKEN_2022)

    def test_immutable_owner_token2022_vault_is_supported(self):
        mint=pump.PROGRAM;authority=dlmm.PROGRAM
        amount,extensions=dlmm._dlmm_vault_amount(
            token_account(pump.TOKEN_2022,mint,authority,((7,0),)),
            mint,authority,pump.TOKEN_2022)
        self.assertEqual(amount,123_456_789)
        self.assertEqual(extensions,(7,))

    def test_transfer_fee_amount_vault_remains_fail_closed(self):
        mint=pump.PROGRAM;authority=dlmm.PROGRAM
        with self.assertRaisesRegex(ValueError,"vault_extension_unsupported"):
            dlmm._dlmm_vault_amount(
                token_account(pump.TOKEN_2022,mint,authority,((2,8),)),
                mint,authority,pump.TOKEN_2022)

    def test_token2022_transfer_checked_is_recognized_by_tape(self):
        keys=["source",pump.PROGRAM,"dest",pump.TOKEN_2022]
        raw=b"\x0c"+(123).to_bytes(8,"little")+b"\x06"
        ix=dict(
            programIdIndex=3,
            accounts=[0,1,2],
            data=pump.b58(raw),
        )
        out=_spl_transfer(ix,keys)
        self.assertIsNotNone(out)
        self.assertEqual(out["kind"],"transfer_checked")
        self.assertEqual(out["amount"],123)
        self.assertEqual(out["mint"],pump.PROGRAM)
        self.assertEqual(out["program"],pump.TOKEN_2022)


if __name__=="__main__":
    unittest.main()
