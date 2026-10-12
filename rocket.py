from ttyengine.launcher import Session, attempt
import math, random, os
cwd = os.getcwd()

lost = False
plr = None

game_id = 0

tracked = []

def track(o):
    if o is None or o in tracked:
        return o
    tracked.append(o)
    try:
        o.ondiscard(lambda: tracked.remove(o) if o in tracked else None)
    except Exception:
        pass
    return o

def kill(o):
    try:
        if o is not None and hasattr(o, 'transform'):
            o.discard()
    except Exception:
        pass

def cleanup():
    for o in list(tracked):
        kill(o)
    tracked.clear()

ginfo = [0, 0]
class ginf():
    def upd(self):
        sc = self.scene
        style = self.style
        new_txt = f'SHOTS :   {ginfo[0]}       HITS :   {ginfo[1]}'
        if new_txt != self._last_txt or self._lost != lost or self.info is None:
            self._last_txt = new_txt
            self._lost = lost
            kill(self.info)
            self.info = track(sc.obj().create(
                style(new_txt, color='darkorange', alpha=0.5 if lost else 1, size=1, width=500),
                z=30))
        t = self.info.transform
        t.x = sc.camx + sc.iround((sc.dimx - t.xlen()) / 2)
        t.y = sc.camy - sc.dimy + t.ylen()

    def start(self, scene, session):
        self.gid = game_id
        self.scene = scene
        self.style = session.style
        self.info = None
        self._last_txt = None
        self._lost = lost

    def final(self, scene, handle):
        if self.gid != game_id:
            kill(self.info)
            handle.cancel()
            return
        self.upd()

class fade():
    def __init__(self, obj, delay=0, time=2, alpha=1, bgalpha=1, callback=None, appear=False, discard=False):
        self.obj = obj
        self.dis = discard
        self.delay = delay
        self._st = time
        self.time = time
        self.alpha = alpha
        self.bgalpha = bgalpha
        self.cb = callback
        self.appear = appear
    def start(self, handle, session, world):
        if hasattr(self.obj, '_fading') or not hasattr(self.obj, 'transform'):
            handle.cancel()
            return
        self.obj._fading = True
        if hasattr(self.obj, '_fadeprogress'):
            self.time *= self.obj._fadeprogress
        else:
            self.obj._fadeprogress = 1
        self.t = self.obj.transform
        self.s = world.scene.styler.style
        def inh(parts):
            for p in parts:
                track(p)
            if parts[0] == self.obj:
                return
            else:
                handle.cancel()
            for p in parts:
                p._fadeprogress = self.obj._fadeprogress
                world.launch(lambda p=p: fade(p, self.delay, self._st, self.alpha, self.bgalpha, self.cb, self.appear, self.dis))
        self.t.onsplit(inh)
        self.lerp(self.obj._fadeprogress)
    def lerp(self, progress, init=False):
        progress = 1-progress if self.appear else progress
        if not init:
            self.obj._fadeprogress = progress
        ct = self.t.vrtext
        new_alpha = self.alpha * progress
        new_bgalpha = self.bgalpha * progress
        self.t.vrtext = self.s(ct, alpha=new_alpha, bgalpha=new_bgalpha, onbg=True, clean=True)
        self.t.rotate(self.t.rotation, True)
        self.t.vrtext = ct
    def final(self, scene, session, handle):
        if self.obj is None or not hasattr(self.obj, 'transform'):
            handle.cancel()
            return
        if self.delay > 0:
            self.delay -= 1/scene.framerate
            return
        if self.time <= 0:
            self.lerp(0)
            delattr(self.obj, '_fading')
            if self.cb: self.cb()
            if self.dis: self.obj.discard()
            handle.cancel()
            return
        self.time -= 1/scene.framerate
        progress = max(0, self.time / self._st)
        self.lerp(progress)

