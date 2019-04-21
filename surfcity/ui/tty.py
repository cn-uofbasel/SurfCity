# ssb/surfcity/ui/tty.py

import asyncio
import copy
import fcntl
import json
import logging
import os
import random
import re
import readline
import shutil
import string
import subprocess
import sys
import tempfile
import termios
import time
import traceback
import tty

app = None
import surfcity.app.net  as net
import surfcity.app.util as util
import surfcity.edlin

logger = logging.getLogger('surfcity_ui_tty')
ui_descr = "(tty ui, v2019-04-19)"

error_message = None

draft_text = None
draft_private_text = None
draft_private_recpts = []

kbd = None

# ----------------------------------------------------------------------

def save_draft(txt, recpts):
    global draft_text, draft_private_text, draft_private_recpts
    if recpts != None:
        draft_private_text = txt
        draft_private_recpts = recpts
        app.the_db.set_config('draft_private_post', json.dumps((txt, recpts)))
    else:
        draft_text = txt
        app.the_db.set_config('draft_post', txt)

# ----------------------------------------------------------------------

help = [

    '''Welcome to SurfCity

Below you find a table with the keyboard bindings followed
by a description of SurfCity's philosophy and an explanation
of the command line options.

You can leave this screen by typing 'q'.

Enjoy!

Santa Cruz, Feb 2019
  ssb:   @AiBJDta+4boyh2USNGwIagH/wKjeruTcDX2Aj1r/haM=.ed25519
  email: <christian.tschudin@unibas.ch>''',

    '''Keyboard bindings:

?       this text
q       quit

e       next thread
y       prev thread
f       scroll forward 5 threads, <space> does the same
b       scroll backwards
number  jump to this thread

p       toggle private/public threads
x       extended public thread list

enter   show current thread's content

!       refresh
s       status
t       toggle flags
u       user directory
_       about SurfCity
''',

    '''About SurfCity

Secure Scuttlebutt (SSB) brings to you a deluge of information,
all appended to the message logs of the respective authors:

     SurfCity is the tool to ride this wavefront.

It does so (a) in forward as well as (b) in backward direction
and (c) widens its scan range dynamically, but WITHOUT having
to store all the participants' huge log files.

Typically, the storage footprint of SurfCity is in the range of
tens of MBytes, while a full SSB client easily consumes GigaBytes
of disk storage. Also, when booting freshly into SurfCity, you
will immediately have messages to display: no need to wait for
long download times and indexing pauses.  In that sense SurfCity
is sustainable, riding the wave with roughly constant storage
space - at least if YOU behave sustainably, e.g. block or un-
follow peers if the list becomes too large ;-)

What does "riding the wavefront" mean?

a) By this we mean that SurfCity's most important task is to
scan the Scuttleverse for new content in the forward direction.
SurfCity will process these fresh messages and store them for a
few weeks only. It will also take note of a discussion thread's
first post and keep this information around for a few months
so it can later display the thread's "title". Finally, SurfCity
keeps track of the SSB crypto peer identifiers and the human-
readable names that have been assigned to them.

b) SurfCity also is able to scan content in backwards direction.
From these "historic" messages, SurfCity collects essential
information e.g. the name that a peer has assigned to him/herself,
or the other peers that a peer follows or blocks. Eventually this
background scan bottoms out when the logs of all followed peers
have been scanned entirely.

c) Finally, the breadth of the wavefront is enlarged as SurfCity
learns about whom you are following. In this case, these peers
are added to your "following list" and are also scanned. This is
part of the SSB concept that messages sent by a peer are only
accessible in that peer's log, hence the need to scan it. The
width of the wavefront is even larger than this, as the followed
peers of a followed peer (FOAF, "friends of a friend") are also
scanned. SurfCity scans these FOAF peers less frequently by
randomly picking some of them, in each round. But it's all
fine because SSB is based on eventual concistency, and random
selection will eventually lead SurfCity to visit every peer
within the wavefront's current breadth.

Prototype and Future Work

Beware, this is experimental software! Its main purpose is to
validate the concept of wavefront riding for SSB and to prepare
the ground for a SSB browser that can run on a smartphone but
does not come with a huge GByte storage requirement.
''',

    '''Explanation of command-line options

-offline        prevents SurfCity from doing any scans, but also
                from downloading any message content. This means
                that only cached messages can be displayed (at
                most a few weeks old) and that threads look
                less complete when activating this option.

-narrow         prevents SurfCity to scan the logs of FOAF
                (friends of a friend): Only peers that you
                decided to follow will be considered in the
                scans. This only affects scanning and is not
                a censoring option: All content that SurfCity
                already collected will be used and displayed.

-nocatchup      "do not scan backwards": prevents SurfCity from
                scanning historic messages.

-noextend       "do not scan forwards": prevents SurfCity from
                probing for new messages that extend the peers'
                logs.'''
]

