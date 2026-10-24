import io, os, re, zipfile

DEFAULT_FONT = 'standard'

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUNDLE = os.path.join(_HERE, 'fonts.zip')
_LOCATIONS = ('./', os.path.join(_HERE, 'fonts'))
_MAGIC = re.compile(r'^[tf]lf2.')
_END = re.compile(r'(.)\s*$')


class FigletError(Exception):
    def __init__(self, error):
        self.error = error

    def __str__(self):
        return self.error


class CharNotPrinted(FigletError):
    pass


class FontNotFound(FigletError):
    pass


class FontError(FigletError):
    pass


def _bundled(filename):
    try:
        with zipfile.ZipFile(_BUNDLE) as bundle:
            return bundle.read(filename)
    except (KeyError, OSError, zipfile.BadZipFile):
        return None


def _locate(font):
    for extension in ('tlf', 'flf'):
        filename = '%s.%s' % (font, extension)
        data = _bundled(filename)
        if data is not None:
            return data
        for location in _LOCATIONS:
            path = os.path.join(location, filename)
            if os.path.isfile(path):
                with open(path, 'rb') as handle:
                    return handle.read()
    return None


def _unpack(data):
    if data and zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as inner:
            return inner.read(inner.namelist()[0])
    return data


def _valid(data):
    header = _unpack(data).split(b'\n', 1)[0].decode('utf-8', 'replace')
    return bool(_MAGIC.search(header))


def available():
    found = set()
    try:
        with zipfile.ZipFile(_BUNDLE) as bundle:
            for name in bundle.namelist():
                if name.endswith(('.flf', '.tlf')) and _valid(bundle.read(name)):
                    found.add(name.split('.', 2)[0])
    except (OSError, zipfile.BadZipFile):
        pass
    for location in _LOCATIONS:
        if os.path.isdir(location):
            for name in os.listdir(location):
                path = os.path.join(location, name)
                if name.endswith(('.flf', '.tlf')) and os.path.isfile(path):
                    with open(path, 'rb') as handle:
                        if _valid(handle.read()):
                            found.add(name.split('.', 2)[0])
    return sorted(found)


class FigletFont:
    def __init__(self, font=DEFAULT_FONT):
        self.font = font
        self.comment = ''
        self.chars = {}
        self.width = {}
        data = _unpack(_locate(font))
        if not data:
            raise FontNotFound(font)
        self.data = data.decode('utf-8', 'replace')
        self.loadFont()

    def loadFont(self):
        try:
            data = re.sub(r'[\u0085  ]', ' ', self.data)
            data = data.splitlines()
            header = data.pop(0)
            if _MAGIC.search(header) is None:
                raise FontError('%s is not a valid figlet font' % self.font)
            header = _MAGIC.sub('', header).split()
            if len(header) < 6:
                raise FontError('malformed header for %s' % self.font)
            hardBlank = header[0]
            height, baseLine, maxLength, oldLayout, commentLines = map(int, header[1:6])
            printDirection = fullLayout = None
            if len(header) > 6:
                printDirection = int(header[6])
            if len(header) > 7:
                fullLayout = int(header[7])
            if fullLayout is None:
                if oldLayout == 0:
                    fullLayout = 64
                elif oldLayout < 0:
                    fullLayout = 0
                else:
                    fullLayout = (oldLayout & 31) | 128
            self.height = height
            self.hardBlank = hardBlank
            self.printDirection = printDirection
            self.smushMode = fullLayout
            for _ in range(commentLines):
                self.comment += data.pop(0)

            def character(data):
                end = None
                width = 0
                rows = []
                for _ in range(height):
                    line = data.pop(0)
                    if end is None:
                        end = _END.search(line).group(1)
                        end = re.compile(re.escape(end) + r'{1,2}\s*$')
                    line = end.sub('', line)
                    if len(line) > width:
                        width = len(line)
                    rows.append(line)
                return width, rows

            for i in range(32, 127):
                width, letter = character(data)
                if i == 32 or ''.join(letter) != '':
                    self.chars[i] = letter
                    self.width[i] = width
            if data:
                for i in 'ÄÖÜäöüß':
                    width, letter = character(data)
                    if ''.join(letter) != '':
                        self.chars[ord(i)] = letter
                        self.width[ord(i)] = width
            while data:
                line = data.pop(0).strip()
                i = line.split(' ', 1)[0]
                if i == '':
                    continue
                if re.search('^0x', i, re.IGNORECASE) is not None:
                    i = int(i, 16)
                    width, letter = character(data)
                    if ''.join(letter) != '':
                        self.chars[i] = letter
                        self.width[i] = width
        except Exception as e:
            raise FontError('problem parsing %s font: %s' % (self.font, e))

    def __str__(self):
        return '<FigletFont object: %s>' % self.font


