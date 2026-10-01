"""The exact bounded before/after-commit lifecycle child from durable tests."""
import os
import sys
from meme_machine.store import Store
from meme_machine.engine import Engine
from tests.support import SCOUT, event, evidence, snapshot


def main():
    store = Store(sys.argv[1], 'synthetic', 100_000_000, 'test')
    engine = Engine(store, [SCOUT])
    engine.consider(event(), evidence(), 100)
    store.hook = lambda stage: os._exit(77) if stage == sys.argv[2] else None
    engine.fill('nomination', snapshot(102), 102)