# ----------------------------------------------------------------------

class Keyboard:

    def __init__(self, loop=None):
        fd = sys.stdin.fileno()
        self.loop = loop or asyncio.get_event_loop()
        self.q = asyncio.Queue(loop=self.loop)
        self.old_settings = termios.tcgetattr(fd)
        # tty.setraw(fd)
        tty.setcbreak(fd, termios.TCSADRAIN)
        self.new_settings = termios.tcgetattr(fd)
        # self.new_settings[0] &= ~termios.ICANON
        # self.new_settings[0] &= ~ (termios.BRKINT | termios.IGNBRK)
        self.new_settings[1] |= termios.OPOST | termios.ONLCR
        self.resume()

    def _upcall(self):
        asyncio.ensure_future(self.q.put(sys.stdin.read()), loop=self.loop)

    async def getcmd(self):
        cmd = await self.q.get()
        if len(cmd) == 1:
            if cmd in ['\r', '\n']:
                return 'enter'
            c = ord(cmd[0])
            if c in [8, 127]:
                return 'del'
            if c < 32:
                return f'ctrl-{chr(64+c)}'
            return cmd
        if cmd.isnumeric():
            return cmd
        return 'key sequence'

    def get_until_dot(self):
        self.pause()
        print("(end input with a single dot on a line)")
        lines = []
        while True:
            ln = input()
            if ln == '.':
                break
            lines.append(ln)
        self.resume()
        return lines

    def pause(self):
        self.loop.remove_reader(sys.stdin)
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN,
                          self.old_settings)
        fcntl.fcntl(sys.stdin.fileno(), fcntl.F_SETFL, ~os.O_NONBLOCK)

    def resume(self):
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN,
                          self.new_settings)
        fcntl.fcntl(sys.stdin.fileno(), fcntl.F_SETFL, os.O_NONBLOCK)
        self.loop.add_reader(sys.stdin, self._upcall)

    def __del__(self):
        sys.stdout.flush()
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN,
                          self.old_settings)

# ----------------------------------------------------------------------

printable = set(string.printable)

def mk_printable(s):
    return s.encode('ascii', errors='replace').decode()
#    global printable
#    return str([ x for x in s if x in printable])

def render_lines(lns, at_bottom=True):
    # calls 'less' on a file which we write here
    global kbd
    # lns = [ mk_printable(s) for s in lns ]
    with tempfile.NamedTemporaryFile(mode="w+t", suffix='.txt') as f:
        f.write("\n".join(lns))
        f.flush()
        kbd.pause()
        # old_in  = termios.tcgetattr(sys.stdin.fileno())
        # old_out  = termios.tcgetattr(sys.stdout.fileno())
        # os.system(f"stty tty; tput reset; less {f.name}")
        # subprocess.run(f"less -c -h0 -S +G {f.name}; tput rmcup ", shell=True, executable='/bin/bash')
        scrn = '' # "echo '\x1b[!p\x1b[?1049h\x1b[!p';" # \x1b[1;45r'; "
        if at_bottom:
            cmd = scrn + f"less -c -h0 -S +G -R {f.name}"
        else:
            cmd = scrn + f"less -c -h0 -S -R {f.name}"
        subprocess.run(cmd, shell=True, start_new_session=True)
        # subprocess.run(["stty", "sane"])
        # subprocess.run(["tput", "rs1"])
        # subprocess.run(["less", f"{f.name}"])
        # termios.tcsetattr(sys.stdin.fileno(),  termios.TCSADRAIN, old_in)
        # termios.tcsetattr(sys.stdout.fileno(), termios.TCSADRAIN, old_out)
        kbd.resume()
    
