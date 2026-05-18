from ttyengine.launcher import Session, attempt
import math, random
from ttyengine.debugger import debug
dinfo = None
#_d, dinfo = debug()

ginfo = [0, 0]
class ginf():
    def upd(self):
        sc = self.scene
        style = self.style
        txt = f'SHOTS :   {ginfo[0]}       HITS :   {ginfo[1]}'
        self.info.create(style(txt, color='darkorange', size=1, width=500))
        t = self.info.transform
        t.x = sc.camx+sc.dimx/2-t.xlen()/2
        t.y = sc.camy-sc.dimy+t.ylen()
    def start(self, scene, session):
        self.scene = scene
        self.style = session.style
        self.info = scene.obj()
    def final(self, scene, handle):
        if len(ginfo) < 2:
            handle.cancel()
            return
        self.upd()

class vanish():
    def __init__(self, obj, delay=0, time=2, alpha=1, bgalpha=1):
        self.obj = obj
        self.delay = delay
        self._st = time
        self.time = time
        self.alpha = alpha
        self.bgalpha = bgalpha
    def start(self, handle, session, scene):
        if hasattr(self.obj, '_vanishing') or not hasattr(self.obj, 'transform'):
            handle.cancel()
            return
        self.obj._vanishing = True
        self.ct = self.obj.transform.vrtext
    def update(self, scene, session, handle):
        if self.obj is None or not hasattr(self.obj, 'transform'):
            handle.cancel()
            return
        if self.delay > 0:
            self.delay -= 1/scene.framerate
            return
        if self.time <= 0:
            self.obj.transform.vtext = session.style(self.ct, alpha=0, bgalpha=0, clean=True)
            self.obj.discard()
            handle.cancel()
            return
        self.time -= 1/scene.framerate
        progress = max(0, self.time / self._st)
        new_alpha = self.alpha * progress
        new_bgalpha = self.bgalpha * progress
        self.obj.transform.vtext = session.style(self.ct, alpha=new_alpha, bgalpha=new_bgalpha, clean=True)

class flash():
    def __init__(self, scene, delay=0, time=1, tar=(0,0,0), st=None):
        self.de = delay
        self._sti = time
        self.ti = time
        self.tar = tar
        self.st = st if st else scene.bgcolor
    def update(self, scene, handle):
        if self.de > 0:
            self.de -= 1/scene.framerate
            return
        if self.ti <= 0:
            handle.cancel()
            scene.bgcolor = self.tar
            return
        self.ti -= 1/scene.framerate
        p = 1 - (max(0, self.ti) / self._sti)
        fin = []
        for i in range(3):
            val = int(self.st[i] + (self.tar[i] - self.st[i]) * p)
            fin.append(min(255, max(0, val)))
        scene.bgcolor = tuple(fin)

class asteroid():
    def __init__(self, plr):
        self.plr = plr
    def start(self, scene, handle, session, world):
        r = random.randrange
        style = session.style
        pt = self.plr.transform
        minw = 2; maxw = 10
        minh = 1; maxh = 5
        def row(): return ('█'*r(minw, maxw))
        ro = ''
        txt = ''
        for i in range(minh,maxh):
            sp = ''.join([p for p in ro if p == ' '])
            pro = ''.join([p for p in ro if p != ' '])
            ro = sp+' '*max(0, len(pro)-1-r(0,maxw-1)) + row()
            txt += ro+'\n'
        dr = r(-180, 180)
        x, y = pt.forward(r(70, 100), 0, dr)
        al = r(7, 10)/10
        self.a = scene.obj().create(style(txt, color='gray', alpha=al), x+pt.x, y+pt.y, rotation=r(-180,180)*0, xvel=r(-10,10)*0, yvel=r(-10,10)*0)
        self.a.forvanish = {'delay': 0.5, 'time': 2, 'alpha': al}
        self.a.imast = True
        def ont(obj2, inter):
            if obj2.physics.phantom or hasattr(obj2, 'imast'): return
            handle.cancel()
            if hasattr(self.a, 'imast'):
                delattr(self.a, 'imast')
            scene.pending.append(lambda: setattr(self.a.physics, 'phantom', True))
            if obj2 == self.plr:
                ginfo[1] += 1
            def spl(ps, ob=obj2):
                if hasattr(ob, 'forvanish'):
                    for p in ps:
                        world.launch(lambda: vanish(p, **ob.forvanish))
            obj2.transform.split_at(obj2.transform.tolocal(inter), spl)
            if hasattr(self.a, 'forvanish'):
                world.launch(lambda: vanish(self.a, **self.a.forvanish))
        self.a.physics.ontouch(ont, when=lambda o: hasattr(o, 'physics'), once=True)
    def update(self, handle):
        try:
            t = self.a.transform
            p = self.a.physics
            f = t.forward(0.5, 0, t.aim(self.plr))
            p.xvel += f[0]
            p.yvel += f[1]
        except: handle.cancel(); return