class explode():
    def __init__(self, x, y, delay=0, time=0.5, radius=25, force=100, callback=None, explode=True):
        self.pos = (x,y)
        self.radi = radius
        self.forc = force
        self.begin = time
        self.timer = self.begin
        self.delay = delay
        self.exp = explode
        self.cb = callback
    def start(self, scene):
        self.bomb = scene.obj().create(z=10, force=self.forc * self.radi, cap=self.forc, radius=self.radi) # bomb
        if self.exp: self.bomb.force.apply(*self.pos)
    def final(self, scene, handle, session):
        if self.delay > 0:
            self.delay -= 1/scene.framerate
            return
        if self.timer <= 0:
            if self.cb:
                self.cb()
            self.bomb.discard()
            handle.cancel()
            return
        self.timer -= 1/scene.framerate
        t = self.bomb.transform
        ex = self.bomb.force
        delta = max(0, self.timer/self.begin)
        t.text = session.style(scene.styler.shapes.circle((ex.radius/2)*(1-delta), 'X', aspect=scene.aspect), alpha=min(1,ex.cap/20)*delta, color='orange', bgcolor=scene.bgcolor)
        t.x, t.y = self.pos
        t.x -= t.xlen()/2
        t.y += t.ylen()/2

class flash():
    def __init__(self, scene, session, delay=0, time=1, tar=None, st=None):
        self.de = delay
        self._sti = time
        self.ti = time
        self.tar = tar if tar else scene.bgcolor
        self.st = st if st else session.fgcolor
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
    def start(self, scene, handle, session, world):
        self.a = None
        self.gid = game_id
        if not hasattr(plr, 'transform'):
            handle.cancel()
            return
        r = random.randrange
        style = session.style
        pt = plr.transform
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
        self.a = track(scene.obj().create(style(txt, color='gray', alpha=al), x+pt.x, y+pt.y, avel=r(-180,180), xvel=r(-10,10), yvel=r(-10,10)))
        self.a.forvanish = {'delay': 0.5, 'time': 2, 'alpha': al, 'discard': True}
        self.a.imast = True
        self.a.ast = True
        def ont(obj2, inter):
            global lost
            if self.gid != game_id: return
            if obj2.physics.phantom or hasattr(obj2, 'imast'): return
            if obj2 == plr:
                self.a.physics.offtouch(ont)
                if not lost: ginfo[1] += 1
                scene.pending.append(lambda: setattr(self.a.physics, 'phantom', True) if hasattr(self.a, 'physics') else None)
                if hasattr(self.a, 'imast'):
                    delattr(self.a, 'imast')
                if hasattr(self.a, 'forvanish'):
                    world.launch(lambda: fade(self.a, **self.a.forvanish))
                handle.cancel()
            t = self.a.transform
            olx,oly = t.x,t.y
            fx,fy = t.forward(1,angle=t.aim(obj2))
            t.x += fx
            t.y += fy
            intr = self.a.physics.collides(obj2)
            intr = next(iter(intr.values()), None) if isinstance(intr, dict) else None
            if intr:
                for wx,wy in intr:
                    obj2.transform.cut(wx,wy)
            obj2.transform.split()
            t.x,t.y = olx,oly
            for xi, yi in inter:
                world.launch(lambda: explode(xi, yi, time=0.3, radius=15, force=50, explode=False))
                break
        self.a.physics.ontouch(ont)
    def update(self, handle):
        if self.gid != game_id:
            kill(self.a)
            handle.cancel()
            return
        try:
            t = self.a.transform
            p = self.a.physics
            f = t.forward(0.5, 0, t.aim(plr))
            p.xvel += f[0]
            p.yvel += f[1]
        except:
            if self.a:
                self.a.discard()
            handle.cancel()
            return

