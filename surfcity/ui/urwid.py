# ssb/surfcity/ui/urwid.py

import asyncio
from   asyncio import get_event_loop, ensure_future
import base64
import copy
import hashlib
import json
import logging
import os
import random
import re
import sys
import time
import traceback
import urwid

app = None
import surfcity.app.net  as net
import surfcity.app.db   as db

logger = logging.getLogger('surfcity_ui_urwid')
ui_descr = " (urwid ui, v2019-04-02)"

the_loop = None # urwid loop

urwid_counter = None
urwid_title = None
urwid_footer = None
urwid_frame = None
urwid_threadList = None
urwid_convoList = None
urwid_msgList = None
urwid_privMsgList = None
urwid_userList = None
screen_size = None

widgets4convoList = []
widgets4threadList = []

# refresh_requested = False
refresh_focus = None
refresh_focus_pos = 0

# new_friends_flag = False
show_extended_network = False

error_message = None

arrow_up      = ['up', 'k']
arrow_down    = ['down', 'j']
arrow_left    = ['left', '<', 'h']
arrow_right   = ['enter', 'right', '>', 'l']
arrow_pg_up   = ['-']
arrow_pg_down = [' ']
key_quit      = ['q', 'Q']

draft_text = None

vacuum_intervall = 60*60*24*7 # once a week

# ----------------------------------------------------------------------


# ----------------------------------------------------------------------

def activate_threadList(secr, clear_focus=False):
    global urwid_frame, urwid_threadList, widgets4threadList
    global refresh_focus, refresh_focus_pos, show_extended_network
    wl = copy.copy(widgets4threadList)
    urwid_threadList = ThreadListBox(secr, wl, show_extended_network)
    if clear_focus:
        refresh_focus = None
        refresh_focus_pos = 0
    else:
        if len(wl) > 0:
            i = 0
            for w in wl:
                if w.key == refresh_focus:
                    break
                i += 1
            if i >= len(wl):
                i = 0 # refresh_focus_pos
            urwid_threadList.set_focus(i)
    urwid_frame.contents['body'] = (urwid_threadList, None)
    output_log("")

def activate_convoList(secr, clearFocus = False):
    global urwid_frame, urwid_convoList, widgets4convoList
    global refresh_focus, refresh_focus_pos
    wl = copy.copy(widgets4convoList)
    urwid_convoList = PrivateConvoListBox(secr, wl)
    if clearFocus:
        refresh_focus = None
        refresh_focus_pos = 0
    else:
        if len(wl) > 0:
            i = 0
            for w in wl:
                if w.key == refresh_focus:
                    break
                i += 1
            if i >= len(wl):
                i = refresh_focus_pos
            urwid_convoList.set_focus(i)
    urwid_frame.contents['body'] = (urwid_convoList, None)
    output_log("")

def activate_help(old_focus = None):
    urwid_helpList = HelpListBox(old_focus)
    urwid_helpList.set_focus(0)
    urwid_frame.contents['body'] = (urwid_helpList, None)
    output_log("")

def activate_user(old_focus = None):
    global urwid_userList
    urwid_userList = UserListBox(old_focus)
    urwid_userList.set_focus(0)
    urwid_frame.contents['body'] = (urwid_userList, None)
    output_log("")

# ----------------------------------------------------------------------

async def construct_threadList(secr, args,
                               cache_only=False, extended_network=False):
    # public threads
    widgets = []
    lst = app.mk_thread_list(secr, args, cache_only = cache_only,
                             extended_network = extended_network)
    blocked = app.the_db.get_following(secr.id, 2)
    odd = True
    logger.info(str(lst))
    for t in lst:
        logger.info(f"thread {t}")
        msgs, txt, _ = await app.expand_thread(secr, t, args, cache_only, blocked)
        logger.info(str(msgs))
        logger.info(str(txt))
        widgets.append(ThreadEntry(t, msgs, txt, 'odd' if odd else 'even'))
        odd = not odd
    return widgets

async def construct_convoList(secr, args, cache_only=False):
    # private conversations
    widgets = []
    convos = await app.mk_convo_list(secr, args, cache_only)
    odd = True
    for c in convos:
        msgs, txt, new_count = await app.expand_convo(secr, c, args, cache_only)
        #                               'oddBold' if odd else 'evenBold')
        #logger.info('convolist')
        #for m in msgs:
        #    logger.info(m)
            
        widgets.append(ConvoEntry(c, msgs, txt, new_count,
                                  'odd' if odd else 'even'))
        odd = not odd
    return widgets

