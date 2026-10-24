# Changelog

## 0.1.0

- First public release.
- Python 3.8 or newer.
- Image decoding falls back to ffmpeg for formats the engine cannot read itself (WebP, TIFF, TGA, AVIF, CMYK JPEG and more), and for damaged files it can still recover.
- `styler.image` without `width` or `height` uses a fixed size (80 columns, or the image's own width if smaller) instead of the terminal size.
- `vsync` now presents frames in step with the display refresh through the compositor, and the new `refresh` setting overrides the detected rate. Synchronized output stays, so a frame is still painted atomically.
- The `ffmpeg` session option is honored even when `sound=False`.
- Decoders always raise `ImageError` for bad data, 16-bit PNG transparency keys are compared in full, and invalid GIF code sizes are rejected.
- Releases are published to PyPI automatically when a version tag is pushed.
