<<<<<<< HEAD
import os, sys, math, threading, time, keyboard, random, traceback, statistics
global e, solids, framerate, gravity, friction, precision, camx, camy, dimx, dimy

framerate = 60
gravity = [0, -0.05]
friction = 0.97
precision = 0.1
e=0

camx = int(0)
camy = int(0)
dimx = 120
dimy = 30
solids = []

class obj():
    def __init__(self):
        global solids
        self.x = 0
        self.y = 0
        self.px = 0
        self.py = 0
        self.vx = 0
        self.vy = 0
        self.ptext = ""
        self.xvel = 0
        self.yvel = 0
        self._text = ""
        self._rtext = ""
        self._htext = ""
        self._rotation = 0
        self.avel = 0
        self.bounciness = 0
        self.mass = 0
        self.dynamic = False
        self._solid = False
        self.touch = [False, False]
        self.hitbox = False
    def __getitem__(self, key):
        return getattr(self, key)
    def __setitem__(self, key, value):
        setattr(self, key, value)
    def xlen(self, text=None):
        text = self._text if not isinstance(text, str) else text
        lens = []
        for row in text.splitlines():
            for i,char in enumerate(row):
                if(char!=" "):
                    lens.append(i)
        return abs(max(lens)-(min(lens)-1))
    def ylen(self, text=None):
        text = self._text if not isinstance(text, str) else text
        lens = 0
        for row in text.splitlines():
            chars = 0
            for char in row:
                if(char!=" " and char!= "\n"):
                    chars+=1
            lens += 1 if chars > 0 else 0
        return lens
    def xc(self, text=None):
        text = self._text if not isinstance(text, str) else text
        return self.xlen(text)/2
    def yc(self, text=None):
        text = self._text if not isinstance(text, str) else text
        return self.ylen(text)/2
    def getpixels(self, x=None,y=None, text=None):
        x = self.x if not isinstance(x, float) else x
        y = self.y if not isinstance(y, float) else y
        text = self._text if not isinstance(text, str) else text
        text = self._htext if self.hitbox else text
        rx = round(x+self.vx) if not self.hitbox else round(x)
        ry = round(y+self.vy) if not self.hitbox else round(y)
        pixels = set()
        rows = text.splitlines()
        for i, row in enumerate(rows):
            for j, char in enumerate(row):
                if (char != " " and char != "\n" and self.hitbox==False) or self.hitbox==True:
                    abs_x = rx + j
                    abs_y = ry - i
                    pixels.add((abs_x, abs_y))
        return pixels
    def collides(self, objs, x=None,y=None, text=None):
        pixels1 = self.getpixels(x,y,text)
        if not isinstance(objs, list):
            objs = [objs]
        for obj2 in objs:
            if(obj2 != self):
                pixels2 = obj2.getpixels()
                intersection = pixels1.intersection(pixels2)
                if intersection:
                    return True, obj2, intersection
        return False, None
    @property
    def text(self):
        return self._text
    @text.setter
    def text(self, value):
        self._htext = value
        self._rtext = value
        self.rotate(self._rotation)
    @property
    def rotation(self):
        return self._rotation
    @rotation.setter
    def rotation(self, value):
        self._rotation = value
        self.rotate(value)
    @property
    def rtext(self):
        return self._rtext
    @rtext.setter
    def rtext(self, value):
        self._rtext = value
        self.rotate(self._rotation)
    @property
    def htext(self):
        return self._htext
    @htext.setter
    def htext(self, value):
        self._htext = value
        self._rtext = value
        self.rotate(self._rotation)
    @property
    def solid(self):
        return self._solid
    @solid.setter
    def solid(self, value):
        global solids
        self._solid = value
        if(value == True):
            if(not any(obj is self for obj in solids)):
                solids.append(self)
        else:
            solids = [obj for obj in solids if obj is not self]
    def rotate(self, angle_degrees):
        angle = math.radians(angle_degrees)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        rows = self._rtext.splitlines()
        if not rows: return
        new_pixels = {}
        height = len(rows)
        width = max(len(r) for r in rows) if rows else 0
        cx, cy = (width-0) / 2, (height-0) / 2
        for y, row in enumerate(rows):
            for x, char in enumerate(row):
                rel_x, rel_y = x - cx, y - cy
                rx = rel_x * cos_a - (rel_y * 2.0) * sin_a
                ry = (rel_x / 2.0) * sin_a + rel_y * cos_a
                nx, ny = int(round(rx + cx)), int(round(ry + cy))
                if (nx, ny) not in new_pixels or new_pixels[(nx, ny)] == " ":
                    new_pixels[(nx, ny)] = char
                fillsize = 0.3
                '''
                for dx, dy in [(fillsize, 0), (-fillsize, 0), (0, fillsize/2), (0, -fillsize/2)]:
                    snx, sny = int(round(rx + cx + dx)), int(round(ry + cy + dy))
                    if (snx, sny) not in new_pixels:
                        new_pixels[(snx, sny)] = "\u2800"
                '''
        if not new_pixels: return
        min_x = min(p[0] for p in new_pixels)
        max_x = max(p[0] for p in new_pixels)
        min_y = min(p[1] for p in new_pixels)
        max_y = max(p[1] for p in new_pixels)
        res = []
        for y in range(min_y, max_y + 1):
            line = ""
            for x in range(min_x, max_x + 1):
                line += new_pixels.get((x, y), " ")
            res.append(line)
        self._text = "\n".join(res)
        self.vx = (self.xc(self._rtext) - self.xc())
        self.vy = -(self.yc(self._rtext) - self.yc())
    #def resize(self, scale):
        
        
    def create(self, text="", sx=0, sy=0, dynamic=False, solid=True, rotation=0, hitbox=False, bounciness=0, mass=None, xvel=0, yvel=0, avel=0):
        global solids
        self.x = sx
        self.y = sy
        self._htext = text
        self._rtext = text
        self._text = text
        self.xvel = xvel
        self.yvel = yvel
        self.avel = avel
        self.bounciness = bounciness
        size = 0
        for row in text.splitlines():
            for char in row:
                if(char != " " and char != "\n"):
                    size+=1
        self.mass = size if mass is None else mass
        self.dynamic = dynamic
        self.hitbox = hitbox
        self.solid = solid
        self.rotation = rotation
        def render():
            def remove():
                px = self.px
                py = self.py
                ptext = self.ptext
                if(px!=round((self.x+self.vx)-round(camx)) or py!=-round((self.y+self.vy)-round(camy)) or ptext!=self._text):
                    rem = (f"\033[{int(py) + 1}d" if py > 0 else "\033[H")
                    for i, row in enumerate(ptext.splitlines()):
                        rem += f"\033[{int(py)+1 + i}d"
                        arow = ""
                        crop = row[abs(min(0, int(px))) : abs(max(0,(dimx)-int(px)))]
                        for j, char in enumerate(crop):
                            if(char == " "):
                                arow += "\033[C"
                            elif(char == "\n"):
                                arow += "\n"
                            else:
                                arow += " "
                        final = f"\033[{max(0,int(px)) + 1}G{arow}"
                        rem += final if 1<=int(py)+1+i<=dimy else ""
                    print(rem, end="", flush=True)
            remove()
            acx = round((self.x+self.vx)-round(camx))
            acy = -round((self.y+self.vy)-round(camy))
            out = (f"\033[{acy + 1}d" if acy > 0 else "\033[H")
            for i, row in enumerate(self.text.splitlines()):
                out += f"\033[{acy+1 + i}d"
                arow = ""
                crop = row[abs(min(0, acx)) : abs(max(0,(dimx)-acx))]
                for j, char in enumerate(crop):
                    if(char == " "):
                        arow += "\033[C"
                    else:
                        arow += char
                final = f"\033[{max(0,acx) + 1}G{arow}"
                out += final if 1<=acy+1+i<=dimy else ""
            self.px = acx
            self.py = acy
            self.ptext = self.text
            print(out, end="", flush=True)
        def physics(axises):
            global e
            def armratio(points, obj, pos=None):
                global e
                xi = []; yi = []
                for ax in points:
                    xi.append(ax[0]); yi.append(ax[1])
                touchcenter = (statistics.mean(xi), statistics.mean(yi))
                arms = []
                for ia, a in enumerate(axises):
                    poss = obj[a] if pos is None else (pos[ia] if isinstance(pos,list) else pos)
                    ratio = ((touchcenter[ia])-(poss+obj[a+'c']() if ia!=1 else poss-obj[a+'c']()))/((obj[a+'c']()))
                    arms.insert(ia,ratio)
                '''exceeds=False
                for ar in arms:
                    if(abs(ar)>1):
                        exceeds = True
                if(exceeds):
                    array = arms.copy()
                    for i in range(len(array)):
                        if array[i] < 0:
                             array[i] = array[i] * (-1)
                    m = max(array)
                    for i,ar in enumerate(arms):
                        arms[i]=ar#/m'''
                return arms
            actualmass = (abs(self.mass)+1)
            for ia, a in enumerate(axises):
                opp_ia = 1 - ia; direction_sign = 1 if a == 'x' else -1
                self[a+'vel'] *= friction
                self[a+'vel'] += gravity[ia]*actualmass
                c = 1 if self[a+'vel'] > 0 else -1 if self[a+'vel'] < 0 else 0
                ch = abs(self[a+'vel']) / actualmass
                self.touch[ia] = False
                while ch > 0:
                    step = min(precision, ch)
                    t = {a: self[a] + (c * step)}
                    col = self.collides(solids, **t)
                    if(col[0] and self.solid):
                        obj2 = col[1]
                        othermass = (abs(obj2.mass)+1)
                        totalmass = actualmass + othermass
                        devmass = actualmass/othermass if obj2.dynamic else 1
                        td = list(armratio(col[2],self))
                        for ix,axx in enumerate(td):
                            td[ix] = axx/devmass
                        otd = list(armratio(col[2],obj2))
                        for ix,axx in enumerate(otd):
                            otd[ix] = axx*devmass
                        touchdelta = td[ia] if not self.hitbox else 0
                        othertouchdelta = otd[ia] if not obj2.hitbox else 0
                        #torque
                        relvel = ((self[a+'vel']+2*(abs(self[a+'vel'])/self[a+'vel']))-obj2[a+'vel'])
                        torque = 1
                        if(obj2.dynamic and not obj2.hitbox):
                            obj2.avel += torque * (((otd[opp_ia]) if ia == 0 else (otd[opp_ia])) * (-relvel if ia == 1 else relvel))
                        if(self.hitbox==False):
                            self.avel += (actualmass if not obj2.dynamic else abs(self.mass) * (1-obj2.bounciness) + 1) * torque * (((td[opp_ia]) if ia == 0 else (td[opp_ia])) * (relvel if ia == 1 else -relvel))
                            e=((round(td[0]*10)/10,round(td[1]*10)/10),self.avel,relvel) if not self.hitbox and self.dynamic else e
                        if(obj2.dynamic):
                            brelvel = ((self[a+'vel']+0*(abs(self[a+'vel'])/self[a+'vel']))-obj2[a+'vel'])
                            power = (actualmass / totalmass)*(1-abs(touchdelta))
                            obj2[a+'vel'] += self[a+'vel']*power
                            remain = (actualmass - othermass) / totalmass
                            self[a+'vel'] *= max(touchdelta, remain)
                            self[a+'vel'] += brelvel * -self.bounciness * (1-obj2.bounciness)
                            obj2[a+'vel'] += -brelvel * -obj2.bounciness * (1-self.bounciness)
                        else:
                            self[a+'vel'] *= -self.bounciness * (1-abs(touchdelta) if not self.hitbox else 1)
                        self.touch[ia] = True
                        break
                    self[a] += c * step
                    ch -= step
            self.avel *= friction
            c = 1 if self.avel > 0 else -1 if self.avel < 0 else 0
            ch = abs(self.avel) / actualmass
            while ch > 0:
                step = min(1, ch)
                self.rotation += c * step
                colr = self.collides(solids)
                if(colr[0] and self.solid):
                    td = armratio(colr[2],self)
                    self.rotation -= c * step
                    slide_cap = 0.5
                    slide_x = -(c * step * td[1]) * actualmass*1
                    slide_y = (c * step * td[0]) * actualmass*1
                    orx,ory=self.xvel,self.yvel
                    self.xvel = max(min(self.xvel + slide_x, slide_cap), -slide_cap)
                    self.yvel = max(min(self.yvel + slide_y, slide_cap), -slide_cap)
                    #trymove
                    self.x+=self.xvel
                    self.y+=self.yvel
                    self.rotation += c * step
                    colm = self.collides(solids)
                    if((colm[0] and self.solid)):
                        self.x-=self.xvel
                        self.y-=self.yvel
                        self.xvel,self.yvel=orx,ory
                        self.rotation -= c * step
                        self.avel *= -self.bounciness
                        for ia,a in enumerate(axises):
                            c = 1 if self[a+'vel'] > 0 else -1 if self[a+'vel'] < 0 else 0
                            ch = abs(self[a+'vel']) / actualmass
                            while ch > 0:
                                step = min(precision, ch)
                                t = {a: self[a] + (c * step)}
                                col = self.collides(solids, **t)
                                if(col[0] and self.solid):
                                    self[a+'vel'] *= -self.bounciness
                                    break
                                self[a] += c * step
                                ch -= step
                        self.rotation += c * step
                        colrr = self.collides(solids)
                        if(colrr[0] and self.solid):
                            self.rotation -= c * step
                    else:
                        continue
                    break
                ch -= step
        def behave():
            while True:
                if(self.dynamic == True):
                    physics(['x', 'y'])
                render()
                time.sleep(1/framerate)
        th = threading.Thread(target=behave, daemon=True)
        th.start()
        return self