async def main(secr, args):
    global widgets4threadList, widgets4convoList, error_message
    global draft_text
    # global refresh_requested #, new_friends_flag

    draft_text = app.the_db.get_config('draft_post')
    try:
        last_vacuum = app.the_db.get_config('last_vacuum')
        now = int(time.time())
        if not last_vacuum or int(last_vacuum) + vacuum_intervall < now:
            logger.info("removing old posts and compacting database")
            app.the_db.forget_posts(app.frontier_window);
            app.the_db.set_config('last_vacuum', now)
            logger.info("database vacuumed")
    except Exception as e:
        logger.info(f"*** {str(e)}")
        logger.info(traceback.format_exc())
    try:
        host = args.pub.split(':')
        port = 8008 if len(host) < 2 else int(host[1])
        pubID = secr.id if len(host) < 3 else host[2]
        host = host[0]

        '''
        async def watchdog(host, port, pubID, keypair):
            await asyncio.sleep(20)
            output_log("disconnect")
            logger.info("disconnect")
            try:
                net.disconnect()
                cor = await net.connect(host, port, pubID, keypair)
                output_log("connected 2 ...")
                ensure_future(cor)
            except Exception as e:
                s = traceback.format_exc()
                output_log(s)
                logger.info("watchdog %s", s)

        ensure_future(watchdog(host, port, pubID, secr.keypair))
        '''

        if not args.offline:
            send_queue = asyncio.Queue(loop=asyncio.get_event_loop())
            net.init(secr.id, send_queue)
            try:
                api = await net.connect(host, port, pubID, secr.keypair)
                output_log("connected, scanning will start soon ...")
            except OSError as e:
                error_message = str(e) # traceback.format_exc()
                logger.exception("exc while connecting")
                # print(e)
                raise urwid.ExitMainLoop()
                return
            except Exception as e:
                error_message = str(e) # traceback.format_exc()
                # urwid.ExitMainLoop()
                logger.exception("exc while connecting")
                return # raise e
            output_log("connected, scanning will start soon ...")
            ensure_future(api)

            await app.scan_my_log(secr, args, output_log, output_counter)
            if not args.noextend:
                await app.process_new_friends(secr, output_log, output_counter)

        widgets4threadList = await construct_threadList(secr, args,
                                                        cache_only=True)
        activate_threadList(secr)
        widgets4convoList  = await construct_convoList(secr, args)

        while True:
            if not args.offline:
                logger.info(f"surfcity {str(time.ctime())} before wavefront")
                await app.scan_wavefront(secr.id, secr, args,
                                         output_log, output_counter)
                logger.info(f"surfcity {str(time.ctime())} after wavefront")
            if app.refresh_requested:
                if urwid_frame.contents['body'][0] == urwid_threadList:
                    output_log("Preparing public content list...")
                    widgets4threadList = await construct_threadList(secr, args,
                                        extended_network = show_extended_network)
                    activate_threadList(secr)
                    widgets4convoList  = await construct_convoList(secr, args)
                elif urwid_frame.contents['body'][0] == urwid_convoList:
                    output_log("Preparing private content list...")
                    widgets4convoList  = await construct_convoList(secr, args)
                    activate_convoList(secr)
                    widgets4threadList = await construct_threadList(secr, args,
                                        extended_network = show_extended_network)
                app.refresh_requested = False
                app.counter_reset(output_counter)
            else:
                # construct the *other* list (that is not being displayed)
                if urwid_frame.contents['body'][0] == urwid_threadList:
                    widgets4convoList  = await construct_convoList(secr, args)
                elif urwid_frame.contents['body'][0] == urwid_convoList:
                    widgets4threadList = await construct_threadList(secr, args)
            if app.new_friends_flag:
                await app.process_new_friends(secr, output_log, output_counter)
                app.new_friends_flag = False

            if not args.offline:
                if (urwid_frame.contents['body'][0] == urwid_threadList or \
                    urwid_frame.contents['body'][0] == urwid_convoList) and \
                    app.new_back+app.new_forw > 0:
                    output_log("Type '!' to refresh screen")
                else:
                    output_log("")

            logger.info("%s", f"surfcity {str(time.ctime())} before sleeping")
            for i in range(50):
                await asyncio.sleep(0.1)
                if app.refresh_requested:
                    break

#        if not args.offline:
#            fu.cancel()

    except Exception as e:
        logger.info("exception in main()")
        if not error_message:
            # s = '\n'.join(traceback.format_exc(-1).split('\n')[1:-2])
            s = traceback.format_exc()
            logger.error(s)
            print(s)
            output_log(f"Exception: {str(e)}\n{s}\n\nuse CTRL-C to terminate")
            error_message = str(e)
        else:
            pass
            # logger.error(error_message)
            # print('x' + error_message)
            # output_log(error_message)
        raise urwid.ExitMainLoop()

# ----------------------------------------------------------------------

def output_log(txt='', end=None, flush=None):
    # print(txt)
    if len(txt) > 0 and txt[0] == '\r':
        txt = txt[1:]
    if len(txt) > 0 and txt[-1] == '\r':
        txt = txt[:-1]
    urwid_footer.set_text(txt)
    pass

def on_unhandled_input(key):
    output_log(f"unhandled event: {str(key)}")

def output_counter():
    urwid_counter.set_text(f"FWD={app.new_forw} BWD={app.new_back} ")


# ----------------------------------------------------------------------

