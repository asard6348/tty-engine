# TTY Engine
The TTY (ASCII terminal) Engine can be used as project template for any kind of applications, games or styled consoles and anything else in TTY terminal program.
It uses internal module scripts for *rendering*, *physics*, *input* and *ASCII styling* system. You can get them from the [engine](./engine) folder and use independently (except the game_engine.py which is the main engine script, that imports and uses most of these).
# Instructions
## Editing
Right in the project folder is batch file **EDIT.bat** which will request an [IDLE](https://docs.python.org/3/library/idle.html) (normally should be installed automatically with python) to open the main project module script. There you can start programming your project. Basic knowledge is that the built-in class *main* has got three important functions:
- `def __init__(self)` - this is the basic initialization def used to declare all public variables via `self.something = something`
- `def start(self, gobj)` - this is the most important part for defining new objects via `self.someobj = gobj.obj().create()` and maybe already for some project's logic
- `def update(self, gobj)` - this is the final part where are happening logical changes to all defined variables and objects rapidly in the project's loop (here is the `self.` indexing required too when you want to use the public variables or objects)
Afterwards you will probably want to detect the user's keyboard and mouse input. It can be easily achieved via the built-in internal module `inp` which has got the following functions:
- `inp.hook(key, func)` - this def will hook an action (def argument `func`) on specific key input
- `inp.unhook(handler)` - this will stop the given handler (result of `inp.hook`) of the specific user's input
- `inp.held(key)` - this returns True or False depending on whether the user is actually holding the given key
- `inp.reset()` - this stops every working handler
## Starting
Next to the EDIT.bat is a quick batch file **START.bat** for automatic project deployment. If you are doing something with the engine's internal module scripts, better way is to start it manually by opening ***game_engine.py*** which is the dominant script for whole engine deployment.
# Global object parameters

# Local object parameters

# Module scripts