=======
import os, sys, math, threading, time, keyboard, random, traceback, statistics
global e, solids, framerate, gravity, friction, precision, camx, camy, dimx, dimy

framerate = 60
gravity = [0, -0.05]
friction = 0.97
precision = 0.1
e=0

camx = int(0)
camy = int(0)
dimx = 120
dimy = 30
solids = []

class obj():
    def __init__(self):
        global solids
        self.x = 0
        self.y = 0
        self.px = 0
        self.py = 0
        self.vx = 0
        self.vy = 0
        self.ptext = ""
        self.xvel = 0
        self.yvel = 0
        self._text = ""
        self._rtext = ""
        self._htext = ""
        self._rotation = 0
        self.avel = 0
        self.bounciness = 0
        self.mass = 0
        self.dynamic = False
        self._solid = False
        self.touch = [False, False]
        self.hitbox = False
    def __getitem__(self, key):
        return getattr(self, key)
    def __setitem__(self, key, value):
        setattr(self, key, value)
    def xlen(self, text=None):
        text = self._text if not isinstance(text, str) else text
        lens = []
        for row in text.splitlines():
            for i,char in enumerate(row):
                if(char!=" "):
                    lens.append(i)
        return abs(max(lens)-(min(lens)-1))
    def ylen(self, text=None):
        text = self._text if not isinstance(text, str) else text
        lens = 0
        for row in text.splitlines():
            chars = 0
            for char in row:
                if(char!=" " and char!= "\n"):
                    chars+=1
            lens += 1 if chars > 0 else 0
        return lens
    def xc(self, text=None):
        text = self._text if not isinstance(text, str) else text
        return self.xlen(text)/2
    def yc(self, text=None):
        text = self._text if not isinstance(text, str) else text
        return self.ylen(text)/2
    def getpixels(self, x=None,y=None, text=None):
        x = self.x if not isinstance(x, float) else x
        y = self.y if not isinstance(y, float) else y
        text = self._text if not isinstance(text, str) else text
        text = self._htext if self.hitbox else text
        rx = round(x+self.vx) if not self.hitbox else round(x)
        ry = round(y+self.vy) if not self.hitbox else round(y)
        pixels = set()
        rows = text.splitlines()
        for i, row in enumerate(rows):
            for j, char in enumerate(row):
                if (char != " " and char != "\n" and self.hitbox==False) or self.hitbox==True:
                    abs_x = rx + j
                    abs_y = ry - i
                    pixels.add((abs_x, abs_y))
        return pixels
    def collides(self, objs, x=None,y=None, text=None):
        pixels1 = self.getpixels(x,y,text)
        if not isinstance(objs, list):
            objs = [objs]
        for obj2 in objs:
            if(obj2 != self):
                pixels2 = obj2.getpixels()
                intersection = pixels1.intersection(pixels2)
                if intersection:
                    return True, obj2, intersection
        return False, None
    @property
    def text(self):
        return self._text
    @text.setter
    def text(self, value):
        self._htext = value
        self._rtext = value
        self.rotate(self._rotation)
    @property
    def rotation(self):
        return self._rotation
    @rotation.setter
    def rotation(self, value):
        self._rotation = value
        self.rotate(value)
    @property
    def rtext(self):
        return self._rtext
    @rtext.setter
    def rtext(self, value):
        self._rtext = value
        self.rotate(self._rotation)
    @property
    def htext(self):
        return self._htext
    @htext.setter
    def htext(self, value):
        self._htext = value
        self._rtext = value
        self.rotate(self._rotation)
    @property
    def solid(self):
        return self._solid
    @solid.setter
    def solid(self, value):
        global solids
        self._solid = value
        if(value == True):
            if(not any(obj is self for obj in solids)):
                solids.append(self)
        else:
            solids = [obj for obj in solids if obj is not self]
    def rotate(self, angle_degrees):
        angle = math.radians(angle_degrees)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        rows = self._rtext.splitlines()
        if not rows: return
        new_pixels = {}
        height = len(rows)
        width = max(len(r) for r in rows) if rows else 0
        cx, cy = (width-0) / 2, (height-0) / 2
        for y, row in enumerate(rows):
            for x, char in enumerate(row):
                rel_x, rel_y = x - cx, y - cy
                rx = rel_x * cos_a - (rel_y * 2.0) * sin_a
                ry = (rel_x / 2.0) * sin_a + rel_y * cos_a
                nx, ny = int(round(rx + cx)), int(round(ry + cy))
                if (nx, ny) not in new_pixels or new_pixels[(nx, ny)] == " ":
                    new_pixels[(nx, ny)] = char
                fillsize = 0.3
                '''
                for dx, dy in [(fillsize, 0), (-fillsize, 0), (0, fillsize/2), (0, -fillsize/2)]:
                    snx, sny = int(round(rx + cx + dx)), int(round(ry + cy + dy))
                    if (snx, sny) not in new_pixels:
                        new_pixels[(snx, sny)] = "\u2800"
                '''
        if not new_pixels: return
        min_x = min(p[0] for p in new_pixels)
        max_x = max(p[0] for p in new_pixels)
        min_y = min(p[1] for p in new_pixels)
        max_y = max(p[1] for p in new_pixels)
        res = []
        for y in range(min_y, max_y + 1):
            line = ""
            for x in range(min_x, max_x + 1):
                line += new_pixels.get((x, y), " ")
            res.append(line)
        self._text = "\n".join(res)
        self.vx = (self.xc(self._rtext) - self.xc())
        self.vy = -(self.yc(self._rtext) - self.yc())
    #def resize(self, scale):
        
        
    def create(self, text="", sx=0, sy=0, dynamic=False, solid=True, rotation=0, hitbox=False, bounciness=0, mass=None, xvel=0, yvel=0, avel=0):
        global solids
        self.x = sx
        self.y = sy
        self._htext = text
        self._rtext = text
        self._text = text
        self.xvel = xvel
        self.yvel = yvel
        self.avel = avel
        self.bounciness = bounciness
        size = 0
        for row in text.splitlines():
            for char in row:
                if(char != " " and char != "\n"):
                    size+=1
        self.mass = size if mass is None else mass
        self.dynamic = dynamic
        self.hitbox = hitbox
        self.solid = solid
        self.rotation = rotation
        def render():
            def remove():
                px = self.px
                py = self.py
                ptext = self.ptext
                if(px!=round((self.x+self.vx)-round(camx)) or py!=-round((self.y+self.vy)-round(camy)) or ptext!=self._text):
                    rem = (f"\033[{int(py) + 1}d" if py > 0 else "\033[H")
                    for i, row in enumerate(ptext.splitlines()):
                        rem += f"\033[{int(py)+1 + i}d"
                        arow = ""
                        crop = row[abs(min(0, int(px))) : abs(max(0,(dimx)-int(px)))]
                        for j, char in enumerate(crop):
                            if(char == " "):
                                arow += "\033[C"
                            elif(char == "\n"):
                                arow += "\n"
                            else:
                                arow += " "
                        final = f"\033[{max(0,int(px)) + 1}G{arow}"
                        rem += final if 1<=int(py)+1+i<=dimy else ""
                    print(rem, end="", flush=True)
            remove()
            acx = round((self.x+self.vx)-round(camx))
            acy = -round((self.y+self.vy)-round(camy))
            out = (f"\033[{acy + 1}d" if acy > 0 else "\033[H")
            for i, row in enumerate(self.text.splitlines()):
                out += f"\033[{acy+1 + i}d"
                arow = ""
                crop = row[abs(min(0, acx)) : abs(max(0,(dimx)-acx))]
                for j, char in enumerate(crop):
                    if(char == " "):
                        arow += "\033[C"
                    else:
                        arow += char
                final = f"\033[{max(0,acx) + 1}G{arow}"
                out += final if 1<=acy+1+i<=dimy else ""
            self.px = acx
            self.py = acy
            self.ptext = self.text
            print(out, end="", flush=True)
        def physics(axises):
            global e
            def armratio(points, obj, pos=None):
                global e
                xi = []; yi = []
                for ax in points:
                    xi.append(ax[0]); yi.append(ax[1])
                touchcenter = (statistics.mean(xi), statistics.mean(yi))
                arms = []
                for ia, a in enumerate(axises):
                    poss = obj[a] if pos is None else (pos[ia] if isinstance(pos,list) else pos)
                    ratio = ((touchcenter[ia])-(poss+obj[a+'c']() if ia!=1 else poss-obj[a+'c']()))/((obj[a+'c']()))
                    arms.insert(ia,ratio)
                '''exceeds=False
                for ar in arms:
                    if(abs(ar)>1):
                        exceeds = True
                if(exceeds):
                    array = arms.copy()
                    for i in range(len(array)):
                        if array[i] < 0:
                             array[i] = array[i] * (-1)
                    m = max(array)
                    for i,ar in enumerate(arms):
                        arms[i]=ar#/m'''
                return arms
            actualmass = (abs(self.mass)+1)
            for ia, a in enumerate(axises):
                opp_ia = 1 - ia; direction_sign = 1 if a == 'x' else -1
                self[a+'vel'] *= friction
                self[a+'vel'] += gravity[ia]*actualmass
                c = 1 if self[a+'vel'] > 0 else -1 if self[a+'vel'] < 0 else 0
                ch = abs(self[a+'vel']) / actualmass
                self.touch[ia] = False
                while ch > 0:
                    step = min(precision, ch)
                    t = {a: self[a] + (c * step)}
                    col = self.collides(solids, **t)
                    if(col[0] and self.solid):
                        obj2 = col[1]
                        othermass = (abs(obj2.mass)+1)
                        totalmass = actualmass + othermass
                        devmass = actualmass/othermass if obj2.dynamic else 1
                        td = list(armratio(col[2],self))
                        for ix,axx in enumerate(td):
                            td[ix] = axx/devmass
                        otd = list(armratio(col[2],obj2))
                        for ix,axx in enumerate(otd):
                            otd[ix] = axx*devmass
                        touchdelta = td[ia] if not self.hitbox else 0
                        othertouchdelta = otd[ia] if not obj2.hitbox else 0
                        #torque
                        relvel = ((self[a+'vel']+2*(abs(self[a+'vel'])/self[a+'vel']))-obj2[a+'vel'])
                        torque = 1
                        if(obj2.dynamic and not obj2.hitbox):
                            obj2.avel += torque * (((otd[opp_ia]) if ia == 0 else (otd[opp_ia])) * (-relvel if ia == 1 else relvel))
                        if(self.hitbox==False):
                            self.avel += (actualmass if not obj2.dynamic else abs(self.mass) * (1-obj2.bounciness) + 1) * torque * (((td[opp_ia]) if ia == 0 else (td[opp_ia])) * (relvel if ia == 1 else -relvel))
                            e=((round(td[0]*10)/10,round(td[1]*10)/10),self.avel,relvel) if not self.hitbox and self.dynamic else e
                        if(obj2.dynamic):
                            brelvel = ((self[a+'vel']+0*(abs(self[a+'vel'])/self[a+'vel']))-obj2[a+'vel'])
                            power = (actualmass / totalmass)*(1-abs(touchdelta))
                            obj2[a+'vel'] += self[a+'vel']*power
                            remain = (actualmass - othermass) / totalmass
                            self[a+'vel'] *= max(touchdelta, remain)
                            self[a+'vel'] += brelvel * -self.bounciness * (1-obj2.bounciness)
                            obj2[a+'vel'] += -brelvel * -obj2.bounciness * (1-self.bounciness)
                        else:
                            self[a+'vel'] *= -self.bounciness * (1-abs(touchdelta) if not self.hitbox else 1)
                        self.touch[ia] = True
                        break
                    self[a] += c * step
                    ch -= step
            self.avel *= friction
            c = 1 if self.avel > 0 else -1 if self.avel < 0 else 0
            ch = abs(self.avel) / actualmass
            while ch > 0:
                step = min(1, ch)
                self.rotation += c * step
                colr = self.collides(solids)
                if(colr[0] and self.solid):
                    td = armratio(colr[2],self)
                    self.rotation -= c * step
                    slide_cap = 0.5
                    slide_x = -(c * step * td[1]) * actualmass*1
                    slide_y = (c * step * td[0]) * actualmass*1
                    orx,ory=self.xvel,self.yvel
                    self.xvel = max(min(self.xvel + slide_x, slide_cap), -slide_cap)
                    self.yvel = max(min(self.yvel + slide_y, slide_cap), -slide_cap)
                    #trymove
                    self.x+=self.xvel
                    self.y+=self.yvel
                    self.rotation += c * step
                    colm = self.collides(solids)
                    if((colm[0] and self.solid)):
                        self.x-=self.xvel
                        self.y-=self.yvel
                        self.xvel,self.yvel=orx,ory
                        self.rotation -= c * step
                        self.avel *= -self.bounciness
                        for ia,a in enumerate(axises):
                            c = 1 if self[a+'vel'] > 0 else -1 if self[a+'vel'] < 0 else 0
                            ch = abs(self[a+'vel']) / actualmass
                            while ch > 0:
                                step = min(precision, ch)
                                t = {a: self[a] + (c * step)}
                                col = self.collides(solids, **t)
                                if(col[0] and self.solid):
                                    self[a+'vel'] *= -self.bounciness
                                    break
                                self[a] += c * step
                                ch -= step
                        self.rotation += c * step
                        colrr = self.collides(solids)
                        if(colrr[0] and self.solid):
                            self.rotation -= c * step
                    else:
                        continue
                    break
                ch -= step
        def behave():
            while True:
                if(self.dynamic == True):
                    physics(['x', 'y'])
                render()
                time.sleep(1/framerate)
        th = threading.Thread(target=behave, daemon=True)
        th.start()
        return self
>>>>>>> 65a89490f617a2b862b52c1a65ca31c61ce7b520
