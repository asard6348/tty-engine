#ENGINE LAUNCHER
from ttyengine.launcher import Session, attempt

def dev(Session=Session): #DEBUG
    main_session = Session() # the terminal session handler
    main_world = main_session.World() # new world instance

    #MODULES
    import os, sys

    #TITLE
    sys.stdout.write(f"\033]0;Test\007") # title
    sys.stdout.flush()
    #DEBUGGER
    #from ttyengine.debugger import debug
    #debugger, dinfo = debug(title='Debugger')

    #SCENE BEHAVIOURS
    class scene1(): # example scene1
        def __init__(self, scene, world, session):   #INITIALIZATION (OPTIONAL)
            self.scene = scene
            self.session = session
            self.world = world
            #VARIABLES
            self.plrspeed = 1
            self.plrmaxspeed = 10
            self.plrspeedfriction = 0.9
            self.plrjumppower = 10
            self.camrange = 10
            self.void = -100
        
        def start(self):    #START
            sc = self.scene
            world = self.world
            inp = self.session.inp
            style = self.session.style
            sc.bgcolor = (30,30,30) # terminal background color
            obj = sc.obj # obj class
            
            self.info = obj().create(style('Press "q" to quit. Hold "e" to rotate.', color='magenta', bgcolor='pink'),0,0,renderspaces=True)
            self.plr = obj().create(style(" O \n(|)\n | \n[ ]", color='white', bgcolor='blue', bgalpha=0.5, bg=sc.bgcolor),0,0,hitbox=True)
            #self.plr.transform.text = "OOOOOOO\n OOOOOO\n OOOOOO\n OOOOOOOOOOO"
            #self.plr.transform.text += "\n[ ]"*5
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
                ip+=20

            def onpress(): # key press events
                def w():
                    self.plr.physics.yvel += self.plrjumppower if self.plr.physics.touch[1] else 0
                def q():
                    self.session.running = False
                def f():
                    self.enemy.transform.x = self.plr.transform.x - self.plr.transform.xlen()*2
                    self.enemy.transform.y = self.plr.transform.y + self.plr.transform.ylen()+1
                    self.enemy.transform.rotation = -90
                def r():
                    self.session.optimize = not self.session.optimize
                def t():
                    self.plr.rendering.show = not self.plr.rendering.show
                def p():
                    self.world.pause = not self.world.pause
                for but in [w,q,f,r,t,p]:
                    def close():
                        self.session.running = False
                    inp.onpress(but.__name__, lambda e, func=but: attempt(func))
            onpress()

        def update(self):   #UPDATE
            sc = self.scene
            world = self.world
            inp = self.session.inp
            style = self.session.style
            
            def whilepressed(): # key hold events
                def k(but):
                    return inp.held(but)
                if(k('e')):
                    self.plr.physics.avel += 1
                #if(k('w')):
                    #gobj.camy+=0.1
                    #self.plr.yvel += self.plrspeed if abs(self.plr.yvel) < self.plrmaxspeed else 0
                #if(k('s')):
                    #gobj.camy-=0.1
                    #self.plr.yvel += -self.plrspeed if abs(self.plr.xvel) < self.plrmaxspeed else 0
                if(k('d')):
                    #gobj.camx+=0.1
                    self.plr.physics.xvel += self.plrspeed if abs(self.plr.physics.xvel) < self.plrmaxspeed else 0
                if(k('a')):
                    #gobj.camx-=0.1
                    self.plr.physics.xvel += -self.plrspeed if abs(self.plr.physics.xvel) < self.plrmaxspeed else 0
            whilepressed()
            
            if(self.plr.transform.y<self.void):
                self.plr.transform.y=0;self.plr.transform.x=0
            if(self.enemy.transform.y<self.void):
                self.enemy.transform.y=0;self.enemy.transform.x=0
            self.plr.physics.xvel *= self.plrspeedfriction
            #self.plr.physics.yvel *= self.plrspeedfriction
            
            camtarx = (inp._mouse_x-sc.dimx/2) + self.plr.transform.x+self.plr.transform.xc(self.plr.transform.htext)
            camtary = (-inp._mouse_y+sc.dimy/2) + self.plr.transform.y-self.plr.transform.yc(self.plr.transform.htext)
            sc.camx += ((camtarx-sc.dimx/2)-sc.camx)/self.camrange#; sc.camx = round(sc.camx)
            sc.camy += ((camtary+sc.dimy/2)-sc.camy)/self.camrange#; sc.camy = round(sc.camy)

            self.info.transform.x = sc.camx
            self.info.transform.y = sc.camy
            
            try:
                dinfo.clear()
                #dinfo.extend([sc.recomp.sub('', x) for x in sc.dinfo])
                dinfo.extend(str((inp.focused, inp.mouse, inp.mouseheld())))
            except: pass

    #LAUNCH THE SCENES
    scene1_handle = main_world.launch(scene1)
    #RUN THE SESSION MAIN LOOP (SYNCHRONOUSLY)
    main_session.run()

attempt(dev)
