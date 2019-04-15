#!/usr/bin/env python3

# partial implementation of EDLIN
# (c) 2019 <christian.tschudin@unibas.ch>

import re

def editor(lines):
    # expects an array of lines, returns an array of lines if modified else None
    modif = False
    curr = 0
    print(f"EDLIN: loading {len(lines)} line(s), current line is {curr+1}")
    while True:
        cmd = input('*')
        if len(cmd) == 0:
            if curr >= len(lines): print("no line to edit")
            else:
                print(f"replace line {curr+1} (type <enter> to keep the line as is):")
                print(lines[curr])
                ln = input()
                if ln != '':
                    lines[curr] = ln
                    modif = True
            continue
        orig = cmd
        cmd = cmd.lower()
        if cmd in ['?', 'h']:
            print('''EDLIN help:
  h        this help text
  q        quit (any modification is lost)
  e        exit (modifications are saved)

  <num>    make line <num> the current line

  a        append text after current line
  d        delete current line
  i        insert text before current line
  l        list from current line to end
  p        like 'l' but make last line the current line
  s<text>  search for <text>

  The last group of commands can be prefixed with a range, which
  is either a line number <num>, or a line number pair <from>,<to>''')
            continue
        if cmd.isnumeric():
            n = int(cmd)
            if n < 1 or n > len(lines): print("out of range")
            else:
                curr = n-1
                print(f"{n}: {lines[curr]}")
            continue
        if cmd == 'q':
            if modif:
                cmd = input("there are changes: really quit? y/n [N]:")
                if cmd.lower() != 'y':
                    continue
            return None
        if cmd == 'e': return lines if modif else None

        rng = re.match(r'([0-9.]+)([^0-9,.])|([0-9.]+),([0-9.]+)([^0-9.])', cmd)
        if rng:
            if rng.group(2):
                cmd = rng.group(2)
                if rng.group(1) == '.':
                    rng = (curr, curr)
                else:
                    rng = ( int(rng.group(1))-1, int(rng.group(1))-1 )
            else:
                cmd = rng.group(5)
                a = curr if rng.group(3) == '.' else int(rng.group(3))-1
                b = curr if rng.group(4) == '.' else int(rng.group(4))-1
                rng = ( a, b )
            if rng[0] < 0 or rng[1] < 0 or rng[0] > rng[1]:
                print("invalid range")
                continue

        if cmd == 'd':
            if rng:
                if rng[0] >= len(lines) or rng[1] >= len(lines):
                    print("invalid range")
                    continue
            else:
                rng = (curr, curr)
            del lines[rng[0]:rng[1]+1]
            curr = rng[0]
            if curr == len(lines) and curr > 0: curr -= 1
            modif = True
            continue
        if cmd in ['a', 'i']:
            if rng:
                if rng[0] != rng[1] or \
                   (cmd == 'i' and rng[0] > len(lines)) or \
                   (cmd == 'a' and rng[0] >= len(lines)):
                    print("invalid range")
                    continue
            else:
                rng = (curr, curr)
            new = []
            print("enter text, terminate with a single '.' on a line")
            while True:
                ln = input()
                if ln == '.': break
                new.append(ln)
            if cmd == 'i':
                lines = lines[:rng[0]] + new + lines[rng[0]:]
                curr = rng[0] + len(new)
                if curr == len(lines) and curr > 0: curr -= 1
                print(f"{len(new)} line(s) inserted")
            else:
                lines = lines[:rng[0]+1] + new + lines[rng[0]+1:]
                curr = rng[0] + 1 + len(new)
                if curr >= len(lines) and curr > 0: curr = len(lines)-1
                print(f"{len(new)} line(s) appended")
            print(f"current line is {curr+1}")
            if len(new) > 0: modif = True
            continue
        if cmd in ['l', 'p']:
            if not rng: rng = (curr, len(lines)-1)
            for i in range(rng[0], rng[1]+1):
                print(f"{i+1}: {lines[i]}")
            if cmd == 'p': curr = rng[1]
            continue
        if cmd[0] == 's':
            orig = orig[orig.index('s')+1:]
            if not rng: rng = (0, len(lines)-1)
            for i in range(rng[0], rng[1]+1):
                if orig in lines[i]:
                    print(f"{i+1}: {lines[i]}")
                    cmd = input("correct entry? y/n [Y]:")
                    if len(cmd) == 0 or cmd in ['y', 'Y']:
                        curr = i
                        break
            else:
                print(f"'{orig}' not found")
            continue
        print(f"unknown command {cmd}")

# ---------------------------------------------------------------------------
if __name__ == '__main__':

    import sys

    if len(sys.argv) != 2:
        print(f"useage: {sys.argv[0]} <filename>")
    else:
        fn = sys.argv[1]
        with open(fn, 'r') as f: buf = f.read()
        buf = buf[:-1] if len(buf) > 0 and buf[-1] == '\n' else buf
        new = editor([] if buf == '' else buf.split('\n'))
        if new != None:
            buf = '' if new == [] else '\n'.join(new) + '\n'
            with open(fn, 'w') as f: f.write(buf)
            print(f"New content: {len(new)} line(s) written to {fn}")

# eof
