from ttyengine.launcher import Session
import random
rand = random.randrange
class main:
    def start(self, scene, session):
        scene.drag=0.9
        self.txt = scene.obj().create('        llll      \n        ll        \n        ll        \nl       ll        \nllllllllllllllllll\n        ll       l\n        ll        \n        ll        \n      llll        ',5,-5,dynamic=True)
        def brk(obj2, inter):
            t2=obj2.transform
            t2.cutpoints(inter)
            t2.split()
        self.txt.physics.ontouch(brk)
        self.inp = session.inp
        def box():
            bx=scene.obj().create('OOOO\nOOOO',rand(0,scene.dimx),-rand(0,scene.dimy), dynamic=True)
            bt=bx.transform
            def onc(nm):
                if (nm=="x" and (bt.x<0 or bt.x>=scene.dimx+bt.xlen())) or (nm=="y" and (bt.y>0 or bt.y<-scene.dimy-bt.ylen())):
                    bx.discard()
            bt.onchange(onc)
        self.inp.onpress('space', box)
    def update(self, scene, session):
        t=self.txt.transform
        p=self.txt.physics
        p.avel+=((-600-p.avel)/10)
        p.xvel=((self.inp._mouse_x-t.xc()-t.x)/1)*p.mass
        p.yvel=((-self.inp._mouse_y+t.yc()-t.y)/1)*p.mass
se = Session()
w = se.World()
w.launch(main)
se.run()
