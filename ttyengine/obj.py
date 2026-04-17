import os, sys, math, random, statistics, re

class obj(): 
    def __init__(self, scene):
        self.scene = scene #-------- APPPLY TO PHYSICS AND RENDER
        self.x = 0
        self.y = 0
        self.px = 0
        self.py = 0
        self.vx = 0
        self.vy = 0
        self.vtext = ""
        self.vrtext = ""
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
        self.touch = (False, False)
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
        ctext = self.scene.recomp.sub('', value)
        self.vrtext = value
        self._htext = ctext
        self._rtext = ctext
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
        ctext = self.scene.recomp.sub('', value)
        self.vrtext = value
        self._rtext = ctext
        self.rotate(self._rotation)
    @property
    def htext(self):
        return self._htext
    @htext.setter
    def htext(self, value):
        ctext = self.scene.recomp.sub('', value)
        self.vrtext = value
        self._htext = ctext
        self._rtext = ctext
        self.rotate(self._rotation)
    @property
    def solid(self):
        return self._solid
    @solid.setter
    def solid(self, value):
        self._solid = value
        if(value == True):
            if(not any(obj is self for obj in self.scene.solids)):
                self.scene.solids.append(self)
        else:
            self.scene.solids = [obj for obj in self.scene.solids if obj is not self]
    def rotate(self, angle_degrees):
        if self.hitbox: self.scene.dinfo.clear()
        
        angle = math.radians(angle_degrees)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        def cal(txt):
            rows = txt.splitlines()
            crows = self.scene.recomp.sub('', txt).splitlines()
            if not rows or not crows: return ""
            new_pixels = {}
            height = len(crows)
            width = max(len(r) for r in crows)
            cx, cy = (width-0) / 2, (height-0) / 2
            newrows = []
            current_style = ""
            for line in rows:
                newline = []
                for part in self.scene.recomp.split(line):
                    if self.scene.recomp.match(part):
                        current_style += part
                    elif part:
                        for char in part:
                            newline.append((char, current_style))
                newrows.append(newline)

            if(self.hitbox):
                self.scene.dinfo.extend(f"angle={math.degrees(angle):.0f} txt_lines={len(crows)} pixels={len(new_pixels)}\n")
                self.scene.dinfo.extend(f"  crows: {crows}\n")
                for y, crow in enumerate(crows):
                    for x, char in enumerate(crow):
                        if char != ' ':
                            self.scene.dinfo.extend(f"  src ({x},{y}) '{char}' -> stored? {any(v[0]==char for v in new_pixels.values())}\n")
                self.scene.dinfo.extend(f"  pixel keys sample: {list(new_pixels.keys())[:10]}\n")
            
            for y, crow in enumerate(crows):
                for x, char in enumerate(crow):
                    styled = newrows[y][x][1] if y < len(newrows) and x < len(newrows[y]) else ""
                    rel_x, rel_y = x - cx, y - cy
                    ASPECT = 0.5
                    rel_x_n = rel_x * ASPECT
                    rel_y_n = rel_y 
                    rx_n = rel_x_n * cos_a - rel_y_n * sin_a
                    ry_n = rel_x_n * sin_a + rel_y_n * cos_a
                    rx = rx_n / ASPECT 
                    ry = ry_n 
                    nx, ny = int(round(rx + cx)), int(round(ry + cy))
                    if (nx, ny) not in new_pixels or new_pixels[(nx, ny)][0] == " ":
                        new_pixels[(nx, ny)] = (char, styled)
                    '''fillsize = 0.3
                    for dx, dy in [(fillsize, 0), (-fillsize, 0), (0, fillsize/2), (0, -fillsize/2)]:
                        snx, sny = int(round(rx + cx + dx)), int(round(ry + cy + dy))
                        if (snx, sny) not in new_pixels:
                            new_pixels[(snx, sny)] = "\u2800"'''
            if not new_pixels: return
            xs = [p[0] for p in list(new_pixels.keys())]
            ys = [p[1] for p in list(new_pixels.keys())]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            res = []
            for y in range(min_y, max_y + 1):
                line = ""
                pstyled = ""
                for x in range(min_x, max_x + 1):
                    if (x, y) in new_pixels:
                        (char, styled) = new_pixels[(x, y)]
                        fin = (styled if styled != pstyled else "") + char
                        pstyled = styled
                    else:
                        fin = ("\033[0m" if pstyled != "" else "") + " "
                        pstyled = ""
                    line += fin
                res.append(line)
            return "\n".join(res)    
        self.vtext = cal(self.vrtext)
        self._text = cal(self._rtext)

        if(self.hitbox):
            self.scene.dinfo.extend(f"{repr(self._rtext)}\n")
            self.scene.dinfo.extend(f"{repr(self.vrtext)}\n")
        
        self.vx = (self.xc(self._rtext) - self.xc(self._text))
        self.vy = -(self.yc(self._rtext) - self.yc(self._text))
    #def resize(self, scale):
        
        
    def render(self):
        bgcolor = f"\033[48;2;{self.scene.bgcolor[0]};{self.scene.bgcolor[1]};{self.scene.bgcolor[2]}m"
        def remove(bgcolor=bgcolor):
            px = self.px
            py = self.py
            ptext = self.ptext
            if(px!=round((self.x+self.vx)-round(self.scene.camx)) or py!=-round((self.y+self.vy)-round(self.scene.camy)) or ptext!=self.vtext):
                rem = (f"\033[{int(py) + 1}d" if py > 0 else "\033[H")
                for part in self.scene.recomp.split(ptext):
                    if(part == "" or self.scene.recomp.match(part)):
                        rem += part
                    else:
                        for i, row in enumerate(part.splitlines()):
                            rem += f"\033[{int(py)+1 + i}d"
                            arow = ""
                            crop = row[abs(min(0, int(px))) : abs(max(0,(self.scene.dimx)-int(px)))]
                            for j, char in enumerate(crop):
                                if(char == " "):
                                    arow += "\033[C"
                                elif(char == "\n"):
                                    arow += "\n"
                                else:
                                    arow += " "
                            final = f"\033[{max(0,int(px)) + 1}G{arow}"
                            rem += final if 1<=int(py)+1+i<=self.scene.dimy else ""
                sys.stdout.write(f"{bgcolor}{rem}\033[0m")
        remove()
        acx = round((self.x+self.vx)-round(self.scene.camx))
        acy = -round((self.y+self.vy)-round(self.scene.camy))
        actext = self.vtext
        out = (f"\033[{acy + 1}d" if acy > 0 else "\033[H")
        for part in self.scene.recomp.split(actext):
            if(part == "" or self.scene.recomp.match(part)):
                out += part
            else:
                for i, row in enumerate(part.splitlines()):
                    out += f"\033[{acy+1 + i}d"
                    arow = ""
                    crop = row[abs(min(0, acx)) : abs(max(0,(self.scene.dimx)-acx))]
                    for j, char in enumerate(crop):
                        if(char == " "):
                            arow += "\033[C"
                        else:
                            arow += char
                    final = f"\033[{max(0,acx) + 1}G{arow}"
                    out += final if 1<=acy+1+i<=self.scene.dimy else ""
        self.px = acx
        self.py = acy
        self.ptext = actext
        sys.stdout.write(f"{bgcolor}{out}\033[0m")

    def physics(self, axises=('x', 'y')):
        def armratio(points, obj, pos=None):
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
            self[a+'vel'] *= self.scene.drag
            self[a+'vel'] += self.scene.gravity[ia]*actualmass
            c = 1 if self[a+'vel'] > 0 else -1 if self[a+'vel'] < 0 else 0
            ch = abs(self[a+'vel']) / actualmass
            tch = list(self.touch); tch[ia] = False
            self.touch = tuple(tch)
            while ch > 0:
                step = min(self.scene.precision, ch)
                t = {a: self[a] + (c * step)}
                col = self.collides(self.scene.solids, **t)
                if(col[0] and self.solid):
                    obj2 = col[1]
                    othermass = (abs(obj2.mass)+1)
                    totalmass = actualmass + othermass
                    td = armratio(col[2],self,self[a]+(c*step))
                    otd = armratio(col[2],obj2)
                    touchdelta = td[ia] if not self.hitbox else 0
                    othertouchdelta = otd[ia] if not obj2.hitbox else 0
                    torque = self.mass
                    #torque
                    if(obj2.dynamic and not obj2.hitbox):
                        obj2.avel += torque * (otd[opp_ia] * ((obj2[a+'vel']-self[a+'vel']) if ia == 1 else -(obj2[a+'vel']-self[a+'vel'])))
                        #self.scene.dinfo=[str(otd[opp_ia])]
                    if(self.hitbox==False):
                        self.avel += torque * (td[opp_ia] * ((self[a+'vel']-obj2[a+'vel']) if ia == 1 else -(self[a+'vel']-obj2[a+'vel'])))
                    if(obj2.dynamic):
                       power = (actualmass / totalmass)*(1-abs(touchdelta))
                       obj2[a+'vel'] += self[a+'vel']*power
                       remain = (actualmass - othermass) / totalmass
                       self[a+'vel'] *= max(touchdelta, remain)
                    else:
                       self[a+'vel'] *= -self.bounciness * (1-abs(touchdelta))
                    tch = list(self.touch); tch[ia] = True
                    self.touch = tuple(tch)
                    break
                self[a] += c * step
                ch -= step
        self.avel *= self.scene.drag
        self.rotation += self.avel / actualmass
        colr = self.collides(self.scene.solids)
        if(colr[0] and self.solid):
            td = armratio(colr[2],self)
            self.rotation -= self.avel / actualmass
            slide_cap = 0.5
            slide_x = (self.avel * abs(td[0])) / actualmass
            slide_y = (abs(self.avel) * td[1]) / actualmass
            orx,ory=self.xvel,self.yvel
            self.xvel = max(min(self.xvel + slide_x, slide_cap), -slide_cap)
            self.yvel = max(min(self.yvel + slide_y, slide_cap), -slide_cap)
            #trymove
            self.x+=self.xvel
            self.y+=self.yvel
            self.rotation += self.avel / actualmass
            colm = self.collides(self.scene.solids)
            if((colm[0] and self.solid)):
                self.x-=self.xvel
                self.y-=self.yvel
                self.xvel,self.yvel=orx,ory
                self.rotation -= self.avel / actualmass
                self.avel *= -self.bounciness
                self.rotation += self.avel / actualmass
                colrr = self.collides(self.scene.solids)
                if(colrr[0] and self.solid):
                    self.rotation -= self.avel / actualmass
                    self.avel *= -1
                    self.rotation += self.avel / actualmass
                    for ia,a in enumerate(axises):
                        c = 1 if self[a+'vel'] > 0 else -1 if self[a+'vel'] < 0 else 0
                        ch = abs(self[a+'vel']) / actualmass
                        while ch > 0:
                            step = min(self.scene.precision, ch)
                            t = {a: self[a] + (c * step)}
                            col = self.collides(self.scene.solids, **t)
                            if(col[0] and self.solid):
                                self[a+'vel'] *= -self.bounciness
                                break
                            self[a] += c * step
                            ch -= step

    def create(self, text="", x=0, y=0, dynamic=False, solid=True, rotation=0, hitbox=False, bounciness=0, mass=None, xvel=0, yvel=0, avel=0):
        self.x = x
        self.y = y
        ctext = self.scene.recomp.sub('', text)
        self.vrtext = text
        self.vtext = text
        self._htext = ctext
        self._rtext = ctext
        self._text = ctext
        self.xvel = xvel
        self.yvel = yvel
        self.avel = avel
        self.bounciness = bounciness
        size = 0
        for row in ctext.splitlines():
            for char in row:
                if(char != " " and char != "\n"):
                    size+=1
        self.mass = size if mass is None else mass
        self.dynamic = dynamic
        self.hitbox = hitbox
        self.solid = solid
        self.rotation = rotation
        
        self.scene.objs.append(self)
        return self

class Scene():
    def __init__(self):
        self.objs = []
        self.dinfo = []
        self.framerate = 60
        
        self.gravity = (0, -0.05)
        self.drag = 0.97
        self.precision = 0.1
        self.solids = []

        self.camx = 0
        self.camy = 0
        self.dimx = 120
        self.dimy = 30
        self.bgcolor = (0, 0, 0)
        self.recomp = re.compile(r'(\x1b\[[0-9;]*[a-zA-Z])')
    def obj(self):
        return obj(self)
