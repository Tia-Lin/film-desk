"""UI regression checks for simpler controls and older session compatibility."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QPointF, QEvent, Qt
from PySide6.QtGui import QMouseEvent
from app import FilmDesk, PhotoCanvas
from engine import Frame, Adjustments, atomic_json, render


class PolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application=QApplication.instance() or QApplication([])

    def test_picker_overlay_tracks_sample_and_clips_at_image_edge(self):
        canvas=PhotoCanvas();canvas.resize(900,650);canvas.show()
        image=np.full((720,1000,3),128,dtype=np.uint8)
        canvas.set_image(image);canvas.set_mode('neutral')
        self.application.processEvents()
        samples=[];canvas.neutral_clicked.connect(samples.append)
        def move(point):
            position=QPointF(canvas.rect.left()+point[0]*canvas.rect.width(),
                             canvas.rect.top()+point[1]*canvas.rect.height())
            event=QMouseEvent(QEvent.Type.MouseMove,position,position,
                             Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
            self.application.sendEvent(canvas,event);self.application.processEvents()
        move([.5,.5])
        box=canvas.neutral_sample_rect()
        self.assertAlmostEqual(box.width()/canvas.rect.width()*1000,13)
        self.assertAlmostEqual(box.height()/canvas.rect.height()*720,13)
        self.assertEqual(samples,[], 'Hovering must not apply a color correction')
        canvas.zoom=2;canvas.update();self.application.processEvents()
        self.assertAlmostEqual(canvas.neutral_sample_rect().width(),box.width()*2)
        canvas.fit();self.application.processEvents();move([0,0])
        edge=canvas.neutral_sample_rect()
        self.assertAlmostEqual(edge.left(),canvas.rect.left())
        self.assertAlmostEqual(edge.top(),canvas.rect.top())
        self.assertAlmostEqual(edge.width()/canvas.rect.width()*1000,7)
        self.application.sendEvent(canvas,QEvent(QEvent.Type.Leave))
        self.assertTrue(canvas.neutral_sample_rect().isEmpty())
        canvas.set_mode('view');self.assertIsNone(canvas.sample_point)
        canvas.close()

    def test_slow_folder_discovery_keeps_window_responsive(self):
        entered=threading.Event();release=threading.Event();threads=[]
        original=Path.iterdir
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=root/'data';data.mkdir()
            (root/'scan.ARW').touch()
            def slow_folder(path):
                threads.append(threading.get_ident());entered.set()
                if not release.wait(5):
                    raise TimeoutError('Test did not release folder discovery')
                return original(path)
            with patch.dict(os.environ,{'FILMDESK_DATA_DIR':str(data)}):
                w=FilmDesk();w.show();errors=[];w.show_error=errors.append
                try:
                    with patch.object(Path,'iterdir',slow_folder):
                        w.load_folder(root)
                        self.assertTrue(entered.wait(2))
                        self.assertNotEqual(threads[0],threading.get_ident())
                        alive=[];QTimer.singleShot(0,lambda:alive.append(True))
                        self.application.processEvents()
                        self.assertEqual(alive,[True])
                        self.assertTrue(w.job_running)
                        self.assertTrue(w.cancel_button.isEnabled())
                        w.cancel_export=True
                        release.set()
                        limit=time.monotonic()+5
                        while w.jobs:
                            self.application.processEvents();time.sleep(.005)
                            self.assertLess(time.monotonic(),limit)
                        self.assertEqual(w.paths,[])
                        self.assertEqual(errors,[])
                finally:
                    release.set();w.close();self.application.processEvents()

    def test_simple_controls_keep_legacy_edits_and_support_undo(self):
        ramp=np.linspace(.06,.94,240,dtype=np.float32)[None,:,None]
        pixels=np.repeat(np.array([.6,.4,.2])*np.exp(-ramp*np.array([1.2,1.6,2.4])),160,axis=0).astype(np.float32)
        frame=Frame(pixels,{'sensor_clip_percent':0,'camera_to_srgb':np.eye(3).tolist()})
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=root/'data';data.mkdir()
            atomic_json(data/'stock-presets.json',{'Fuji Pro 400H':{'warmth':.2},'My indie 200':{'warmth':.1}})
            for name in ['blank.ARW','photo.ARW']:(root/name).touch()
            old=Adjustments(film_stock='Fuji Pro 400H',crop=[.1,.1,.9,.9],rotation=1,mirror=True,
                exposure=.2,warmth=.17,neutral_gains=[1.2,.95,.82])
            session={'app':'Film Desk','version':'1.0.0','folder':str(root),'current':str(root/'photo.ARW'),
                'reference_path':None,'reference':None,'pending_crops':[],
                'photos':{'blank.ARW':vars(Adjustments()),'photo.ARW':copy.deepcopy(vars(old))}}
            path=root/'legacy.filmdesk';atomic_json(path,session)
            with patch.dict(os.environ,{'FILMDESK_DATA_DIR':str(data)}),patch('app.decode_raw',return_value=frame):
                w=FilmDesk();w.show();errors=[];w.show_error=errors.append
                def drain():
                    limit=time.monotonic()+10
                    while w.jobs or w.preview_timer.isActive() or w.thumbnail_timer.isActive():
                        self.application.processEvents();time.sleep(.005)
                        self.assertLess(time.monotonic(),limit)
                    self.application.processEvents();self.assertEqual(errors,[])
                w.load_session(path);drain()
                self.assertEqual(w.snapshot()['photos']['photo.ARW'],vars(old))
                expected,_=render(frame,old)
                np.testing.assert_array_equal(w.last_pixels,expected)
                self.assertFalse(hasattr(w,'stock_combo'))
                self.assertFalse(hasattr(w,'light_temperature'))
                self.assertEqual([w.output_mode_combo.itemText(i) for i in range(w.output_mode_combo.count())],['Color','Black & white'])
                self.assertEqual(w.output_mode_combo.currentText(),'Color')
                self.assertIn('Fuji Pro 400H',w.presets)
                with patch('app.QInputDialog.getItem',return_value=('Fuji Pro 400H',True)):
                    w.load_preset()
                drain()
                self.assertEqual(w.adjustments[w.current].warmth,.2)
                self.assertEqual(w.adjustments[w.current].crop,old.crop)
                self.assertEqual(w.adjustments[w.current].neutral_gains,old.neutral_gains)
                w.undo();drain()
                self.assertEqual(w.snapshot()['photos']['photo.ARW'],vars(old))
                w.mode_combo.setCurrentIndex(w.mode_combo.findData('Roll color'));drain()
                self.assertEqual(w.adjustments[w.current].color_mode,'Auto color')
                w.set_roll_color();drain()
                self.assertEqual(w.mode_combo.currentData(),'Roll color')
                w.undo();drain()
                self.assertTrue(w.advanced_panel.isHidden())
                self.assertTrue(w.quality.isHidden())
                for name in ['tint','shadows','highlights','curve']:
                    self.assertFalse(w.sliders[name].isVisible())
                for name in ['exposure','contrast','saturation','warmth']:
                    self.assertTrue(w.sliders[name].isVisible())
                w.advanced_toggle.setChecked(True);self.application.processEvents()
                self.assertTrue(w.sliders['shadows'].isVisible())
                w.advanced_toggle.setChecked(False)
                before=copy.deepcopy(w.snapshot()['photos']['photo.ARW'])
                w.sliders['exposure'].slider.setValue(65);drain()
                self.assertEqual(w.adjustments[w.current].exposure,.65)
                w.undo();drain()
                self.assertEqual(w.snapshot()['photos']['photo.ARW'],before)
                w.reset_current();drain()
                reset=w.adjustments[w.current]
                self.assertEqual(reset.film_stock,old.film_stock)
                self.assertEqual(reset.crop,old.crop)
                self.assertEqual((reset.rotation,reset.mirror),(1,True))
                self.assertEqual(reset.neutral_gains,[1,1,1])
                w.crop_button.setChecked(True);w.toggle_crop();drain()
                self.assertEqual(w.crop_button.text(),'Done cropping')
                w.crop_button.setChecked(False);w.toggle_crop();drain()
                self.assertEqual(w.crop_button.text(),'Crop photo')
                w.write_recovery()
                w.load_session(data/'last-session.filmdesk');drain()
                self.assertIsNone(w.session_path,'Recovery should not become the named save destination')
                reopened=FilmDesk();reopened.show()
                limit=time.monotonic()+10
                while reopened.startup_timer.isActive() or reopened.jobs or reopened.thumbnail_timer.isActive():
                    self.application.processEvents();time.sleep(.005)
                    self.assertLess(time.monotonic(),limit)
                self.assertEqual(Path(reopened.current).name,'photo.ARW')
                self.assertTrue(reopened.advanced_panel.isHidden())
                reopened.close()
                w.close();self.application.processEvents()


if __name__=='__main__':unittest.main()
