import json
import tempfile
import unittest
from pathlib import Path

from meme_machine.pump_acceleration_confirmations import ConfirmationBook


class ConfirmationBookTests(unittest.TestCase):
    def book(self):
        cohort={
            "source_run":1,
            "cohort":[
                {"wallet":"skill-a","tokens_traded_30d":10,"win_rate_30d":0.7,
                 "roi_30d":2.0,"funding_group":"fund-1"},
                {"wallet":"skill-b","tokens_traded_30d":10,"win_rate_30d":0.8,
                 "roi_30d":3.0,"funding_group":"fund-1"},
                {"wallet":"skill-c","tokens_traded_30d":10,"win_rate_30d":0.6,
                 "roi_30d":1.0,"funding_group":"fund-2"},
            ],
        }
        return ConfirmationBook(cohort,100)

    def test_skilled_wallets_collapse_shared_funding_group(self):
        book=self.book()
        events=[
            {"wallet":"skill-a","buy":True},
            {"wallet":"skill-b","buy":True},
            {"wallet":"skill-c","buy":True},
        ]
        result=book.signal_inputs(events,200,"creator","mint")
        self.assertEqual(result["skilled_wallet_clusters"],2)
        self.assertEqual(result["explicit_funding_groups_observed"],2)

    def test_creator_history_excludes_current_mint_and_future_graduation(self):
        book=self.book()
        for i in range(6):
            book.observe_creation({
                "mint":f"m{i}","creator":"c","available_time":110+i,
            })
        book.observe_graduation("m0",120)
        book.observe_graduation("m1",250)
        result=book.signal_inputs([],200,"c","m5")
        self.assertEqual(result["creator_history_launches"],5)
        self.assertEqual(result["creator_quality_bps"],2000)


if __name__=="__main__":
    unittest.main()
