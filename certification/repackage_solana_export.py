"""Package an already-exported offline fixture ZIP in supported transfer chunks.

Does not redownload or reprocess the original large hourly artifacts.
"""
import hashlib
import json
from pathlib import Path
import tempfile
from certification.export_solana_retained import download

ARTIFACT=10874679369
DIGEST='b7f25be0857bee238831dd6624ace391af86f42e757b9233dd4f04aea81fc2bb'

def main():
    out=Path('solana-retained-transfer');out.mkdir()
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'subset.zip';download(ARTIFACT,path,DIGEST)
        chunks=[]
        with path.open('rb') as source:
            number=0
            while data:=source.read(24*1024*1024):
                target=out/f'part-{number}.bin';target.write_bytes(data)
                chunks.append(dict(name=target.name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()));number+=1
        if number>4:raise ValueError('unexpected_compact_export_size')
        (out/'receipt.json').write_text(json.dumps(dict(artifact=ARTIFACT,zip_sha256=DIGEST,chunks=chunks),indent=2)+'\n')
        print(json.dumps(dict(chunks=chunks,no_market_access=True)))
if __name__=='__main__':main()
