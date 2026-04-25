# ScripTree resources

Cross-platform icon assets. The loader (`scriptree.core.branding`) picks
the best format available at runtime and gracefully falls back if any
are missing.

## Expected files

| File | Used by | Notes |
|---|---|---|
| `scriptree.ico` | Windows: window icon, taskbar, `ScripTree.lnk` shortcut | Multi-resolution (16, 32, 48, 64, 128, 256 px). Required for crisp scaling in Explorer. |
| `scriptree.icns` | macOS: Dock icon, `.app` bundles | Standard Apple icon container. Optional if `scriptree.png` exists. |
| `scriptree.png` | Linux + universal fallback | 256×256 or 512×512. Also consumed by the macOS runtime if `.icns` is missing. |

Drop the files into this folder. The branding module discovers them by
name — no registration needed.

## Generating the formats

From a single source PNG (say, 1024×1024 with transparency):

```bash
# Windows .ico — ImageMagick or pillow:
magick convert source.png -define icon:auto-resize=256,128,64,48,32,16 scriptree.ico

# macOS .icns — use iconutil (needs an iconset folder of PNGs at standard sizes):
#   icon_16x16.png, icon_16x16@2x.png, icon_32x32.png, icon_32x32@2x.png,
#   icon_128x128.png, icon_128x128@2x.png, icon_256x256.png, icon_256x256@2x.png,
#   icon_512x512.png, icon_512x512@2x.png
iconutil -c icns scriptree.iconset -o scriptree.icns

# Universal PNG — just copy a 256×256 or 512×512 version:
cp source_256.png scriptree.png
```
