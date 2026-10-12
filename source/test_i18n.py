"""Language switching changes presentation without changing a conversion."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy,json,re,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication,QPushButton,QDialogButtonBox,QTextBrowser,QDialog
from PySide6.QtCore import QTimer
from app import FilmDesk
from engine import Frame,Adjustments,atomic_json,render
from session_state import conversion_signature
from i18n import tr,set_language,_catalog

class LanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.application=QApplication.instance() or QApplication([])

    def drain(self,w):
        end=time.monotonic()+10
        while w.jobs or w.preview_timer.isActive() or w.thumbnail_timer.isActive():
            self.application.processEvents();time.sleep(.005)
            self.assertLess(time.monotonic(),end)

    def test_switch_preserves_edits_pixels_names_and_completion_signature(self):
        ramp=np.linspace(.06,.94,240,dtype=np.float32)[None,:,None]
        pixels=np.repeat(np.array([.6,.4,.2])*np.exp(-ramp*np.array([1.2,1.6,2.4])),160,axis=0).astype(np.float32)
        frame=Frame(pixels,{'sensor_clip_percent':0,'camera_to_srgb':np.eye(3).tolist()})
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'Color';root.mkdir();(root/'Color.ARW').touch()
            data=Path(directory)/'data';data.mkdir()
            tuning=Adjustments(exposure=.2,warmth=.17,crop=[.1,.1,.9,.9],neutral_gains=[1.2,.95,.82])
            atomic_json(data/'stock-presets.json',{'Color':{'warmth':.2}})
            session={'app':'Film Desk','version':'1.4.0','folder':str(root),'photos':{'Color.ARW':vars(tuning)},'current':str(root/'Color.ARW'),'pending_crops':[]}
            path=Path(directory)/'session.filmdesk';atomic_json(path,session)
            with patch.dict(os.environ,{'FILMDESK_DATA_DIR':str(data),'FILMDESK_LANGUAGE':'en'}),patch('app.decode_raw',return_value=frame):
                w=FilmDesk();w.startup_timer.stop();w.show_error=lambda message: self.fail(message);w.load_session(path);self.drain(w)
                before=copy.deepcopy(w.snapshot());positive=w.last_pixels.copy();dirty=w.dirty;undo=copy.deepcopy(w.undo_stack)
                w.change_language('zh_CN');self.application.processEvents()
                self.assertEqual(w.output_mode_combo.currentText(),'彩色')
                self.assertEqual(w.output_mode_combo.currentData(),'Color')
                self.assertEqual(w.folder_label.text(),'Color');self.assertIn('Color',w.presets)
                self.assertEqual(w.snapshot(),before);self.assertEqual(w.dirty,dirty);self.assertEqual(w.undo_stack,undo)
                self.assertEqual(conversion_signature(w.snapshot()),conversion_signature(before))
                np.testing.assert_array_equal(w.last_pixels,positive)
                w.output_mode_combo.setCurrentIndex(w.output_mode_combo.findData('Black & white'));self.drain(w)
                self.assertEqual(w.output_mode_combo.currentText(),'黑白')
                self.assertEqual(w.adjustments[w.current].color_mode,'Black & white')
                self.assertTrue(np.all(w.last_pixels[:,:,0]==w.last_pixels[:,:,1]))
                w.undo();self.drain(w);w.change_language('en')
                self.assertEqual(w.snapshot()['photos'],before['photos'])
                np.testing.assert_array_equal(w.last_pixels,positive)
                w.change_language('zh_CN');w.close();self.application.processEvents()
            env={k:v for k,v in os.environ.items() if k!='FILMDESK_LANGUAGE'};env['FILMDESK_DATA_DIR']=str(data)
            with patch.dict(os.environ,env,clear=True):
                reopened=FilmDesk();reopened.startup_timer.stop()
                self.assertEqual(reopened.language,'zh_CN');self.assertEqual(reopened.output_mode_combo.itemText(0),'彩色')
                reopened.close()
        set_language('en')

    def test_translations_keep_parameters_and_standard_buttons(self):
        for source,target in _catalog.items():
            self.assertEqual(sorted(re.findall(r'\{[^}]+\}',source)),sorted(re.findall(r'\{[^}]+\}',target)),source)
        set_language('zh_CN')
        self.assertEqual(tr('{p0} / {p1} · {p2} · {p3}',p0=1,p1=3,p2='Color.ARW',p3='exported'),'1／3 · Color.ARW · 已导出')
        box=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.assertIn('关闭',box.button(QDialogButtonBox.StandardButton.Close).text())
        set_language('en')

    def test_offline_guides_in_selected_language(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'FILMDESK_DATA_DIR':directory,'FILMDESK_LANGUAGE':'zh_CN'}):
            w=FilmDesk();w.startup_timer.stop();seen=[]
            def capture(dialog):
                browser=dialog.findChild(QTextBrowser);seen.append(browser.toPlainText())
                return 0
            with patch.object(QDialog,'exec',capture):
                w.show_scanning_guide();w.show_camera_support()
            self.assertIn('5500',seen[0]);self.assertIn('白平衡',seen[0]);self.assertIn('Sony A7 IV',seen[1]);self.assertIn('扩展名',seen[1])
            w.close()
        set_language('en')

if __name__=='__main__':unittest.main()
