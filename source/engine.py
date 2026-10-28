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

VERSION = "1.5.1"
RAW_EXTENSIONS = {".arw", ".dng", ".nef", ".nrw", ".cr2", ".cr3", ".raf", ".orf", ".rw2", ".pef", ".srw", ".raw"}
SRGB_PROFILE = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
_CAMERA_MATRICES = {}
_MATRIX_LOCK = threading.Lock()


@dataclass
class Adjustments:
    film_stock: str = ""  # Legacy session metadata; never used for conversion.
    crop: list[float] = field(default_factory=lambda: [0., 0., 1., 1.])
    rotation: int = 0
    mirror: bool = True
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
        values = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        # Older sessions without this field were unflipped. Preserve that intent
        # and their confirmed-export signatures; only fresh scans use the default.
        values.setdefault("mirror", False)
        obj = cls(**values)
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
            "raw_size": [int(scan.shape[1]), int(scan.shape[0])],
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
    automatic = auto_crop(frame)
    crop = crop or automatic
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
    reference = {"base": base.tolist(), "metadata": frame.metadata, "crop": crop,
                 "uneven": bool(np.max(spread) > 1.35), "flat_field_enabled": False}
    candidates = [crop]
    if np.allclose(crop, automatic, atol=1/max(frame.pixels.shape[:2]), rtol=0):
        # auto_crop reserves 5% inside the opening for photo statistics. A blank
        # can calibrate almost the whole clear opening: retain a 1% edge margin.
        x0, y0, x1, y1 = crop
        for fraction in [.044, .033, .022, .011][::-1]:
            candidates.insert(0, clean_crop([x0-(x1-x0)*fraction, y0-(y1-y0)*fraction,
                                              x1+(x1-x0)*fraction, y1+(y1-y0)*fraction]))
    for field_crop in candidates:
        try:
            reference["flat_field"] = measure_flat_field(frame, field_crop, base)
            reference.pop("flat_field_error", None)
            break
        except ValueError as exc:
            # An unsuitable spatial reference can still supply the base color.
            reference["flat_field_error"] = str(exc)
    return reference


# A low-order surface models broad illumination, rather than copying reference
# grain, scratches, dust, or individual pixels into every photograph.
_FIELD_POWERS = tuple((x, degree-x) for degree in range(5) for x in range(degree+1))


def _field_basis(x, y):
    return np.stack([x**i*y**j for i, j in _FIELD_POWERS], axis=-1)


