from ttyengine import launcher
import time

ses = launcher.Session()
wor = ses.World()
#ses.debug()

class main:
    def start(self, scene, session):
        o = scene.obj
        inp = session.inp
        st = session.style
        self.scene = scene
        self.st = st
        self.startup = o().create('\n\nMove with WASD keys. Change FPS by E/Q. Pause with SPACE. Click to toggle cell.', z=20)
        self.pause = True
        
        self.pixels = {}

        def pix(mx, my, data):
            wx = ((mx + ((scene.camx+0.5)//2*2))+0.5) // 2 * 2
            wy = scene.iround(-my + scene.camy)
            
            pos = (wx, wy)
            if pos in self.pixels:
                self.pixels[pos].discard()
                del self.pixels[pos]
            else:
                self.pixels[pos] = o().create(st('██', 'orange'), wx, wy, rotation=0, z=10, aspect=1)

            if self.startup:
                self.startup.discard()
                self.startup = None

        inp.onmouse('click', pix)

        def pas():
            self.pause = not self.pause
        inp.onpress('space', pas)
        inp.onpress('x', exit)

        self.infobj = o().create()
        self.steps = 0
        scene.framerate = 30
        self.last_step = time.time()

        self.datobj = o().create('FPS: ' + str(int(scene.framerate)) + ('  PAUSED' if self.pause else ''), scene.camx+4, scene.camy, z=20)

    def final(self, scene, session):
        inp = session.inp
        camspeed = (60 / max(1, scene.framerate)) * 0.15 *((scene.dimx+scene.dimy)/25)
        scene.camx += (inp.held('d') - inp.held('a')) * camspeed
        scene.camy += (inp.held('w') - inp.held('s')) * (camspeed * 0.5)
        
        scene.framerate = max(1, scene.framerate + (inp.held('e') - inp.held('q')))
        
        interval = 1.0 / scene.framerate
        now = time.time()

        if not self.pause and (now - self.last_step) >= interval:
            self.last_step = now
            
            alive = set(self.pixels.keys())
            neighbor_counts = {}

            for x, y in alive:
                for dx in (-2, 0, 2):
                    for dy in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        pos = (x + dx, y + dy)
                        neighbor_counts[pos] = neighbor_counts.get(pos, 0) + 1

            next_alive = set()
            for pos, count in neighbor_counts.items():
                if count == 3 or (count == 2 and pos in alive):
                    next_alive.add(pos)

            dying = alive - next_alive
            birthing = next_alive - alive

            for pos in dying:
                self.pixels[pos].discard()
                del self.pixels[pos]

            for x, y in birthing:
                self.pixels[(x, y)] = self.scene.obj().create(self.st('██', 'orange'), x, y, rotation=0, z=10, aspect=1)

            if self.pixels:
                self.steps += 1
                self.infobj.transform.text = str(self.steps) + ' steps.'

        self.infobj.transform.x, self.infobj.transform.y = scene.camx, scene.camy
        self.datobj.create('FPS: ' + str(int(scene.framerate)) + ('  PAUSED' if self.pause else ''), scene.camx + self.infobj.transform.xlen() + 4, scene.camy, z=20)
        if self.startup:
            self.startup.create(x=scene.camx, y=scene.camy)

wor.launch(main)
ses.run()
