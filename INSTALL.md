# Film Desk installation and first launch

[简体中文](INSTALL.zh-CN.md) · [Project guide](README.md)

These instructions cover Film Desk 1.5.1 for Apple Silicon (M-series) Macs running macOS 26 or later. This download does not run on Intel Macs or Windows.

## Download and install

Download from the [GitHub release](https://github.com/Tia-Lin/film-desk/releases/tag/v1.5.1) for this version. The Baidu mirror in the README still contains version 1.4.0. Choose either DMG or ZIP.

1. DMG: open the disk image, copy Film Desk.app into Applications, then eject the image.
2. ZIP: extract it, then copy Film Desk.app into Applications.
3. When updating, quit Film Desk and replace the existing copy in its original location to avoid duplicate versions.

## When macOS blocks the first launch

The current release has a local ad hoc signature. It has no Apple Developer ID signature and has not been notarized by Apple. Local signing does not establish the developer's identity. You may see an unidentified-developer warning or a message that Apple cannot check the app for malicious software.

Only after confirming the source and file integrity, and choosing to trust the app:

1. Double-click Film Desk in Applications. Dismiss the warning.
2. Open **System Settings → Privacy & Security** and scroll to the Film Desk warning.
3. Click **Open Anyway**, authenticate if requested, then confirm **Open**.

Apple provides this per-app exception flow; a successful exception is remembered for later launches. Keep system-wide security checks enabled. See [Apple's official instructions](https://support.apple.com/en-us/102445).

If Open Anyway is missing, try launching the app again before checking. On an organization-managed Mac, your administrator may restrict this setting.

## Damaged-app or malware warnings

Stop if macOS says the app is damaged, will damage your computer, or contains malware. Download again from the release, compare its checksum, and report the full warning, macOS version, and filename in [GitHub Issues](https://github.com/Tia-Lin/film-desk/issues). Do not force it to run by removing quarantine attributes or disabling Gatekeeper or SIP. These warnings differ from a missing-notarization warning. [Apple explains the warnings here](https://support.apple.com/en-us/102445).

## Optional SHA-256 verification

In Terminal, run this command for a DMG in your default Downloads folder; adjust the path if needed:

```sh
shasum -a 256 "$HOME/Downloads/Film-Desk-1.5.1-macOS-arm64.dmg"
```

Compare the result with the matching filename in `Film-Desk-1.5.1-SHA256SUMS.txt` on the release page. For ZIP verification, change `.dmg` to `.zip` in the command. A match confirms identical bytes to the published file, not Apple security certification. Do not open a file with a different digest.

## Access to your photo folder

macOS may request access when you select scans on Desktop or in Documents. Choose Allow to process that folder. This permission is separate from the first-launch security exception; normal use does not need Full Disk Access.

Film Desk processes photos offline and never modifies or uploads the original RAWs. Open a scan folder and set a blank, developed but unexposed frame from the same roll as the reference before converting.