class player():
    def init(self, scene, session, world, handle, sound):
        global plr
        inp = session.inp
        style = session.style
        scene.gravity = (0,0)
        scene.drag = 1
        self.smcam = 5
        self.lsinfo = None
        self.lsy = 10
        self.started = False
        gid = game_id

        plr = track(scene.obj().create(style('''
    █
   ███
  ██ ██
 ██   ██
██     ██''', color='brightblue'),dynamic=True, hitbox=False, mass=50))
        t = plr.transform
        p = plr.physics
        self.thrustspeed = 0.1*p.mass
        self.thrustmax = 3*p.mass
        self.thrustbreak = 0.9

        def trigger_lost():
            global lost
            if self.lsinfo or gid != game_id:
                return
            lost = True
            self.smcam = 20
            lsinfo = track(scene.obj().create(
                style('YOU LOST!', size=2, color='black', bgcolor='red') + '\n' +
                style('PRESS R TO RESET', color='black', bgcolor='red'),
                z=20, renderspaces=True))
            lst = lsinfo.transform
            lst.x = scene.camx + scene.iround((scene.dimx - lst.xlen()) / 2)
            lst.y = scene.camy - scene.iround(scene.dimy / 4) + scene.iround(lst.ylen() / 2)
            world.launch(lambda: fade(lsinfo, 0, 2, appear=True))
            self.lsinfo = lsinfo
        self.trigger_lost = trigger_lost

        def swslf(ps):
            global plr
            if gid != game_id:
                return
            for par in ps:
                track(par)
            ac = None
            for par in ps:
                if hasattr(par, 'physics') and (ac is None or par.physics.mass > ac.physics.mass):
                    ac = par
            for pr in [pr for pr in ps if pr != ac]:
                if hasattr(pr, 'physics'):
                    pr.physics.phantom = True
            plr = ac
            if plr:
                p = plr.physics
                self.thrustspeed = 0.1 * p.mass
                self.thrustmax = 3 * p.mass
                self.thrustbreak = 0.9
                plr.transform.onsplit(swslf)
        t.onsplit(swslf)

        self.camtarx = scene.camx
        self.camtary = scene.camy
        def camfollow(x=None, y=None, smooth=1):
            if x is not None: self.camtarx = x
            if y is not None: self.camtary = y
            ir = int
            xdelta = ((ir(self.camtarx)-ir(scene.dimx/2))-ir(scene.camx))/smooth
            ydelta = ((ir(self.camtary)+ir(scene.dimy/2))-ir(scene.camy))/smooth
            scene.camx += xdelta
            scene.camy += ydelta
            return xdelta, ydelta
        self.camfollow = camfollow
        camfollow(t.x+t.xc(), t.y-t.yc())

        self.info = track(scene.obj().create(session.style('ZOOM OUT BY "CTRL" + "-", QUIT BY "Q", START GAME BY "F"', color='black', bgcolor='white'), renderspaces=True))
        self._ad = -1

        def shoot():
            t = plr.transform
            p = plr.physics
            sx, sy = t.forward(t.ylen())
            spawn_x = t.x + t.xc() + sx
            spawn_y = t.y - t.yc() + sy
            bullet = track(scene.obj().create(style('●', color='yellow', bgcolor='yellow'), spawn_x, spawn_y, rotation = t.rotation, mass=0, phantom=True))
            bt = bullet.transform
            bp = bullet.physics
            for i, d in enumerate(t.forward(3)):
                if i==0: bp.xvel += d
                else: bp.yvel += d
            def destroy(obj2, points):
                global lost
                ph = obj2.physics
                tr = obj2.transform
                if hasattr(obj2, 'imast'):
                    if not lost: ginfo[0] += 1
                    ph.phantom = True
                    delattr(obj2, 'imast')
                tr.cutpoints(points)
                vanish_data = getattr(obj2, 'forvanish', None)
                tr.split()
                if vanish_data:
                    world.launch(lambda: fade(obj2, **vanish_data))
            def dis():
                maxi = 1
                if abs(bp.xvel) <= maxi and abs(bp.yvel)*1/bt.scene.aspect <= maxi:
                    bullet.discard()
            bp.ontouch(destroy, when=lambda o: o is not plr)
            world.launch(lambda: fade(bullet, 0.5, 1, callback=bullet.discard))
        self._shoot = shoot
        self._shoot_delay = 0

    def start(self, scene, session, world, handle, sound):
        inp = session.inp

        self.init(scene, session, world, handle, sound)

        def close(): session.running = not session.running
        inp.onpress('q', close, True)

        def onf():
            if self.started:
                return
            self.started = True
            self._ad = 0
            world.launch(lambda scene, session: flash(scene, session, time=0.5, st=(255,255,255)))
            if hasattr(self.info, 'transform'):
                self.info['text'] = session.style('STARTED!', size=3, color='white', bgcolor='blue')
                world.launch(lambda: fade(self.info, 0.5, 0.5, callback=self.info.discard))
                world.launch(ginf)
        inp.onpress('f', onf, True)

        music = sound.play('rocket.mp3', loop=True) if os.path.exists(os.path.join(cwd, 'rocket.mp3')) else None

        def reset_game():
            global lost, game_id
            if lost:
                game_id += 1
                cleanup()
                if music: music.play()
                ginfo[0] = 0
                ginfo[1] = 0
                lost = False
                self.init(scene, session, world, handle, sound)
        inp.onpress('r', reset_game, True)

    def update(self, scene, session, world, handle):
        global plr
        if self.started and not self.lsinfo:
            if not hasattr(plr, 'transform') or plr.physics.mass <= 8:
                self.trigger_lost()
        if not hasattr(plr, 'transform'):
            return
        inp = session.inp
        t = plr.transform
        p = plr.physics

        if not self.lsinfo:
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

            if self._shoot_delay > 0:
                self._shoot_delay -= 1/scene.framerate
            if inp.mouseheld(0) and self._shoot_delay <= 0:
                self._shoot_delay = 0.2
                self._shoot()

        if self._ad > 0:
            self._ad -= 1/scene.framerate
        if self._ad <= 0 and self._ad != -1:
            self._ad = 1
            world.launch(lambda: asteroid())

        self.camfollow(t.x+t.xc(), t.y-t.yc(), self.smcam)
        if hasattr(self.info, 'transform'):
            self.info.transform.x, self.info.transform.y = 0+scene.camx, 0+scene.camy
        if hasattr(self.lsinfo, 'transform'):
            lst = self.lsinfo.transform
            lst.x = scene.camx + scene.iround((scene.dimx - lst.xlen()) / 2)
            lst.y = scene.camy - scene.iround(scene.dimy / 4) + scene.iround(lst.ylen() / 2)
        if not self.lsinfo:
            p.avel = t.alerp(t.point(inp._mouse_x + scene.camx - t.xc(), scene.camy - inp._mouse_y + t.yc()))*plr.physics.mass

