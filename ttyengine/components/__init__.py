#_owned - list of owned variables which will be inspected upon obj().create()
#_required - list of required components to be included upon obj().create()
#_default - bool of the component auto-inclusion upon obj().create()
#def on_discard() - function that will be called upon obj().discard()

from .inherit import _metainit, _change_callback, _lerpable, _keyed
from .transform import transform
from .physics import physics
from .pen import pen
from .force import force
from .joint import _param, _jointlist, _edge, joint
from .light import light
from .humanoid import humanoid
from .shared import _easing
