"""Regression checks for startup decisions and confirmed export state."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from engine import Adjustments, atomic_json
from app import FilmDesk
from session_state import (conversion_signature,completion_matches,jpeg_digest,
                           verified_existing_export,finished_export_snapshot)


def example(root):
    folder=root/'scans';destination=root/'JPEG'
    state={'app':'Film Desk','folder':str(folder),'reference_path':str(folder/'blank.ARW'),
        'reference':None,'roll_model':None,'quality':95,'current':str(folder/'photo.ARW'),
        'output_folder':str(destination),'pending_crops':[],
        'photos':{'blank.ARW':vars(Adjustments(included=False)),
                  'photo.ARW':vars(Adjustments())},'completed_export':None}
    destination.mkdir()
    output=destination/'photo.jpg';output.write_bytes(b'confirmed test export')
    results=[{'status':'exported','source':str(folder/'photo.ARW'),
              'destination':str(output),'sha256':jpeg_digest(output)}]
    return state,results,destination


class SessionStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application=QApplication.instance() or QApplication([])

    def test_completed_export_ignores_navigation_but_tracks_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            state,results,destination=example(Path(directory))
            done=finished_export_snapshot(state,results,destination,False)
            self.assertTrue(completion_matches(done))
            browsing=copy.deepcopy(done)
            browsing.update(current=str(Path(state['folder'])/'blank.ARW'),backlight_kelvin=6500,
                            output_folder=str(destination/'another'),version='future')
            browsing['photos']['photo.ARW']['film_stock']='Legacy label'
            self.assertTrue(completion_matches(browsing))
            for field,value in [('exposure',.2),('crop',[.1,.1,.9,.9]),('rotation',1),
                                ('color_mode','Black & white'),('included',False),('neutral_gains',[1.1,1,1])]:
                edited=copy.deepcopy(done);edited['photos']['photo.ARW'][field]=value
                self.assertFalse(completion_matches(edited),field)
            edited=copy.deepcopy(done);edited['quality']=100
            self.assertFalse(completion_matches(edited))

    def test_partial_failed_cancelled_or_unverified_exports_remain_unfinished(self):
        with tempfile.TemporaryDirectory() as directory:
            state,results,destination=example(Path(directory))
            for attempt,cancelled in [([],False),(results,True),
                ([dict(results[0],status='error')],False),
                ([dict(results[0],status='skipped',verified=False)],False)]:
                done=finished_export_snapshot(state,attempt,destination,cancelled)
                self.assertFalse(completion_matches(done))
            state['photos']['another.ARW']=vars(Adjustments())
            self.assertFalse(completion_matches(finished_export_snapshot(state,results,destination,False)))

    def test_skipped_files_require_current_recipe_and_matching_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            state,results,destination=example(Path(directory))
            done=finished_export_snapshot(state,results,destination,False)
            output=destination/'photo.jpg'
            self.assertTrue(verified_existing_export(done,destination,output))
            skips=[dict(results[0],status='skipped',verified=True)]
            self.assertTrue(completion_matches(finished_export_snapshot(done,skips,destination,False)))
            changed=copy.deepcopy(done);changed['photos']['photo.ARW']['warmth']=.2
            self.assertFalse(verified_existing_export(changed,destination,output))
            self.assertFalse(verified_existing_export(done,destination/'other',output))
            output.write_bytes(b'externally changed JPEG')
            self.assertFalse(verified_existing_export(done,destination,output))

    def test_completed_startup_does_not_touch_scan_folder_or_overwrite_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=root/'data';data.mkdir()
            state,results,destination=example(root)
            done=finished_export_snapshot(state,results,destination,False)
            recovery=data/'last-session.filmdesk';atomic_json(recovery,done);before=recovery.read_bytes()
            original_is_dir=Path.is_dir
            def protect_scan_folder(path):
                if path==Path(state['folder']):
                    raise AssertionError('Finished startup must not touch the scan folder')
                return original_is_dir(path)
            with patch.dict(os.environ,{'FILMDESK_DATA_DIR':str(data)}),patch.object(Path,'is_dir',protect_scan_folder):
                window=FilmDesk();window.show()
                limit=time.monotonic()+3
                while window.startup_timer.isActive():
                    self.application.processEvents();time.sleep(.005)
                    self.assertLess(time.monotonic(),limit)
                self.assertIsNone(window.folder)
                self.assertEqual(window.paths,[])
                self.assertFalse(window.recovery_button.isHidden())
                self.assertEqual(window.recovery_button.text(),'Reopen last roll')
                self.assertEqual(window.photo_title.text(),'Ready for a new roll')
                window.close();self.application.processEvents()
            self.assertEqual(recovery.read_bytes(),before)

    def test_unfinished_startup_resumes_and_explicit_open_always_opens(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=root/'data';data.mkdir()
            state,results,destination=example(root)
            done=finished_export_snapshot(state,results,destination,False)
            unfinished=copy.deepcopy(done);unfinished['photos']['photo.ARW']['contrast']=1.1
            recovery=data/'last-session.filmdesk';atomic_json(recovery,unfinished)
            with patch.dict(os.environ,{'FILMDESK_DATA_DIR':str(data)}),patch.object(Path,'is_dir',return_value=True),patch.object(FilmDesk,'load_session') as load:
                for explicit in [False,True]:
                    if explicit:atomic_json(recovery,done)
                    window=FilmDesk(session=str(recovery) if explicit else None)
                    limit=time.monotonic()+3
                    while window.startup_timer.isActive():
                        self.application.processEvents();time.sleep(.005)
                        self.assertLess(time.monotonic(),limit)
                    load.assert_called_with(recovery)
                    window.close();self.application.processEvents();load.reset_mock()


if __name__=='__main__':unittest.main()