class background():
    def start(self):
        self.density = 0.08
        self.s = []
        self._per = 0

    def _spawn(self, scene, session, world, x, y):
        r = random.random
        st = session.style
        alpha = round(r() * 0.5 + 0.4, 1)
        text = st('★', alpha=alpha)
        star = scene.obj().create(text, x=x, y=y, z=-10)
        world.launch(lambda: fade(star, 0, 0.3, alpha, 1, lambda: world.launch(lambda: fade(star, 1, 1, alpha, 1, star.discard)), True))
        star.ondiscard(lambda: self.s.remove(star) if star in self.s else None)
        self.s.append(star)

    def update(self, scene, session, world):
        for s in list(self.s):
            if abs(s.transform.x - scene.camx) > scene.dimx or abs(s.transform.y - scene.camy) > scene.dimy:
                s.discard()

        limit = int(scene.dimx * scene.dimy * self.density)
        current = len(self.s)
        if current >= limit:
            return

        self._per -= 1 / scene.framerate
        if self._per > 0:
            return
        self._per = 0.005 + (current / limit) * 0.05

        r = random.random
        self._spawn(scene, session, world,
                    x=scene.camx + r() * scene.dimx,
                    y=scene.camy - r() * scene.dimy)


def d():
    se = Session()
    w = se.World()
    h = w.launch(player)
    hbg = w.launch(background)
    se.run()
attempt(d)
