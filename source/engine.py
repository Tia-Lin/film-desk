"""Film Desk's independent RAW negative processing engine.

Camera-native linear RGB -> film-relative optical density -> aligned positive
linear light -> sRGB. No camera JPEG, automatic RAW brightness, or photo tone
curve is used. The generic model is a practical starting point, not a measured
film-stock characterization. Preview analysis is reused for full-size export.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
import io
import json
import math
import os
import tempfile
import threading
import numpy as np
import rawpy
from PIL import Image, ImageCms, ImageFilter

VERSION = "1.1.0"
RAW_EXTENSIONS = {".arw", ".dng", ".nef", ".nrw", ".cr2", ".cr3", ".raf", ".orf", ".rw2", ".pef", ".srw", ".raw"}
SRGB_PROFILE = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
_CAMERA_MATRICES = {}
_MATRIX_LOCK = threading.Lock()


@dataclass
class Adjustments:
    film_stock: str = "Kodak Portra 400"
    crop: list[float] = field(default_factory=lambda: [0., 0., 1., 1.])
    rotation: int = 0
    mirror: bool = False
    exposure: float = 0.
    contrast: float = 1.
    saturation: float = 1.
    warmth: float = 0.
    tint: float = 0.
    shadows: float = 0.
    highlights: float = 0.
    curve: float = 2.
    color_mode: str = "Auto color"
    neutral_gains: list[float] = field(default_factory=lambda: [1., 1., 1.])
    included: bool = True

    @classmethod
    def from_dict(cls, data):
        obj = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        obj.crop = clean_crop(obj.crop)
        obj.rotation = int(obj.rotation) % 4
        if obj.color_mode not in {"Auto color", "Roll color", "Black & white"}:
            obj.color_mode = "Auto color"
        for k, limits in {"exposure": (-4, 4), "contrast": (.5, 1.8), "saturation": (0, 2),
                          "warmth": (-1, 1), "tint": (-1, 1), "shadows": (-1, 1),
                          "highlights": (-1, 1), "curve": (.5, 5)}.items():
            v = float(getattr(obj, k))
            if not math.isfinite(v):
                raise ValueError(f"Invalid {k} in session")
            setattr(obj, k, float(np.clip(v, *limits)))
        gains = np.asarray(obj.neutral_gains, dtype=float)
        if gains.shape != (3,) or not np.all(np.isfinite(gains)) or np.any(gains <= 0):
            raise ValueError("Invalid neutral balance in session")
        obj.neutral_gains = np.clip(gains, .1, 10).tolist()
        return obj


@dataclass
class Frame:
    pixels: np.ndarray
    metadata: dict


def clean_crop(crop):
    c = np.asarray(crop, dtype=float)
    if c.shape != (4,) or not np.all(np.isfinite(c)):
        raise ValueError("Invalid crop")
    x0, y0, x1, y1 = np.clip(c, 0, 1)
    if x1 - x0 < .01 or y1 - y0 < .01:
        raise ValueError("Crop must have a width and height of at least 1%")
    return [float(x0), float(y0), float(x1), float(y1)]


def crop_pixels(pixels, crop):
    x0, y0, x1, y1 = clean_crop(crop)
    h, w = pixels.shape[:2]
    return pixels[max(0, round(y0*h)):min(h, round(y1*h)),
                  max(0, round(x0*w)):min(w, round(x1*w))]


def decode_raw(path, preview=True, max_side=1500):
    """Decode with fixed unity WB and gamma 1; retain consistent sensor scaling."""
    path = Path(path)
    with rawpy.imread(str(path)) as raw:
        if raw.num_colors != 3:
            raise ValueError("This version supports RGB camera RAW files")
        scan = raw.raw_image_visible
        step = max(1, int(max(scan.shape[:2]) / 1800))
        clip_percent = float(np.mean(scan[::step, ::step] >= raw.white_level) * 100)
        other = raw.other
        metadata = {
            "source": str(path), "iso": float(other.iso_speed),
            "shutter": float(other.shutter_speed), "aperture": float(other.aperture),
            "sensor_clip_percent": clip_percent,
            "white_level": int(raw.white_level),
        }
        # adjust_maximum_thr=0 prevents per-image maximum rescaling. Unity WB
        # prevents the usual daylight coefficients from silently being applied.
        pixels = raw.postprocess(
            half_size=preview, output_color=rawpy.ColorSpace.raw, output_bps=16,
            gamma=(1, 1), user_wb=[1, 1, 1, 1], use_camera_wb=False,
            use_auto_wb=False, no_auto_bright=True, adjust_maximum_thr=0,
        )
        matrix, verified = camera_matrix(raw, pixels if preview else None)
        metadata["camera_to_srgb"] = matrix
        metadata["camera_matrix_verified"] = verified
        metadata["decoded_size"] = [pixels.shape[1], pixels.shape[0]]
    if preview and max(pixels.shape[:2]) > max_side:
        # PIL RGB resizing would reduce 16-bit RGB to 8 bits. Resize the three
        # float channels independently to keep faint dense-negative information.
        h, w = pixels.shape[:2]
        size = (round(w*max_side/max(h, w)), round(h*max_side/max(h, w)))
        channels = [np.asarray(Image.fromarray(pixels[..., c].astype(np.float32)).resize(
            size, Image.Resampling.BOX), dtype=np.float32) for c in range(3)]
        pixels = np.stack(channels, axis=-1) / 65535.
    elif preview:
        pixels = pixels.astype(np.float32) / 65535.
    return Frame(pixels, metadata)


def camera_matrix(raw, camera_preview=None):
    """Recover LibRaw's linear camera-to-sRGB transform without a tone curve.

    rawpy does not expose LibRaw's calculated rgb_cam matrix for these Sony
    files (color_matrix is zero). Fit paired linear outputs and verify the
    residual. This uses the camera transform, not a film-stock profile. Cache
    only verified results, so a featureless file cannot poison later decodes.
    """
    key = tuple(np.asarray(raw.rgb_xyz_matrix).flatten().tolist())
    with _MATRIX_LOCK:
        if key in _CAMERA_MATRICES:
            return _CAMERA_MATRICES[key], True
        kwargs = dict(half_size=True, output_bps=16, gamma=(1,1), user_wb=[1,1,1,1],
                      use_camera_wb=False, use_auto_wb=False, no_auto_bright=True, adjust_maximum_thr=0)
        if camera_preview is None:
            camera_preview = raw.postprocess(output_color=rawpy.ColorSpace.raw, **kwargs)
        srgb = raw.postprocess(output_color=rawpy.ColorSpace.sRGB, **kwargs)
        stride = max(1, camera_preview.shape[0]*camera_preview.shape[1]//45000)
        a = camera_preview.reshape(-1,3)[::stride].astype(np.float64)/65535.
        b = srgb.reshape(-1,3)[::stride].astype(np.float64)/65535.
        valid = np.all((b>.005)&(b<.95),axis=1)
        if valid.sum() < 100:
            return np.eye(3).tolist(), False
        a,b = a[valid],b[valid]
        matrix,_,rank,_ = np.linalg.lstsq(a,b,rcond=None)
        residual = float(np.mean(np.abs(a@matrix-b)))
        white = matrix.sum(axis=0)
        if rank!=3 or residual>.0003 or np.any(abs(matrix)>5) or np.any(abs(white-1)>.03):
            return np.eye(3).tolist(), False
        # Preserve the film-relative neutral established by channel alignment.
        matrix /= white
        _CAMERA_MATRICES[key] = matrix.tolist()
        return matrix.tolist(), True


def auto_crop(frame):
    """Find a centered film-holder opening; manual crop remains available.

    Median profiles resist isolated sprocket holes. This is deliberately
    conservative: irregular or overlapping scans need a manual rectangle.
    """
    a = frame.pixels
    if a.dtype == np.uint16:
        a = a.astype(np.float32) / 65535.
    signal = np.max(a, axis=2)
    h, w = signal.shape
    row = np.median(signal[:, int(w*.15):int(w*.85)], axis=1)
    col = np.median(signal[int(h*.15):int(h*.85), :], axis=0)

    def extent(profile):
        smooth = np.convolve(profile, np.ones(7)/7, mode="same")
        threshold = max(float(np.percentile(smooth, 90))*.12, 1e-4)
        indices = np.flatnonzero(smooth > threshold)
        if not len(indices):
            return .04, .96
        left, right = int(indices[0]), int(indices[-1])
        # Exclude the soft holder edge from inversion statistics.
        inset = max(2, round((right-left)*.05))
        left, right = left+inset, right-inset
        if right-left < len(profile)*.25:
            return .04, .96
        return left/len(profile), (right+1)/len(profile)

    x0, x1 = extent(col)
    y0, y1 = extent(row)
    return clean_crop([x0, y0, x1, y1])


def reference_from_frame(frame, crop=None):
    crop = crop or auto_crop(frame)
    a = crop_pixels(frame.pixels, crop).astype(np.float32)
    if frame.pixels.dtype == np.uint16:
        a /= 65535.
    # Central uniform region, away from holder edges, dust, and vignetting.
    h, w = a.shape[:2]
    roi = a[int(h*.2):int(h*.8), int(w*.2):int(w*.8)]
    base = np.median(roi, axis=(0, 1))
    if np.any(base < 1e-4):
        raise ValueError("Film reference is too dark. Crop to the clear, unexposed film.")
    spread = np.percentile(roi.reshape(-1, 3), 90, axis=0) / np.maximum(
        np.percentile(roi.reshape(-1, 3), 10, axis=0), 1e-6)
    return {"base": base.tolist(), "metadata": frame.metadata, "crop": crop,
            "uneven": bool(np.max(spread) > 1.35)}


def exposure_scale(metadata, reference):
    """Normalize reference and capture to the same scan exposure, when known."""
    if not reference:
        return 1.
    def amount(m):
        t, iso, aperture = m.get("shutter", 0), m.get("iso", 0), m.get("aperture", 0)
        return t*iso/aperture**2 if min(t, iso, aperture) > 0 else 0
    ref = amount(reference.get("metadata", {}))
    current = amount(metadata)
    return current/ref if ref > 0 and current > 0 else 1.


def density(pixels, metadata, reference):
    a = pixels.astype(np.float32)
    if pixels.dtype == np.uint16:
        a /= 65535.
    if reference:
        base = np.array(reference["base"], dtype=np.float32) * exposure_scale(metadata, reference)
    else:
        # Used only when no film-base reference exists. Automatic per-channel
        # endpoint alignment removes the resulting constant density offset.
        base = np.ones(3, dtype=np.float32)
    return np.log(np.maximum(base, 1e-6) / np.maximum(a, 1/65535.))


def analyze(frame, adjustments, reference=None, roll_model=None):
    d = density(crop_pixels(frame.pixels, adjustments.crop), frame.metadata, reference)
    # Holder lips and uneven film borders can survive an automatic crop. Use
    # an inner analysis area without throwing away those pixels on export.
    # This keeps a narrow dark border from setting the color endpoints.
    h, w = d.shape[:2]
    my, mx = int(h*.035), int(w*.035)
    d = d[my:h-my or h, mx:w-mx or w]
    step = max(1, int(np.sqrt(d.shape[0]*d.shape[1] / 220000)))
    samples = d[::step, ::step].reshape(-1, 3)
    low = np.percentile(samples, .15, axis=0)
    high = np.percentile(samples, 99.85, axis=0)
    if adjustments.color_mode == "Roll color" and roll_model:
        low = np.array(roll_model["low"], dtype=np.float32)
        high = np.array(roll_model["high"], dtype=np.float32)
    span = np.maximum(high-low, .12)
    return {"low": low.tolist(), "high": (low+span).tolist(),
            "warning": "Low-density range; check the crop or film-base reference."
            if np.any(high-low < .12) else ""}


def _linear_positive(pixels, metadata, adjustments, reference, model):
    d = density(pixels, metadata, reference)
    low = np.asarray(model["low"], dtype=np.float32)
    span = np.maximum(np.asarray(model["high"], dtype=np.float32)-low, .12)
    v = np.clip((d-low)/span, -.2, 1.5)
    k = adjustments.curve
    v = np.maximum(np.expm1(v*k)/np.expm1(k), 0)
    if adjustments.color_mode == "Black & white":
        v = np.repeat(np.mean(v, axis=2, keepdims=True), 3, axis=2)
    else:
        matrix = np.asarray(metadata.get("camera_to_srgb", np.eye(3)), dtype=np.float32)
        v = np.maximum(v @ matrix, 0)
        gains = np.asarray(adjustments.neutral_gains, dtype=np.float32) * np.array([
            2**(adjustments.warmth*.65+adjustments.tint*.2),
            2**(-adjustments.tint*.4),
            2**(-adjustments.warmth*.65+adjustments.tint*.2)], dtype=np.float32)
        v *= gains
    v *= 2**adjustments.exposure
    luminance = np.maximum(np.sum(v*np.array([.2126, .7152, .0722]), axis=2, keepdims=True), 1e-7)
    # Contrast and brightness corrections use one luminance ratio, preserving
    # RGB ratios instead of clipping/curving each color independently.
    mapped = .18*(luminance/.18)**adjustments.contrast
    mapped *= 2**(adjustments.shadows*.8*np.exp(-luminance*5))
    mapped *= 2**(adjustments.highlights*.65*np.minimum(luminance, 1))
    v *= mapped/luminance
    gray = np.sum(v*np.array([.2126, .7152, .0722]), axis=2, keepdims=True)
    v = np.maximum(gray+(v-gray)*adjustments.saturation, 0)
    return v


def encode_srgb(linear):
    a = np.clip(linear, 0, 1)
    return np.where(a <= .0031308, a*12.92, 1.055*a**(1/2.4)-.055)


def render(frame, adjustments, reference=None, model=None, roll_model=None, orient=True):
    model = model or analyze(frame, adjustments, reference, roll_model)
    a = crop_pixels(frame.pixels, adjustments.crop)
    out = np.empty(a.shape, dtype=np.uint8)
    for start in range(0, len(a), 192):
        linear = _linear_positive(a[start:start+192], frame.metadata, adjustments, reference, model)
        out[start:start+192] = np.rint(encode_srgb(linear)*255).astype(np.uint8)
    if orient:
        if adjustments.mirror:
            out = out[:, ::-1]
        if adjustments.rotation:
            out = np.rot90(out, -adjustments.rotation)
    return np.ascontiguousarray(out), model


def negative_preview(frame):
    a = frame.pixels.astype(np.float32)
    if frame.pixels.dtype == np.uint16:
        a /= 65535.
    white = np.maximum(np.percentile(a.reshape(-1, 3)[::8], 99.5, axis=0), 1e-4)
    return np.rint(encode_srgb(a/white)*255).astype(np.uint8)


def neutral_balance(frame, adjustments, reference, model, point):
    """Point is normalized in the displayed, cropped, rotated positive."""
    # Render the linear image once at preview resolution and orient identically.
    crop = crop_pixels(frame.pixels, adjustments.crop)
    neutral = Adjustments.from_dict(asdict(adjustments))
    neutral.neutral_gains = [1., 1., 1.]
    neutral.warmth = neutral.tint = 0.
    a = _linear_positive(crop, frame.metadata, neutral, reference, model)
    if neutral.mirror:
        a = a[:, ::-1]
    if neutral.rotation:
        a = np.rot90(a, -neutral.rotation)
    h, w = a.shape[:2]
    x, y = int(point[0]*w), int(point[1]*h)
    radius = max(3, round(min(h, w)*.008))
    roi = a[max(0,y-radius):min(h,y+radius+1), max(0,x-radius):min(w,x+radius+1)]
    values = np.median(roi, axis=(0,1))
    if np.any(values < .003) or np.max(values) > 1.3:
        raise ValueError("Choose a neutral midtone or light gray area, away from clipped highlights.")
    target = float(np.exp(np.mean(np.log(np.maximum(values, 1e-6)))))
    return np.clip(target/values, .2, 5).tolist()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".film-desk-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, indent=2, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def export_jpeg(source, destination, adjustments, reference, model, quality=95):
    """Full-resolution decode. Never overwrite an existing file, even on a race."""
    destination = Path(destination)
    if destination.exists():
        return {"status": "skipped", "source": str(source), "destination": str(destination),
                "reason": "File already exists"}
    destination.parent.mkdir(parents=True, exist_ok=True)
    full = decode_raw(source, preview=False)
    pixels, _ = render(full, adjustments, reference, model=model)
    fd, temporary = tempfile.mkstemp(prefix=".film-desk-", suffix=".jpg", dir=destination.parent)
    try:
        os.close(fd)
        Image.fromarray(pixels).save(temporary, "JPEG", quality=int(np.clip(quality, 75, 100)),
                                     subsampling=0, icc_profile=SRGB_PROFILE, optimize=True)
        # A hard link is an atomic, no-clobber publish on a local filesystem.
        # If another process created the name meanwhile, do not overwrite it.
        try:
            os.link(temporary, destination)
        except FileExistsError:
            return {"status": "skipped", "source": str(source), "destination": str(destination),
                    "reason": "File already exists"}
        except OSError:
            # Some external filesystems do not support hard links. O_EXCL still
            # protects existing files; clean up partial copies if writing fails.
            created = False
            try:
                with destination.open("xb") as target, open(temporary, "rb") as source_file:
                    created = True
                    import shutil
                    shutil.copyfileobj(source_file, target)
            except FileExistsError:
                return {"status": "skipped", "source": str(source), "destination": str(destination),
                        "reason": "File already exists"}
            except Exception:
                if created:
                    destination.unlink(missing_ok=True)
                raise
        return {"status": "exported", "source": str(source), "destination": str(destination),
                "size": [pixels.shape[1], pixels.shape[0]], "profile": "sRGB", "quality": quality}
    finally:
        Path(temporary).unlink(missing_ok=True)
