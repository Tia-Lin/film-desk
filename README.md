# Film Desk 1.1

A simple, offline Mac app for turning camera-scanned film negatives into positive JPEGs.

**Download Film Desk from [Releases](https://github.com/Tia-Lin/film-desk/releases/latest).** This Apple Silicon build runs on macOS 26 or later and was tested with Sony A7 IV scans on macOS 27.0.1. Extract the ZIP and copy Film Desk.app to your Applications folder. You do not need Python, Resolve, or an internet connection to use it.

## Convert your next roll

1. **Open folder…** — choose the folder of camera RAW scans. Thumbnails are prepared automatically.
2. Select the blank, unexposed film frame and click **Set blank reference**. It measures the film base and is excluded from export.
3. Select a photo. Choose **Film for this roll** once; it applies to all photo frames in the folder. Start with the automatic result.
4. Adjust **Brightness**, **Contrast**, **Color intensity**, or **Warmth** only if needed. **Balance colors** lets you click a known white or gray object. Avoid colored objects and blown-out highlights.
5. **Crop photo** lets you drag around one film image; click **Done cropping** to return to the positive. **Rotate 90°** turns the image clockwise. Scroll to zoom, drag to pan, and use **Fit** to see the entire image.
6. **Export JPEGs…** — check the destination and export. JPEGs keep the RAW base names, use embedded sRGB profiles, and retain full cropped resolution. Quality defaults to 95. Existing JPEGs are skipped; use a new folder when exporting revised edits.

**Apply adjustments to roll** copies the current photo's color and brightness settings to the other photos, preserving their individual crops. **Reset adjustments** resets the current photo's color and brightness while keeping its film selection, crop, and orientation. Undo and redo are available from Edit or with standard Mac shortcuts.

Edits are saved automatically, and your last roll reopens when you launch the app. **Continue last session** is shown only if the original folder needs to be located again. Use **File → Save edits…** to save a named session, and **File → Open saved edits…** to reopen one. Original RAW files are never modified.

## A shorter film menu

The everyday menu contains Portra 400, Portra 160, Gold 200, Portra 800, Ektar 100, UltraMax 400, Fujicolor 200, Fujicolor 400, and **Black & white**. It is deliberately a selection of common films, rather than an exhaustive catalog. Discontinued Fuji entries and duplicate/less-used choices from the first version are omitted.

Choose **Black & white** for monochrome negatives; unnecessary color controls disappear. **Other film…** lets you name an indie film or another stock. Save its settings in Advanced if you want to reuse them. The short list was checked against [Kodak's product listings](https://kodak.cinestillfilm.com/products/) and [Fujifilm's current film shop](https://my.fujifilm.com/fr/pellicules-photo-argentique) on October 8, 2026. Availability and packaging vary by region.

Film names select your saved tuning when available. The initial color response is generic; these are editable starting settings, **not measured stock profiles**. The app does not manufacture a distinctive film look or undo development differences. Older sessions and presets remain compatible even when their film names are absent from the everyday menu.

## Advanced, when needed

The **Advanced** section starts closed. It contains optional controls:

- **Green / magenta, Shadow brightness, Highlight brightness, Film response** — extra color and tone adjustments.
- **Roll matching** — tune a representative positive and choose **Match roll to this photo**, then **Apply adjustments to roll**. This shares one response across similar frames. Auto color otherwise estimates a response separately for each photo.
- **Flip horizontally** — correct reversed writing or a mirrored scan. **Restore automatic crop** replaces a manual rectangle. **Use this crop for all photos** is useful only when the frame positions are consistent.
- **Refresh roll thumbnails** — rebuild previews after changes across the roll. **Highlight lost detail** shows clipped highlights in red and shadows in blue; the overlay is not exported.
- **Save settings for this film** — remember your tuning for future rolls.
- **Blank reference** — choose an external blank frame, replace the reference, or remove it.
- **Scanner notes** — record the backlight temperature. The default is 5500 K. This field is a note, not a second white-balance adjustment.

Keep the light uniform and RAW exposure unclipped. Use a new blank reference for a different roll or light spectrum/intensity. Capture exposure differences are normalized using shutter/ISO/aperture metadata, but the app cannot measure a backlight change or remove uneven illumination. Partial frames and damaged film ends can need a manual crop. Dust, scratches, and grain are retained; missing image content is not reconstructed. Keep the RAW files for future reinterpretation.

## Half-frame scans

The app converts one picture per RAW file. Automatic cropping estimates the illuminated holder opening; it does not identify a physical film format or split two half-frame pictures in one scan. Check the crop and use Crop photo to select one image precisely. A crop can be copied across the roll when scanning positions match.

## Source and verification

The source in `source/` is MIT licensed. Dependency licenses and source locations are in `licenses/` and `THIRD-PARTY-NOTICES.txt`. The app has no account, uploads, telemetry, subscription, or network calls. This personal build is locally signed, without paid Developer ID notarization.

Verification includes linear inversion, B&W output, exposure normalization, holder-edge exclusion, neutral balance, crop/orientation, avoiding overwrites, session persistence, legacy settings preservation, and keyboard-slider undo. A real-RAW workflow test also covers automatic thumbnails, roll film selection, custom preset persistence, reopening edits, full-size JPEG export, and skipping existing files. Other RAW extensions are accepted through LibRaw; real-camera verification used Sony A7 IV ARWs.

For development on an Apple Silicon Mac with Python 3.14, from `source/`:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -p 'test_*.py'
QT_QPA_PLATFORM=offscreen FILMDESK_TEST_RAW="/path/to/test film" .venv/bin/python -m unittest test_workflow
.venv/bin/python -m PyInstaller --noconfirm FilmDesk.spec
```

The optional real-RAW test expects the provided 34-frame test roll and writes only to temporary directories. Packaging needs Apple's command-line build tools. The build specification includes the sibling guide and licenses. Compatible LGPL libraries can be replaced and the app rebuilt/re-signed; modification and reverse engineering for debugging library changes are permitted under the included licenses.
