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

def ghostplr(o):
    p = getattr(o, 'physics', None)
    if p is not None:
        p.ghost(lambda other: other is plr)

def vanish(o, *args, **kwargs):
    t = getattr(o, 'transform', None)
    if t is None:
        return None
    '''if getattr(o, 'ast', False):
        ghostplr(o)
        t.onsplit(lambda parts: [ghostplr(p) for p in parts])'''
    t.onsplit(lambda parts: [track(p) for p in parts])
    return t.fade(*args, **kwargs)

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
        width = r(20, 30)
        height = r(20, 30)
        cx, cy = width / 2.0, height / 1.0
        base_radius = min(cx, cy) * 0.85
        txt = ""
        for y in range(height):
            row_str = ""
            dy = y - cy
            for x in range(width):
                dx = (x - cx) * 1.8
                dist = math.sqrt(dx * dx + dy * dy)
                angle = math.atan2(dy, dx)
                noise = math.sin(angle * 4) * 2.2 + math.cos(angle * 7) * 1.5 + random.uniform(-0.8, 0.8)
                if dist <= (base_radius + noise):
                    row_str += "█"
                else:
                    row_str += " "
            txt += row_str.rstrip() + "\n"
        dr = r(-180, 180)
        x, y = pt.forward(r(70, 100), 0, dr)
        ox, oy = pt.pivot()
        al = r(7, 10)/10
        self.a = track(scene.obj().create(style(txt, color='gray', alpha=al), x+ox, y+oy, avel=r(-180,180), xvel=r(-10,10), yvel=r(-10,10)))
        self.a.forvanish = {'delay': 0.5, 'time': 1, 'discard': True}
        self.a.imast = True
        self.a.ast = True
        def ont(obj2, inter):
            global lost
            if self.gid != game_id: return
            if obj2.physics.phantom or hasattr(obj2, 'imast'): return
            if obj2 == plr:
                self.a.physics.offtouch(ont)
                for xi, yi in inter:
                    world.launch(lambda: explode(xi, yi, time=0.3, radius=15, force=50, explode=False))
                    break
                if not lost: ginfo[1] += 1
                scene.pending.append(lambda: setattr(self.a.physics, 'phantom', True) if hasattr(self.a, 'physics') else None)
                if hasattr(self.a, 'imast'):
                    delattr(self.a, 'imast')
                if hasattr(self.a, 'forvanish'):
                    vanish(self.a, **self.a.forvanish)
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

        '''thr1 = scene.obj().create(style('████████', color=(120,180,220)), dynamic=True)
        thr2 = scene.obj().create(style('████████', color=(120,180,220)), dynamic=True)
        def att(th, nu):
            th.create(yoffset=-abs(t.yc(t.rtext)))
            th.create(xoffset=-(abs(t.xc(t.rtext))-1)*(-1 if nu==2 else 1))
        att(thr1, 1)
        att(thr2, 2)
        t.onchange(lambda at: (att(thr1, 1) and att(thr2, 2)) if at=='rtext' else None)
        plr.add('joint')
        plr.joint.attach((thr1, thr2), 'fixed')'''

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
            lst.fade(1, time=2, start=0)
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

        scene.follow(plr)

        self.info = track(scene.obj().create(session.style('ZOOM OUT BY "CTRL" + "-", QUIT BY "Q", START GAME BY "F"', color='black', bgcolor='white'), renderspaces=True))
        self._ad = -1

        def shoot():
            t = plr.transform
            p = plr.physics
            px, py = t.pivot()
            sx, sy = t.forward(t.ylen(t.rtext))
            spawn_x = px + sx
            spawn_y = py + sy
            aim = t.point(inp._mouse_x + scene.camx, scene.camy - inp._mouse_y, origin=(spawn_x, spawn_y))
            bullet = track(scene.obj().create(style('●\n●\n●', color='yellow', bgcolor='yellow'), spawn_x, spawn_y, rotation = aim, mass=0, phantom=True))
            bt = bullet.transform
            bp = bullet.physics
            lx, ly = bt.pivot(True)
            bt.x = spawn_x - lx
            bt.y = spawn_y - ly
            for i, d in enumerate(t.forward(3, angle=aim)):
                if i==0: bp.xvel += d
                else: bp.yvel += d
            def destroy(obj2, points):
                global lost
                ph = obj2.physics
                tr = obj2.transform
                if hasattr(obj2, 'imast'):
                    if not lost: ginfo[0] += 1
                    if getattr(obj2, 'ast', False):
                        ghostplr(obj2)
                        tr.onsplit(lambda parts: [ghostplr(p) for p in parts])
                    delattr(obj2, 'imast')
                tr.cutpoints(points)
                vanish_data = getattr(obj2, 'forvanish', None)
                if vanish_data:
                    vanish(obj2, **vanish_data)
                tr.split()
            def dis():
                maxi = 1
                if abs(bp.xvel) <= maxi and abs(bp.yvel)*1/bt.scene.aspect <= maxi:
                    bullet.discard()
            bp.ontouch(destroy, when=lambda o: o is not plr)
            vanish(bullet, 0, time=1, delay=0.5, discard=True)
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
            scene.fade(scene.bgcolor, time=0.5, start=(255,255,255))
            if hasattr(self.info, 'transform'):
                self.info['text'] = session.style('STARTED!', size=3, color='white', bgcolor='blue')
                vanish(self.info, 0, time=0.5, delay=0.5, discard=True)
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

        if not self.lsinfo:
            p.avel = t.alerp(t.point(inp._mouse_x + scene.camx, scene.camy - inp._mouse_y)) * p.mass

    def final(self, scene):
        if hasattr(plr, 'transform'):
            scene.follow(plr, smooth=self.smcam)
        cx, cy = scene.iround(scene.camx), scene.iround(scene.camy)
        if hasattr(self.info, 'transform'):
            self.info.transform.x, self.info.transform.y = cx, cy
        if hasattr(self.lsinfo, 'transform'):
            lst = self.lsinfo.transform
            lst.x = cx + scene.iround((scene.dimx - lst.xlen()) / 2)
            lst.y = cy - scene.iround(scene.dimy / 4) + scene.iround(lst.ylen() / 2)

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
        star.transform.fade(1, time=0.3, start=0, callback=lambda: vanish(star, 0, time=1, delay=1, discard=True))
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
