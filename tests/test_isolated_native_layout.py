"""Explicit fixed copied paths and genuine isolated own-process observations."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from meme_machine.operational.artifact_storage import Scratch
from meme_machine.operational import isolated_native_entry as entry
from meme_machine.operational import isolated_native_layout as layout
from meme_machine.operational.isolated_native_layout import NativeLayoutRefused as Refused
from meme_machine.runtime import isolated_native_liveness as liveness
from meme_machine.runtime.robinhood import plane


def private_layout(scope,**changes):
    image=scope/'native-image';work=scope/'native-work'
    image.mkdir(mode=0o700);work.mkdir(mode=0o700)
    (work/'native').mkdir(mode=0o700);(work/'tmp').mkdir(mode=0o700)
    manifest=dict(schema='isolated-native-copied-image-v1',financial_authority=False,
        provider_calls=0,actual_service_restrictions_verified=False,
        source_commit='a'*40,source_tree='b'*40)
    raw=json.dumps(manifest,sort_keys=True).encode();(image/'manifest.json').write_bytes(raw)
    values=dict(profile=layout.PROFILE,image_root=str(image),work_root=str(work),
        parent_pid=os.getppid(),manifest_sha256=hashlib.sha256(raw).hexdigest())
    values.update(changes)
    return layout.NativeChildLayout(**values)


class NativeLayoutTests(unittest.TestCase):
    def test_fixed_geometry_environment_and_manifest_pin_drive_only_explicit_entry(self):
        with Scratch() as scope:
            owned=private_layout(scope.path)
            self.assertEqual(layout.NativeChildLayout.from_value(owned.value()),owned)
            self.assertEqual(owned.executable,Path(owned.image_root)/'runtime/bin/python3.12')
            self.assertEqual(owned.environment()['LD_LIBRARY_PATH'],str(Path(owned.image_root)/'runtime/lib'))
            self.assertEqual(owned.environment()['TMPDIR'],str(owned.temporary_directory))
            self.assertFalse(owned.state_directory.exists())
            with patch.object(layout.Path,'cwd',return_value=owned.native_directory):owned.require_entry()
            self.assertEqual(entry._image_identity(owned)['source_commit'],'a'*40)
            with patch('meme_machine.runtime.isolated_native_resources.IsolatedNativeResources') as create:
                entry._new_resources('explicit test input',owned)
                self.assertEqual(create.call_args.args[0],owned.state_directory)
                entry._new_resources('explicit test input')
                self.assertEqual(create.call_args.args[0],'/work/native/state')
            with self.assertRaises(AttributeError):owned.image_root='/unapproved'
            (owned.manifest).write_bytes(b'changed')
            with self.assertRaisesRegex(entry.IsolatedEntryBlocked,'manifest_changed'):
                entry._image_identity(owned)
            scope.check();scope.success=True

    def test_foreign_profile_geometry_parent_and_extra_selector_are_refused(self):
        with Scratch() as scope:
            owned=private_layout(scope.path)
            for change in (dict(profile='namespace'),dict(parent_pid=True),dict(parent_pid=1),
                    dict(work_root=str(scope.path/'other-work')),dict(manifest_sha256='self-approved'),
                    dict(image_root=owned.image_root+'/../native-image')):
                with self.subTest(change=change),self.assertRaises(Refused):
                    layout.NativeChildLayout.from_value(dict(owned.value(),**change))
            with self.assertRaisesRegex(Refused,'shape'):
                layout.NativeChildLayout.from_value(dict(owned.value(),entry='arbitrary.module'))
            with patch.object(layout.Path,'cwd',return_value=owned.native_directory),\
                    patch.object(layout.os,'getppid',return_value=owned.parent_pid+1),\
                    self.assertRaisesRegex(Refused,'parent_changed'):owned.require_entry()
            with self.assertRaisesRegex(Refused,'entry_directory'):owned.require_entry()
            scope.check();scope.success=True


class NativeLivenessTests(unittest.TestCase):
    def tearDown(self):
        active=liveness.current_scope()
        if active is not None:active.close()

    def test_actual_own_identity_is_fresh_foreign_observation_remains_unknown(self):
        scope=liveness.install_native_liveness();identity=scope.identity()
        boot,pid,start=identity.split(':')
        self.assertEqual(int(pid),os.getpid())
        self.assertEqual(scope.observe(identity),liveness.ALIVE)
        self.assertEqual(plane.process_identity(),identity)
        self.assertTrue(plane.alive(identity))
        foreign=f'{boot}:{int(pid)+1}:{start}'
        self.assertEqual(scope.observe(foreign),liveness.UNKNOWN)
        with self.assertRaises(liveness.NativeLivenessUnknown):plane.alive(foreign)
        self.assertEqual(scope.observe(f'{boot}:{pid}:{int(start)+1}'),liveness.DEAD)
        self.assertFalse(plane.alive(f'{boot}:{pid}:{int(start)+1}'))
        with self.assertRaises(liveness.NativeLivenessUnknown):liveness.install_native_liveness()
        scope.close();self.assertIsNone(liveness.current_scope())
        self.assertFalse(plane.alive('not an identity')) # Original production path.

    def test_denied_stale_or_forked_own_identity_never_falls_back_to_dead(self):
        scope=liveness.install_native_liveness();identity=scope.identity()
        for error in (PermissionError('fixed denial'),FileNotFoundError('fixed missing')):
            with self.subTest(error=type(error).__name__),patch.object(liveness,'_capture',side_effect=error):
                self.assertEqual(scope.observe(identity),liveness.UNKNOWN)
                with self.assertRaises(liveness.NativeLivenessUnknown):plane.alive(identity)
                with self.assertRaises(liveness.NativeLivenessUnknown):plane.process_identity()
        with patch.object(liveness.os,'getpid',return_value=os.getpid()+1):
            with self.assertRaises(liveness.NativeLivenessUnknown):plane.alive(identity)
        with self.assertRaises(liveness.NativeLivenessUnknown):plane.alive('corrupt identity')

    def test_native_recovery_rolls_back_and_preserves_unknown_owner_claim(self):
        with Scratch() as fixture:
            scope=liveness.install_native_liveness();boot,pid,start=scope.identity().split(':')
            path=fixture.path/'plane.sqlite';store=plane.Plane(path,clock=lambda:100)
            store.observe('candidate','pons','1',{'n':1},ordering=(1,),watermark={'block':1},
                interpretation={'policy':'frozen'},observed=100,deadline=105,priority=2)
            claimed=store.claim();self.assertIsNotNone(claimed)
            foreign=f'{boot}:{int(pid)+1}:{start}'
            store.db.execute('UPDATE candidates SET owner=? WHERE id=?',(foreign,'candidate'))
            before=dict(store.db.execute('SELECT * FROM candidates WHERE id=?',('candidate',)).fetchone())
            with self.assertRaises(liveness.NativeLivenessUnknown):store.recover()
            after=dict(store.db.execute('SELECT * FROM candidates WHERE id=?',('candidate',)).fetchone())
            self.assertEqual(before,after)
            store.close()
            with self.assertRaises(liveness.NativeLivenessUnknown):plane.Plane(path,clock=lambda:100)
            # Failed startup closed its connection; exact retained owner remains.
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT owner FROM candidates').fetchone(),(foreign,))
                db.execute('BEGIN EXCLUSIVE');db.rollback()
            scope.close();fixture.check();fixture.success=True


if __name__=='__main__':unittest.main()
