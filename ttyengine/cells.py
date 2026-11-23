from . import ansi


def parse(text):
    rows = []
    for line in text.splitlines():
        cells = []
        style = ''
        for part in ansi.SEQUENCE.split(line):
            if not part:
                continue
            if ansi.SEQUENCE.match(part):
                if part in ansi.RESETS:
                    style = ''
                else:
                    style += part
                continue
            for char in part:
                cells.append((char, style))
        rows.append(cells)
    return rows


def blank(cell):
    return cell is None or (cell[0] == ' ' and not cell[1])


def build(rows):
    out = []
    for cells in rows:
        end = len(cells)
        while end and blank(cells[end - 1]):
            end -= 1
        parts = []
        style = ''
        for cell in cells[:end]:
            char, now = (' ', '') if cell is None else cell
            if now != style:
                if style:
                    parts.append(ansi.RESET)
                parts.append(now)
                style = now
            parts.append(char)
        if style:
            parts.append(ansi.RESET)
        out.append(''.join(parts))
    return '\n'.join(out)
