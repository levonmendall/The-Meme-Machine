"""Fatal owned-child handoff; libraries never terminate their caller process."""
import json


class NativeOwnerDrainFailure(RuntimeError):
    """The original drain fence elapsed with source/thread owners still alive.

    The fixed child entry must hand this to process termination. Retained owners
    must not be closed concurrently or passed through asyncio.Runner.close().
    """
    def __init__(self,receipt):
        super().__init__('isolated_native_shutdown_incomplete')
        self.receipt=json.loads(json.dumps(receipt,allow_nan=False))
        self._retained=[]

    def retain(self,*owners):
        self._retained.extend(owners)
