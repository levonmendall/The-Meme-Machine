"""Assert a preserved implementation fails one behavioral regression."""
import sys,unittest

def main():
 suite=unittest.defaultTestLoader.loadTestsFromName(sys.argv[1])
 result=unittest.TextTestRunner(verbosity=2).run(suite)
 if not (result.testsRun==1 and len(result.failures)==1 and not result.errors):
  raise SystemExit('expected exactly one behavioral assertion failure')

if __name__=='__main__':main()
