import tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine.durable_publication import ReportPublisher

class PublisherTests(unittest.TestCase):
    def test_stalled_report_io_has_one_bounded_mailbox_and_cannot_block_caller(self):
        entered=threading.Event();release=threading.Event()
        def stalled(*args):entered.set();release.wait(5);raise OSError('publisher_failure')
        with tempfile.TemporaryDirectory() as temp,patch('meme_machine.durable_publication.publish_json',side_effect=stalled):
            publisher=ReportPublisher(Path(temp)/'report.json')
            try:
                publisher.submit({'reservation':'durable'});self.assertTrue(entered.wait(1))
                started=time.monotonic()
                for i in range(100):publisher.submit({'open_position':i})
                self.assertLess(time.monotonic()-started,.2)
                self.assertEqual(publisher.queue.qsize(),1);self.assertGreater(publisher.dropped,0)
                self.assertFalse(publisher.close(timeout=.01))
            finally:release.set();publisher.close(timeout=1)
            self.assertFalse(publisher.result['published']);self.assertEqual(publisher.result['error'],'OSError')
