# Changelog

## Unreleased

- New `humanoid` component: `scene.obj().create(None, x, y, humanoid={'parts': {...}})` builds a jointed, posable figure from a dict of part texts, with `pose`, `walk`, `velocity`, `jump`, `detach`, `add_part` and `remove_part`.
- Objects and components raise a clear `TypeError` when indexed with something other than a setting name, and are no longer iterable by accident. Unknown names and settings of components an object does not have raise `KeyError`, and `name in obj` reports whether the setting exists.
- `transform.bounce(normal, angle=None, incoming_only=False)` and the new `transform.approaching(normal, angle=None)` let a heading that already leaves the surface stay unchanged.
- New `bouncethreshold` setting (`scene.bouncethreshold` and per-body `physics` setting) for the impact speed below which collisions stop bouncing.
- Callbacks that are bound methods are now called with the right number of arguments in `ontouch`, `onchange` and the other callback hooks.
- Assigning an unknown setting through a component, such as `transform['nope'] = 1`, raises `KeyError` instead of silently creating an attribute.

## 0.1.0

- First public release.
- Python 3.8 or newer.
- The default physics `precision` is `0.5`, which keeps fast objects cheap to simulate. Set `scene.precision` (or an object's `precision`) to change it.
- New `ttyengine.region` module and `Session(region=...)` setting. A region can be a preset (`line`, `column`, `top`, `bottom`, `left`, `right`, `box`, `centered`, `inline`), a tuple, a dict of insets, or use percentages and `start`/`center`/`end` alignment, so the engine can draw a single line, a column or a panel for command-line and text-UI programs.
- `region.inline(rows)` draws below the cursor on the normal screen and scrolls the terminal when needed.
- `session.World(region=...)` gives every world its own part of the session's region.
- `scene.canvas` and `scene.view` replace juggling `termx`, `termy`, `dimx`, `dimy`, `dimxoffset` and `dimyoffset`, which keep working. `Styler.fill` accepts `region=`.
- `termxoffset`, `termyoffset`, `termwidth` and `termheight` are now aliases for the parts of `session.region`. A negative `termwidth` or `termheight` leaves that many cells unused instead of collapsing the region.
- When a session that draws in part of the terminal stops, the cursor returns to where it was.
- Image decoding falls back to ffmpeg for formats the engine cannot read itself (WebP, TIFF, TGA, AVIF, CMYK JPEG and more), and for damaged files it can still recover.
- `styler.image` without `width` or `height` uses a fixed size (80 columns, or the image's own width if smaller) instead of the terminal size.
- `vsync` now presents frames in step with the display refresh through the compositor, and the new `refresh` setting overrides the detected rate. Synchronized output stays, so a frame is still painted atomically.
- The `ffmpeg` session option is honored even when `sound=False`.
- Decoders always raise `ImageError` for bad data, 16-bit PNG transparency keys are compared in full, and invalid GIF code sizes are rejected.
- Releases are published to PyPI automatically when a version tag is pushed.
