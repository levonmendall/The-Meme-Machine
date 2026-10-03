"""Controller-only one-shot signer. The private key never leaves process memory."""
import base64
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time

resource.setrlimit(resource.RLIMIT_CORE,(0,0))
root=Path('/workspace/allocation-controller-closure-20261003T121620Z')
root.mkdir(exist_ok=False)
key=subprocess.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072'],
    capture_output=True,check=True).stdout
public=subprocess.run(['openssl','pkey','-pubout'],input=key,capture_output=True,check=True).stdout
(root/'ALLOCATION_PUBLIC_KEY.pem').write_bytes(public)
identity=dict(version='independent-allocation-attestation-trust-v1',purpose='allocation-attestation-only',
    separate_from_owner_execution_permit=True,algorithm='RSA-3072/OpenSSL-dgst-SHA256',
    allocation_public_key_sha256=hashlib.sha256(public).hexdigest(),public_key_bytes=len(public),
    established_utc_ns=time.time_ns(),private_key_storage='ephemeral controller-process memory only',
    private_key_preserved=False,owner_execution_permit_created=False)
(root/'KEY_ESTABLISHMENT.json').write_text(json.dumps(identity,sort_keys=True,indent=2)+'\n')
identity['previous_private_key_discarded_and_not_reused']=True
identity['process_attestation_precondition_sha256']='426617b42a14fe546ad48834108a6489a0ad2e45585187d39ad002de8741110c'
identity['key_generation_procedure']='openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072; OpenSSL pkey -pubout; stdout/private stdin captured only in controller process memory; RLIMIT_CORE=0'
(root/'KEY_ESTABLISHMENT.json').write_text(json.dumps(identity,sort_keys=True,indent=2)+'\n')
print(json.dumps(identity,sort_keys=True),flush=True)
deadline=time.monotonic()+3600
request=root/'ALLOCATION_PAYLOAD.json'
while not request.exists():
    if time.monotonic()>=deadline:
        key=b''
        raise SystemExit('allocation_payload_not_supplied; signing key discarded')
    time.sleep(1)
payload=json.loads(request.read_bytes())
canonical=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
(root/'CANONICAL_ALLOCATION_PAYLOAD.json').write_bytes(canonical)
signature=subprocess.run(['openssl','dgst','-sha256','-sign','/dev/stdin',str(root/'CANONICAL_ALLOCATION_PAYLOAD.json')],
    input=key,capture_output=True,check=True).stdout
key=b''
(root/'ALLOCATION_SIGNATURE.bin').write_bytes(signature)
verified=subprocess.run(['openssl','dgst','-sha256','-verify',str(root/'ALLOCATION_PUBLIC_KEY.pem'),
    '-signature',str(root/'ALLOCATION_SIGNATURE.bin'),str(root/'CANONICAL_ALLOCATION_PAYLOAD.json')],capture_output=True,check=True)
envelope=dict(payload=payload,signature_base64=base64.b64encode(signature).decode())
data=json.dumps(envelope,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'
(root/'SIGNED_ALLOCATION.json').write_bytes(data)
(root/'SIGNING_RECEIPT.json').write_text(json.dumps(dict(canonical_payload_sha256=hashlib.sha256(canonical).hexdigest(),signed_allocation_sha256=hashlib.sha256(data).hexdigest(),allocation_public_key_sha256=identity['allocation_public_key_sha256'],signing_utc_ns=time.time_ns(),openssl_sha256_verified=verified.returncode==0,verification_output=verified.stdout.decode().strip(),private_key_discarded=True,private_key_ever_preserved=False),sort_keys=True,indent=2)+'\n')
print(json.dumps(dict(signed_allocation_sha256=hashlib.sha256(data).hexdigest(),
    independently_verified=verified.stdout.decode().strip(),private_key_discarded=True)),flush=True)
