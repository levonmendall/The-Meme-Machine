"""Finite signature unit tests. Keys are ephemeral, not execution authority."""
import base64
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'harness'))
from core import canonical,file_sha
from preserve import persist
from attest import signed_document


class SignatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=tempfile.TemporaryDirectory();cls.root=Path(cls.folder.name)
        cls.private=cls.root/'unit-private.pem';cls.public=cls.root/'unit-public.pem'
        subprocess.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:2048',
                        '-out',str(cls.private)],check=True,capture_output=True,timeout=10)
        subprocess.run(['openssl','pkey','-in',str(cls.private),'-pubout','-out',str(cls.public)],
                       check=True,capture_output=True,timeout=10)
        cls.payload={'version':'UNIT TEST ONLY','execution_authorized':False}
        target=cls.root/'payload';target.write_bytes(canonical(cls.payload))
        signature=cls.root/'signature'
        subprocess.run(['openssl','dgst','-sha256','-sign',str(cls.private),'-out',str(signature),str(target)],
                       check=True,capture_output=True,timeout=10)
        cls.envelope={'payload':cls.payload,'signature_base64':base64.b64encode(signature.read_bytes()).decode()}

    @classmethod
    def tearDownClass(cls):cls.folder.cleanup()

    def test_signature_and_independent_key_hash_required(self):
        path=self.root/'signed.json';persist(path,self.envelope)
        self.assertEqual(signed_document(path,self.public,file_sha(self.public)),self.payload)

    def test_payload_tampering_rejected(self):
        path=self.root/'changed.json';persist(path,dict(self.envelope,payload={'version':'changed','execution_authorized':False}))
        with self.assertRaises(ValueError):signed_document(path,self.public,file_sha(self.public))

    def test_trust_key_hash_tampering_rejected(self):
        path=self.root/'key.json';persist(path,self.envelope)
        with self.assertRaises(ValueError):signed_document(path,self.public,'0'*64)

    def test_unsigned_self_assertion_rejected(self):
        path=self.root/'unsigned.json';persist(path,{'payload':self.payload,'verified':True})
        with self.assertRaises(ValueError):signed_document(path,self.public,file_sha(self.public))
