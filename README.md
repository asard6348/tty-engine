# TTY Engine
The TTY (ASCII terminal) Engine can be used as project template for any kind of applications, games, styled consoles and anything else in TTY terminal program.
It uses internal module scripts for *rendering*, *physics*, *input* and *ASCII styling* system. For other purposes they can be used as independent modules/libraries (except the game_engine.py which is the main engine script, that imports and uses most of each other).
# Building a project
This project template repository is structured with the main [engine](./engine) folder and two simple scripts for easy interaction. There can be also anything else that is not related to the engine, for example *resources* where would be maybe some another module scripts, images, audio etc.
## Editing
Right in the project folder is script **EDIT.pyw** which will request an [IDLE](https://docs.python.org/3/library/idle.html) (normally should be installed automatically with python) to open the main project module script. There you can start programming your project. Basic knowledge is that the built-in class *main* has got three important functions:
- `def __init__(self)` - this is the basic initialization def used to declare all public variables via `self.something = something`
- `def start(self, gobj)` - this is the most important part for defining new objects via `self.someobj = gobj.obj().create()` and maybe already for some project's logic
- `def update(self, gobj)` - this is the final part where are happening logical changes to all defined variables and objects rapidly in the project's loop (here is the `self.` indexing required too when you want to use the public variables or objects)
## Global object parameters
There are several parameters of the object module script, which are being used even by the whole engine. They can be got in the main module script from the ***gobj*** argument inside the functions *start* and *update*. Here is a list of them:
- `gobj.framerate` (default: `60`) - important variable determining the whole simulation's speed by framerate (FPS)
- `gobj.camx`, `gobj.camy` - x and y axis offset of objects rendering in world space
- `gobj.dimx`, `gobj.dimy` - width (columns) and height (rows) of the terminal window's ASCII character grid, outside which will be rendered text cropped; main engine script is setting it dynamically every frame to match the actual window size
- `gobj.gravity` (default: `[0, -0.05]`) - effective for linear velocity of `obj.dynamic` objects
- `gobj.friction` (default: `0.97`) - global "air" friction (smooth slowing down) effective for linear velocity of `obj.dynamic` objects
- `gobj.precision` (default: `0.1`) - precision of collisions and step of movement to reach full velocity in frame, effective for `obj.dynamic` objects
- `gobj.solids` - list of all `obj.solid` objects
### Object class
Same as all of these parameters, the most important thing in this engine, `class obj()`, can be got from the *gobj* argument via `gobj.obj`. When you are creating a new object, you need to instantiate the *obj* class first and then call the function *create*, which creates a new working object instance and returns the class back. Like this: `self.someobj = gobj.obj().create(text="")`.
## Local object parameters

## Input
Afterwards you will probably want to detect the user's keyboard and mouse input. It can be easily achieved via the built-in internal module `inp` which has got the following functions:
- `inp.hook(key, func)` - this def will hook an action (def argument `func`) on specific key input
- `inp.unhook(handler)` - this will stop the given handler (result of `inp.hook`) of the specific user's input
- `inp.held(key)` - this returns True or False depending on whether the user is actually holding the given key
- `inp.reset()` - this stops every working handler
## Starting
Next to the EDIT.pyw is a quick script **START.py** for automatic project deployment. If you are doing something with the engine's internal module scripts, better way is to start it manually by opening ***game_engine.py*** which is the dominant script for whole engine deployment.
# Module scripts
