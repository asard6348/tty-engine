#ENGINE LAUNCHER
from ttyengine.launcher import Session
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
        sc.bgcolor = (30,0,0) # terminal background color
        obj = sc.obj # obj class
        
        self.info = obj().create('Press "q" to quit. Hold "e" to rotate.',0,0, False, False)
        self.plr = obj().create(style(" O \n(|)\n | \n[ ]", color='blue'),0,0,True,True,0,True)
        #self.plr.text = "OOOOOOO\n OOOOOO\n OOOOOO\n OOOOOOOOOOO"
        #self.plr.text += "\n[ ]"*5
        self.enemy = obj().create("OOOOOO\n"*4,25,-(sc.dimy+1), bounciness=1)
        self.enemy.y += self.enemy.ylen()
        self.enemy.dynamic = True; self.enemy.hitbox = False
        self.ground = obj().create("██████████████████████████████████████████████████████████████████████████████", -15, -(sc.dimy+1))
        self.floor = obj().create("OOOOOO\n OOOOO",self.enemy.x,self.enemy.y+6)
        self.peak = obj().create("O\n"*20,self.ground.x-55,self.ground.y-6)
        def p(txt,x=0,y=0):
            return obj().create(txt,x,y)
        p1=p("OOOOOOOOO",self.ground.x-20,self.ground.y)
        p2=p("OOOOOOOOO\nOOOOOOOOO",p1.x-20,p1.y+1)
        p3=p("OOOOOOOOO\nOOOOOOOOO",p2.x-30,p2.y-5)
        ip=20
        for i in range(0,6):
            p("OOOOOOOOO", p3.x-ip,p3.y)
            ip+=20

        def onpress(): # key press events
            def w():
                self.plr.yvel += self.plrjumppower if self.plr.touch[1] else 0
            def q():
                inp.stop_all()
                self.session.running = False
            def f():
                self.enemy.x = self.plr.x - self.plr.xlen()*2
                self.enemy.y = self.plr.y + self.plr.ylen()+1
                self.enemy.rotation = -90
            for but in [w,q,f]:
                def run(func):
                    func()
                inp.onpress(but.__name__, lambda e, func=but: run(func))
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
                self.plr.avel += 1
            #if(k('w')):
                #gobj.camy+=0.1
                #self.plr.yvel += self.plrspeed if abs(self.plr.yvel) < self.plrmaxspeed else 0
            #if(k('s')):
                #gobj.camy-=0.1
                #self.plr.yvel += -self.plrspeed if abs(self.plr.xvel) < self.plrmaxspeed else 0
            if(k('d')):
                #gobj.camx+=0.1
                self.plr.xvel += self.plrspeed if abs(self.plr.xvel) < self.plrmaxspeed else 0
            if(k('a')):
                #gobj.camx-=0.1
                self.plr.xvel += -self.plrspeed if abs(self.plr.xvel) < self.plrmaxspeed else 0
        whilepressed()
        
        if(self.plr.y<self.void):
            self.plr.y=0;self.plr.x=0
        if(self.enemy.y<self.void):
            self.enemy.y=0;self.enemy.x=0
        self.plr.xvel *= self.plrspeedfriction
        #self.plr.yvel *= self.plrspeedfriction
        sc.camx += (self.plr.x+self.plr.xc(self.plr.htext)-(sc.dimx/2)-sc.camx)/self.camrange#; sc.camx = round(sc.camx)
        sc.camy += (self.plr.y-self.plr.yc(self.plr.htext)+(sc.dimy/2)-sc.camy)/self.camrange#; sc.camy = round(sc.camy)
        self.info.x = sc.camx
        self.info.y = sc.camy
        try:
            dinfo.clear()
            dinfo.extend([sc.recomp.sub('', x) for x in sc.dinfo])
        except: pass

#LAUNCH THE SCENES
scene1_handle = main_world.launch(scene1)
#RUN THE SESSION MAIN LOOP (SYNCHRONOUSLY)
main_session.run()
