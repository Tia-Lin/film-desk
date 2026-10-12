# Camera support

[English](SUPPORTED_CAMERAS.md) | [简体中文](SUPPORTED_CAMERAS.zh-CN.md)

Film Desk 1.4 uses **rawpy 0.27.1 / LibRaw 0.22.1**. It is designed for standard three-channel RGB camera RAWs; the processing is not hard-coded for Sony.

**Validated with real film scans: Sony A7 IV, ARW.** Tests cover RAW decoding, conversion, neutral sampling, saved edits, and full-resolution JPEG export. No other camera/model/recording mode has yet been independently validated in this project. A listed extension means the app accepts the format, not that every model or RAW mode is guaranteed.

| Manufacturer / format family | Accepted extension(s) | Film Desk validation |
|---|---|---|
| Sony | `.arw` | A7 IV tested; other models unverified |
| Canon | `.cr2`, `.cr3` | Decoder-dependent; unverified |
| Nikon | `.nef`, `.nrw` | Decoder-dependent; unverified |
| Fujifilm | `.raf` | Decoder-dependent; unverified, including X-Trans modes |
| Olympus / OM System | `.orf` | Decoder-dependent; unverified |
| Panasonic | `.rw2` | Decoder-dependent; unverified |
| Pentax | `.pef` | Decoder-dependent; unverified |
| Samsung | `.srw` | Decoder-dependent; unverified |
| Adobe DNG / various cameras | `.dng` | Variant- and decoder-dependent; unverified |
| Other RAW families | `.raw` | Device- and decoder-dependent; unverified |

## What limits compatibility?

- The exact model and RAW mode must be supported by the bundled decoder. Lossless, compressed, high-efficiency, computational, linear, HDR, and special capture modes can differ; a matching filename extension is insufficient.
- The decoded RAW must report three color channels. Native monochrome-sensor RAWs and four-color sensors are not supported by the current engine. Black-and-white **film scanned with a normal RGB camera** is supported.
- The camera-to-sRGB transform is derived from the decoder's camera information. If it cannot be verified, the app uses an identity fallback and displays a warning for color conversion. Inspect the positive before exporting. Decoding a file is not proof of validated color accuracy.
- The folder loader accepts only the extensions above. Formats such as native `.x3f`, `.3fr`, `.iiq`, `.rwl`, JPEG, and TIFF are not currently accepted as scan inputs, even if another decoder/software supports them.
- Scanner-generated DNGs and processed image DNGs are not equivalent to original camera RAWs; this pipeline is designed for camera scans.

Consult [LibRaw's 0.22 camera list](https://www.libraw.org/supported-cameras) for model-level decoder support. That list assumes all relevant build features are enabled; support in this bundled build can differ. See also [rawpy's project documentation](https://github.com/letmaik/rawpy).

For an unverified camera, try a small roll first: use the original RAWs and a blank film reference, check orientation/crop, inspect neutral and saturated colors, and export one full-size JPEG. To report a compatibility issue, provide camera model, RAW recording mode, file extension, app version, and the error text. Share sample files only if you are comfortable making their contents available; photographs are not uploaded by the app.
