# TTY Engine

A terminal rendering, physics and sound engine for Python. It has no required
dependencies: image decoding (PNG, JPEG, GIF, BMP, PNM), FIGlet text, the audio
mixer and terminal/input handling are all implemented in the standard library.

Objects are built from components (`transform`, `rendering`, `physics`, `pen`,
`force`, `joint`, `light`) that are attached automatically from the keyword
arguments you pass to `create()`.

## Install

```sh
pip install git+https://github.com/asard6348/tty-engine
```

Requires Python 3.8 or newer on Windows, macOS or Linux, in a terminal that
supports ANSI escape sequences (truecolor and the kitty keyboard protocol are
used when available).

Optional extras:

| Extra | Install | Adds |
|---|---|---|
| `keyboard` | `pip install "ttyengine[keyboard]"` | Low-level key press/release tracking (`inp.held`). Needs root on Linux/macOS. |
| `ffmpeg` | `pip install "ttyengine[ffmpeg]"` | Bundled ffmpeg for decoding compressed audio. |

Without the `keyboard` package the engine falls back to terminal input.

## Quick start

```python
from ttyengine import Session

class main:
    def start(self, scene, session):
        scene.obj().create('hello, tty', 5, -3)

        def quit():
            session.running = False
        session.inp.onpress('x', quit)

session = Session(sound=False)
world = session.World()
world.launch(main)
session.run()
```

A `launch()`ed handle is a class (or a plain function) whose optional
`start`, `update` and `final` methods receive any of `scene`, `session`,
`world`, `handle` and `sound` by parameter name. See `example.py`,
`gameoflife.py`, `ant.py` and `rocket.py` for larger programs.

## Tests

```sh
python -m unittest discover -s tests
```

## Licensing

Bundled FIGlet fonts and code are covered by `ttyengine/figlet-LICENSE.txt`.