def measure_flat_field(frame, crop, base):
    a = crop_pixels(frame.pixels, crop).astype(np.float32)
    if frame.pixels.dtype == np.uint16:
        a /= 65535.
    h, w = a.shape[:2]
    if min(h, w) < 64:
        raise ValueError("The blank reference is too small for uneven-light correction.")
    if not np.all(np.isfinite(a)):
        raise ValueError("The blank reference contains invalid pixel values.")
    if np.max(np.mean(a >= .995, axis=(0, 1))) > .001:
        raise ValueError("The blank reference is clipped. Reduce scan exposure and photograph it again.")
    nx, ny = min(21, w//8), min(21, h//8)
    xs, ys = np.linspace(0, w, nx+1).astype(int), np.linspace(0, h, ny+1).astype(int)
    samples, coordinates = [], []
    for y0, y1 in zip(ys[:-1], ys[1:]):
        for x0, x1 in zip(xs[:-1], xs[1:]):
            samples.append(np.median(a[y0:y1, x0:x1], axis=(0, 1)))
            coordinates.append([(x0+x1)/w-1, (y0+y1)/h-1])
    samples = np.asarray(samples)
    if np.any(samples < .0005):
        raise ValueError("The blank reference has dark or blocked areas. Crop to clear film covering the photo area.")
    if np.max(np.max(samples, axis=0)/np.min(samples, axis=0)) > 4:
        raise ValueError("The blank reference varies too strongly. Check the holder, film, and backlight.")
    coordinates = np.asarray(coordinates)
    design = _field_basis(coordinates[:, 0], coordinates[:, 1])
    signal = np.log(samples/np.asarray(base))
    weights = np.ones(len(samples))
    for _ in range(6):
        weighted = np.sqrt(weights)[:, None]
        coefficients, _, rank, _ = np.linalg.lstsq(design*weighted, signal*weighted, rcond=None)
        residual = np.max(np.abs(signal-design@coefficients), axis=1)
        weights = np.minimum(1, .025/np.maximum(residual, 1e-6))
    if rank != len(_FIELD_POWERS) or np.percentile(residual, 90) > .12:
        raise ValueError("The blank reference has too much detail or staining for a smooth lighting correction.")
    # Store the actual sampled bounds in full, unrotated image coordinates.
    full_h, full_w = frame.pixels.shape[:2]
    x0, y0, x1, y1 = clean_crop(crop)
    bounds = [round(x0*full_w)/full_w, round(y0*full_h)/full_h,
              round(x1*full_w)/full_w, round(y1*full_h)/full_h]
    model = {"schema": 1, "coefficients": coefficients.tolist(), "crop": bounds,
             "aspect": full_w/full_h, "raw_size": frame.metadata.get("raw_size")}
    # Reject a polynomial that extrapolates wildly between the measured tiles.
    x, y = np.meshgrid(np.linspace(-1, 1, 33), np.linspace(-1, 1, 33))
    fitted = _field_basis(x, y)@coefficients
    if np.any(np.abs(fitted) > np.log(4)):
        raise ValueError("The blank reference varies too strongly. Check the holder, film, and backlight.")
    return model


def validate_reference(reference):
    """Validate saved spatial calibration before it replaces an active session."""
    base = np.asarray(reference["base"], dtype=float)
    if base.shape != (3,) or not np.all(np.isfinite(base)) or np.any(base <= 0):
        raise ValueError("Invalid film-base reference in session")
    clean_crop(reference.get("crop", [0, 0, 1, 1]))
    if not isinstance(reference.get("flat_field_enabled", False), bool):
        raise ValueError("Invalid uneven-light correction in session")
    model = reference.get("flat_field")
    if model is None:
        if reference.get("flat_field_enabled"):
            raise ValueError("The saved uneven-light correction has no calibration. Set the blank reference again.")
        return
    c = np.asarray(model["coefficients"], dtype=float)
    aspect = float(model["aspect"])
    if (model.get("schema") != 1 or c.shape != (len(_FIELD_POWERS), 3)
            or not np.all(np.isfinite(c)) or np.max(np.abs(c)) > 10
            or not math.isfinite(aspect) or not .1 < aspect < 10):
        raise ValueError("Invalid uneven-light calibration in session")
    clean_crop(model["crop"])
    raw_size = model.get("raw_size")
    if raw_size is not None and (not isinstance(raw_size, list) or len(raw_size) != 2
            or any(not isinstance(n, int) or n <= 0 for n in raw_size)):
        raise ValueError("Invalid reference sensor size in session")


def flat_field_for_frame(frame, crop, reference):
    """A spatial map belongs to fixed capture coordinates, never the photo crop."""
    if not reference or not reference.get("flat_field_enabled", False):
        return None, ""
    validate_reference(reference)
    model = reference["flat_field"]
    h, w = frame.pixels.shape[:2]
    raw_size = model.get("raw_size")
    if ((raw_size and frame.metadata.get("raw_size") != raw_size)
            or abs((w/h)/model["aspect"]-1) > .003):
        return None, "Uneven-light correction skipped: the scan dimensions differ from the blank reference."
    ref_aperture = reference.get("metadata", {}).get("aperture", 0)
    aperture = frame.metadata.get("aperture", 0)
    if min(ref_aperture, aperture) > 0 and abs(math.log2(aperture/ref_aperture)) > .03:
        return None, "Uneven-light correction skipped: use a reference photographed at the same aperture."
    c, r = clean_crop(crop), model["crop"]
    # Allow a few preview pixels of rounding/holder-edge detection difference.
    tolerance = .003
    if c[0] < r[0]-tolerance or c[1] < r[1]-tolerance or c[2] > r[2]+tolerance or c[3] > r[3]+tolerance:
        return None, "Uneven-light correction skipped: crop this photo inside the area covered by the blank reference."
    return model, ""


def spatial_density_offset(frame, crop, model, start=0, stop=None):
    """Evaluate a bounded row strip at original sensor positions, before rotation."""
    if model is None:
        return None
    h, w = frame.pixels.shape[:2]
    x0, y0, x1, y1 = clean_crop(crop)
    left, top, right, bottom = round(x0*w), round(y0*h), round(x1*w), round(y1*h)
    stop = bottom-top if stop is None else min(stop, bottom-top)
    r = model["crop"]
    x = (((np.arange(left, right, dtype=np.float32)+.5)/w-r[0])/(r[2]-r[0])*2-1)[None, :]
    y = (((np.arange(top+start, top+stop, dtype=np.float32)+.5)/h-r[1])/(r[3]-r[1])*2-1)[:, None]
    result = np.zeros((stop-start, right-left, 3), dtype=np.float32)
    for (i, j), coefficients in zip(_FIELD_POWERS, model["coefficients"]):
        result += ((x**i)*(y**j))[..., None]*np.asarray(coefficients, dtype=np.float32)
    # A malformed saved surface must never amplify arbitrarily.
    return np.clip(result, -np.log(4), np.log(4))


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


def density(pixels, metadata, reference, spatial_offset=None):
    a = pixels.astype(np.float32)
    if pixels.dtype == np.uint16:
        a /= 65535.
    if reference:
        base = np.array(reference["base"], dtype=np.float32) * exposure_scale(metadata, reference)
    else:
        # Used only when no film-base reference exists. Automatic per-channel
        # endpoint alignment removes the resulting constant density offset.
        base = np.ones(3, dtype=np.float32)
    result = np.log(np.maximum(base, 1e-6) / np.maximum(a, 1/65535.))
    return result if spatial_offset is None else result+spatial_offset


def analyze(frame, adjustments, reference=None, roll_model=None):
    field, field_warning = flat_field_for_frame(frame, adjustments.crop, reference)
    d = density(crop_pixels(frame.pixels, adjustments.crop), frame.metadata, reference,
                spatial_density_offset(frame, adjustments.crop, field))
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
            "flat_field_applied": field is not None, "flat_field_warning": field_warning,
            "warning": "Low-density range; check the crop or film-base reference."
            if np.any(high-low < .12) else ""}