SM_EQUAL = 1
SM_LOWLINE = 2
SM_HIERARCHY = 4
SM_PAIR = 8
SM_BIGX = 16
SM_HARDBLANK = 32
SM_KERN = 64
SM_SMUSH = 128


class _Builder:
    def __init__(self, text, font, direction, width, justify):
        self.text = [ord(c) for c in text]
        self.direction = direction
        self.width = width
        self.font = font
        self.justify = justify
        self.iterator = 0
        self.maxSmush = 0
        self.curCharWidth = 0
        self.prevCharWidth = 0
        self.currentTotalWidth = 0
        self.blankMarkers = []
        self.queue = []
        self.buffer = ['' for _ in range(font.height)]

    def run(self):
        while self.iterator < len(self.text):
            self.addCharToProduct()
            self.iterator += 1
        if self.buffer[0] != '':
            self.queue.append(self.buffer)
        out = ''
        for buffer in self.queue:
            buffer = self.justifyString(buffer)
            out += self.replaceHardblanks(buffer)
        return out

    def getCharAt(self, i):
        if i < 0 or i >= len(self.text):
            return None
        c = self.text[i]
        if c not in self.font.chars:
            return None
        return self.font.chars[c]

    def getCurChar(self):
        return self.getCharAt(self.iterator)

    def getCurWidth(self):
        i = self.iterator
        if i < 0 or i >= len(self.text):
            return None
        c = self.text[i]
        if c not in self.font.chars:
            return None
        return self.font.width[c]

    def addCharToProduct(self):
        curChar = self.getCurChar()
        if self.text[self.iterator] == ord('\n'):
            self.blankMarkers.append(([row for row in self.buffer], self.iterator))
            self.handleNewLine()
            return
        if curChar is None:
            return
        if self.width < self.getCurWidth():
            raise CharNotPrinted('Width is not enough to print this character')
        self.curCharWidth = self.getCurWidth()
        self.maxSmush = self.smushAmount(self.buffer, curChar)
        self.currentTotalWidth = len(self.buffer[0]) + self.curCharWidth - self.maxSmush
        if self.text[self.iterator] == ord(' '):
            self.blankMarkers.append(([row for row in self.buffer], self.iterator))
        if self.currentTotalWidth >= self.width and self.buffer[0]:
            self.handleNewLine()
        else:
            for row in range(self.font.height):
                self.addCurCharRowToBufferRow(curChar, row)
        self.prevCharWidth = self.curCharWidth

    def getLeftSmushedChar(self, i, addLeft):
        idx = len(addLeft) - self.maxSmush + i
        if idx >= 0 and idx < len(addLeft):
            left = addLeft[idx]
        else:
            left = ''
        return left, idx

    def smushRow(self, curChar, row):
        addLeft = self.buffer[row]
        addRight = curChar[row]
        if self.direction == 'right-to-left':
            addLeft, addRight = addRight, addLeft
        for i in range(self.maxSmush):
            left, idx = self.getLeftSmushedChar(i, addLeft)
            right = addRight[i] if i < len(addRight) else ''
            smushed = self.smushChars(left=left, right=right)
            characters = list(addLeft)
            if 0 <= idx <= len(characters):
                characters[idx] = smushed
                addLeft = ''.join(characters)
        return addLeft, addRight

    def addCurCharRowToBufferRow(self, curChar, row):
        addLeft, addRight = self.smushRow(curChar, row)
        self.buffer[row] = addLeft + addRight[self.maxSmush:]

    def cutBufferCommon(self):
        self.currentTotalWidth = 0
        self.buffer = ['' for _ in range(self.font.height)]
        self.blankMarkers = []
        self.prevCharWidth = 0
        curChar = self.getCurChar()
        if curChar is None:
            return
        self.maxSmush = self.smushAmount(self.buffer, curChar)

    def handleNewLine(self):
        if self.blankMarkers:
            saved_buffer, saved_iterator = self.blankMarkers.pop()
            self.queue.append(saved_buffer)
            self.iterator = saved_iterator
        else:
            self.queue.append(self.buffer)
            self.iterator -= 1
        self.cutBufferCommon()

    def justifyString(self, buffer):
        if self.justify == 'right':
            for row in range(self.font.height):
                buffer[row] = (' ' * (self.width - len(buffer[row]) - 1)) + buffer[row]
        elif self.justify == 'center':
            for row in range(self.font.height):
                buffer[row] = (' ' * int((self.width - len(buffer[row])) / 2)) + buffer[row]
        return buffer

    def replaceHardblanks(self, buffer):
        return ('\n'.join(buffer) + '\n').replace(self.font.hardBlank, ' ')

    def smushAmount(self, buffer, curChar):
        if (self.font.smushMode & (SM_SMUSH | SM_KERN)) == 0:
            return 0
        maxSmush = self.curCharWidth
        for row in range(self.font.height):
            lineLeft = buffer[row]
            lineRight = curChar[row]
            if self.direction == 'right-to-left':
                lineLeft, lineRight = lineRight, lineLeft
            linebd = len(lineLeft.rstrip(' ')) - 1
            if linebd < 0:
                linebd = 0
            if linebd < len(lineLeft):
                ch1 = lineLeft[linebd]
            else:
                linebd = 0
                ch1 = ''
            charbd = len(lineRight) - len(lineRight.lstrip(' '))
            if charbd < len(lineRight):
                ch2 = lineRight[charbd]
            else:
                charbd = len(lineRight)
                ch2 = ''
            amt = charbd + len(lineLeft) - 1 - linebd
            if ch1 == '' or ch1 == ' ':
                amt += 1
            elif ch2 != '' and self.smushChars(left=ch1, right=ch2) is not None:
                amt += 1
            if amt < maxSmush:
                maxSmush = amt
        return maxSmush

    def smushChars(self, left='', right=''):
        if left == ' ':
            return right
        if right == ' ':
            return left
        if (self.prevCharWidth < 2) or (self.curCharWidth < 2):
            return
        mode = self.font.smushMode
        if (mode & SM_SMUSH) == 0:
            return
        if (mode & 63) == 0:
            if left == self.font.hardBlank:
                return right
            if right == self.font.hardBlank:
                return left
            if self.direction == 'right-to-left':
                return left
            return right
        if mode & SM_HARDBLANK:
            if left == self.font.hardBlank and right == self.font.hardBlank:
                return left
        if left == self.font.hardBlank or right == self.font.hardBlank:
            return
        if mode & SM_EQUAL:
            if left == right:
                return left
        smushes = ()
        if mode & SM_LOWLINE:
            smushes += (('_', r'|/\[]{}()<>'),)
        if mode & SM_HIERARCHY:
            smushes += (
                ('|', r'/\[]{}()<>'),
                (r'\/', '[]{}()<>'),
                ('[]', '{}()<>'),
                ('{}', '()<>'),
                ('()', '<>'),
            )
        for a, b in smushes:
            if left in a and right in b:
                return right
            if right in a and left in b:
                return left
        if mode & SM_PAIR:
            for pair in [left + right, right + left]:
                if pair in ['[]', '{}', '()']:
                    return '|'
        if mode & SM_BIGX:
            if left == '/' and right == '\\':
                return '|'
            if right == '/' and left == '\\':
                return 'Y'
            if left == '>' and right == '<':
                return 'X'
        return


class Figlet:
    def __init__(self, font=DEFAULT_FONT, direction='auto', justify='auto', width=80):
        self.font = font
        self._direction = direction
        self._justify = justify
        self.width = width
        self.Font = FigletFont(font)

    @property
    def direction(self):
        if self._direction == 'auto':
            if self.Font.printDirection == 1:
                return 'right-to-left'
            return 'left-to-right'
        return self._direction

    @property
    def justify(self):
        if self._justify == 'auto':
            return 'left' if self.direction == 'left-to-right' else 'right'
        return self._justify

    def renderText(self, text):
        return _Builder(text, self.Font, self.direction, self.width, self.justify).run()

    def getFonts(self):
        return available()


def figlet_format(text, font=DEFAULT_FONT, **kwargs):
    return Figlet(font, **kwargs).renderText(text)
