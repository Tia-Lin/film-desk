"""Spatial calibration must remove known scan errors without changing scene tone."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import json
import tempfile
import time
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QLineEdit
from engine import (Frame, Adjustments, reference_from_frame, validate_reference,
                    flat_field_for_frame, spatial_density_offset, density,
                    analyze, render, neutral_balance, export_jpeg, atomic_json, crop_pixels)
from app import FilmDesk
from session_state import conversion_signature


CROP=[.1,.1,.9,.9]
BASE=np.array([.52,.38,.19],np.float32)


def setup_frames(h=480,w=640,noise=False):
    y,x=np.meshgrid((np.arange(h)+.5)/h*2-1,(np.arange(w)+.5)/w*2-1,indexing='ij')
    light=np.stack([-.35*(x*x+y*y)+.13*x,
                    -.29*(x*x+y*y)-.07*y,
                    -.42*(x*x+y*y)-.11*x+.07*y],axis=-1)
    field=np.exp(light).astype(np.float32)
    # This scene has real vertical tone variation which must be preserved.
    d=(.25+.8*(x+1)/2+.1*np.sin(y*3))[...,None]*np.array([1.2,1.6,2.4])
    blank=BASE*field
    if noise:
        blank=blank*np.random.default_rng(14).normal(1,.012,blank.shape)
        blank[110:118,140:148]*=.02
        blank[210:218,340:348]*=.02
    metadata={'raw_size':[1280,960],'iso':100,'shutter':.1,'aperture':8,
              'sensor_clip_percent':0,'camera_to_srgb':np.eye(3).tolist()}
    return (Frame(blank.astype(np.float32),metadata),
            Frame((BASE*field*np.exp(-d)).astype(np.float32),metadata),
            Frame((BASE*np.exp(-d)).astype(np.float32),metadata))


class FlatFieldTests(unittest.TestCase):
    def test_removes_known_spatial_color_and_brightness_errors(self):
        blank,scan,ideal=setup_frames(noise=True)
        ref=reference_from_frame(blank,CROP)
        self.assertIn('flat_field',ref)
        self.assertFalse(ref['flat_field_enabled'])
        a=Adjustments(crop=CROP)
        legacy_ref={k:v for k,v in ref.items() if not k.startswith('flat_field')}
        before,_=render(scan,a,ref)
        legacy,_=render(scan,a,legacy_ref)
        np.testing.assert_array_equal(before,legacy)
        ref['flat_field_enabled']=True
        field,warning=flat_field_for_frame(scan,CROP,ref)
        self.assertEqual(warning,'')
        corrected=density(crop_pixels(scan.pixels,CROP),scan.metadata,ref,
                          spatial_density_offset(scan,CROP,field))
        expected=density(crop_pixels(ideal.pixels,CROP),ideal.metadata,
                         {'base':BASE.tolist()})
        self.assertLess(float(np.max(np.abs(corrected-expected))),.006)
        target,_=render(ideal,a,{'base':BASE.tolist()})
        after,model=render(scan,a,ref)
        error=lambda p:float(np.mean(np.abs(p.astype(float)-target)))
        self.assertTrue(model['flat_field_applied'])
        self.assertGreater(error(before),5)
        self.assertLess(error(after),.7)
        self.assertLess(error(after),error(before)*.08)

    def test_uniform_field_preserves_tone_and_black_and_white_stays_gray(self):
        blank,scan,ideal=setup_frames()
        blank=Frame(np.broadcast_to(BASE,blank.pixels.shape).copy(),blank.metadata)
        ref=reference_from_frame(blank,CROP);ref['flat_field_enabled']=True
        a=Adjustments(crop=CROP)
        expected,_=render(ideal,a,{'base':BASE.tolist()})
        out,_=render(ideal,a,ref)
        # Floating-point evaluation may move a value exactly on an 8-bit boundary.
        self.assertLessEqual(np.max(np.abs(out.astype(float)-expected)),1)
        self.assertLess(np.mean(np.abs(out.astype(float)-expected)),.0001)
        varying_ref=reference_from_frame(setup_frames()[0],CROP)
        varying_ref['flat_field_enabled']=True
        a.color_mode='Black & white'
        gray,model=render(scan,a,varying_ref)
        self.assertTrue(model['flat_field_applied'])
        np.testing.assert_array_equal(gray[...,0],gray[...,1])
        np.testing.assert_array_equal(gray[...,1],gray[...,2])

    def test_sensor_coordinates_survive_crop_rotation_mirror_and_export_strips(self):
        blank,_,_=setup_frames()
        ref=reference_from_frame(blank,CROP);ref['flat_field_enabled']=True
        _,scan,ideal=setup_frames(960,1280)
        scan=Frame(np.rint(scan.pixels*65535).astype(np.uint16),scan.metadata)
        a=Adjustments(crop=[.16,.13,.84,.86],rotation=1,mirror=True)
        model=analyze(ideal,a,{'base':BASE.tolist()})
        expected,_=render(ideal,a,{'base':BASE.tolist()},model=model)
        actual,out_model=render(scan,a,ref,model=model)
        self.assertTrue(out_model['flat_field_applied'])
        self.assertLess(np.mean(np.abs(actual.astype(float)-expected)),.6)
        # A crop uses the corresponding part of the original map, not a resized map.
        field,_=flat_field_for_frame(scan,a.crop,ref)
        whole=spatial_density_offset(scan,a.crop,field)
        sliced=np.concatenate([spatial_density_offset(scan,a.crop,field,s,s+192)
                               for s in range(0,whole.shape[0],192)])
        np.testing.assert_array_equal(sliced,whole)

    def test_preview_and_full_jpeg_share_calibration_and_exposure_scaling(self):
        blank,scan,_=setup_frames()
        ref=reference_from_frame(blank,CROP);ref['flat_field_enabled']=True
        _,full,_=setup_frames(960,1280)
        full=Frame(np.rint(full.pixels*.5*65535).astype(np.uint16),dict(full.metadata,shutter=.05))
        a=Adjustments(crop=CROP,rotation=1,mirror=True)
        preview,model=render(scan,a,ref)
        with tempfile.TemporaryDirectory() as directory,patch('engine.decode_raw',return_value=full):
            path=Path(directory)/'original-name.jpg'
            result=export_jpeg('original-name.ARW',path,a,ref,model)
            self.assertTrue(result['flat_field_applied'])
            self.assertEqual(result['flat_field_warning'],'')
            with Image.open(path) as image:
                self.assertIn('icc_profile',image.info)
                small=np.asarray(image.resize((preview.shape[1],preview.shape[0]),Image.Resampling.BOX))
                self.assertLess(np.mean(np.abs(small.astype(float)-preview)),1.5)
        gains=neutral_balance(scan,a,ref,model,[.5,.5])
        self.assertTrue(np.all(np.isfinite(gains)))

    def test_rejects_clipped_blocked_and_too_small_references(self):
        blank,_,_=setup_frames()
        cases=[]
        clipped=blank.pixels.copy();clipped[60:180,70:230,0]=1
        cases.append((Frame(clipped,blank.metadata),'clipped'))
        blocked=blank.pixels.copy();blocked[60:180,70:230]=0
        cases.append((Frame(blocked,blank.metadata),'dark or blocked'))
        cases.append((Frame(blank.pixels[:50,:50],blank.metadata),'too small'))
        for frame,message in cases:
            ref=reference_from_frame(frame,CROP)
            self.assertNotIn('flat_field',ref)
            self.assertIn(message,ref['flat_field_error'])
            self.assertFalse(ref['flat_field_enabled'])

    def test_incompatible_photos_fall_back_with_explicit_warning(self):
        blank,scan,_=setup_frames()
        ref=reference_from_frame(blank,CROP);ref['flat_field_enabled']=True
        for crop,metadata,reason in [
                ([0,0,1,1],scan.metadata,'area covered'),
                (CROP,dict(scan.metadata,aperture=11),'aperture'),
                (CROP,dict(scan.metadata,raw_size=[3000,2000]),'dimensions')]:
            frame=Frame(scan.pixels,metadata);a=Adjustments(crop=crop)
            out,model=render(frame,a,ref)
            self.assertFalse(model['flat_field_applied'])
            self.assertIn(reason,model['flat_field_warning'])
            off=copy.deepcopy(ref);off['flat_field_enabled']=False
            expected,_=render(frame,a,off)
            np.testing.assert_array_equal(out,expected)

    def test_saved_map_is_portable_and_validated(self):
        blank,scan,_=setup_frames()
        ref=reference_from_frame(blank,CROP);ref['flat_field_enabled']=True
        saved=json.loads(json.dumps(ref,allow_nan=False));validate_reference(saved)
        a=Adjustments(crop=CROP)
        np.testing.assert_array_equal(render(scan,a,ref)[0],render(scan,a,saved)[0])
        for change in ['nan','shape','crop','enabled','missing']:
            invalid=copy.deepcopy(saved)
            if change=='nan':invalid['flat_field']['coefficients'][0][0]=float('nan')
            if change=='shape':invalid['flat_field']['coefficients']=[[1,2,3]]
            if change=='crop':invalid['flat_field']['crop']=[.8,.8,.2,.2]
            if change=='enabled':invalid['flat_field_enabled']='false'
            if change=='missing':invalid.pop('flat_field')
            with self.assertRaises(ValueError,msg=change):validate_reference(invalid)


class FlatFieldUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.application=QApplication.instance() or QApplication([])

    def drain(self,w):
        limit=time.monotonic()+20
        while w.jobs or w.preview_timer.isActive() or w.thumbnail_timer.isActive():
            self.application.processEvents();time.sleep(.005)
            self.assertLess(time.monotonic(),limit)
        self.application.processEvents()

    def test_toggle_undo_language_saved_session_and_legacy_upgrade(self):
        blank,scan,_=setup_frames(240,320)
        def decode(path,*args,**kwargs):return blank if Path(path).stem=='blank' else scan
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=root/'data';data.mkdir();folder=root/'scans';folder.mkdir()
            for name in ['blank.ARW','photo.ARW']:(folder/name).touch()
            legacy_ref=reference_from_frame(blank,CROP)
            legacy_ref={k:v for k,v in legacy_ref.items() if not k.startswith('flat_field')}
            session={'app':'Film Desk','version':'1.4.0','folder':str(folder),
                     'reference':legacy_ref,'reference_path':str(folder/'blank.ARW'),
                     'current':str(folder/'photo.ARW'),'pending_crops':[],
                     'photos':{'blank.ARW':asdict(Adjustments(crop=CROP,included=False)),
                               'photo.ARW':asdict(Adjustments(crop=CROP))}}
            atomic_json(root/'legacy.filmdesk',session)
            with patch.dict(os.environ,{'FILMDESK_DATA_DIR':str(data),'FILMDESK_LANGUAGE':'en'}),patch('app.decode_raw',side_effect=decode):
                w=FilmDesk();w.startup_timer.stop();w.show_error=lambda e:self.fail(e)
                w.load_session(root/'legacy.filmdesk');self.drain(w)
                self.assertFalse(w.flat_field_checkbox.isChecked())
                before=w.snapshot();positive=w.last_pixels.copy()
                self.assertEqual(w.reference,legacy_ref)
                w.flat_field_checkbox.setChecked(True);self.drain(w)
                self.assertTrue(w.flat_field_checkbox.isChecked())
                self.assertTrue(w.last_model['flat_field_applied'])
                self.assertFalse(np.array_equal(w.last_pixels,positive))
                self.assertNotEqual(conversion_signature(w.snapshot()),conversion_signature(before))
                enabled=copy.deepcopy(w.snapshot());pixels=w.last_pixels.copy()
                w.change_language('zh_CN')
                self.assertEqual(w.flat_field_checkbox.text(),'校正照明不均')
                self.assertTrue(w.flat_field_checkbox.isChecked())
                self.assertEqual(w.snapshot(),enabled)
                atomic_json(root/'enabled.filmdesk',enabled)
                w.undo();self.drain(w)
                self.assertFalse(w.flat_field_checkbox.isChecked())
                np.testing.assert_array_equal(w.last_pixels,positive)
                w.redo();self.drain(w)
                np.testing.assert_array_equal(w.last_pixels,pixels)
                w.load_session(root/'enabled.filmdesk');self.drain(w)
                self.assertTrue(w.flat_field_checkbox.isChecked())
                np.testing.assert_array_equal(w.last_pixels,pixels)
                w.clear_reference();self.drain(w)
                self.assertFalse(w.flat_field_checkbox.isChecked())
                self.assertTrue(w.flat_field_checkbox.isHidden())
                w.change_language('en');w.close();self.application.processEvents()

    def test_export_summary_reports_photos_outside_calibration(self):
        blank,scan,_=setup_frames(240,320)
        ref=reference_from_frame(blank,CROP);ref['flat_field_enabled']=True
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=root/'data';data.mkdir();folder=root/'scans';folder.mkdir()
            (folder/'photo.ARW').touch()
            session={'app':'Film Desk','folder':str(folder),'reference':ref,
                     'reference_path':str(folder/'blank.ARW'),'current':str(folder/'photo.ARW'),
                     'photos':{'photo.ARW':asdict(Adjustments())},'pending_crops':[]}
            atomic_json(root/'session.filmdesk',session)
            with patch.dict(os.environ,{'FILMDESK_DATA_DIR':str(data),'FILMDESK_LANGUAGE':'en'}),patch('app.decode_raw',return_value=scan),patch('engine.decode_raw',return_value=scan):
                w=FilmDesk();w.startup_timer.stop();w.show_error=lambda e:self.fail(e)
                w.load_session(root/'session.filmdesk');self.drain(w)
                self.assertIn('area covered',w.warning_label.text())
                destination=root/'JPEG';summaries=[]
                def accept(dialog):
                    dialog.findChild(QLineEdit).setText(str(destination))
                    return QDialog.DialogCode.Accepted
                def summary(message):
                    summaries.append(message.text());return QMessageBox.StandardButton.Ok
                with patch.object(QDialog,'exec',accept),patch.object(QMessageBox,'exec',summary):
                    w.start_export();self.drain(w)
                self.assertIn('not applied to 1 exported photos',summaries[0])
                report=json.loads(next(destination.glob('*.json')).read_text())
                self.assertFalse(report['results'][0]['flat_field_applied'])
                self.assertIn('area covered',report['results'][0]['flat_field_warning'])
                self.assertTrue((destination/'photo.jpg').is_file())
                w.close();self.application.processEvents()


if __name__=='__main__':unittest.main()
