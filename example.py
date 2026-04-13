#MODULES
import os, sys

class main():
    def __init__(self):   #VARIABLES
        self.plrspeed = 1
        self.plrmaxspeed = 10
        self.plrspeedfriction = 0.9
        self.plrjumppower = 10
        self.camrange = 10
        self.void = -100

        #DEBUGGER
        from ttyengine.debugger import debug
        self.debugger, self.dinfo = debug(title='Debugger')
    
    def start(self, gobj, inp, style, term):    #START
        sys.stdout.write(f"\033]0;Test\007") # title
        sys.stdout.flush()
        gobj.bgcolor = (30,0,0) # terminal background color
        obj = gobj.obj # obj class
        
        self.info = obj().create('Press "q" to quit. Hold "e" to rotate.',0,0, False, False)
        self.plr = obj().create(style(" O \n(|)\n | \n[ ]", color='blue'),0,0,True,True,0,True)
        #self.plr.text = "OOOOOOO\n OOOOOO\n OOOOOO\n OOOOOOOOOOO"
        #self.plr.text += "\n[ ]"*5
        self.enemy = obj().create("OOOOOO\n"*4,25,-(gobj.dimy+1), bounciness=1)
        self.enemy.y += self.enemy.ylen()
        self.enemy.dynamic = True; self.enemy.hitbox = False
        self.ground = obj().create("██████████████████████████████████████████████████████████████████████████████", -15, -(gobj.dimy+1))
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
                os._exit(0)
            def f():
                self.enemy.x = self.plr.x - self.plr.xlen()*2
                self.enemy.y = self.plr.y + self.plr.ylen()+1
                self.enemy.rotation = -90
            for but in [w,q,f]:
                def run(func):
                    func()
                inp.onpress(but.__name__, lambda e, func=but: run(func))
        onpress()

    def update(self, gobj, inp, style):   #UPDATE
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
        gobj.camx += (self.plr.x+self.plr.xc(self.plr.htext)-(gobj.dimx/2)-gobj.camx)/self.camrange#; gobj.camx = round(gobj.camx)
        gobj.camy += (self.plr.y-self.plr.yc(self.plr.htext)+(gobj.dimy/2)-gobj.camy)/self.camrange#; gobj.camy = round(gobj.camy)
        self.info.x = gobj.camx
        self.info.y = gobj.camy
        try: self.dinfo.clear()
        except: pass
        try: self.dinfo.extend([gobj.recomp.sub('', x) for x in gobj.dinfo])
        except: pass
        
#ENGINE LAUNCHER
from ttyengine import launcher
launcher.launch(main)
