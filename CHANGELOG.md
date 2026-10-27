# Changelog

## Unreleased

- New `ttyengine.net` package for UDP and TCP servers, clients and peer-to-peer meshes with no dependencies. `Node` hosts, connects, relays and sends messages on named channels; `Sync` shares a session, world, scene, object or single variable with every connected node, with per-entity and per-variable ownership, reliable or latest-wins updates, late-join snapshots and `Sync.attach` to run inside the frame loop. Objects owned by another node are frozen locally (`obj._remote`) so `Scene.tick` skips their physics and joints. Nodes ignore frames from peers that have not completed the handshake, reject spoofed sender ids, cap decompressed payloads at 64 MiB, authenticate with an HMAC challenge when a password is set, and let remote peers write only the variables that were actually shared. Malformed or hostile sync operations are counted in `Sync.rejected` and kept in `Sync.errors` instead of raising. Network protocol version 2.
- `styler.image` now defaults `shades` to a 256-step gradient from a space to `█`, so images come out as monochrome shaded text unless `color=True` is given. The new `bgcolor` argument fills every cell with a background color and blends transparent pixels into it.
- The `rendering` component is merged into `transform`: `show`, `z`, `spaces`, `front()` and `back()` now live on `obj.transform`, and `obj.rendering` no longer exists.
- Per-object `transform.aspect` is now honoured everywhere an object's own geometry is computed (transform, physics, joint, light, force, pen and humanoid) instead of falling back to `scene.aspect`.
- New `humanoid` component: `scene.obj().create(None, x, y, humanoid={'parts': {...}})` builds a jointed, posable figure from a graph of parts. Parts are placed by `at`/`pin` anchors, mirrored with `mirror`, grouped with `group` and animated with `poses` and `cycles`; the figure offers `pose`, `animate`, `velocity`, `jump`, `detach`, `add_part`, `add_parts` and `remove_part`, `ragdoll`. Joints default to an `elasticity` of 1.25 so a standing figure rests without jitter. New `snap` joint setting rigidly places a physical joint's follower back when it is stretched further than the given distance.
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