# ----------------------------------------------------------------------
# aux procedures

def my_format(txt, style='left'):
    txt = txt.split('\n')
    out = []
    # w = 79
    # if style in ['center', 'para']:
    w = shutil.get_terminal_size((80, 25))[0] - 1
    if style == 'center':
        for t in txt:
            out.append(' '* ((w-len(t))//2) + t)
    elif style == 'rule':
        for t in txt:
            t = ' ' + '.'* ((w-len(t))//2 - 1) + t
            out.append(t + '.'*(w-len(t)))
    elif style == 'para':
        for t in txt:
            while len(t) > w-3:
                i = w-5
                while i > 0 and not t[i] in ' \t':
                    i -= 1
                if i <= 0:
                    out.append('| ' + t[0:w-4])
                    t = t[w-4:]
                else:
                    out.append('| ' + t[0:i])
                    while t[i] in ' \t' and i < len(t)-1:
                        i += 1
                    t = t[i:]
            out.append('| ' + t)
    elif style == 'repeat':
        out = [ (txt[0] * w)[:w] ]
    else:
        out = txt

    return out

async def aux_get_recpts(secr):
    global draft_text, draft_private_text, draft_private_recpts
    print()
    if draft_private_recpts == []:
        print("Private message: enter the recipients, one per line")
        draft_private_recpts = kbd.get_until_dot()
        save_draft(draft_private_text, draft_private_recpts)

    while True:
        print("Recipients:")
        good, bad = util.lookup_recpts(secr, app, draft_private_recpts)
        both = bad + good
        save_draft(draft_private_text, both)
        both = [ f"[{r[0]}]({r[1]})" for r in util.expand_recpts(app, both) ]
        print('  ' + '\n  '.join(both))
        if bad != []:
            while True:
                print("Invalid recipients. Now what? (Cancel/Edit) [E]: ", end='', flush=True)
                cmd = await kbd.getcmd()
                print()
                if cmd.lower() == 'c':
                    print("canceled")
                    return None
                if cmd.lower() in ['e', 'enter']:
                    break
            print("starting the line editor ...")
            kbd.pause()
            new = surfcity.edlin.editor(both)
            kbd.resume()
            if new:
                save_draft(draft_private_text, new)
            continue
            
        print("Recipients OK? (Yes/Cancel/Edit) [E]: ", end='', flush=True)
        cmd = await kbd.getcmd()
        if cmd.lower() == 'c':
            print("\ncanceled")
            return None
        if cmd.lower() in ['e', 'enter']:
            print("\nstarting the line editor ...")
            new = util.expand_recpts(app, draft_private_recpts)
            kbd.pause()
            new = surfcity.edlin.editor()
            kbd.resume()
            if new:
                save_draft(draft_private_text, new)
            continue
        if cmd.lower() == 'y':
            print()
            return draft_private_recpts
        print()

async def aux_get_body(title, recpts, is_private=False):
    global draft_text, draft_private_text, draft_private_recpts
    body = draft_private_text if is_private else draft_text
    if not body:
        print(title + ", new text:")
        body = kbd.get_until_dot()
        if recpts:
            recpts = util.expand_recpts(app, recpts)
            recpts = [f"[{r[0]}]({r[1]})" for r in recpts]
            print(f"-- {recpts}")
            body = [', '.join(recpts), '' ] + body
        save_draft(body, draft_private_recpts if is_private else None)

    while True:
        print(body)
        print(f"{title}:")
        if len(body) > 0:
            print('| ' + '\n| '.join(body))
        print("Text OK? (Yes_go_to_preview/Cancel/Edit) [E]: ", end='', flush=True)
        cmd = await kbd.getcmd()
        if cmd.lower() == 'c':
            print("\ncanceled")
            return None
        if cmd.lower() in ['e', 'enter']:
            print("\nstarting the line editor ...")
            kbd.pause()
            new = surfcity.edlin.editor(body)
            kbd.resume()
            if new != None:
                body = new
                save_draft(body, draft_private_recpts if is_private else None)
            continue
        print()
        if cmd.lower() == 'y':
            return body

# ----------------------------------------------------------------------

async def cmd_backward(secr, args, list_state):
    print("backward")
    if list_state['show'] == 'Public':
        tlist = list_state['publ']
    else:
        tlist = list_state['priv']
    if len(tlist) == 0:
        print("no threads")
        return
    current = list_state['current']
    step = list_state['step']
    if current < step:
        list_state['current'] = 0
        return
    current -= step
    step = os.get_terminal_size().lines // 4 - 1
    low, high = (current-step+1, current)
    if low < 0:
        low = 0
    if low != high:
        print(f"{list_state['show']} threads ({low+1}-{high+1} of {len(tlist)})")
    for i in range(low, high):
        print("_____")
        print("#%-3d" %(i+1), end='')
        ls2 = copy.copy(list_state)
        ls2['current'] = i
        await cmd_summary(secr, args, ls2)
    # if low != high:
    #     print()
    list_state['current'] = current
    list_state['step'] = step

async def cmd_bottom(secr, args, list_state):
    print('>')
    current = len(list_state['publ']) - 1
    if current < 0:
        current = 0
    list_state['current'] = current

async def cmd_compose(secr, args, list_state):
    if list_state['show'] == 'Public':
        print("not implemented")
        return
    else: # private mode
        recpts = await aux_get_recpts(secr)
        if recpts == None: return
        if secr.id in recpts:
            recpts.remove(secr.id)
        if len(recpts) == 0:
            recpts = None
        while True:
            body = await aux_get_body("Message body", recpts, True)
            if body == None: return
            txt =  my_format(" recipient(s) ", 'rule')
            txt += my_format('\n'.join(recpts), 'para')
            txt += my_format(" private message body ", 'rule')
            txt += my_format('\n'.join(body), 'para')
            txt += my_format("", 'rule')
            print('\n' + '\n'.join(txt) + '\n')
            while True:
                print("OK? (Back/Cancel/Send) [B]: ", end='', flush=True)
                cmd = await kbd.getcmd()
                if cmd.lower() == 'c':
                    print("\ncanceled")
                    return
                if cmd.lower() == 's':
                    app.submit_private_post(secr, '\n'.join(body)+'\n', recpts)
                    print("\nmessage queued")
                    save_draft(None, [])
                    return
                print()
                if cmd.lower() in ['b', 'enter']:
                    break
            

async def cmd_enter(secr, args, list_state):
    print()
    if list_state['show'] == 'Public':
        t = list_state['publ'][list_state['current']]
        msgs, _, _ = await app.expand_thread(secr, t,
                                             args, None, ascii=True)
        app.the_db.update_thread_lastread(t)
    else:
        msgs, title, _ = await app.expand_convo(secr,
                                      list_state['priv'][list_state['current']],
                                         args, True, ascii=True)
    help_text = "[type 'q' to quit, " + \
                "'<' to jump to the beginning, " + \
                "'>' to jump to the end]"
    txt = [""]
    txt += my_format(help_text, 'center')
    txt += my_format("---oldest---", 'center')

    if list_state['show'] == 'Public':
        if len(msgs) > 0 and 'root' in msgs[0]['content']:
            txt += my_format("[some older messages out of reach]", 'center')
    else:
        txt += [""]
        txt += my_format(f"private conversation with", 'center')
        txt += my_format(title[0][1][:-1], 'center')

    for m in msgs:
        a = m['author']
        n = app.feed2name(m['author'])
        if not n:
            n = m['author']
        txt += [""]
        txt += my_format(f" {mk_printable(n)} ({app.utc2txt(m['timestamp'],False)}) ",
                         'rule')
        t = mk_printable(m['content']['text'])
        t = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'[\1]', t)
        txt += my_format(t, 'para')
        txt += my_format(f" {m['key']} ", 'rule')

    txt += [""]
    txt += my_format("---newest---", 'center')
    txt += my_format(help_text, 'center')
    txt += ["\n"]
    render_lines(txt)

async def cmd_forward(secr, args, list_state):
    print("forward")
    if list_state['show'] == 'Public':
        tlist = list_state['publ']
    else:
        tlist = list_state['priv']
    current = list_state['current']
    if len(tlist) == 0:
        print("no threads")
        return
    step = os.get_terminal_size().lines // 4 - 1
    low, high = (current+1, current + step)
    if high >= len(tlist):
        high = len(tlist) - 1
    if low > high:
        low = high
    if low != high:
        print(f"{list_state['show']} threads ({low+1}-{high+1} of {len(tlist)})")
        # print("")
    for i in range(low, high):
        print("_____")
        print("#%-3d" %(i+1), end='')
        ls2 = copy.copy(list_state)
        ls2['current'] = i
        await cmd_summary(secr, args, ls2)
    # if low != high:
    #     print()
    list_state['current'] = high
    list_state['step'] = high - low

async def cmd_help(*args):
    print("?")
    print(f"HELP for the 'tty SurfCity client'" + '''

?       this text
q       quit

e       next thread
y       prev thread
f       scroll forward 5 threads, <space> does the same
b       scroll backwards
number  jump to this thread

p       toggle private/public threads
x       extended public thread list

enter   show current thread's content

c       compose new posting
r       reply to current posting

!       refresh
s       status
t       toggle flags
u       user directory
_       about SurfCity
''')

async def cmd_next(secr, args, list_state):
    print('next')
    if list_state['current']+1 < len(list_state['publ']):
        list_state['current'] += 1
    list_state['step'] = 1

async def cmd_prev(secr, args, list_state):
    print('previous')
    current = list_state['current']
    list_state['current'] = 0 if current <= 0 else current - 1
    list_state['step'] = 1

async def cmd_privpubl(secr, args, list_state):
    if list_state['show'] == 'Public':
        list_state['show'] = 'Private'
        print("private -- preparing list of conversations ... ", end='', flush=True)
        list_state['priv'] = await app.mk_convo_list(secr, args,
                                        cache_only = args.offline)
    else:
        list_state['show'] = 'Public'
        print("public -- preparing list of thread ... ", end='', flush=True)
        list_state['publ'] = app.mk_thread_list(secr, args,
                                     cache_only = args.offline,
                                     extended_network = list_state['extended'])
    print("done")
    app.new_forw = 0
    app.new_back = 0
    list_state['current'] = 0
    list_state['step'] = 1

async def cmd_refresh(secr, args, list_state):
    print('refresh')
    if app.new_forw == 0 and app.new_back == 0:
        return
    print(f"for FWD={app.new_forw}/BWD={app.new_back} new messages\n")
    app.new_forw = 0
    app.new_back = 0
    if list_state['show'] == 'Public':
        i = len(list_state['publ'])
        if list_state['current'] >= i:
            list_state['current'] = 0 if i == 0 else i-1
        t = None if i == 0 else list_state['publ'][list_state['current']]
        lst = app.mk_thread_list(secr, args,
                                 cache_only = args.offline,
                                 extended_network = list_state['extended'])
                                 # extended_network = not args.narrow)
        list_state['publ'] = lst
    else:
        i = len(list_state['priv'])
        if list_state['current'] >= i:
            list_state['current'] = 0 if i == 0 else i-1
        t = None if i == 0 else list_state['priv'][list_state['current']]
        lst = await app.mk_convo_list(secr, args,
                                      cache_only = args.offline)
        list_state['priv'] = lst
    if t in lst:
        list_state['current'] = lst.index(t)
        list_state['step'] = 1
    else:
        list_state['current'] = 0

async def cmd_reply(secr, args, list_state):
    if list_state['show'] == 'Public':
        print("not implemented")
        return
    else: # private mode
        print()
        recpts = list_state['priv'][list_state['current']]['recps']
        recpts = list(set(recpts + [secr.id]))
        recpts2 = copy.copy(recpts)
        recpts2.remove(secr.id)
        m = list_state['priv'][list_state['current']]['msgs'][-1]
        if 'root' in m['content']:
            root, branch = m['content']['root'], m['key']
        else:
            root, branch = m['key'], m['key']
        while True:
            body = await aux_get_body("Message body", recpts2, True)
            if body == None: return
            txt =  my_format(" recipient(s) ", 'rule')
            txt += my_format('\n'.join(recpts), 'para')
            txt += my_format(" private message body ", 'rule')
            txt += my_format('\n'.join(body), 'para')
            txt += my_format("", 'rule')
            print('\n' + '\n'.join(txt) + '\n')
            while True:
                print("OK? (Back/Cancel/Send) [B]: ", end='', flush=True)
                cmd = await kbd.getcmd()
                if cmd.lower() == 'c':
                    print("\ncanceled")
                    return
                if cmd.lower() == 's':
                    app.submit_private_post(secr, '\n'.join(body)+'\n',
                                            recpts, root, branch)
                    print("\nmessage queued")
                    save_draft(None, [])
                    return
                print()
                if cmd.lower() in ['b', 'enter']:
                    break

async def cmd_status(secr, args, list_state):
    print("status")
    s = []
    if args.offline:
        s.append('offline')
    if args.narrow:
        s.append('narrow')
    if not args.nocatchup:
        s.append('catchup')
    if not args.noextend:
        s.append('extend')
    if len(s) > 0:
        print(f"flags: {s}")
    print(f"new msgs: fwd={app.new_forw}, bwd={app.new_back}")
    print()

async def cmd_summary(secr, args, list_state):
    if list_state['show'] == 'Public':
        i = len(list_state['publ'])
        if list_state['current'] >= i:
            list_state['current'] = 0 if i == 0 else i-1
        t = list_state['publ'][list_state['current']]
        _, txt, _ = await app.expand_thread(secr, t, args, None, ascii=True)
    else:
        i = len(list_state['priv'])
        if list_state['current'] >= i:
            list_state['current'] = 0 if i == 0 else i-1
        c = list_state['priv'][list_state['current']]
        _, txt, _ = await app.expand_convo(secr, c, args, True, ascii=True)
    title = txt.pop(0)
    if title[0]:
        print(f"* '{title[1][:71]}'")
    else:
        print(f"  '{title[1][:71]}'")
    for m in txt:
        print("      %-10s  %-46s   %s" % (m[1][:10], m[2][:46], m[0]))

async def cmd_top(secr, args, list_state):
    print('<')
    list_state['current'] = 0

async def cmd_userdir(secr, args, list_state):

    def user2line(feedID, isFriend = False):
        prog = '0'
        front,_ = app.the_db.get_id_front(feedID)
        if front > 0:
            low = app.the_db.get_id_low(feedID)
            if low > 0:
                prog = str((front - low + 1)*100 // front)
        prog = f"  {prog}%"[-4:]
        n = app.feed2name(feedID)
        if not n:
            n = '?'
        fr = '* ' if isFriend else '  '
        return f"{fr}{(n+10*' ')[:10]} {feedID}  {prog}"

    hrule = '\n---\n'
    lines = ['## USER DIRECTORY', hrule]
    me = app.the_db.get_config('id')
    lines.append(f"My feedID:\n\n{user2line(me)}")
    lines.append(hrule)

    pubs = app.the_db.list_pubs()
    frnd = app.the_db.get_friends(me)

    fol = app.the_db.get_following(me)
    t = []
    for f in fol:
        if f in pubs:
            t.append(user2line(f, f in frnd))
    t.sort(key=lambda x:x[2:].lower())
    t = [f"Accredited pubs: {len(pubs)}\n"] + t
    #if len(t) > 1:
    #    t.append('')
    lines.append('\n'.join(t))
    lines.append(hrule)

    fol = app.the_db.get_following(me)
    t1, t2 = [], []
    for f in fol:
        if f in pubs:
            continue
        ln = user2line(f, f in frnd)
        if ln[2:12] == '?         ':
            t2.append(ln)
        else:
            t1.append(ln)
    t1.sort(key=lambda x:x[2:].lower())
    t2.sort(key=lambda x:x[2:].lower())
    t = [f"Followed feeds (* =friend/following back): {len(fol)-len(pubs)}\n"] + t1 + t2
    # if len(t) > 1:
    #     t.append('')
    lines.append('\n'.join(t))
    lines.append(hrule)

    folr = app.the_db.get_followers(me)
    t = []
    for f in folr:
        if f in frnd:
            continue
        t.append(user2line(f))
    t.sort(key=lambda x:x[2:].lower())
    t = [f"Follower feeds (other than friends): {len(t)}\n"] + t
    # if len(t) > 1:
    #     t.append('')
    lines.append('\n'.join(t))
    lines.append(hrule)

    blk = app.the_db.get_following(me, 2)
    t = []
    for f in blk:
        t.append(user2line(f))
    t.sort(key=lambda x:x.lower())
    # if len(t) > 0:
    #     t.append('')
    t = [f"Blocked feeds: {len(blk)}\n"] + t
    lines.append('\n'.join(t))
    lines.append(hrule)

    ffol = app.the_db.get_follofollowing(me)
    t = []
    for f in ffol:
        if f in fol:
            continue
        t.append(user2line(f))
    t.sort(key=lambda x: '~~~~~'+x[2:].lower() if x[2:3]=='?' else x[2:].lower())
    # if len(t) > 0:
    #     t.append('')
    t = [f"Number of feeds followed by the feeds I follow: {len(ffol)}\n"] + t
    lines.append('\n'.join(t))
    lines.append(hrule)
    lines.append("END OF USER DIRECTORY")

    render_lines(lines, at_bottom=False)

async def cmd_xtended(secr, args, list_state):
    if list_state['show'] != 'Public':
        print("xtended only valid in public mode")
        return
    list_state['extended'] = ~list_state['extended']
    print("xtended friends' list of threads\nnow ", end='')
    print("enabled" if list_state['extended'] else "disabled")
    print("public -- preparing list of thread ... ", end='', flush=True)
    list_state['publ'] = app.mk_thread_list(secr, args,
                                     cache_only = args.offline,
                                     extended_network = list_state['extended'])
    print("done")
    app.new_forw = 0
    app.new_back = 0
    print()

async def cmd_about(secr, args, list_state):
    hrule = '\n-------------------------------------------------------------------------------\n'
    lines = [hrule]
    for t in help:
        lines.append(t)
        lines.append(hrule)
    render_lines(lines, at_bottom=False)

# ----------------------------------------------------------------------

cmds = {
    'enter': cmd_enter,
    'summary': cmd_summary,
    'h' : cmd_help,
    '?' : cmd_help,
    '<' : cmd_top,
    '>' : cmd_bottom,
    'b' : cmd_backward,
    '-' : cmd_backward,
    'f' : cmd_forward,
    ' ' : cmd_forward,
    'e' : cmd_next,
    'y' : cmd_prev,
    '!' : cmd_refresh,
    'p' : cmd_privpubl,
    'c' : cmd_compose,
    'r' : cmd_reply,
    's' : cmd_status,
    'u' : cmd_userdir,
    'x' : cmd_xtended,
    '_' : cmd_about,
}

# ----------------------------------------------------------------------


async def scanner(secr, args):
    while True:
        logger.info("%s", f"surfcity-tty {str(time.ctime())} before wavefront")
        try:
            await app.scan_wavefront(secr.id, secr, args)
        except Exception as e:
            logger.info(" ** scanner exception %s", str(e))
            logger.info(" ** %s", traceback.format_exc())
        logger.info("%s", f"surfcity-tty {str(time.ctime())} after wavefront")
        if app.new_friends_flag:
            await app.process_new_friends(secr)
            # app.new_friends_flag = False
        logger.info("%s", f"surfcity {str(time.ctime())} before sleeping")
        await asyncio.sleep(5)

async def main(kbd, secr, args):
    global error_message
    global draft_text, draft_private_text, draft_private_recpts

    draft_text = app.the_db.get_config('draft_post')
    priv = app.the_db.get_config('draft_private_post')
    if priv != None:
        try:
            priv = json.loads(priv)
            draft_private_text, draft_private_recpts = priv
            if type(draft_private_text) == str:
                draft_private_text = draft_private_text.split('\n')
        except:
            pass

    try:
        if not args.offline:
            host = args.pub.split(':')
            if len(host) == 1:
                pattern = host[0]
                pubs = app.the_db.list_pubs()
                for pubID in pubs:
                    pub = pubs[pubID]
                    if pattern in pubID or pattern in pub['host']:
                        host, port = pub['host'], pub['port']
                        break
                else:
                    raise Exception(f"no such pub '{pattern}'")
            else:
                port = 8008 if len(host) < 2 else int(host[1])
                pubID = secr.id if len(host) < 3 else host[2]
                host = host[0]

            send_queue = asyncio.Queue(loop=asyncio.get_event_loop())
            net.init(secr.id, send_queue)
            try:
                print("connecting to\n" + f"  {host}:{port}:{pubID}")
                api = await net.connect(host, port, pubID, secr.keypair)
            except OSError as e:
                logger.info(f"OSError exc: {e}")
                print(e)
                return
            except Exception as e:
                error_message = str(e) # traceback.format_exc()
                # urwid.ExitMainLoop()
                logger.info(f"exc while connecting: {e}")
                print(e)
                return

            app.the_db.add_pub(pubID, host, port)
            print("connected, scanning will start soon ...")
            asyncio.ensure_future(api)

            await app.scan_my_log(secr, args, print)
            if not args.noextend:
                await app.process_new_friends(secr, print)
            asyncio.ensure_future(scanner(secr, args))

        list_state = {
            'publ': app.mk_thread_list(secr, args, cache_only = args.offline,
                                       extended_network = False),
            'current': 0,
            'step': 1,
            'show': "Public",
            'extended': False
        }
        while True:
            if list_state['show'] == 'Public':
                if len(list_state['publ']) == 0:
                    print("no threads")
                else:
                    print("_____")
                    print("#%-3d" %(list_state['current']+1), end='')
                    # print(f"{list_state[3]} thread #{list_state[1]+1}")
                    await cmds['summary'](secr, args, list_state)
                    print()
            else:
                if len(list_state['priv']) == 0:
                    print("no private conversations")
                else:
                    print("_____")
                    print("#%-3d" %(list_state['current']+1), end='')
                    # print(f"{list_state[3]} thread #{list_state[1]+1}")
                    await cmds['summary'](secr, args, list_state)
                    print()
                pass

            if list_state['show'] == 'Public':
                prompt = "sc_extd> "  if list_state['extended'] else \
                         "sc_publ> "
            else:
                prompt = "sc_priv> "
            if app.new_forw > 0:
                prompt = f"(+{app.new_forw}){prompt}"
            print(prompt, end='', flush=True)
            num = ''
            while True:
                cmd = await kbd.getcmd()
                if cmd.isnumeric():
                    num += cmd
                    print(cmd, end='', flush=True)
                    continue
                if cmd == 'del':
                    if num != '':
                        num = num[:-1]
                        print('\b \b', end='', flush=True)
                    continue
                break
            if num != '' and cmd == 'enter':
                print()
                num = int(num)
                t = list_state['publ'] if list_state['show'] == 'Public' else list_state['publ']
                if num == 0 or num > len(t):
                    print("\nindex out of range.")
                else:
                    list_state['current'] = num -1
                continue
            if cmd in ['q', 'Q', 'ctrl-C', 'ctrl-D']:
                print('quit')
                break
            if cmd in cmds:
                await cmds[cmd](secr, args, list_state)
            else:
                print(f"\nunknown cmd '{cmd}'. Type '?' for help.\n")

    except:
        traceback.print_exc()

# ----------------------------------------------------------------------

def launch(app_core, secr, args):
    global app, kbd

    app = app_core
    print(ui_descr)

    the_loop = asyncio.get_event_loop()
    try:
        kbd = Keyboard()
        the_loop.run_until_complete(main(kbd, secr, args))
    except Exception as e:
        s = traceback.format_exc()
        logger.info("main exc %s", s)
        print(s)
    finally:
        kbd.__del__()

    if error_message:
        print(error_message)

# eof
