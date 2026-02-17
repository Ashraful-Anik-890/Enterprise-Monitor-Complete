# Electron App Resources

This directory should contain application icons.

## Required Icons

### For macOS:
- `icon.icns` - macOS application icon (512x512 @ 2x)

### For Windows:
- `icon.ico` - Windows application icon (256x256)

### For Linux:
- `icon.png` - PNG icon (512x512)

### For System Tray:
- `iconTemplate.png` - macOS menu bar icon (16x16 or 32x32)
- Small version of main icon for Windows tray

## How to Create Icons

### Using Online Tools:
1. Create a 1024x1024 PNG image
2. Use https://cloudconvert.com to convert:
   - PNG → ICNS (macOS)
   - PNG → ICO (Windows)

### Using Command Line:

**macOS (ICNS):**
```bash
mkdir icon.iconset
sips -z 16 16     icon-1024.png --out icon.iconset/icon_16x16.png
sips -z 32 32     icon-1024.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32     icon-1024.png --out icon.iconset/icon_32x32.png
sips -z 64 64     icon-1024.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128   icon-1024.png --out icon.iconset/icon_128x128.png
sips -z 256 256   icon-1024.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256   icon-1024.png --out icon.iconset/icon_256x256.png
sips -z 512 512   icon-1024.png --out icon.iconset/icon_256x256@2x.png
sips -z 512 512   icon-1024.png --out icon.iconset/icon_512x512.png
sips -z 1024 1024 icon-1024.png --out icon.iconset/icon_512x512@2x.png
iconutil -c icns icon.iconset
```

**Windows (ICO):**
```bash
# Use ImageMagick
convert icon-1024.png -define icon:auto-resize=256,128,64,48,32,16 icon.ico
```

## Default Behavior

If no icons are provided, Electron will use default system icons.

For production, always include custom branded icons!

## Current Status

⚠️ **No icons included** - Add your company icons here before packaging for distribution.
