import copy,json,unittest
from pathlib import Path
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.pons import raw_event
from meme_machine.lanes.pons.ramses import _raw_ramses_event

FIXTURE=Path(__file__).with_name('fixtures')/'public_log_timestamp_35915320840.json'

class ProviderLogTimestampTests(unittest.TestCase):
    def setUp(self):self.f=json.loads(FIXTURE.read_text())
    def readers(self,event=None,receipt=None,header=None,observed_at=None):
        e=event or self.f['event'];r=receipt or self.f['receipt'];h=header or self.f['header']
        kw=dict(address=self.f['event']['address'],receipt=r,header=h,
                observed_at=observed_at if observed_at is not None else int(h['timestamp'],16))
        return (lambda:raw_event(self.f['abi'],e,confirmation='confirmed',**kw),
                lambda:_raw_ramses_event(self.f['abi'],e,**kw))
    def test_archived_optional_timestamp_mismatch_uses_authenticated_header_time(self):
        self.assertNotIn(self.f['event'],self.f['receipt']['logs'])
        for read in self.readers():
            row=read();self.assertEqual(row['event_at'],int(self.f['header']['timestamp'],16))
            self.assertTrue(row['decoded']['name'])
        e=copy.deepcopy(self.f['event']);e.pop('blockTimestamp')
        for read in self.readers(event=e):read()
    def test_every_identity_payload_field_and_unknown_extension_still_must_match(self):
        for field in ('address','blockHash','blockNumber','transactionHash','transactionIndex','logIndex','topics','data','removed','unknownExtension'):
            e=copy.deepcopy(self.f['event'])
            e[field]=True if field=='removed' else ['0x'+'00'*32] if field=='topics' else '0x01'
            for read in self.readers(event=e):
                with self.subTest(field=field),self.assertRaises((BoundaryError,ValueError)):read()
        for field,value in [('status','0x0'),('transactionHash','0x01'),('transactionIndex','0x01'),('blockHash','0x01'),('logs',[])]:
            r=copy.deepcopy(self.f['receipt']);r[field]=value
            for read in self.readers(receipt=r):
                with self.subTest(receipt_field=field),self.assertRaises(BoundaryError):read()
    def test_future_header_remains_rejected(self):
        for read in self.readers(observed_at=int(self.f['header']['timestamp'],16)-1):
            with self.assertRaisesRegex(BoundaryError,'future_event'):read()

if __name__=='__main__':unittest.main()
