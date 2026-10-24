# Changelog

## Unreleased

- New `ttyengine.region` module and `Session(region=...)` setting. A region can be a preset (`line`, `column`, `top`, `bottom`, `left`, `right`, `box`, `centered`, `inline`), a tuple, a dict of insets, or use percentages and `start`/`center`/`end` alignment, so the engine can draw a single line, a column or a panel for command-line and text-UI programs.
- `region.inline(rows)` draws below the cursor on the normal screen and scrolls the terminal when needed.
- `session.World(region=...)` gives every world its own part of the session's region.
- `scene.canvas` and `scene.view` replace juggling `termx`, `termy`, `dimx`, `dimy`, `dimxoffset` and `dimyoffset`, which keep working. `Styler.fill` accepts `region=`.
- `termxoffset`, `termyoffset`, `termwidth` and `termheight` are now aliases for the parts of `session.region`. A negative `termwidth` or `termheight` leaves that many cells unused instead of collapsing the region.
- When a session that draws in part of the terminal stops, the cursor returns to where it was.

## 0.1.0

- First public release.
- Python 3.8 or newer.
- Image decoding falls back to ffmpeg for formats the engine cannot read itself (WebP, TIFF, TGA, AVIF, CMYK JPEG and more), and for damaged files it can still recover.
- `styler.image` without `width` or `height` uses a fixed size (80 columns, or the image's own width if smaller) instead of the terminal size.
- `vsync` now presents frames in step with the display refresh through the compositor, and the new `refresh` setting overrides the detected rate. Synchronized output stays, so a frame is still painted atomically.
- The `ffmpeg` session option is honored even when `sound=False`.
- Decoders always raise `ImageError` for bad data, 16-bit PNG transparency keys are compared in full, and invalid GIF code sizes are rejected.
- Releases are published to PyPI automatically when a version tag is pushed.
