# Film Desk

[简体中文](README.zh-CN.md) · [Supported cameras](SUPPORTED_CAMERAS.md) · [Installation and first launch](INSTALL.md) · [Download](https://github.com/Tia-Lin/film-desk/releases/latest)

A simple, offline Mac app for turning camera-scanned film negatives into positive JPEGs.

**Copy Film Desk.app into Applications.** Replace your existing copy in the same folder when updating. The downloadable Apple Silicon build requires macOS 26 or later. Sony A7 IV scans have been tested; other accepted RAW formats are described in [Supported cameras](SUPPORTED_CAMERAS.md). You do not need Python, Resolve, or an internet connection to use it.

## Downloads and first launch

- [GitHub release](https://github.com/Tia-Lin/film-desk/releases/tag/v1.5.0): DMG, ZIP, checksums, and installation instructions.
- [Baidu Netdisk mirror](https://pan.baidu.com/s/15wbCfAXCBIA4cL81iml-Tg?pwd=2333), extraction code **2333**: the older 1.4.0 DMG, ZIP, and checksum file; it does not include uneven-light correction. Use GitHub for 1.5.0. Platform availability and download requirements can change.

Choose DMG or ZIP. The build is locally ad hoc signed, without a Developer ID signature or Apple notarization. If macOS blocks the first launch, follow the [installation guide](INSTALL.md) for Apple's per-app Open Anyway procedure. Baidu sign-in or client requirements depend on its current download flow.

## Language

Choose **Language / 语言 → English or 简体中文**. The change is immediate and is remembered on the next launch. It preserves photo adjustments, filenames, and export completion. The default follows the system language (Chinese or English). App controls, tooltips, guides, and normal messages are translated. Native macOS file pickers follow the system language; decoder and system error details may remain in their original language.

## Convert your next roll

1. **Open folder…** — choose the folder of camera RAW scans. Thumbnails are prepared automatically.
2. Select the blank, unexposed film frame and click **Set blank reference**. It measures the film base and is excluded from export.
3. Select a photo. Choose **Color** or **Black & white** for the roll. Start with the automatic result.
4. Adjust **Brightness**, **Contrast**, **Color intensity**, or **Warmth** only if needed. **Balance colors** shows a box around the area under your pointer. Keep the whole box inside a known white or gray object and click to sample it. The box follows your pointer, scales with the displayed image, and clips at image edges. It is only a guide and is not exported. Avoid colored objects and blown-out highlights.
5. **Crop photo** lets you drag around one film image; click **Done cropping** to return to the positive. **Rotate 90°** turns the image clockwise. Scroll to zoom, drag to pan, and use **Fit** to see the entire image.
6. **Export JPEGs…** — check the destination and export. JPEGs keep the RAW base names, use embedded sRGB profiles, and retain full cropped resolution. Quality defaults to 95. Existing JPEGs are skipped; use a new folder when exporting revised edits.

**Apply adjustments to roll** copies the current photo's color and brightness settings to the other photos, preserving their individual crops. **Reset adjustments** resets the current photo's color and brightness while keeping its color or black-and-white output, crop, and orientation. Undo and redo are available from Edit or with standard Mac shortcuts.

Edits are saved automatically. Startup follows the work's status:

- **Unfinished roll:** reopen it automatically, including after a canceled or failed export.
- **Confirmed complete export:** start ready for a new roll. **Reopen last roll** restores the previous photos and edits on request.
- **Edits after export:** resume the roll again, because the JPEGs no longer represent the current adjustments. Browsing photos and opening Help do not change completion.
- **Unavailable unfinished folder:** show **Continue last session** so you can locate it; the saved edits are retained.

A roll is finished when every selected photo has a confirmed JPEG export. Existing files count only when they match the current settings and the previously confirmed file bytes. Skipped, unverified JPEGs keep the session unfinished; export to a new folder for revised versions. Old sessions without a completion record resume conservatively until a new export is confirmed. Completion is saved before the export summary is shown, and a fresh start never deletes the previous recovery session.

 Use **File → Save edits…** to save a named session, and **File → Open saved edits…** to reopen one. Original RAW files are never modified.

## Controls that change the picture

**Color** preserves and balances the RGB channels. **Black & white** produces grayscale and hides the color controls. These choices apply to the photo frames in the roll; the blank reference and individual edits are preserved.

Film-stock names and the backlight-temperature note have been removed. They did not select measured film profiles or change the conversion. The underlying conversion and default color result are unchanged. Existing sessions retain their edits, reference, crop, orientation, and old metadata.

## Photographing film

Open **Help → How to photograph film…** for the complete guide, including lighting, white balance, exposure, focus, blank-frame capture, and half-frame scans. It is available offline inside the app.

For example, with a Sony A7 IV, a starting setup is RAW, manual exposure, ISO 100, f/8, manual focus, and a fixed 5500 K scanning light. Change shutter speed to get enough signal without clipping clear film in any channel; there is no required shutter speed. Keep the film flat, the camera parallel, and the illumination evenly diffused.

Camera white balance affects the camera preview/JPEG, but Film Desk does not apply it to camera RAW decoding. A fixed 5500 K camera setting is useful for consistent previews. The lamp's actual spectrum and uniformity still matter; identical Kelvin labels do not guarantee identical scan colors. The blank reference measures film-base color. Optional uneven-light correction also measures a smooth spatial map; neither provides a complete spectral calibration.

Capture a clear, unexposed but developed piece of the same roll through the same holder and diffuser, preferably at the same exposure. Use a new reference when the roll or light setup changes. Capture one picture per RAW, including half-frame film; the app does not split two pictures automatically.

Further reading: [camera-scanning setup](https://www.negativelabpro.com/guide/scanning/), [illumination spectra](https://jackw01.github.io/scanlight/), and [Sony A7 IV ISO](https://helpguide.sony.net/ilc/2110/v1/en/contents/TP1000640844.html). Film Desk's RAW behavior is defined by its own conversion engine.

## Correct uneven lighting

After setting a blank reference, optionally enable **Correct uneven lighting** beneath it. This roll-wide setting compensates for broad backlight brightness/color gradients and lens shading before negative inversion. It starts off, so existing edits retain their original conversion. Older references are measured again from their RAW only when you enable the feature.

The reference must show clear, developed but unexposed film across the photo area. Keep the camera position, lens, magnification, focus, aperture, holder, diffuser, and light settings fixed. Rephotograph the reference after changing the setup. A small clear patch can establish film-base color but cannot calibrate a whole picture. Crop out opaque holder edges, sprockets, photographed content, and development stains. The app smooths broad variation rather than copying dust, grain, or scratches into other photos; it is not dust removal or a correction for scene lighting.

Calibration uses fixed capture coordinates, so cropping, rotation, and mirroring do not stretch the lighting map. Preview, neutral sampling, and full-resolution JPEG export use the same map. Clipped, dark, very small, or strongly irregular references cannot enable correction. Photos with different recorded sensor dimensions/aperture or crops outside the calibrated area use ordinary conversion and show a warning; the export summary and report identify such exports. Changes in lamp output or camera position cannot be detected reliably from metadata.

The setting and calibration are saved with your edits and support undo/redo. Changing correction clears the previous matched roll response; match the roll again if needed. Export revised photos to a new folder because existing JPEGs are skipped. Turn the checkbox off to compare the original conversion.

## Exposure feedback

The app warns when the RAW capture is sensor-clipped. This measurement covers the whole scan, so bright light outside the film can also trigger it. Inspect the film area: if it is clipped, reduce scan exposure (for example, shorten shutter time) and rescan. Advanced → Highlight lost detail shows clipping in the converted positive; adjust brightness or tone before assuming the RAW is damaged. Neither check reliably diagnoses the exposure of the original film photograph. Film stock, development, scene lighting, and scan exposure are confounding factors. There is currently no calibrated underexposure score or recommended stop correction for the original photograph.

## Advanced, when needed

The **Advanced** section starts closed. It contains optional controls:

- **Green / magenta, Shadow brightness, Highlight brightness, Film response** — extra color and tone adjustments.
- **Roll matching** — tune a representative positive and choose **Match roll to this photo**, then **Apply adjustments to roll**. This shares one response across similar frames. Automatic per photo otherwise estimates a response separately for each photo. Roll matching is available for color output.
- **Flip horizontally** — correct reversed writing or a mirrored scan. **Restore automatic crop** replaces a manual rectangle. **Use this crop for all photos** is useful only when the frame positions are consistent.
- **Refresh roll thumbnails** — rebuild previews after changes across the roll. **Highlight lost detail** shows clipped highlights in red and shadows in blue; the overlay is not exported.
- **Save adjustments… / Load saved adjustments…** — name real tuning and apply it to the current photo in a future session. Use Apply adjustments to roll to copy it to the other photos. Saved tuning from older versions remains available; a saved name identifies actual adjustments, not a measured film profile. Crops, orientation, and sampled neutral balance are not included.
- **Blank reference** — choose an external blank frame, replace the reference, or remove it.

Keep the light uniform and RAW exposure unclipped. Use a new blank reference for a different roll or light spectrum/intensity. Capture exposure differences are normalized using shutter/ISO/aperture metadata, but the app cannot infer a backlight change; use optional uneven-light correction only with a matching reference. Partial frames and damaged film ends can need a manual crop. Dust, scratches, and grain are retained; missing image content is not reconstructed. Keep the RAW files for future reinterpretation.

## Source and verification

The source in `source/` is MIT licensed. Dependency licenses and source locations are in `licenses/` and `THIRD-PARTY-NOTICES.txt`. The app has no account, uploads, telemetry, subscription, or network calls. The downloadable build is locally signed, without a Developer ID signature or Apple notarization.

Verification includes linear inversion, B&W output, exposure normalization, holder-edge exclusion, neutral balance, crop/orientation, avoiding overwrites, session persistence, legacy settings preservation, and keyboard-slider undo. A real-RAW workflow test also covers automatic thumbnails, color/grayscale selection, named adjustment persistence, reopening edits, full-size JPEG export, and skipping existing files. Other RAW extensions are accepted through LibRaw; real-camera verification used Sony A7 IV ARWs.

For development on an Apple Silicon Mac with Python 3.14, from `source/`:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
FILMDESK_LANGUAGE=en QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -p 'test_*.py'
QT_QPA_PLATFORM=offscreen FILMDESK_TEST_RAW="/path/to/test film" .venv/bin/python -m unittest test_workflow
.venv/bin/python -m PyInstaller --noconfirm FilmDesk.spec
```

The optional real-RAW test expects the provided 34-frame test roll and writes only to temporary directories. Packaging needs Apple's command-line build tools. The build specification includes both languages, the camera-support documents, and licenses. Use FILMDESK_LANGUAGE=en or zh_CN to override the interface language during development. Compatible LGPL libraries can be replaced and the app rebuilt/re-signed; modification and reverse engineering for debugging library changes are permitted under the included licenses.
