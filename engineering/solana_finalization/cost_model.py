"""Generate the current seven-blocker cost report from recorded measurements.

Previous assumed promotion/body-fetch scenarios remain in Git history.
Uncertified production incidence stays null while provider capacity is open.
"""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from engineering.solana_closure.cost_model import main

if __name__=='__main__':main()
