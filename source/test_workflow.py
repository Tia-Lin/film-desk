"""Optional offscreen controller test with real camera scans.

FILMDESK_TEST_RAW=/path/to/scans QT_QPA_PLATFORM=offscreen python -m unittest test_workflow
The source folder is read only. Exports and recovery use temporary directories.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox
from PySide6.QtCore import Qt
from app import FilmDesk, STYLE
from session_state import completion_matches


@unittest.skipUnless(os.environ.get("FILMDESK_TEST_RAW"),"Set FILMDESK_TEST_RAW to run the real-RAW workflow")
class WorkflowTest(unittest.TestCase):
    def test_reference_presets_session_and_full_export(self):
        app=QApplication.instance() or QApplication([])
        app.setApplicationName("Film Desk tests");app.setStyleSheet(STYLE)
        folder=Path(os.environ["FILMDESK_TEST_RAW"]).resolve()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.dict(os.environ,{"FILMDESK_DATA_DIR":str(root/"data")}):
                window=FilmDesk()
                errors=[]
                window.show_error=errors.append
                def drain():
                    end=time.monotonic()+45
                    while window.jobs or window.preview_timer.isActive() or window.thumbnail_timer.isActive():
                        app.processEvents();time.sleep(.01)
                        self.assertLess(time.monotonic(),end,"Background job timed out")
                    app.processEvents()
                    self.assertEqual(errors,[])
                window.load_folder(folder);drain()
                self.assertEqual(len(window.paths),34)
                self.assertTrue(all(a.mirror for a in window.adjustments.values()))
                self.assertTrue(window.mirror_button.isChecked())
                self.assertTrue(all(not window.list.item(i).icon().isNull() for i in range(34)))
                self.assertTrue(window.advanced_panel.isHidden())
                window.use_current_reference();drain()
                self.assertIsNotNone(window.reference)
                self.assertFalse(window.adjustments[window.reference_path].included)
                original_reference=window.snapshot()['reference']
                window.list.item(0).setCheckState(Qt.CheckState.Checked)
                self.assertEqual(window.list.item(0).checkState(),Qt.CheckState.Unchecked)
                window.list.setCurrentRow(17);drain()
                positive=window.last_pixels.copy()
                self.assertIsNotNone(window.last_model)
                self.assertGreater(positive.shape[1],800)
                window.output_mode_combo.setCurrentText("Black & white");drain()
                self.assertEqual(window.adjustments[window.current].color_mode,"Black & white")
                self.assertTrue(all(a.color_mode=='Black & white' for k,a in window.adjustments.items() if k!=window.reference_path))
                self.assertFalse(window.mode_combo.isEnabled())
                self.assertFalse(window.match_roll_button.isEnabled())
                self.assertEqual(window.reference,original_reference)
                self.assertFalse(window.sliders['saturation'].isEnabled())
                self.assertFalse(window.neutral_button.isEnabled())
                np.testing.assert_array_equal(window.last_pixels[...,0],window.last_pixels[...,1])
                np.testing.assert_array_equal(window.last_pixels[...,1],window.last_pixels[...,2])
                window.undo();drain()
                self.assertEqual(window.adjustments[window.current].color_mode,"Auto color")
                np.testing.assert_array_equal(window.last_pixels,positive)
                window.sliders["warmth"].set_value(.15);window.sliders_changed();drain()
                with patch("app.QInputDialog.getText",return_value=("Warm portraits",True)):
                    window.save_preset()
                self.assertEqual(json.loads(window.presets_path.read_text())["Warm portraits"]["warmth"],.15)
                window.reset_current();drain()
                with patch("app.QInputDialog.getItem",return_value=("Warm portraits",True)):
                    window.load_preset()
                drain()
                self.assertEqual(window.adjustments[window.current].warmth,.15)
                window.output_mode_combo.setCurrentText('Black & white');drain()
                window.output_mode_combo.setCurrentText('Color');drain()
                self.assertEqual(window.adjustments[window.current].color_mode,'Auto color')
                self.assertEqual(window.reference,original_reference)
                self.assertEqual(window.adjustments[window.current].warmth,.15)
                current=window.current
                window.apply_look();drain()
                self.assertTrue(all(a.warmth==.15 for k,a in window.adjustments.items() if k!=window.reference_path))
                session=root/"test.filmdesk"
                window.session_path=session;window.save_session()
                saved=window.snapshot()
                window.load_session(session);drain()
                self.assertEqual(window.current,current)
                self.assertEqual(window.snapshot()["photos"],saved["photos"])
                self.assertEqual(window.backlight_kelvin,5500)
                window.write_recovery()
                self.assertTrue((root/"data/last-session.filmdesk").exists())
                window.flat_field_checkbox.setChecked(True);drain()
                self.assertTrue(window.reference['flat_field_enabled'])
                self.assertTrue(window.last_model['flat_field_applied'])
                selected={"DSC02027.ARW","DSC02036.ARW"}
                for k,a in window.adjustments.items():
                    a.included=Path(k).name in selected
                window.sync_checks()
                destination=root/"JPEG"
                def accept_export(dialog):
                    dialog.findChild(QLineEdit).setText(str(destination))
                    return QDialog.DialogCode.Accepted
                summaries=[]
                def accept_summary(message):
                    summaries.append(message.text())
                    return QMessageBox.StandardButton.Ok
                with patch.object(QDialog,"exec",accept_export),patch.object(QMessageBox,"exec",accept_summary):
                    window.start_export();drain()
                    self.assertTrue(completion_matches(window.snapshot()))
                    self.assertEqual({p.name for p in destination.glob("*.jpg")},{"DSC02027.jpg","DSC02036.jpg"})
                    for p in destination.glob("*.jpg"):
                        with Image.open(p) as image:
                            self.assertGreater(image.width*image.height,10_000_000)
                            self.assertIn("icc_profile",image.info)
                    report=json.loads(next(destination.glob('*.json')).read_text())
                    self.assertTrue(all(r['flat_field_applied'] for r in report['results']))
                    window.start_export();drain()
                    self.assertTrue(completion_matches(window.snapshot()),'Verified skips must preserve completion')
                self.assertIn("2 JPEGs exported",summaries[0])
                self.assertIn("2 existing files skipped",summaries[1])
                self.assertEqual(len(list(destination.glob("*.json"))),2)
                self.assertEqual(len(list(destination.glob("*.filmdesk"))),2)
                self.assertFalse((destination/"DSC02010.jpg").exists())
                reopened=FilmDesk()
                self.assertIn("Warm portraits",reopened.presets)
                limit=time.monotonic()+3
                while reopened.startup_timer.isActive():
                    app.processEvents();time.sleep(.01)
                    self.assertLess(time.monotonic(),limit)
                self.assertIsNone(reopened.folder,'Completed export should start with a clean window')
                self.assertEqual(reopened.recovery_button.text(),'Reopen last roll')
                window.close();reopened.close()
                app.processEvents()


if __name__=="__main__":
    unittest.main()
