#ENGINE LAUNCHER
from ttyengine.launcher import Session, attempt

def dev(Session=Session): #DEBUG
    main_session = Session()
    main_world = main_session.World()

    #MODULES
    import sys
    import math

    #TITLE
    sys.stdout.write(f"\033]0;TTY Simulator\007")
    sys.stdout.flush()
    #DEBUGGER
    #main_session.debug(title='Debugger')

    #SCENE BEHAVIOURS
    class explode():
        def __init__(self, scene, x,y,radius=25,force=200,timer=0.5):
            self.pos = (x,y)
            self.bomb = scene.obj().create(x=x, y=y, force=force*radius, cap=force, radius=radius, position=(x,y)) # bomb
            self.bomb.force.apply()
            self.power = force
            self.begin = timer
            self.timer = self.begin
        def update(self, scene, handle, session):
            if self.timer <= 0:
                self.bomb.discard()
                handle.cancel()
                return
            self.timer -= 1/scene.framerate
            t = self.bomb.transform
            ex = self.bomb.force
            delta = (self.timer/self.begin) if self.begin != 0 else 0
            t.text = session.style(scene.styler.shapes.circle((ex.radius/2)*(1-delta), 'X', aspect=scene.aspect), alpha=max(0,min(1,self.power/20)*delta), color='orange')
            t.x, t.y = self.pos
            t.x -= t.xlen()/2
            t.y += t.ylen()/2

    class main():
        def __init__(self, scene, world, session):   #INITIALIZATION (OPTIONAL)
            self.scene = scene
            self.session = session
            self.world = world
            #VARIABLES
            self.plrspeed = 1
            self.plrmaxspeed = 10
            self.plrspeedfriction = 0.9
            self.plrjumppower = 10
            self.camrange = 5
            self.camspeed = 0.7
            self.void = -100
            #scene.bgcolor = (255,255,255)
            self.pencolor = (50, 120, 155)
            self.scpencolor = (155, 120, 50)

        def start(self):    #START
            sc = self.scene
            world = self.world
            inp = self.session.inp
            style = self.session.style
            obj = sc.obj
            def w2(mx, my):
                return mx + sc.iround(sc.camx), sc.iround(sc.camy) - my
            self.w2 = w2
            self.tarx = 0*sc.dimx/2
            self.tary = -sc.dimy/2

            self.scene.gravity = (0,-0.05)
            #scene.drag = 0.97
            self.psp = obj().create('PAUSED', y=-1, show=world.pausephysics, z=50)
            '''self.info = obj().create(style('Press "q" to quit. Hold "e" to rotate.', color='magenta', bgcolor='pink'),0,0,renderspaces=True,z=10)
            plrtext = style(f"{style(' O ', color=(241,194,125), reset=False)}\n{style('(|)', color='brightblue', reset=False)}\n{style(' | ', color='green', reset=False)}\n{style('[ ]', color='gray', reset=False)}",
                            )
            self.plr = obj().create(plrtext,0,0,hitbox=True,renderspaces=False)
            def plref(parts):
                if 0 < len(parts): self.plr = parts[0]
                else: self.plr = None
            self.plr.transform.onsplit(plref)
            sc.follow(self.plr)
            self.enemy = obj().create("OOOOOO\n"*4,25,-(sc.dimy+1), bounciness=1)
            self.enemy.transform.y += self.enemy.transform.ylen()
            self.enemy.physics.dynamic = True; self.enemy.physics.hitbox = False
            self.ground = obj().create("██████████████████████████████████████████████████████████████████████████████", -15, -(sc.dimy+1), dynamic=False)
            self.floor = obj().create("OOOOOO\n OOOOO",self.enemy.transform.x,self.enemy.transform.y+6, dynamic=False)
            self.peak = obj().create("O\n"*20,self.ground.transform.x-55,self.ground.transform.y-6, dynamic=False)
            def pp(txt,x=0,y=0):
                return obj().create(txt,x,y,dynamic=False)
            p1=pp("OOOOOOOOO",self.ground.transform.x-20,self.ground.transform.y)
            p2=pp("OOOOOOOOO\nOOOOOOOOO",p1.transform.x-20,p1.transform.y+1)
            p3=pp("OOOOOOOOO\nOOOOOOOOO",p2.transform.x-30,p2.transform.y-5)
            ip=20
            for i in range(0,6):
                pp("OOOOOOOOO", p3.transform.x-ip,p3.transform.y)
                ip+=20'''

            '''c = {'g': style("█",(24,30,24),reset=False)*2,
                 'dp': style("█",(143,8,112),reset=False)*2,
                 'w': style("█",'white',reset=False)*2,
                 'v': style("█",(161,50,201),reset=False)*2,
                 'dv': style("█",'darkpurple',reset=False)*2,
                 'p': style("█",(255,143,225),reset=False)*2,
                 'y': style("█",'brightorange',reset=False)*2,}
            self.art = obj().create(style(f"""
                      {c['g']}                                          {c['g']}
                      {c['g']*2}        {c['g']*7}                {c['g']*2}
                      {c['g']}{c['dp']}{c['g']*4}{c['dp']*7}{c['g']*3}      {c['g']*2}{c['dp']}{c['g']}
                        {c['g']}{c['dp']*2}{c['g']}{c['dp']*7}{c['g']}{c['dp']*3}{c['g']*3}{c['dp']*3}{c['g']*3}
                  {c['g']*5}{c['dp']*10}{c['g']*2}{c['dp']*9}{c['g']}
                  {c['g']}{c['dp']*16}{c['g']*2}{c['dp']*6}{c['g']}
                    {c['g']*2}{c['dp']*6}{c['g']*4}{c['dp']*6}{c['g']}{c['dp']*5}{c['g']}
                    {c['g']}{c['dp']*6}{c['g']}{c['w']*4}{c['g']*2}{c['dp']*3}{c['g']*2}{c['dp']*4}{c['g']}
                  {c['g']}{c['dp']*6}{c['g']}{c['w']*6}{c['g']*5}{c['dp']*4}{c['g']*2}
                {c['g']*3}{c['dp']*3}{c['g']*3}{c['w']*2}{c['g']}{c['w']*3}{c['g']*3}{c['dp']*8}{c['g']*2}  {c['g']*2}
                      {c['g']*6}{c['w']*6}{c['g']}{c['dp']*11}{c['g']*2}{c['p']}{c['g']*3}
                        {c['g']}{c['p']}{c['dp']}{c['g']*3}{c['w']*4}{c['v']}{c['g']}{c['dp']*5}{c['g']}{c['dp']*2}{c['g']*4}{c['v']}{c['p']}{c['v']}{c['p']}{c['g']}
                      {c['g']}{c['p']*6}{c['v']*4}{c['p']}{c['g']}{c['dp']*5}{c['g']*6}{c['p']*2}{c['v']}{c['p']*2}{c['g']}
                      {c['g']}{c['p']}{c['dp']}{c['p']*9}{c['g']}{c['dp']*4}{c['g']}{c['v']}{c['p']}{c['v']}{c['g']}{c['y']}{c['g']}{c['v']}{c['p']*3}{c['g']}
                      {c['g']}{c['p']*9}{c['v']}{c['g']*2}{c['dp']*4}{c['g']}{c['p']*3}{c['g']*4}{c['p']*2}{c['g']*2}
                        {c['g']}{c['p']*5}{c['v']}{c['g']*5}{c['dp']*4}{c['g']}{c['p']*3}{c['v']}{c['g']*3}{c['p']*4}{c['g']}
                          {c['g']*7}{c['v']*2}{c['g']*3}{c['dp']*3}{c['g']}{c['p']*3}{c['v']}{c['g']}{c['y']}{c['g']*6}
                        {c['g']}{c['p']}{c['g']*11}{c['dp']*2}{c['g']}{c['v']*3}{c['g']*5}
                    {c['g']*2}{c['p']}{c['v']*2}{c['g']*4}{c['p']*3}{c['g']*3}{c['dp']*2}{c['g']}{c['v']}{c['g']*2}
                  {c['g']}{c['p']*5}{c['g']}{c['y']}{c['g']}{c['p']*2}{c['v']}{c['g']*4}{c['dp']*2}{c['g']*2}
                {c['g']}{c['p']*6}{c['g']*3}{c['p']*3}{c['v']}{c['g']*4}{c['dp']}{c['g']}
                {c['g']}{c['p']*5}{c['g']}{c['y']}{c['g']}{c['p']*5}{c['g']}{c['v']}{c['g']*4}
              {c['g']*3}{c['p']*4}{c['g']*3}{c['p']*3}{c['g']*3}{c['v']}{c['g']}
          {c['g']*6}{c['v']*3}{c['g']*3}{c['p']}{c['v']}{c['g']}{c['dv']*2}{c['g']*2}
    {c['g']*13}{c['y']}{c['g']*3}{c['y']}{c['g']}{c['y']}{c['g']*2}
      {c['g']}{c['v']}{c['g']*14}{c['y']*2}{c['g']*5}
        {c['g']}{c['v']*3}{c['g']*4}{c['v']*3}{c['g']}{c['dv']}{c['dp']}{c['g']*3}{c['dp']*4}{c['g']*2}
          {c['g']*3}{c['v']*4}{c['g']*3}{c['dp']*11}{c['g']}
              {c['g']*5}{c['dv']}{c['dp']*5}{c['g']*2}{c['dp']*6}{c['g']}
                {c['g']}{c['dp']*7}{c['g']*2}{c['dp']*7}{c['dv']}{c['g']}
              {c['g']*2}{c['dp']*7}{c['g']}  {c['g']}{c['dp']*6}{c['g']}
              {c['g']*4}{c['dp']*3}{c['dv']}{c['g']}    {c['g']*7}
            {c['g']*9}    {c['g']*8}
        {c['g']*9}      {c['g']*8}
      {c['g']*7}            {c['g']*10}
  {c['g']*9}            {c['g']}{c['y']*2}{c['g']*8}
{c['g']*10}                    {c['y']*6}{c['g']}
{c['g']*8}{c['y']*2}
{c['y']}{c['g']*4}{c['y']*3}
  {c['y']*4}
"""),dynamic=True)'''

            if not hasattr(self, 'plr'): self.plr = None

            self.pen = obj().create(penchar='█', pradius=2)
            self.penc = 0
            def on_click_pen(mx, my, data, pencolor=None):
                if pencolor is None: pencolor = self.pencolor
                self.pen.pen.pradius=2 if data==0 else 1
                self.pen.pen.x, self.pen.pen.y = w2(mx, my)
                self.pen.pen.down(char=style(self.pen.pen.char, color=(self.penc+13 if data==0 else 'gray') if not pencolor else pencolor))
                self.penc = 0 if self.penc >= 13 else self.penc + 1
                if data == 2:
                    self.pen.pen.cancel()
            def on_release_pen(mx, my, data, dynamic):
                if self.pen.pen.active:
                    self.pen.pen.move(*w2(mx, my))
                if data == 2:
                    self.pen.pen.drop()
                    self.pen.pen.cutcommit(r=0, hitbox=False)
                self.pen.pen.up(dynamic=dynamic, friction=0.99)
            inp.onmouse('click', on_click_pen)
            inp.onmouse('release', lambda mx, my, data: on_release_pen(mx, my, data, False))
            def on_move_pen(mx, my, data):
                if inp.held('space'):
                    on_click_pen(mx, my, 0, self.scpencolor)
                wx, wy = w2(mx, my)
                for p in (self.pen.pen, self.tpen.pen):
                    if p.active:
                        p.move(wx, wy, rebuild=False)
                if inp.held('z', delay=0.2):
                    self.erase(wx, wy)
            inp.onmouse('move', on_move_pen)
            inp.onrelease('space', lambda: on_release_pen(inp._mouse_x, inp._mouse_y, 0, True))

            self.epen = obj().create(penchar='█', pradius=2)
            self.esize = 2
            self.erasing = False
            shape = set(self.epen.pen.footprint(self.esize))
            self.curx = max(x for x, _ in shape)
            self.cury = max(y for _, y in shape)
            def rim(x, y):
                return (x, y) in shape and not all((x + a, y + b) in shape for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1)))
            box = [''.join('█' if rim(x, y) else ' ' for x in range(-self.curx, self.curx + 1)) for y in range(self.cury, -self.cury - 1, -1)]
            self.cursor = obj().create(style('\n'.join(box), 'white'), 0, 0, show=False, phantom=True, dynamic=False, z=20)
            def erasable(o):
                p = getattr(o, 'physics', None)
                if p is None or p.phantom:
                    return False
                return all(o is not s for s in (self.push, self.cursor, self.pen.pen.current_obj, self.tpen.pen.current_obj))
            def erase(wx, wy):
                self.epen.pen.cut(wx, wy, r=self.esize, when=erasable)
            self.erase = erase

            self.tpen = obj().create(penchar='█', pradius=2)
            self.tgrab = []
            self.tpts = {}
            def following(o):
                j = getattr(o, 'joint', None)
                return j is not None and any(e.follower is j for e in j._edges.values())
            def ballink(a, b, coll=False):
                if a is b or not hasattr(a, 'transform') or not hasattr(b, 'transform'):
                    return
                if following(b):
                    a, b = b, a
                    if following(b):
                        return
                for x, y in ((a, b), (b, a)):
                    j = getattr(x, 'joint', None)
                    if j is not None and id(y) in j._edges:
                        return
                if getattr(a, 'joint', None) is None:
                    a.add('joint')
                if getattr(b, 'joint', None) is None:
                    b.add('joint')
                # join at the point where the stroke crossed from one object into the other, so the
                # two objects meet at that edge (pin on both) instead of at b's centre
                at = self.tpts.get((id(a), id(b))) or self.tpts.get((id(b), id(a)))
                a.joint.attach(b, 'ball', radius='keep', physical=True, collide=coll, at=at)
            def tdown():
                pen = self.tpen.pen
                if pen.active:
                    return
                pen.x, pen.y = w2(inp._mouse_x, inp._mouse_y)
                self.tgrab = []
                self.tpts = {}
                pen.down(char=style(pen.char, color='cyan'), phantom=True, dynamic=False)
            def tup(coll=False):
                pen = self.tpen.pen
                if not pen.active:
                    return
                stroke = pen.up()
                stroke.transform.fade(0, time=0.3, discard=True)
                objs = [o for o in self.tgrab if hasattr(o, 'transform')]
                for a, b in zip(objs, objs[1:]):
                    ballink(a, b, coll)
                self.tgrab = []
                self.tpts = {}
            inp.onpress('t', tdown, True)
            inp.onpress('y', tdown, True)
            inp.onrelease('t', tup, True)
            inp.onrelease('y', lambda: tup(True), True)

            self.push = sc.obj().create(force=30*40, cap=30, radius=40, show=False)
            self.push.transform.text = sc.styler.shapes.circle(5, style('X', 'red'), aspect=sc.aspect)

            self.grips = []
            self.gripping = False
            self.nogrip = False
            self.gripspeed = 20
            self.gripelastic = 1
            self.gripkeys = ('kind', 'collide', 'elasticity', 'xoffset', 'yoffset', 'pinx', 'piny')
            def grabbable(o):
                p = getattr(o, 'physics', None)
                if p is None or p.phantom or not p.dynamic:
                    return False
                return all(o is not s for s in (self.push, self.cursor, self.pen, self.epen, self.tpen, self.pen.pen.current_obj, self.tpen.pen.current_obj))
            def grip(x, y):
                self.grips = []
                point = (x + 0.5, y - 0.5)
                for o in list(sc.objs):
                    if not grabbable(o):
                        continue
                    px = o.physics.getpixels()
                    if not any((x + i, y + j) in px for i in (-1, 0, 1) for j in (-1, 0, 1)):
                        continue
                    g = obj().create(x=point[0], y=point[1], dynamic=False, phantom=True, show=False)
                    if following(o):
                        if getattr(o, 'joint', None) is None:
                            o.add('joint')
                        o.joint.attach(g, 'ball', at=point, collide=False, elasticity=self.gripelastic)
                    else:
                        g.add('joint')
                        g.joint.attach(o, 'ball', at=point, collide=False, elasticity=self.gripelastic)
                    self.grips.append(g)
            def drag(x, y):
                tx, ty = x + 0.5, y - 0.5
                lim = self.gripspeed
                for g in self.grips:
                    t = g.transform
                    t.x += max(-lim, min(lim, tx - t.x))
                    t.y += max(-lim, min(lim, ty - t.y))
            def release():
                for g in self.grips:
                    jt = getattr(g, 'joint', None)
                    partners = [e.follower for e in jt._edges.values() if e.follower is not jt] if jt is not None else []
                    g.discard()
                    for f in partners:
                        for k in self.gripkeys:
                            f._params.pop(k, None)
                self.grips = []
            self.grip = grip
            self.drag = drag
            self.release = release

            def onpress(): # key press events
                def w():
                    pass
                    #if self.plr: self.plr.physics.yvel += self.plrjumppower if self.plr.physics.touch[1] and abs(self.plr.physics.yvel) < self.plr.physics.mass*0.2 else 0
                def q():
                    self.session.running = False
                def f():
                    self.enemy.transform.x = self.plr.transform.x - self.plr.transform.xlen()*2
                    self.enemy.transform.y = self.plr.transform.y + self.plr.transform.ylen()+1
                    self.enemy.transform.rotation = -90
                def r():
                    self.session.autodim = not self.session.autodim
                def t():
                    if self.plr: self.plr.rendering.show = not self.plr.rendering.show
                def p():
                    self.world.pausephysics = not self.world.pausephysics
                    self.psp.rendering.show=world.pausephysics
                def x():
                    ax, ay = self.w2(*inp.mouse)
                    world.launch(lambda scene: explode(scene=scene,x=ax,y=ay,timer=0.3,radius=50,force=1000))
                for but in [w,q,f,r,t,p,x]:
                    def close():
                        self.session.running = False
                    inp.onpress(but.__name__, but)
            onpress()

        def update(self):   #UPDATE
            sc = self.scene
            inp = self.session.inp
            cmspeed = self.camspeed*((sc.dimx+sc.dimy)/100)

            def whilepressed(): # key hold events
                def k(but):
                    return inp.held(but, delay=0.2)
                if(k('e')):
                    self.plr.physics.avel += 1
                if(k('w')):
                    self.tary += cmspeed/2
                    #if self.plr: self.plr.yvel += self.plrspeed if abs(self.plr.yvel) < self.plrmaxspeed else 0
                    if self.plr: self.plr.physics.yvel += self.plrjumppower if self.plr.physics.grounded and abs(self.plr.physics.yvel) < self.plr.physics.mass*0.2 else 0
                if(k('s')):
                    self.tary += -cmspeed/2
                    #if self.plr: self.plr.yvel += -self.plrspeed if abs(self.plr.xvel) < self.plrmaxspeed else 0
                if(k('d')):
                    self.tarx += cmspeed
                    if self.plr: self.plr.physics.xvel += self.plrspeed if abs(self.plr.physics.xvel) < self.plrmaxspeed else 0
                if(k('a')):
                    self.tarx += -cmspeed
                    if self.plr: self.plr.physics.xvel += -self.plrspeed if abs(self.plr.physics.xvel) < self.plrmaxspeed else 0
                if(k('c')):
                    ax, ay = self.w2(*inp.mouse)
                    self.push.transform.x = ax - self.push.transform.xc()
                    self.push.transform.y = ay + self.push.transform.yc()
                    self.push.rendering.show = True
                    self.push.force.apply(ax,ay)
                else:
                    self.push.rendering.show = False
                if(k('up')): sc.dimyoffset += 1#self.tary += self.camspeed/2
                if(k('down')): sc.dimyoffset += -1#self.tary += -self.camspeed/2
                if(k('right')): sc.dimxoffset += 1#self.tarx += self.camspeed
                if(k('left')): sc.dimxoffset += -1#self.tarx += -self.camspeed
            whilepressed()

            # fell below the void: put it back at the origin. Jointed objects go back together
            # (one rigid move, velocities cleared); resetting them one at a time left the others
            # far below, and the joints then flung everything apart.
            done = set()
            for o in list(self.scene.objs):
                if id(o) in done or not (hasattr(o, 'physics') and o.transform.y<self.void):
                    continue
                jt = getattr(o, 'joint', None)
                members = jt.group() if jt is not None else [o]
                done.update(id(m) for m in members)
                if jt is not None and len(members) > 1:
                    jt.teleport(-o.transform.x, -o.transform.y)
                else:
                    o.transform.y=0;o.transform.x=0
                    o.physics.xvel = o.physics.yvel = o.physics.avel = 0
            if self.plr:
                self.plr.physics.xvel *= self.plrspeedfriction
                #self.plr.physics.yvel *= self.plrspeedfriction

        def final(self):    #FINAL
            sc = self.scene
            inp = self.session.inp

            # camera follow
            camtarx = (inp._mouse_x-sc.dimx/2)*0
            camtary = (-inp._mouse_y+sc.dimy/2)*0
            #sc.dimxoffset += ((camtarx)-sc.dimxoffset)/self.camrange
            #sc.dimyoffset += ((camtary)-sc.dimyoffset)/self.camrange
            if self.plr:
                sc.follow(self.plr, smooth=self.camrange, offset=(camtarx, camtary))
                self.tarx, self.tary = sc.focus(self.plr)
            else:
                sc.follow(self.tarx, self.tary, smooth=self.camrange, offset=(camtarx, camtary))

            if hasattr(self, 'info'):
                self.info.transform.x = sc.camx
                self.info.transform.y = sc.camy
            if hasattr(self, 'psp'):
                self.psp.transform.x = sc.camx
                self.psp.transform.y = sc.camy-1
            if self.pen.pen.active:
                self.pen.pen.move(*self.w2(inp._mouse_x, inp._mouse_y))
            tp = self.tpen.pen
            if tp.active:
                tp.move(*self.w2(inp._mouse_x, inp._mouse_y))
                so = tp.current_obj
                if hasattr(so, 'physics'):
                    trail = {q: i for i, q in enumerate(tp.trail())}
                    found = []
                    hits = so.physics.collides([s for s in sc.solids if s is not so], full=True)
                    for o, inter in hits.items():
                        op = o.physics
                        if not op.phantom and o not in self.tgrab:
                            entry = min(inter, key=lambda q: trail.get(q, len(trail)))
                            found.append((trail.get(entry, len(trail)), o, entry))
                    found.sort(key=lambda f: f[0])
                    for _, o, entry in found:
                        if self.tgrab:
                            # world point (cell centre) where the stroke entered o
                            self.tpts[(id(self.tgrab[-1]), id(o))] = (entry[0] + 0.5, entry[1] - 0.5)
                        self.tgrab.append(o)
            if inp.mouseheld(2):
                self.pen.pen.cut(
                    *self.w2(inp._mouse_x, inp._mouse_y),
                    r=0, when=lambda o: hasattr(o, 'physics')
                )

            ep = self.epen.pen
            if inp.held('z', delay=0.2):
                wx, wy = self.w2(inp._mouse_x, inp._mouse_y)
                self.erase(wx, wy)
                ep.cutcommit(r=self.esize, keep=True, hitbox=False)
                self.cursor.transform.x = round(wx) - self.curx
                self.cursor.transform.y = round(wy) + self.cury
                self.cursor.rendering.show = True
                self.erasing = True
            elif self.erasing:
                ep.cancel()
                self.cursor.rendering.show = False
                self.erasing = False

            if inp.held('g', delay=0.2):
                gx, gy = self.w2(inp._mouse_x, inp._mouse_y)
                if not self.gripping:
                    self.grip(gx, gy)
                    if self.grips:
                        self.gripping = True
                    else:
                        self.nogrip = True
                self.drag(gx, gy)
                self.cursor.transform.x = round(gx) - self.curx
                self.cursor.transform.y = round(gy) + self.cury
                self.cursor.rendering.show = True
            elif self.gripping or self.nogrip:
                self.release()
                self.gripping = False
                self.nogrip = False
                self.cursor.rendering.show = False

            self.session.dinfo = [sc.recomp.sub('', x) for x in sc.dinfo]

    #LAUNCH THE SCENES
    main_handle = main_world.launch(main)

    ww = main_session.World(False)
    class m():
        def start(self, scene, session):
            scene.bgcolor = (30, 0, 0)
            st = session.style
            scene.obj().create('hey\nhow are you\nyou knew that you can have millions of worlds in one terminal session?\nalso with '+st('c', 0)+st('o', 2)+st('l', 3)+st('o', 5)+st('r', 6)+st('s', 7)+st('!', 'violet'))
    ww.launch(m)

    #RUN THE SESSION MAIN LOOP (SYNCHRONOUSLY)
    main_session.run()

attempt(dev)
