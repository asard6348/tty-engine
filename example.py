#ENGINE LAUNCHER
from ttyengine.launcher import Session, attempt

def dev(Session=Session): #DEBUG
    main_session = Session()
    main_world = main_session.World()

    #MODULES
    import sys

    #TITLE
    sys.stdout.write(f"\033]0;TTY Simulator\007")
    sys.stdout.flush()
    #DEBUGGER
    #from ttyengine.debugger import debug
    #debugger, dinfo = debug(title='Debugger')

    #SCENE BEHAVIOURS
    class explode():
        def __init__(self, scene, x,y,radius=25,force=200,timer=0.5):
            self.pos = (x,y)
            self.bomb = scene.obj().create(x=x, y=y, exradius=radius, exforce=force) # bomb
            self.bomb.explosion.explode()
            self.begin = timer
            self.timer = self.begin
        def update(self, scene, handle, session):
            if self.timer <= 0:
                self.bomb.discard()
                handle.cancel()
                return
            self.timer -= 1/scene.framerate
            t = self.bomb.transform
            ex = self.bomb.explosion
            delta = (self.timer/self.begin) if self.begin != 0 else 0
            t.text = session.style(ex.circle((ex.radius/2)*(1-delta), 'X'), alpha=min(1,ex.force/20)*delta, color='orange', bgcolor=scene.bgcolor)
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
            self.camspeed = 5
            self.void = -100
        
        def start(self):    #START
            sc = self.scene
            world = self.world
            inp = self.session.inp
            style = self.session.style
            sc.bgcolor = (255,255,255)
            sc.gravity = (0,0)
            obj = sc.obj
            self.tarx = 0
            self.tary = 0

            '''self.info = obj().create(style('Press "q" to quit. Hold "e" to rotate.', color='magenta', bgcolor='pink'),0,0,renderspaces=True)
            plrtext = style(f"{style(' O ', color=(241,194,125), reset=False)}\n{style('(|)', color='brightblue', reset=False)}\n{style(' | ', color='green', reset=False)}\n{style('[ ]', color='gray', reset=False)}",
                            )
            self.plr = obj().create(plrtext,0,0,hitbox=True,renderspaces=False)
            def plref(parts):
                if 0 < len(parts): self.plr = parts[0]
                else: self.plr = None
            self.plr.transform.onsplit(plref)
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
            
            if not hasattr(self, 'plr'): self.plr = None

            self.pen = obj().create(penchar='█')
            self.penc = 0
            def on_click_pen(mx, my, data):
                self.pen.pen._x = mx + sc.camx
                self.pen.pen._y = sc.camy - my
                self.pen.pen.down(char=style(self.pen.pen.char, color=(self.penc+13 if data==0 else 'black')))
                self.penc = 0 if self.penc >= 13 else self.penc + 1
                if data == 2:
                    self.pen.pen.cancel()
            def on_release_pen(mx, my, data):
                if data == 2:
                    if self.pen.pen.current_obj: self.pen.pen.current_obj.discard()
                    self.pen.pen.commit(r=0, hitbox=False)
                self.pen.pen.up(dynamic=True)
            inp.onmouse('click', on_click_pen)
            inp.onmouse('release', on_release_pen)

            self.push = sc.obj().create(exradius=40, exforce=60, show=False)
            self.push.transform.text = self.push.explosion.circle(5, style('X', 'red'))

            def onpress(): # key press events
                def w():
                    if self.plr: self.plr.physics.yvel += self.plrjumppower if self.plr.physics.touch[1] and self.plr.physics.yvel==0 else 0
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
                    self.world.pause = not self.world.pause
                def x():
                    mx, my = inp.mouse
                    ax=mx + self.scene.camx
                    ay=self.scene.camy - my
                    world.launch(lambda scene: explode(scene=scene,x=ax,y=ay,timer=0.3))
                for but in [w,q,f,r,t,p,x]:
                    def close():
                        self.session.running = False
                    inp.onpress(but.__name__, lambda e, func=but: attempt(func))
            onpress()

        def update(self):   #UPDATE
            sc = self.scene
            inp = self.session.inp
            
            def whilepressed(): # key hold events
                def k(but):
                    return inp.held(but)
                if(k('e')):
                    self.plr.physics.avel += 1
                if(k('w')):
                    self.tary += self.camspeed/2
                    #if self.plr: self.plr.yvel += self.plrspeed if abs(self.plr.yvel) < self.plrmaxspeed else 0
                if(k('s')):
                    self.tary += -self.camspeed/2
                    #if self.plr: self.plr.yvel += -self.plrspeed if abs(self.plr.xvel) < self.plrmaxspeed else 0
                if(k('d')):
                    self.tarx += self.camspeed
                    if self.plr: self.plr.physics.xvel += self.plrspeed if abs(self.plr.physics.xvel) < self.plrmaxspeed else 0
                if(k('a')):
                    self.tarx += -self.camspeed
                    if self.plr: self.plr.physics.xvel += -self.plrspeed if abs(self.plr.physics.xvel) < self.plrmaxspeed else 0
                if(k('c')):
                    mx, my = inp.mouse
                    ax=mx + self.scene.camx
                    ay=self.scene.camy - my
                    self.push.transform.x = ax - self.push.transform.xc()
                    self.push.transform.y = ay + self.push.transform.yc()
                    self.push.rendering.show = True
                    self.push.explosion.explode(ax,ay)
                else:
                    self.push.rendering.show = False
                if(k('up')): sc.dimyoffset += 1#self.tary += self.camspeed/2
                if(k('down')): sc.dimyoffset += -1#self.tary += -self.camspeed/2
                if(k('right')): sc.dimxoffset += 1#self.tarx += self.camspeed
                if(k('left')): sc.dimxoffset += -1#self.tarx += -self.camspeed
            whilepressed()
            
            for o in self.scene.objs:
                if(hasattr(o, 'physics') and o.transform.y<self.void):
                    o.transform.y=0;o.transform.x=0
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
                self.tarx = self.plr.transform.x+self.plr.transform.xc(self.plr.transform.htext)
                self.tary = self.plr.transform.y-self.plr.transform.yc(self.plr.transform.htext)
            sc.camx += (self.tarx + camtarx - (sc.dimx/2) - sc.camx) / self.camrange
            sc.camy += (self.tary + camtary + (sc.dimy/2) - sc.camy) / self.camrange

            if hasattr(self, 'info'):
                self.info.transform.x = sc.camx
                self.info.transform.y = sc.camy
            if self.pen.pen.active:
                self.pen.pen.move(inp._mouse_x + sc.camx, sc.camy - inp._mouse_y)
            if inp.mouseheld(2):
                self.pen.pen.cut(
                    inp._mouse_x + sc.camx,
                    sc.camy - inp._mouse_y,
                    r=0, when=lambda o: hasattr(o, 'physics')
                )
            
            try: # debug info register
                dinfo.clear()
                dinfo.extend([sc.recomp.sub('', x) for x in sc.dinfo])
            except: pass

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
