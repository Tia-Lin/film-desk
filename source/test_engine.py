"""Regression checks for data safety and meaningful conversion behavior."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image, ImageCms
from engine import *


def synthetic_frame(h=120,w=180):
    # Known film-relative density ramp with independent dye sensitivities.
    level=np.linspace(.05,.95,w,dtype=np.float32)[None,:,None]
    base=np.array([.65,.42,.18],dtype=np.float32)
    density=level*np.array([1.2,1.6,2.4],dtype=np.float32)
    pixels=np.repeat(base*np.exp(-density),h,axis=0)
    return Frame(pixels,{"iso":100,"shutter":.1,"aperture":8}),{"base":base.tolist(),"metadata":{"iso":100,"shutter":.1,"aperture":8}}


class EngineTests(unittest.TestCase):
    def test_density_inversion_is_monotonic_and_neutral(self):
        frame,ref=synthetic_frame()
        out,model=render(frame,Adjustments(mirror=False),ref)
        self.assertTrue(np.all(np.diff(out[60,:,0].astype(int))>=0))
        self.assertLessEqual(int(np.max(np.ptp(out.astype(int),axis=2))),1)
        self.assertLess(out[0,0,0],15)
        self.assertGreater(out[0,-1,0],245)

    def test_exposure_metadata_normalizes_scan_variants(self):
        frame,ref=synthetic_frame()
        alternate=Frame(frame.pixels*.5,{"iso":100,"shutter":.05,"aperture":8})
        a=density(frame.pixels,frame.metadata,ref)
        b=density(alternate.pixels,alternate.metadata,ref)
        np.testing.assert_allclose(a,b,atol=1e-6)

    def test_thin_holder_edge_does_not_set_color_response(self):
        frame,ref=synthetic_frame(240,360)
        model=analyze(frame,Adjustments(),ref)
        dirty=Frame(frame.pixels.copy(),frame.metadata)
        dirty.pixels[:5]=[.0001,.0002,.001]
        dirty.pixels[-5:]=[.0001,.0002,.001]
        dirty.pixels[:,:5]=[.0001,.0002,.001]
        dirty.pixels[:,-5:]=[.0001,.0002,.001]
        cleaned=analyze(dirty,Adjustments(),ref)
        np.testing.assert_allclose(cleaned['low'],model['low'],atol=1e-6)
        np.testing.assert_allclose(cleaned['high'],model['high'],atol=1e-6)

    def test_orientation_matches_crop_and_mirror(self):
        frame,ref=synthetic_frame()
        a=Adjustments(crop=[.1,.2,.9,.8],mirror=False)
        base,model=render(frame,a,ref)
        a.rotation=1;a.mirror=True
        oriented,_=render(frame,a,ref,model=model)
        np.testing.assert_array_equal(oriented,np.rot90(base[:,::-1],-1))

    def test_new_scans_flip_but_saved_orientation_is_preserved(self):
        frame,ref=synthetic_frame()
        unflipped,_=render(frame,Adjustments(mirror=False),ref)
        flipped,_=render(frame,Adjustments(),ref)
        np.testing.assert_array_equal(flipped,unflipped[:,::-1])
        for saved,expected in [({},False),({'mirror':False},False),({'mirror':True},True)]:
            restored=Adjustments.from_dict(saved)
            self.assertEqual(restored.mirror,expected)
            actual,_=render(frame,restored,ref)
            np.testing.assert_array_equal(actual,flipped if expected else unflipped)

    def test_black_and_white_keeps_channels_equal(self):
        frame,ref=synthetic_frame()
        frame.pixels[...,0]*=.7
        a=Adjustments(color_mode="Black & white",warmth=.9,tint=.8)
        out,_=render(frame,a,ref)
        np.testing.assert_array_equal(out[...,0],out[...,1])
        np.testing.assert_array_equal(out[...,1],out[...,2])

    def test_srgb_transfer_function(self):
        out=encode_srgb(np.array([0.,.0031308,.18,1.,2.]))
        np.testing.assert_allclose(out,[0,.04044994,.46135613,1,1],atol=1e-6)

    def test_invalid_session_controls_rejected(self):
        for settings in [{"crop":[1,1,0,0]},{"exposure":float("nan")},{"neutral_gains":[1,-1,1]}]:
            with self.assertRaises(ValueError):
                Adjustments.from_dict(settings)

    def test_holder_crop_excludes_dark_surround(self):
        a=np.zeros((180,240,3),np.float32)
        a[35:150,45:205]=[.6,.4,.2]
        crop=auto_crop(Frame(a,{}))
        self.assertGreater(crop[0],.17)
        self.assertLess(crop[2],.87)
        self.assertGreater(crop[1],.17)
        self.assertLess(crop[3],.87)

    def test_reference_uses_uniform_clear_film(self):
        a=np.zeros((180,240,3),np.float32)
        a[35:150,45:205]=[.6,.4,.2]
        a[80,120]=[0,0,0]  # Dust must not change the reference.
        ref=reference_from_frame(Frame(a,{}))
        np.testing.assert_allclose(ref["base"],[.6,.4,.2],atol=1e-6)

    def test_full_export_has_srgb_and_wont_overwrite(self):
        frame,ref=synthetic_frame()
        full=Frame(np.rint(frame.pixels*65535).astype(np.uint16),frame.metadata)
        a=Adjustments();model=analyze(frame,a,ref)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"DSC12345.jpg"
            with patch("engine.decode_raw",return_value=full) as decode:
                result=export_jpeg("DSC12345.ARW",path,a,ref,model)
                self.assertEqual(result["status"],"exported")
                decode.assert_called_once_with("DSC12345.ARW",preview=False)
            before=path.read_bytes()
            with Image.open(path) as image:
                self.assertEqual(image.size,(180,120))
                profile=ImageCms.ImageCmsProfile(io.BytesIO(image.info["icc_profile"]))
                self.assertIn("sRGB",ImageCms.getProfileDescription(profile))
            with patch("engine.decode_raw") as decode:
                result=export_jpeg("DSC12345.ARW",path,a,ref,model)
                self.assertEqual(result["status"],"skipped")
                decode.assert_not_called()
            self.assertEqual(before,path.read_bytes())
            self.assertFalse(any(p.name.startswith(".film-desk-") for p in Path(directory).iterdir()))

    def test_neutral_picker_uses_displayed_orientation(self):
        frame,ref=synthetic_frame()
        a=Adjustments(rotation=1,mirror=True)
        model=analyze(frame,a,ref)
        gains=neutral_balance(frame,a,ref,model,[.5,.5])
        np.testing.assert_allclose(gains,[1,1,1],atol=.01)

    def test_atomic_session_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"session.filmdesk"
            atomic_json(p,{"app":"Film Desk","photos":{"scan.ARW":asdict(Adjustments())}})
            loaded=json.loads(p.read_text())
            self.assertEqual(Adjustments.from_dict(loaded["photos"]["scan.ARW"]).crop,[0,0,1,1])


if __name__=="__main__":
    unittest.main()
