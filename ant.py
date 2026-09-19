from ttyengine import launcher

ses = launcher.Session()
wor = ses.World()

class main:
    def start(self, scene, session):
        o = scene.obj
        inp = session.inp
        st = session.style
        self.startup = o().create('\n\nMove with WASD keys. Change FPS by E/Q. Pause with SPACE. Click to summon ant there.', z=20)
        self.pause = False
        
        self.pixels = []
        self.solids = []
        def pix(mx,my,data):
            wx = ((mx + ((scene.camx+0.5)//2*2))+0.5) // 2 * 2
            wy = scene.iround(-my + scene.camy)
            delet = False
            for pxi in self.pixels:
                pxit = pxi.transform
                if pxit.x == wx and pxit.y == wy:
                    pxi.discard()
                    self.pixels.remove(pxi)
                    delet = True
            if not delet:
                self.pixels.append(o().create(st('██', 'orange'), wx, wy, rotation=0, z=10, aspect=1, dynamic=False, crot=0))
            if self.startup:
                self.startup.discard()
                self.startup = None
        inp.onmouse('click', pix)
        def pas():
            self.pause = not self.pause
        inp.onpress('space', pas)
        inp.onpress('q', exit)

        self.infobj = o().create()
        self.steps = 0
        scene.framerate = 60

        self.datobj = o().create('FPS: ' + str(int(scene.framerate)) + ('  PAUSED' if self.pause else ''), scene.camx+4, scene.camy, z=20)
    def final(self, scene, session):
        inp = session.inp
        camspeed = (60 / max(1, scene.framerate)) * 0.15 *((scene.dimx+scene.dimy)/25)
        scene.camx+=(inp.held('d')-inp.held('a'))*camspeed
        scene.camy+=(inp.held('w')-inp.held('s'))*(camspeed*0.5)
        frmspeed = 1
        scene.framerate+=(inp.held('e')-inp.held('q'))*(frmspeed)
        if not self.pause:
            for p in self.pixels:
                t = p.transform
                op = p.physics.collides(self.solids)
                if op:
                    p.crot = (p.crot - 90) % 360
                    to_remove = [sol for sol in self.solids if round(sol.transform.x) == t.x and round(sol.transform.y) == t.y]
                    for sol in to_remove:
                        sol.discard()
                        self.solids.remove(sol)
                else:
                    p.crot = (p.crot + 90) % 360
                    self.solids.append(scene.obj().create('██', t.x, t.y, dynamic=False))
                fx, fy = t.forward(angle=p.crot)
                fx, fy = scene.iround(fx), scene.iround(fy)
                t.x = t.x+(fx)*2
                t.y = t.y+(fy)
            if self.pixels:
                self.steps += 1
                self.infobj.transform.text = str(self.steps)+' steps.'
        self.infobj.transform.x, self.infobj.transform.y = scene.camx, scene.camy
        self.datobj.create('FPS: ' + str(int(scene.framerate)) + ('  PAUSED' if self.pause else ''), scene.camx + self.infobj.transform.xlen() + 4, scene.camy, z=20)
        if self.startup:
            self.startup.create(x=scene.camx,y=scene.camy)

wor.launch(main)
ses.run()