def mouse_scroll(obj, size, button):
    if button == 4:
        obj.keypress(size, 'up')
    if button == 5:
        obj.keypress(size, 'down')

def smooth_scroll(obj, size, key):
    lw = obj.body
    if key in arrow_up:
        pos = lw.get_focus()[1]
        try:
            p = lw.get_prev(pos)[1]
            lw.set_focus(p)
            obj.shift_focus(size, 5)
        except:
            pass
        return True
    if key in arrow_down:
        pos = lw.get_focus()[1]
        n = lw.get_next(pos)[1]
        if n:
            lw.set_focus(n)
            obj.shift_focus(size, size[1]-10)
        return True
    return False
    
# ----------------------------------------------------------------------

help = [

    '''Welcome to SurfCity

Below you find a table with the keyboard bindings followed
by a description of SurfCity's philosophy and an explanation
of the command line options.

You can leave this screen by typing '<' or left-arrow.

Enjoy!

Santa Cruz, Feb 2019
  ssb:   @AiBJDta+4boyh2USNGwIagH/wKjeruTcDX2Aj1r/haM=.ed25519
  email: <christian.tschudin@unibas.ch>''',

    '''Keyboard bindings:

?                      this help screen
q, ESC                 quit

r                      refresh Private or Public screen
p                      toggle between Private and Public screen
e                      toggle extended network (when in Public screen,
                       and when doing the next screen refresh)

u                      user directory screen (rudimentary)

c                      compose new message
r                      reply in a thread

>, l, right-arrow, enter   enter detail page
<, h, left-arrow       leave detail page
down/up-arrow, j/k     move upwards/downwards in the list
page-down, page-up     scroll through the list''',

    '''About SurfCity

Secure Scuttlebutt (SSB) brings to you a deluge of information,
all appended to the message logs of the respective authors:

     SurfCity is the tool to ride this wavefront.

It does so (a) in forward as well as (b) in backward direction
and (c) widens its scan range dynamically, but WITHOUT having
to store all the participants' huge log files.

Typically, the storage footprint of SurfCity is in the range of tens
of MBytes, while a full SSB client easily requires several hundreds of
MegaBytes of disk storage. Also, when booting freshly into SurfCity,
you will immediately have messages to display: no need to wait for
long download times and indexing pauses.  In that sense SurfCity is
sustainable, riding the wave with roughly constant storage space - at
least if YOU behave sustainably, e.g. block or un-follow peers if the
list becomes too large ;-)

What does "riding the wavefront" mean?

a) By this we mean that SurfCity's most important task is to
scan the Scuttleverse for new content in the forward direction.
SurfCity will process these fresh messages and store them for a
few weeks only. It will also take note of a discussion thread's
first post and keep this information around for a few months
so it can later display the thread's "title". Finally, SurfCity
keeps track of the SSB crypto peer identifiers and the human-
readable names that have been assigned to them.

b) SurfCity is also able to scan content in backwards direction.
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
does not come with a huge storage requirement.
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

class HelpListBox(urwid.ListBox):

    _selectable = True

    def __init__(self, goback, lst=[]):
        self.goback = goback
        self.title = "Help Text"
        urwid_title.set_text(self.title)
        lst = [urwid.Text('v--- H E L P ---v', 'center')]
        for h in help:
            t = urwid.AttrMap(urwid.Text(h), 'odd')
            p = urwid.Pile([urwid.Text(''),t,urwid.Text('')])
            lst.append(urwid.Padding(p, left=2, right=2))
        lst.append(urwid.Text('^--- H E L P ---^', 'center'))
        body = urwid.SimpleFocusListWalker(lst)
        super(HelpListBox, self).__init__(body)

    def keypress(self, size, key):
        key =  super(HelpListBox, self).keypress(size, key)

        if key in key_quit:
            raise urwid.ExitMainLoop()
        if key in arrow_pg_down:
            return self.keypress(size, 'page down')
        if key in arrow_pg_up:
            return self.keypress(size, 'page up')
        if not key in arrow_left:
            return key
        urwid_title.set_text(self.goback.title)
        urwid_frame.contents['body'] = (self.goback, None)

    def mouse_event(self, size, event, button, x, y, focus):
        mouse_scroll(self, size, button)

# ----------------------------------------------------------------------

class UserListBox(urwid.ListBox):

    _selectable = True

    def _user2line(self, feedID, isFriend = False):
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

    def _lines2widget(self, lns):
        t = urwid.AttrMap(urwid.Text('\n'.join(lns)), 'odd')
        p = urwid.Pile([urwid.Text(''),t,urwid.Text('')])
        return urwid.Padding(p, left=2, right=2)

    def __init__(self, goback, lst=[]):
        self.goback = goback
        self.title = "User Directory"

        urwid_title.set_text(self.title)
        lst = [urwid.Text('v--- U S E R S ---v', 'center')]
        me = app.the_db.get_config('id')

        lst.append(self._lines2widget([f"My feedID:\n\n{self._user2line(me)}\n"]))

        pubs = app.the_db.list_pubs()
        frnd = app.the_db.get_friends(me)

        fol = app.the_db.get_following(me)
        t = []
        for f in fol:
            if f in pubs:
                t.append(self._user2line(f, f in frnd))
        t.sort(key=lambda x:x[2:].lower())
        t = [f"Accredited pubs: {len(pubs)}\n"] + t
        if len(t) > 1:
            t.append('')
        lst.append(self._lines2widget(t))

        fol = app.the_db.get_following(me)
        t1, t2 = [], []
        for f in fol:
            if f in pubs:
                continue
            ln = self._user2line(f, f in frnd)
            if ln[2:12] == '?         ':
                t2.append(ln)
            else:
                t1.append(ln)
        t1.sort(key=lambda x:x[2:].lower())
        t2.sort(key=lambda x:x[2:].lower())
        t = [f"Followed feeds (* =friend/following back): {len(fol)-len(pubs)}\n"] + t1 + t2
        if len(t) > 1:
            t.append('')
        lst.append(self._lines2widget(t))

        folr = app.the_db.get_followers(me)
        t = []
        for f in folr:
            if f in frnd:
                continue
            t.append(self._user2line(f))
        t.sort(key=lambda x:x[2:].lower())
        t = [f"Follower feeds (other than friends): {len(t)}\n"] + t
        if len(t) > 1:
            t.append('')
        lst.append(self._lines2widget(t))

        blk = app.the_db.get_following(me, 2)
        t = []
        for f in blk:
            t.append(self._user2line(f))
        t.sort(key=lambda x:x.lower())
        if len(t) > 0:
            t.append('')
        t = [f"Blocked feeds: {len(blk)}\n"] + t
        lst.append(self._lines2widget(t))

        ffol = app.the_db.get_follofollowing(me)
        t = []
        for f in ffol:
            if f in fol:
                continue
            t.append(self._user2line(f))
        t.sort(key=lambda x: '~~~~~'+x[2:].lower() if x[2:3]=='?' else x[2:].lower())
        if len(t) > 0:
            t.append('')
        t = [f"Number of feeds followed by the feeds I follow: {len(ffol)}\n"] + t
        lst.append(self._lines2widget(t))

        lst.append(urwid.Text('^--- U S E R S ---^', 'center'))
        body = urwid.SimpleFocusListWalker(lst)
        super(UserListBox, self).__init__(body)

    def keypress(self, size, key):
        key =  super(UserListBox, self).keypress(size, key)

        if key in key_quit:
            raise urwid.ExitMainLoop()
        if key in arrow_pg_down:
            return self.keypress(size, 'page down')
        if key in arrow_pg_up:
            return self.keypress(size, 'page up')
        if key in ['?']:
            return activate_help(urwid_userList)
        if not key in arrow_left:
            return key
        urwid_title.set_text(self.goback.title)
        urwid_frame.contents['body'] = (self.goback, None)

    def mouse_event(self, size, event, button, x, y, focus):
        mouse_scroll(self, size, button)

# ----------------------------------------------------------------------

class ConvoEntry(urwid.AttrMap):

    _selectable = True

    def __init__(self, convo, msgs, txt, new_count, attr=None):
        self.convo = convo
        self.msgs = msgs
        self.key = self.convo # for the jump_to_last_entry_after_refresh logic
        self.star = urwid.Text('*' if new_count > 0 else ' ')
        self.count = urwid.Text(('selected', f"({new_count} new)" \
                                 if new_count > 0 else ""), 'right')
        self.convo_title = txt[0][1]
        lines = [ urwid.Text(f"{self.convo_title[:75]} ({len(msgs)} messages)") ]
        for ln in txt[1:]:
            lines.append(urwid.Columns([
                (12, urwid.Text(ln[1][:10]+'  ', 'left', wrap='clip')),
                urwid.Text(ln[2], 'left', wrap='clip'),
                (16, urwid.Text('   '+ln[0]+' ','right', wrap='clip'))
            ]))
        lines.append(self.count)
        pile = urwid.AttrMap(urwid.Pile(lines), attr)
        cols = urwid.Columns([(2,self.star),pile])
        super(ConvoEntry, self).__init__(cols, None, focus_map='selectedPrivate')

class PrivateConvoListBox(urwid.ListBox):

    _selectable = True

    def __init__(self, secr, lst=[]):
        self.secr = secr
        self.title = "PRIVATE conversations:"
        urwid_title.set_text(self.title)
        body = urwid.SimpleFocusListWalker(lst)
        super(PrivateConvoListBox, self).__init__(body)

    def keypress(self, size, key):
        global urwid_privMsgList
        global refresh_focus, refresh_focus_pos # refresh_requested, 
        if smooth_scroll(self, size, key):
            return
        key = super(PrivateConvoListBox, self).keypress(size, key)

        if key in key_quit:
            raise urwid.ExitMainLoop()
        if key in arrow_pg_down:
            return self.keypress(size, 'page down')
        if key in arrow_pg_up:
            return self.keypress(size, 'page up')
        if key in ['!']:
            app.refresh_requested = True
            if self.focus:
                refresh_focus = self.focus.key
                refresh_focus_pos = self.get_focus()[1]
            else:
                refresh_focus = None
                refresh_focus_pos = 0
            return
        if key in ['p', 'p']:
            return activate_threadList(self.secr, True)
        if key in ['?']:
            return activate_help(urwid_convoList)
        if key in ['u', 'U']:
            return activate_user(urwid_convoList)
        if key in ['c']:
            w = EditDialog('new PRIVATE message', draft_text)
            c = ConfirmTextDialog()
            w.open(lambda txt: c.open(txt,
                           lambda : w.reopen(),
                           lambda y: app.submit_private_post(self.secr,y))
            )
            return
        if key in ['r']:
            dest = self.focus.convo_title
            w = EditDialog(f"Private reply to {dest}", draft_text)
            c = ConfirmTextDialog()
            w.open(lambda txt: c.open(txt,
                           lambda : w.reopen(),
                           lambda y: app.submit_private_post(self.secr,y,
                                                             self.root,
                                                             self.branch))
            )
            return

        if not key in ['enter', '>', 'right']:
            return key
        self.focus.star.set_text('')
        self.focus.count.set_text('')
        for t in self.focus.convo['threads']:
            app.the_db.update_thread_lastread(t)
        lst = [urwid.Text('---oldest---', 'center')]
        root, branch = (None, None) # we only want the last one
        for m in self.focus.msgs:
            branch = m['key']
            root = m['content']['root'] if 'root' in m['content'] else branch
            a = m['author']
            n = app.feed2name(m['author'])
            if not n:
                n = m['author']
            n = urwid.Columns([urwid.Text(n),
                               (13, urwid.Text(app.utc2txt(m['timestamp'])))])
            t = m['content']['text']
            t = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'[\1]', t)
            t = urwid.AttrMap(urwid.Text(t), 'odd')
            r = urwid.Text(m['key'], 'right')
            p = urwid.Pile([urwid.Text(''),n,t,r,urwid.Text('')])
            lst.append(urwid.Padding(p, left=2, right=2))
        lst.append(urwid.Text('---newest---', 'center'))
        
        # nms = []
        # for r in self.focus.convo['recps']:
        #     n = app.feed2name(r)
        #     if not n:
        #          n = r[:10]
        #     nms.append(n)
        ## if len(nms) == 0:
        ##     nms = [app.feed2name(secr.id)]
        # title = f"Private conversation with <{', '.join(nms)[:50]}>:"
        title = f"Private conversation with {self.focus.convo_title[:50]}:"

        urwid_privMsgList = PrivateMessageListBox(self.secr, urwid_convoList,
                                                  title, lst,
                                                  root, branch)
        urwid_privMsgList.set_focus(len(lst)-1)
        urwid_frame.contents['body'] = (urwid_privMsgList, None)

    def mouse_event(self, size, event, button, x, y, focus):
        mouse_scroll(self, size, button)

class PrivateMessageListBox(urwid.ListBox):
    # private convo messages

    _selectable = True

    def __init__(self, secr, goback, title, lst=[], root=None, branch=None):
        self.secr = secr
        self.goback = goback
        self.title = title
        urwid_title.set_text(title)
        self.root = root
        self.branch = branch
        body = urwid.SimpleFocusListWalker(lst)
        super(PrivateMessageListBox, self).__init__(body)

    def keypress(self, size, key):
        global screen_size
        screen_size = (size[0], size[1]+3)

        key =  super(PrivateMessageListBox, self).keypress(size, key)

        if key in key_quit:
            raise urwid.ExitMainLoop()
        if key in arrow_pg_down:
            return self.keypress(size, 'page down')
        if key in arrow_pg_up:
            return self.keypress(size, 'page up')
        if key in ['?']:
            return activate_help(urwid_privMsgList)
            # return activate_help(urwid_convoList)

        if key in ['c']:
            w = EditDialog('new PRIVATE message', draft_text)
            c = ConfirmTextDialog()
            w.open(lambda txt: c.open(txt,
                           lambda : w.reopen(),
                           lambda y: app.submit_private_post(self.secr,y))
            )
            return
        if key in ['r']:
            dest = self.title[self.title.index('<'):-1]
            w = EditDialog(f"Private reply to {dest}", draft_text)
            c = ConfirmTextDialog()
            w.open(lambda txt: c.open(txt,
                           lambda : w.reopen(),
                           lambda y: app.submit_private_post(self.secr,y,
                                                             self.root,
                                                             self.branch))
            )
            return
        
        if not key in arrow_left:
            return key
        urwid_title.set_text(self.goback.title)
        urwid_frame.contents['body'] = (self.goback, None)
    
    def mouse_event(self, size, event, button, x, y, focus):
        mouse_scroll(self, size, button)

# ----------------------------------------------------------------------

class ThreadEntry(urwid.AttrMap):

    _selectable = True

    def __init__(self, key, msgs, txt, attr=None):
        self.key = key
        self.msgs = msgs
        new_count = txt[0][0]
        self.star = urwid.Text('*' if new_count > 0 else ' ')
        self.count = urwid.Text(('selected', f"({new_count} new)" \
                                 if new_count > 0 else ""), 'right')
        # lines = [ urwid.Text((attr+'Bold',f"'{txt[0][1][:75]}'")) ]
        lines = [ urwid.Text((attr+'Bold',f"'{txt[0][1][:75]}'")) ]
        for ln in txt[1:]:
            lines.append(urwid.Columns([
                (12, urwid.Text(ln[1][:10]+'  ', 'left', wrap='clip')),
                urwid.Text(ln[2], 'left', wrap='clip'),
                (16, urwid.Text('   '+ln[0]+' ','right', wrap='clip'))
            ]))
        lines.append(self.count)
        pile = urwid.AttrMap(urwid.Pile(lines), attr)
        cols = urwid.Columns([(2,self.star),pile])
        super(ThreadEntry, self).__init__(cols, None, focus_map='selected')

class MessageListBox(urwid.ListBox):
    # public thread's messages

    _selectable = True

    def __init__(self, secr, goback, title, lst=[], root=None, branch=None):
        self.secr = secr
        self.goback = goback
        self.title = title
        urwid_title.set_text(title)
        self.root = root
        self.branch = branch
        body = urwid.SimpleFocusListWalker(lst)
        super(MessageListBox, self).__init__(body)

    def keypress(self, size, key):
        key =  super(MessageListBox, self).keypress(size, key)

        if key in key_quit:
            raise urwid.ExitMainLoop()
        if key in arrow_pg_down:
            return self.keypress(size, 'page down')
        if key in arrow_pg_up:
            return self.keypress(size, 'page up')
        if key in ['?']:
            # if self.goback == urwid_threadList:
            return activate_help(urwid_msgList)
            # else:
            #     return activate_help(urwid_privMsgList)
        if key in ['c', 'r']:
            root, branch = (self.root, self.branch)
            if key == 'c':
                w = EditDialog(f"new PUBLIC message and chat", draft_text)
                root, branch = (None, None)
            else:
                w = EditDialog(f"PUBLIC msg in chat {self.title[8:50]}",
                               draft_text)
            c = ConfirmTextDialog()
            w.open(lambda txt: c.open(txt,
                           lambda : w.reopen(),
                           lambda y: app.submit_public_post(self.secr, y,
                                                            root, branch))
            )
            return
        if not key in arrow_left:
            return key

        urwid_title.set_text(self.goback.title)
        urwid_frame.contents['body'] = (self.goback, None)

    def mouse_event(self, size, event, button, x, y, focus):
        mouse_scroll(self, size, button)

class ThreadListBox(urwid.ListBox):
    # list of public threads

    _selectable = True

    def __init__(self, secr, lst=[], show_extended_network=False):
        self.secr = secr
        self.title = "PUBLIC chats (extended network):" \
                     if show_extended_network else \
                        "PUBLIC chats (with or from people I follow):"
        urwid_title.set_text(self.title)
        body = urwid.SimpleFocusListWalker(lst)
        super(ThreadListBox, self).__init__(body)

    def keypress(self, size, key):
        global urwid_msgList, show_extended_network
        global refresh_focus, refresh_focus_pos # refresh_requested,
        global screen_size
        screen_size = (size[0], size[1]+3)

        if smooth_scroll(self, size, key):
            return
        key = super(ThreadListBox, self).keypress(size, key)

        if key in key_quit:
            raise urwid.ExitMainLoop()
        if key in arrow_pg_down:
            return self.keypress(size, 'page down')
        if key in arrow_pg_up:
            return self.keypress(size, 'page up')
        if key in ['e', 'E']:
            show_extended_network = not show_extended_network
            # output_log(f"show_extended_network now= {show_extended_network}")
            key = '!'
        if key in ['!']:
            app.refresh_requested = True
            if self.focus:
                refresh_focus = self.focus.key
                refresh_focus_pos = self.get_focus()[1]
            else:
                refresh_focus = None
                refresh_focus_pos = 0
            return
        if key in ['?']:
            return activate_help(urwid_threadList)
        if key in ['u', 'U']:
            return activate_user(urwid_threadList)
        if key in ['p', 'P']:
            return activate_convoList(self.secr, True)
        if key in ['c']:
            w = EditDialog(f"new PUBLIC message and chat", draft_text)
            c = ConfirmTextDialog()
            w.open(lambda txt: c.open(txt,
                           lambda : w.reopen(),
                           lambda y: app.submit_public_post(self.secr, y))
            )
            return
        if not key in arrow_right:
            return key

        self.focus.star.set_text('')
        self.focus.count.set_text('')
        app.the_db.update_thread_lastread(self.focus.key)
        lst = [urwid.Text('---oldest---', 'center')]
        if len(self.focus.msgs) > 0 and 'root' in self.focus.msgs[0]['content']:
            lst.append(urwid.Text('[some older messages out of reach]', 'center'))
        root, branch = (None, None) # we only want the last one
        for m in self.focus.msgs:
            branch = m['key']
            root = m['content']['root'] if 'root' in m['content'] else branch
            a = m['author']
            n = app.feed2name(m['author'])
            if not n:
                n = m['author']
            n = urwid.Columns([urwid.Text(n),
                               (13, urwid.Text(app.utc2txt(m['timestamp'])))])
            t = m['content']['text']
            t = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'[\1]', t)
            t = urwid.AttrMap(urwid.Text(t), 'odd')
            r = urwid.Text(m['key'], 'right')
            p = urwid.Pile([urwid.Text(''),n,t,r,urwid.Text('')])
            lst.append(urwid.Padding(p, left=2, right=2))
        lst.append(urwid.Text('---newest---', 'center'))

        title = app.the_db.get_thread_title(self.focus.key)
        if title:
            title = f"Public: '{app.text2synopsis(title)}'"
        else:
            title = "Public: <unknown first post>"

        urwid_msgList = MessageListBox(self.secr, urwid_threadList, title, lst,
                                       root, branch)
        urwid_msgList.set_focus(len(lst)-1)
        urwid_frame.contents['body'] = (urwid_msgList, None)

    def mouse_event(self, size, event, button, x, y, focus):
        mouse_scroll(self, size, button)

# ----------------------------------------------------------------------

class EditDialog(urwid.Overlay):

    def __init__(self, bannerTxt, draft=None):
        header_text = urwid.Text(('banner', bannerTxt + \
                                  '\n(use TAB to select buttons)'),
                                 align = 'center')
        header = urwid.AttrMap(header_text, 'banner')

        self.edit = urwid.Edit(multiline=True)
        if draft:
            self.edit.set_edit_text(draft)
        self.edit.set_edit_pos(0)

        # body_text = urwid.Text(text, align = 'center')
        # body_filler = urwid.Filler(body_text, valign = 'top')
        body_filler = urwid.Filler(self.edit, valign = 'top')
        body_padding = urwid.Padding(
            body_filler,
            left = 1,
            right = 1
        )
        body = urwid.LineBox(body_padding)

        w = the_loop.widget
        footer1 = urwid.Button('Cancel', lambda x:self.close())
        footer2 = urwid.Button('Preview', lambda x: self._callback())
        # footer = urwid.AttrWrap(footer, 'selectable', 'focus')
        footer = urwid.GridFlow([footer1,footer2], 11, 1, 1, 'center')

        self.layout = urwid.Frame(body, header = header, footer = footer)
        super(EditDialog, self).__init__(urwid.LineBox(self.layout), w,
                                         align = 'center', valign = 'middle',
                                         width = screen_size[0]-2,
                                         height = screen_size[1]-2)
        
    def keypress(self, size, key):
        # if key in key_quit:
        #     raise urwid.ExitMainLoop()
        if key in ['esc']:
            global draft_text
            draft_text = self.edit.get_edit_text()
            app.the_db.set_config('draft_post', draft_text)
            self.close()
        if key in ['tab']:
            paths = [[1, 'body'], [1, 'footer', 0], [1, 'footer', 1]]
            fp = self.get_focus_path()
            i = (paths.index(fp) + 1) % len(paths)
            self.set_focus_path(paths[i])
            return
        key = super(EditDialog, self).keypress(size, key)

    def open(self, ok_callback):
        self.callback = ok_callback
        self.set_focus_path([1, 'body'])
        the_loop.widget = self

    def reopen(self):
        self.set_focus_path([1, 'body'])
        the_loop.widget = self

    def _callback(self):
        global draft_text
        self.close()
        txt = self.edit.get_edit_text()
        draft_text = txt
        app.the_db.set_config('draft_post', draft_text)
        self.callback(txt)
        
    def close(self):
        the_loop.widget = urwid_frame
        the_loop.draw_screen()

class ConfirmTextDialog(urwid.Overlay):

    def __init__(self):
        header_text = urwid.Text(('selected', ' Really post this message? \n(use up/down arrows to scroll, TAB to select buttons)'),
                                 align = 'center')
        header = urwid.AttrMap(header_text, 'banner')

        self.body_text = urwid.Text('dummy', align = 'left')
        body_filler = urwid.ListBox(urwid.SimpleFocusListWalker([self.body_text]))
        body_padding = urwid.Padding(body_filler, left = 1, right = 1)
        body = urwid.LineBox(body_padding)

        w = the_loop.widget
        footer1 = urwid.Button('back',  lambda x:self._back_callback())
        footer2 = urwid.Button('cancel', lambda x:self.close())
        footer3 = urwid.Button(' send!',  lambda x:self._send_callback())
        # footer = urwid.AttrWrap(footer, 'selectable', 'focus')
        footer = urwid.GridFlow([footer1,footer2,footer3], 10, 1, 1, 'center')

        self.layout = urwid.Frame(body, header = header, footer = footer)
        super(ConfirmTextDialog, self).__init__(urwid.LineBox(self.layout), w,
                                         align = 'center', valign = 'middle',
                                         width = screen_size[0]-2,
                                         height = screen_size[1]-2)
        
    def keypress(self, size, key):
        # if key in key_quit:
        #     raise urwid.ExitMainLoop()
        if key in ['esc']:
            self.close()
        if key in ['tab']:
            paths = [[1, 'body', 0],   [1, 'footer', 0],
                     [1, 'footer', 1], [1, 'footer', 2]]
            fp = self.get_focus_path()
            i = (paths.index(fp) + 1) % len(paths)
            self.set_focus_path(paths[i])
            return
        key = super(ConfirmTextDialog, self).keypress(size, key)

    def open(self, text, back_callback, send_callback):
        self.back_callback = back_callback
        self.send_callback = send_callback
        r = r"(#[a-zA-Z0-9\-_\.]+)|(%.{44}\.sha256)|(@.{44}.ed25519)|(\(([^\)]+)\)\[[^\]]+\])|(\[[^\]]+\]\([^\)]+\))"
        all = []
        pos = 0
        for i in re.finditer(r, text):
            s = i.span()
            if s[0] > pos:
                all.append(i.string[pos:s[0]])
            m = i.string[i.start(0):i.end(0)]
            if m[0] in ['@', '%', '&']:
                m = f"{m[:8]}.."
            elif m[0] in ['(']:
                m = re.match(r"\(([^\)]+)\)\[([^\]]+)\]", m)
                m = m.group(1)
            elif m[0] in ['[']:
                m = re.match(r"\[([^\]]+)\]\(([^\)]+)\)", m)
                m = m.group(1)
            all.append(('cypherlink', m))
            pos = s[1]
        if pos < len(text):
            all.append(text[pos:len(text)])
        self.body_text.set_text(all)
        self.set_focus_path([1, 'body'])
        the_loop.widget = self

    def _back_callback(self):
        self.close()
        self.back_callback()

    def _send_callback(self):
        global draft_text
        logger.info("send_callback")
        self.close()
        draft_text = None
        app.the_db.get_config('draft_post', None)
        self.send_callback(str(self.body_text.get_text()[0]))
        
    def close(self):
        the_loop.widget = urwid_frame
        the_loop.draw_screen()

# ----------------------------------------------------------------------

def launch(app_core, secr, args):
    global app, the_loop
    global urwid_counter, urwid_title, urwid_header
    global urwid_footer, urwid_threadList, urwid_convoList, urwid_frame

    app = app_core
    print(ui_descr)

    palette = [
            ('even', 'default', 'default', 'standout'),
            ('evenBold', 'default,bold', 'default'),
            ('odd', 'white', 'dark gray', 'standout'),
            ('oddBold', 'white,bold', 'dark gray', 'standout'),
            ('header', 'black', 'light green', 'underline'),
            ('selected', 'black', 'light red', 'standout'),
            ('selectedPrivate', 'black', 'light blue', 'standout'),
            ('cypherlink', 'light blue', 'default', 'underline')
    ]
    screen = urwid.raw_display.Screen()
    screen.register_palette(palette)
    screen.set_terminal_properties(screen.colors)

    urwid_counter = urwid.Text('FWD=0 BWD=0 ', 'right', wrap='clip')
    urwid_title = urwid.Text('PUBLIC chats:', wrap='clip')
    urwid_header = urwid.Pile([
            urwid.Columns([('pack',urwid.Text(f"SurfCity - a log-less SSB client{ui_descr}", wrap='clip')),
                           urwid_counter
            ]),
        urwid_title
    ])
    urwid_hdrmap = urwid.AttrMap(urwid_header, 'header')
    if args.offline:
        urwid_footer = urwid.Text('Offline') # , wrap='clip')
    else:
        urwid_footer = urwid.Text('Welcome, please stand by ...', wrap='clip')
    urwid_ftrmap = urwid.AttrMap(urwid.Columns([
            urwid_footer,
            ('pack', urwid.Text(" Type '?' for help.", 'right'))
        ]), 'header')
    urwid_threadList = urwid.ListBox([urwid.Text('Almost there ...')])
    urwid_convoList = PrivateConvoListBox(secr, [urwid.Text('Just a moment...')])
    urwid_frame = urwid.Frame(urwid_threadList, header=urwid_hdrmap,
                                  footer=urwid_ftrmap,
                                  focus_part = 'body')

    logger.info("%s", f"surfcity {str(time.ctime())} starting")

    evl = urwid.AsyncioEventLoop(loop=asyncio.get_event_loop())
    ensure_future(main(secr, args))
    the_loop = urwid.MainLoop(urwid_frame, palette, event_loop=evl,
                              unhandled_input=on_unhandled_input)
    try:
        the_loop.run()
    except Exception as e:
        s = traceback.format_exc()
        logger.info("main exc %s", s)
        print(s)

    if error_message:
        print(error_message)

# eof