class player():
    def start(self, scene, session, world, handle):
        inp = session.inp
        style = session.style
        scene.gravity = (0,0)
        scene.drag = 1

        self.rocket = scene.obj().create(style('''
    █    
   ███   
  ██ ██  
 ██   ██ 
██     ██''', color='brightblue'),dynamic=True, hitbox=False, mass=50)
        t = self.rocket.transform
        p = self.rocket.physics
        self.thrustspeed = 0.1*p.mass
        self.thrustmax = 3*p.mass
        self.thrustbreak = 0.9
        def swslf(ps):
            ac = None
            for par in ps:
                if hasattr(par, 'physics') and (ac==None or par.physics.mass > ac.physics.mass):
                    ac = par
            self.rocket = ac
            if self.rocket:
                t = self.rocket.transform
                p = self.rocket.physics
                self.thrustspeed = 0.1*p.mass
                self.thrustmax = 3*p.mass
                self.thrustbreak = 0.9
                self.rocket.transform.onsplit(swslf)
            else: handle.cancel()
        t.onsplit(swslf)

        self.camtarx = scene.camx
        self.camtary = scene.camy
        def camfollow(x=None, y=None, smooth=1):
            if x is not None: self.camtarx = x
            if y is not None: self.camtary = y
            xdelta = ((self.camtarx-scene.dimx/2)-scene.camx)/smooth
            ydelta = ((self.camtary+scene.dimy/2)-scene.camy)/smooth
            scene.camx += xdelta
            scene.camy += ydelta
            return xdelta, ydelta
        self.camfollow = camfollow
        
        self.info = scene.obj().create(session.style('ZOOM OUT BY "CTRL" + "-"', color='black', bgcolor='white'), renderspaces=True)
        self._ad = -1
        def onf():
            self._ad = 0
            world.launch(lambda scene: flash(scene, time=0.5, st=(255,255,255)))
            if hasattr(self.info, 'transform'):
                self.info['text'] = style('STARTED!', size=3, color='white', bgcolor='blue')
                world.launch(lambda: vanish(self.info, 0.5, 0.5))
                world.launch(ginf)
        session.inp.onpress('f', lambda e: onf(), True)
        
        def shoot():
            t = self.rocket.transform
            p = self.rocket.physics
            sx, sy = t.forward(t.ylen())
            spawn_x = t.x + t.xc() + sx
            spawn_y = t.y - t.yc() + sy
            bullet = scene.obj().create(style('●', color='yellow', bgcolor='yellow'), spawn_x, spawn_y, rotation = t.rotation, mass=0, phantom=True)
            bt = bullet.transform
            bp = bullet.physics
            for i, d in enumerate(t.forward(3)):
                if i==0: bp.xvel += d
                else: bp.yvel += d
            def destroy(obj2, points):
                if hasattr(obj2, 'imast'):
                    ginfo[0] += 1
                    if hasattr(obj2, 'physics'):
                        obj2.physics.phantom = True
                    delattr(obj2, 'imast')
                obj2.transform.cutpoints(points)
                vanish_data = getattr(obj2, 'forvanish', None)
                if not vanish_data:
                    obj2.transform.split()
                    return
                def vn(parts):
                    for p in parts:
                        p.forvanish = vanish_data
                        world.launch(lambda p=p, vd=vanish_data: vanish(p, **vd))
                res = obj2.transform.split(vn)
                if res is None:
                    world.launch(lambda: vanish(obj2, **vanish_data))
            def dis():
                maxi = 1
                if abs(bp.xvel) <= maxi and abs(bp.yvel)*1/bt._aspect <= maxi:
                    bullet.discard()
            bp.ontouch(destroy, when=lambda o: o is not self.rocket)
            world.launch(lambda: vanish(bullet, 0.5, 1))
        self._shoot = shoot
        self._shoot_delay = 0

        def close(): session.running = not session.running
        inp.onpress('q', lambda e: close(), True)

    def update(self, scene, session, world, handle):
        if not hasattr(self.rocket, 'transform'):
            handle.cancel()
            return
        inp = session.inp
        t = self.rocket.transform
        p = self.rocket.physics

        if inp.held('space'):
            p.xvel *= self.thrustbreak
            p.yvel *= self.thrustbreak
        dirs = {'w': 0, 's': 180, 'd': 90, 'a': -90}
        for key, off in dirs.items():
            if inp.held(key, True):
                f = t.forward(self.thrustspeed, off)
                p.xvel += f[0]
                p.yvel += f[1]
        speed = math.sqrt(p.xvel**2 + (p.yvel*2)**2)
        if speed > self.thrustmax:
            scale = self.thrustmax / speed
            p.xvel *= scale
            p.yvel *= scale
        p.avel = p.alerp(t.point(inp._mouse_x + scene.camx - t.xc(), scene.camy - inp._mouse_y + t.yc()))*self.rocket.physics.mass

        if self._shoot_delay > 0:
            self._shoot_delay -= 1/scene.framerate
        if inp.mouseheld(0) and self._shoot_delay <= 0:
            self._shoot_delay = 0.2
            self._shoot()

        if self._ad > 0:
            self._ad -= 1/scene.framerate
        if self._ad <= 0 and self._ad != -1:
            self._ad = 1
            world.launch(lambda: asteroid(self.rocket))
            
    def final(self, scene, world):
        t = self.rocket.transform
        self.camfollow(t.x+t.xc(), t.y-t.yc())
        if hasattr(self.info, 'transform'):
            self.info.transform.x, self.info.transform.y = 0+scene.camx, 0+scene.camy

        if dinfo is not None:
            dinfo.clear()
            dinfo.extend(str(world.handles))

class background():
    def start(self):
        self.limit = 15
        self.s = []
    def update(self, scene, session):
        l = 0
        for s in list(self.s):
            if abs(s.transform.x-scene.camx) > scene.dimx or abs(s.transform.y-scene.camy) > scene.dimy:
                self.s.remove(s)
                s.discard()
                continue
            l += 1
        if l >= self.limit: return
        c = lambda *args, **kwargs: scene.obj().create(*args, **kwargs)
        r = random.randrange
        st = session.style
        while l < self.limit:
            self.s.append(c(st('★', alpha=r(4, 9)/10), r(0, scene.dimx)+scene.camx, -r(0, scene.dimy)+scene.camy))
            l += 1
        

def d():
    se = Session()
    if dinfo is not None: se.inp.focused = False
    w = se.World()
    h = w.launch(player)
    hbg = w.launch(background)
    se.run()
attempt(d)