def _linear_positive(pixels, metadata, adjustments, reference, model, spatial_offset=None):
    d = density(pixels, metadata, reference, spatial_offset)
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
    model = dict(model or analyze(frame, adjustments, reference, roll_model))
    field, warning = flat_field_for_frame(frame, adjustments.crop, reference)
    model.update(flat_field_applied=field is not None, flat_field_warning=warning)
    a = crop_pixels(frame.pixels, adjustments.crop)
    out = np.empty(a.shape, dtype=np.uint8)
    for start in range(0, len(a), 192):
        offset = spatial_density_offset(frame, adjustments.crop, field, start, start+192)
        linear = _linear_positive(a[start:start+192], frame.metadata, adjustments, reference, model, offset)
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


def neutral_sample_bounds(width, height, point):
    """Pixel bounds of the picker patch in the oriented positive preview."""
    x, y = int(point[0]*width), int(point[1]*height)
    radius = max(3, round(min(height, width)*.008))
    return (max(0,x-radius), max(0,y-radius),
            min(width,x+radius+1), min(height,y+radius+1))


def neutral_balance(frame, adjustments, reference, model, point):
    """Point is normalized in the displayed, cropped, rotated positive."""
    # Render the linear image once at preview resolution and orient identically.
    crop = crop_pixels(frame.pixels, adjustments.crop)
    neutral = Adjustments.from_dict(asdict(adjustments))
    neutral.neutral_gains = [1., 1., 1.]
    neutral.warmth = neutral.tint = 0.
    field, _ = flat_field_for_frame(frame, adjustments.crop, reference)
    a = _linear_positive(crop, frame.metadata, neutral, reference, model,
                         spatial_density_offset(frame, adjustments.crop, field))
    if neutral.mirror:
        a = a[:, ::-1]
    if neutral.rotation:
        a = np.rot90(a, -neutral.rotation)
    h, w = a.shape[:2]
    x0, y0, x1, y1 = neutral_sample_bounds(w, h, point)
    roi = a[y0:y1, x0:x1]
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
    pixels, rendered_model = render(full, adjustments, reference, model=model)
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
                "flat_field_applied": rendered_model["flat_field_applied"],
                "flat_field_warning": rendered_model["flat_field_warning"],
                "size": [pixels.shape[1], pixels.shape[0]], "profile": "sRGB", "quality": quality}
    finally:
        Path(temporary).unlink(missing_ok=True)
