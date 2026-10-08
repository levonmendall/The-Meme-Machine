import unittest
from meme_machine.operational.storage_measurement import Trend


class StorageMeasurement(unittest.TestCase):
    def sample(self,at,state,wal,cpu):
        return dict(timestamp=at,storage_totals=dict(state_root_bytes=state,archive_bytes=state//2,learning_store_bytes=state//4),
                    storage={'native.sqlite':1000+state,'native.sqlite-wal':wal},host=dict(cpu_count=2,
                    disks={'/mnt/volume/state':dict(free_bytes=100000)},observation_stack={'observer':dict(cpu_usage_ns=cpu,memory_bytes=123)}))

    def test_hour_growth_peak_wal_and_separate_observer_overhead(self):
        trend=Trend();trend.add(self.sample(100,1000,10,0));trend.add(self.sample(1900,2000,500,10**9));trend.add(self.sample(3700,3000,0,2*10**9))
        row=trend.result();self.assertEqual(row['net_state_root_growth'],2000)
        self.assertEqual(row['net_bytes_per_hour'],2000);self.assertEqual(row['peak_wal_bytes'],500)
        self.assertEqual(row['archive_growth'],1000);self.assertEqual(row['learning_store_growth'],500)
        self.assertAlmostEqual(row['projected_days_to_volume_capacity'],100000/48000)
        self.assertAlmostEqual(row['observation_overhead']['observer']['cpu_percent_of_host'],100/3600)
        self.assertEqual(row['main_db_growth']['native.sqlite'],2000)

    def test_zero_growth_has_no_fabricated_exhaustion_projection(self):
        trend=Trend();trend.add(self.sample(1,100,10,100));trend.add(self.sample(61,100,0,50))
        row=trend.result();self.assertIsNone(row['projected_days_to_volume_capacity'])
        self.assertTrue(row['observation_overhead']['observer']['counter_reset'])
        self.assertIsNone(row['observation_overhead']['observer']['cpu_percent_of_host'])
