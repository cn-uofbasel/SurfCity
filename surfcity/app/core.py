#!/usr/bin/env python3

# ssb/app_core.py

import asyncio
from   asyncio import ensure_future
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

import surfcity.app.db  as db
import surfcity.app.net as net
import ssb.local.config as config

logger = logging.getLogger('ssb_app_core')

the_db = None

# frontier_window = 60*60*24*180 # 180 days
frontier_window = 60*60*24*7 * 4 # 4 weeks
refresh_requested = False
new_friends_flag = False

# ----------------------------------------------------------------------

def text2synopsis(txt,ascii=False):
    txt = ' '.join(txt.split('\n'))
    txt = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'[\1]', txt)
    txt = re.sub(r' +', ' ', txt)
    if ascii:
        txt = txt.encode('ascii',errors='replace').decode()
    return txt.strip()

def utc2txt(ts, fixed_width=True):
    now = time.time()
    t = time.localtime(ts)
    if now - ts < 60*60*24*180: # half a year
        t = time.strftime("%b %e/%H:%M", t)
    else:
        t = time.strftime("%b %e, %Y", t)
    return t if fixed_width else t.replace('  ', ' ')

def feed2name(feedID):
    n = the_db.get_about(feedID, 'myname')
    if not n:
        n = the_db.get_about(feedID, 'name')
        if not n:
            n = the_db.get_about(feedID, 'named')
            if n:
                n = json.loads(n)
                if len(n) > 0:
                    n = n[0]
                else:
                    n = None
    return n

def update_about_name(feedID, name=None, named=None, myalias=None):
    if name: # chosen by feedID itself
        the_db.update_about(feedID, 'name', name)
    if named: # assigned by others
        n = the_db.get_about(feedID, 'named')
        if n:
            n = json.loads(n)
        else:
            n = []
        if not named in n:
            n.append(named)
        the_db.update_about(feedID, 'named', json.dumps(n))
    if myalias:
        the_db.update_about(feedID, 'myname', myalias)

# ----------------------------------------------------------------------

new_back = 0
new_forw = 0

def counter_add(b,f,ntfy=None):
    global new_back, new_forw
    new_back += b
    new_forw += f
    ntfy and ntfy()
    # urwid_counter.set_text(f"FWD={new_forw} BWD={new_back}")

def counter_reset(ntfy=None):
    global new_back, new_forw
    new_back, new_forw = 0,0
    ntfy and ntfy()
    # urwid_counter.set_text(f"FWD=0 BWD=0")

# ----------------------------------------------------------------------

def mstr2dict(secr, mstr):
    if not mstr:
        return None
    d = json.loads(mstr)
    if type(d) != dict:
        return None
    if not 'value' in d:
        # logger.info(f" ** mstr2dict: new envelope for {d['author']}:{d['sequence']}")
        # logger.info(mstr)
        m = config.formatMsg(d['previous'], d['sequence'], d['author'],
                             d['timestamp'], d['hash'], d['content'],
                             d['signature'])
        # logger.info(m)
        key = hashlib.sha256(m.encode('utf8')).digest()
        key = f"%{base64.b64encode(key).decode('ascii')}.sha256"
        d = { 'key': key, 'value': d, 'timestamp': int(time.time()*1000) }
        mstr = json.dumps(d, indent=2);
        # logger.info(f" ** mstr2dict new key {key} for {d['value']['author']}:{d['value']['sequence']}")
    v = d['value']
    if not 'content' in v:
        return None
    if type(v['content']) == str:
        c = base64.b64decode(v['content'].split('.')[0]) # remove the .box
        c = secr.unboxPrivateData(c)
        if c != None:
            # logger.info(c)
            try:
                v['content'] = json.loads(c.decode('utf8'))
            except:
                v['content'] = '?decoding error?'
            v['private'] = True
    c = v['content']
    if type(c) == dict and c['type'] == 'post':
        the_db.add_key(d['key'], [v['author'], v['sequence']])
    v['raw'] = mstr
    v['key'] = d['key']
    return v

async def get_msgs(secr, name, limit=1):
    msgs = []
    async for mstr in net.get_msgs(name, limit):
        m = mstr2dict(secr, mstr)
        if m:
            msgs.append(m)
    return msgs

async def id_get_frontier(secr, author, out=None):
    # returns (seqno,key)
    logger.debug(f" id_get_frontier{author}")
    low, high = 1, 256
    key = None
    # grow until we find first seqno without msg
    star = '|/-\\'
    starndx = 0
    while True:
        # logger.info(f" frontier: probing {high}")
        if out:
            out(star[starndx] + '\r', end='', flush=True)
            starndx = (starndx+1) % len(star)
        msgs = await get_msgs(secr, [author,high], 1)
        if len(msgs) == 0:
            break
        low, high = high, 2*high
        key = msgs[0]['key']
    # narrow it down
    while (high - low) > 1:
        # logger.info(f" frontier: narrow down [{low}..{high}]")
        if out:
            out(star[starndx] + '\r', end='', flush=True)
            starndx = (starndx+1) % len(star)
        seqno = int((high+low)/2)
        msgs = await get_msgs(secr, [author,seqno], 1)
        if len(msgs) != 0:
            low = seqno
            key = msgs[0]['key']
        else:
            high = seqno
    # logger.info(f" frontier: got {author} {seqno - high + low}")
    return (low, key) # seqno - high + low

def msg2recps(msg, me):
    # extract recps if msg was encrypted, return [] otherwise
    recps = []
    if 'private' in msg and msg['private']:
        c = msg['content']
        if 'recps' in c and type(c['recps']) == list:
            for r in c['recps']:
                if type(r) == str:
                    recps.append(r)
                else:
                    recps.append('?')
        if not msg['author'] in recps:
            recps.append(msg['author'])
        # if me in recps:
        #     recps.remove(me)
        recps.sort()
    return recps

def process_msg(msg, me, backwards=False):
    global new_friends_flag

    msg['this'] = msg['author'] + ':' + str(msg['sequence'])
    if type(msg['content']) != dict:
        return
    logger.debug(f"process_msg {msg['this']}")
    t = msg['content']['type']
    cutoff = int(time.time()) - frontier_window
    if  t == 'post':
        # print('  post')
        # convert time to secs, and do sanity check
        ts = int(msg['timestamp']/1000)
        if ts > time.time():
            ts = time.time()
        msg['timestamp'] = ts
        if ts >= cutoff:
            logger.debug(f"process_msg() add {(msg['author'], msg['sequence'])}")
            the_db.add_post(msg['raw'], (msg['author'], msg['sequence']), ts)
        if 'mentions' in msg['content'] and msg['content']['mentions']:
            for m in msg['content']['mentions']:
                # print(m)
                if 'link' in m and 'name' in m and m['name'] != 'undefined':
                    l = m['link']
                    if type(l) == dict and 'link' in l and 'name' in l:
                        l = l['link']
                    if type(l) == str and l[:1] == '@':
                        update_about_name(l, named=m['name'])
        if 'root' in msg['content']:
            if type(msg['content']['root']) == str:
                rkey = msg['content']['root']
                # if  'timestamp' in msg:
                #     ts = msg['timestamp']/1000
                #     if ts > time.time():
                #
                ts = msg['timestamp']
                try:
                    if the_db.get_thread_newest(rkey) < ts:
                        the_db.update_thread_newest(rkey, ts)
                except:
                    the_db.add_thread(msg2recps(msg, me), rkey, ts)
                the_db.add_tip_to_thread(rkey, msg['key'])
                if 'branch' in msg['content']:
                    br = msg['content']['branch']
                    if type(br) == str:
                        br = [br]
                    for key in br:
                        the_db.add_tip_to_thread(rkey, key)
                the_db.add_author_to_thread(rkey, msg['author'])
        elif 'text' in msg['content'] and type(msg['content']['text']) == str:
                                               # start of a new thread
            mkey = msg['key']
            the_db.add_thread(msg2recps(msg, me), mkey, msg['timestamp'])
            the_db.add_author_to_thread(mkey, msg['author'])
            the_db.add_tip_to_thread(mkey, mkey)
            txt = text2synopsis(msg['content']['text'])[:256]
            the_db.update_thread_title(mkey, txt)
    elif t == 'about' and 'name' in msg['content'] and \
              'about' in msg['content'] and msg['content']['name'] != 'undefined':
        a = msg['content']['about'] 
        if a == msg['author']:
            update_about_name(msg['author'], name=msg['content']['name'])
        elif msg['author'] == me:
            update_about_name(a, myalias=msg['content']['name'])
        else:
            update_about_name(a, named=msg['content']['name'])
    elif t == 'contact' and type(msg['content']) == dict and \
         not 'pub' in msg['content'] and 'contact' in msg['content'] and \
         type(msg['content']['contact']) == str:
        c = msg['content']
        if 'blocking' in c and c['blocking']:
            the_db.update_follow(msg['author'], c['contact'], 2, backwards)
        elif 'following' in c:
            if c['following']:
                if not new_friends_flag and msg['author'] == me:
                    if not backwards or not c['contact'] in \
                                                    the_db.get_following(me):
                        new_friends_flag = True
                the_db.update_follow(msg['author'], c['contact'],
                                        0, backwards)
            else:
                the_db.update_follow(msg['author'], c['contact'],
                                        1, backwards)
    elif t == 'pub' and msg['author'] == me and 'address' in msg['content']:
        a = msg['content']['address']
        the_db.add_pub(a['key'], a['host'], a['port'])
    
# ----------------------------------------------------------------------

async def scan_my_log(secr, args, out=None, ntfy=None):
    global refresh_requested
    # find out how far our log reaches

    front,_ = the_db.get_id_front(secr.id)
    if front <= 1: # we never scanned the network, do it now
        out and out("Bootstrapping into own log, determining its size...")
        front, key = await id_get_frontier(secr, secr.id, out)
        out and out(f"Log for {secr.id} has {front} entries.")
        the_db.update_id_front(secr.id, front, key)
        refresh_requested = True
    if front == 0: # empty log
        out and out("own log is empty")
        return
    low = the_db.get_id_low(secr.id)
    if args.nocatchup or low == 1:
        # full log seen, nothing left to scan (except new stuff)
        return

    if low == -1: # it's the first scan
        end = front + 1
    else:
        end = low
    start = end
    ts = 0
    # loop whole log or until we find at least one followed feed
    cnt = 0
    if start > 1:
        out and out('\r' + "scanned 0 entries of own log", end='', flush=True)

    while start > 1:
        # scan backwards
        start = 1 if (start - 40) < 1 else start - 40
        msgs = await get_msgs(secr, [secr.id, start], end - start)
        msgs.reverse()
        # ts = None
        for msg in msgs:
            # if not ts:
            #     ts = msg['timestamp']
            process_msg(msg, secr.id, backwards=True)
            counter_add(1,0,ntfy)
            cnt += 1
            out and out('\r' + f"scanned {cnt} entries of own log", end='', flush=True)
        if len(the_db.get_following(secr.id)) > 0:
            break
        end = start
    the_db.update_id_low(secr.id, start)
    out and out('\r' + f"Total of {front-start+1} from {front} own log entries scanned so far.")

async def scan_wavefront(me, secr, args, out=None, ntfy=None):
    await scan_my_log(secr, args, out, ntfy)

    out and out("Visiting logs of followed feeds")
    following = the_db.get_following(me)
    following.append(me)
    i = 0
    out and out(f"0 of {len(following)} followed feeds visited...", end='', flush=True)
    for f in following:
        front,_ = the_db.get_id_front(f)
        if front <= 1:
            continue
            # front = await id_get_frontier(secr, f)
            # the_db.update_id_front(f, front, prev??)
        if not args.nocatchup:
            # scan backwards
            low = the_db.get_id_low(f)
            # if ts > (time.time() - frontier_window): # two weeks
            #     print(f"\r  up to date {i}    ", end='')
            if low != 1:
                if low == -1:
                    start = front - 10
                    end = front + 1
                else:
                    start = low - 10
                    end = low
                if start < 1:
                    start = 1
                msgs = await get_msgs(secr, [f,start], end - start)
                msgs.reverse()
                # ts = None
                for m in msgs:
                    # if not ts:
                    #     ts = m['timestamp']/1000
                    process_msg(m, me, backwards=True)
                    counter_add(1,0,ntfy)
                if len(msgs) > 0:
                    the_db.update_id_low(f, start)
        if refresh_requested:
            out and out("\nList refresh requested")
            return
        i += 1
        out and out('\r'+f"{i} of {len(following)} followed feeds visited...", end='', flush=True)
    pass
    '''
        if not args.noextend:
            # scan forwards
            msgs = await get_msgs(secr, [f,front+1], 10)
            if len(msgs) > 0:
                # print()
                # print(msgs)
                for m in msgs:
                    await process_msg(m, me, backwards=False)
                    counter_add(0,1)
                the_db.update_id_front(f, m['sequence'])
        i += 1
        # output_log(f"\r{i} of {len(following)} followed ids visited")
        if refresh_requested:
            output_log("List refresh requested")
            return
        output_log(f"{i} of {len(following)} followed feeds visited...")
    output_log("All followed feeds visited.")
    '''

    if args.narrow:
        return
    out and out('\n'+"Visiting logs of randomly selected follo-followed feeds")
    ffollowing = the_db.get_follofollowing(me)
    # remove direct following, which we already covered:
    for f in following:
        if f in ffollowing:
            ffollowing.remove(f)
    if 2*len(following) < len(ffollowing):
        ffollowing = random.sample(ffollowing, 2*len(following))
    i = 0
    out and out(f"0 of {len(ffollowing)} random follo-followed feeds visited...", end='', flush=True)
    for f in ffollowing:
        front,_ = the_db.get_id_front(f)
        if front <= 1:
            front, key = await id_get_frontier(secr, f, out)
            the_db.update_id_front(f, front, key)
        if not args.nocatchup:
            # backwards
            low = the_db.get_id_low(f)
            # if ts > (time.time() - frontier_window): # two weeks
            #     output_log(f"\r  up to date {i}    ")
            batch_size = 20
            # batch_size = 5
            if low != 1:
                if low == -1:
                    start = front - batch_size
                    end = front +1
                else:
                    start = low - batch_size
                    end = low
                if start < 1:
                    start = 1
                msgs = await get_msgs(secr, [f,start], end - start)
                msgs.reverse()
                # ts = None
                for m in msgs:
                    # if not ts:
                    #     ts = m['timestamp']/1000
                    process_msg(m, me, backwards=True)
                    counter_add(1,0,ntfy)
                if len(msgs) > 0:
                    the_db.update_id_low(f, start)
        if refresh_requested:
            out and out("\nList refresh requested")
            return
        # forward
        msgs = await get_msgs(secr, [f,front+1], 5)
        if len(msgs) > 0:
            for m in msgs:
                process_msg(m, me, backwards=False)
                counter_add(0,1,ntfy)
            the_db.update_id_front(f, m['sequence'], m['key'])
        i += 1

        if refresh_requested:
            out and out("\nList refresh requested")
            return
        out and out('\r'+f"{i} of {len(ffollowing)} random follo-followed feeds visited...", end='', flush=True)
    # output_log("")
    return

async def mk_convo_list(secr, args, cache_only): # newest thread first
    threads = the_db.list_newest_threads(limit=args.nr_thr, public=False)
    convos = {}
    order = []
    for t in threads:
        recps = the_db.get_thread_recps(t)
        if secr.id in recps:
            recps.remove(secr.id)
        recps.sort()
        r = str(recps)
        if not r in order:
            order.append(r)
        if not r in convos:
            convos[r] = { 'threads': [], 'recps': recps }
        r = convos[r]
        r['threads'].append(t)
    lst = []
    for r in order:
        msgs = []
        new_count = 0
        for t in convos[r]['threads']:
            lastread = the_db.get_thread_lastread(t)
            queue = the_db.get_thread_tips(t)
            queue.append(t)
            done = []
            while len(queue) > 0:
                k = queue.pop()
                if k in done:
                    continue
                done.append(k)
                nm = the_db.get_msgName(k)
                if not nm:
                    continue
                rec = the_db.get_post(nm)
                m = None
                if rec:
                    m = mstr2dict(secr, rec[0])
                    if m:
                        m['timestamp'] = rec[1]
                if not m:
                    if args.offline or cache_only:
                        continue
                    m = await get_msgs(secr, nm)
                    if len(m) == 0:
                        continue
                    m = m[0]
                    # cache the new msg:
                    ts = int(m['timestamp']/1000)
                    if ts > time.time():
                        ts = time.time()
                    m['timestamp'] = ts
                    the_db.add_post(m['raw'], (m['author'], m['sequence']), ts)
                c = m['content']
                if type(c) != dict or c['type'] != 'post':
                    continue
                msgs.append(m)
                if m['timestamp'] > lastread:
                    new_count += 1
        msgs.sort(key=lambda x:x['timestamp'])
        convos[r]['msgs'] = msgs
        convos[r]['new_count'] = new_count
        lst.append(convos[r])
    return lst

'''
async def mk_convo_list(secr, threads, args, cache_only): # newest thread first
    convos = {}
    order = []
    for t in threads:
        recps = the_db.get_thread_recps(t)
        if secr.id in recps:
            recps.remove(secr.id)
        recps.sort()
        r = str(recps)
        if not r in order:
            order.append(r)
        if not r in convos:
            convos[r] = { 'threads': [], 'recps': recps }
        r = convos[r]
        r['threads'].append(t)
    lst = []
    for r in order:
        msgs = []
        for t in convos[r]['threads']:
            queue = the_db.get_thread_tips(t)
            queue.append(t)
            done = []
            while len(queue) > 0:
                k = queue.pop()
                if k in done:
                    continue
                done.append(k)
                nm = the_db.get_msgName(k)
                if not nm:
                    continue
                m = mstr2dict(secr, the_db.get_post(nm))
                if not m:
                    if args.offline or cache_only:
                        continue
                    m = await get_msgs(secr, nm)
                    if len(m) == 0:
                        continue
                    m = m[0]
                c = m['content']
                if type(c) != dict or c['type'] != 'post':
                    continue
                msgs.append(m)
        msgs.sort(key=lambda x:x['timestamp'])
        convos[r]['msgs'] = msgs
        lst.append(convos[r])
    return lst
'''

def mk_thread_list(secr, args, cache_only=False, extended_network=False):
    # public threads
    lst = the_db.list_newest_threads(limit=args.nr_thr, public=True)
    if not extended_network:
        fol = the_db.get_following(secr.id)
        if not secr.id in fol:
            fol.append(secr.id)
        following = set(fol)
        # logger.info(f"** following set: {following} / {extended_network}")
        # only those threads where we follow at least one of the authors
        lst2 = []
        for t in lst:
            authors = the_db.get_thread_authors(t)
            # logger.info(f"**       authors: {authors}")
            isect = [a for a in authors if a in following]
            if len(isect) == 0:
                # lst.remove(t)
                pass
            else:
                # logger.info(f"**       --> NOT removed")
                lst2.append(t)
            lst = lst2
    # blocked = the_db.get_following(secr.id, 2)
    # logger.info(f"**       len={len(lst)}")
    return lst

# ----------------------------------------------------------------------

async def expand_convo(secr, convo, args, cache_only, ascii=False):
    txt = []
    nms = []
    lst = convo['recps']
    # logger.info(f"expand_convo(): recps={lst}")
    if len(lst) == 0: # only me
        lst = [secr.id]
    for r in lst:
        n = feed2name(r)
        if not n:
            n = r
        elif ascii:
            n = n.encode('ascii', errors='replace').decode()
        nms.append(n)
    txt.append((False, f"<{', '.join(nms)[:50]}>"))
    msgs = convo['msgs']
    msgs.sort(key=lambda x:x['timestamp'])

    new_count = 0
    msgs2 = msgs[-args.nr_msg:]
    for m in msgs2:
        a = m['author']
        n = feed2name(m['author'])
        if not n:
            n = m['author']
        if ascii:
            n = n.encode('ascii', errors='replace').decode()
        # n = (n + ' '*10)[:10]
        t = text2synopsis(m['content']['text'],ascii=ascii)
        txt.append( (utc2txt(m['timestamp']), n, t) )
    if len(msgs2) > 0:
        pass
    else:
        # nm = the_db.get_msgName(k)
        txt.append( ('?', '?', '?') ) # f"-- empty thread? {nm}")
    return (msgs, txt, convo['new_count'])

async def expand_thread(secr, t, args, cache_only,
                        blocked=None, ascii=False):
    ''' returns a tuple (a,b,c) with two lists:
     a) list of sorted messages
     b) list with
           ndx=0     (new_count, titleStr)
           ndx=1..   (date, author, msgStartStr)
     c) isPrivateFlag
    '''
    recps = the_db.get_thread_recps(t)
    title = the_db.get_thread_title(t)

    title = text2synopsis(title,ascii) if title else ".."
    lastread = the_db.get_thread_lastread(t)
    msgs = []

    new_count = 0
    done = []
    queue = the_db.get_thread_tips(t)
    queue.append(t)
    # logger.info(f"tips: {queue}")
    while len(queue) > 0:
        k = queue.pop()
        if k in done:
            continue
        done.append(k)
        nm = the_db.get_msgName(k)
        if not nm:
            # logger.info(f"no name for {k}")
            continue
        r = the_db.get_post(nm)
        m = None
        if r:
            m = mstr2dict(secr, r[0])
            if m:
                m['timestamp'] = r[1]
        if not m:
            if args.offline or cache_only:
                # logger.info(f"cache_only")
                continue
            m = await get_msgs(secr, nm)
            if len(m) == 0:
                # logger.info(f"cannot load msg")
                continue
            m = m[0]
            # cache the new msg:
            ts = int(m['timestamp']/1000)
            if ts > time.time():
                ts = time.time()
            m['timestamp'] = ts
            the_db.add_post(m['raw'], (m['author'], m['sequence']), ts)
        if blocked and m['author'] in blocked:
            # logger.info("blocked!")
            continue
        c = m['content']
        if type(c) != dict or c['type'] != 'post':
            # logger.info("not a post!")
            continue
        msgs.append(m)
        if m['timestamp'] > lastread:
            new_count += 1
        '''
        for f in ['branch']: # 'reply']:
            if f in c:
                b = c[f]
                if type(b) == str:
                    b = [b]
                for r in b:
                    nm = the_db.get_msgName(r)
                    if nm and not nm in done:
                        queue.append(nm)
        '''
    # logger.info(f"msgs before sort: {msgs}")
    msgs.sort(key=lambda x:x['timestamp'])
    #if len(msgs) > args.nr_msg or (len(msgs)>0 and msgs[0]['key'] != t):
    #    if args.nr_msg > 1:
    #        txt.append('[...]\n')
    #elif len(msgs) < args.nr_msg and not title:
    #    txt.append("  ...                   > [message out of reach]\n")

    # logger.info(f"msgs={msgs}, {args.nr_msg}")
    txt = [ (new_count, title) ]
    msgs2 = msgs[-args.nr_msg:]
    for m in msgs2:
        a = m['author']
        n = feed2name(m['author'])
        if not n:
            n = m['author']
        if ascii:
            n = n.encode('ascii', errors='replace').decode()
        # n = (n + ' '*10)[:10]
        t = text2synopsis(m['content']['text'], ascii=ascii)
        txt.append( (utc2txt(m['timestamp']), n, t) )
    # if len(msgs2) == 0:
    #     nm = the_db.get_msgName(t)
    #     txt.append( ('?', '?', nm) ) # f"-- empty thread? {nm}")
    return (msgs, txt, recps != [])


def my_cb(secr, data, ntfy=None):
    # logger.info(f" my_cb {type(data)} <{str(data)[:60]}>")
    try:
        msg = mstr2dict(secr, data.decode('utf8'))
        if msg:
            # logger.info(f"my_cb: {msg}")
            process_msg(msg, secr.id)
            front,_ = the_db.get_id_front(msg['author'])
            if msg['sequence'] > front:
                the_db.update_id_front(msg['author'],
                                       msg['sequence'], msg['key'])
                counter_add(0,1,ntfy)
                # output_log(f"{msg['author']}:{msg['sequence']}")
            else:
                pass
                # output_log("** LOW {msg['author']}:{msg['sequence']}")
    except Exception as e:
        logger.info(" ** my_cb exception %s", str(e))
        logger.info(" ** %s", traceback.format_exc())
        pass

async def process_new_friends(secr, out=None, ntfy=None):
    # logger.info("process_new_friends() starting")
    following = the_db.get_following(secr.id)
    following.append(secr.id)
    try:
        for feed in following:
            front,_ = the_db.get_id_front(feed)
            if front < 1:
                out and out(f"Probe frontier for {feed}")
                front, key = await id_get_frontier(secr, feed, out)
                msgs = await get_msgs(secr, (feed,front))
                process_msg(msgs[0], secr.id)
                the_db.update_id_front(feed, front, key)
            net.start_feed_watching((feed,front+1),
                                    lambda data: my_cb(secr,data,ntfy))
    except:
        logger.exception("process_new_friend")
        print("exception in process_new_friend()")
    # logger.info("process_new_friends() done")

# ----------------------------------------------------------------------

async def push(msg):
    try:
        net.my_feed_send_queue.put(msg)
    except Exception as e:
        logger.info(" ** push %s", str(e))
        logger.info(" ** %s", traceback.format_exc())
    
def submit_public_post(secr, txt, root=None, branch=None):
    # logger.info('public_post()')
    seq, key = the_db.get_id_front(secr.id)
    txt = {
        "type": "post",
        "text": txt,
        "recps": None
    }
    if root:
        txt['root'] = root
    if branch:
        txt['branch'] = branch
    msg = config.formatMsg(key, seq+1, secr.id,
                          int(time.time() * 1000),
                          'sha256', txt, None)
    # logger.info(msg)
    sig = base64.b64encode(secr.sign(msg.encode('utf8'))).decode('ascii') +\
          '.sig.ed25519'
    msg = msg[:-2] + ',\n  "signature": "%s"\n}' % sig
    # logger.info(msg)

    jmsg = json.loads(msg)
    if not 'author' in jmsg or not 'signature' in jmsg:
            raise ValueError
    s = base64.b64decode( jmsg['signature'] )
    i = msg.find(',\n  "signature":')
    m = (msg[:i] + '\n}').encode('utf8')
    if not config.verify_signature(jmsg['author'], m, s):
        logger.info("  invalid signature")
    else:
        logger.info("  valid signature")

    withKeys = False
    if withKeys:
        h = hashlib.sha256(msg.encode('utf8')).digest()
        msg = { 'key' : '%' + base64.b64encode(h).decode('ascii') + '.sha256',
                'value': json.loads(msg),
                'timestamp': int(time.time() * 1000) }
        # logger.info(json.dumps(msg, indent=2))
    else:
        msg = json.loads(msg)

    # logger.info("put public msg into queue")
    asyncio.ensure_future(push(msg))

def submit_private_post(secr, txt, root=None, branch=None):
    # logger.info('private_post()')
    seq, key = the_db.get_id_front(secr.id)
    recps = ['@AiBJDta+4boyh2USNGwIagH/wKjeruTcDX2Aj1r/haM=.ed25519', secr.id]
    txt = {
        "type": "post",
        "text": txt,
        "recps": recps
    }
    if root:
        txt['root'] = root
    if branch:
        txt['branch'] = branch
    box = secr.boxPrivateData(json.dumps(txt).encode('utf8'), recps)
    box = base64.b64encode(box).decode('ascii') + '.box'
    msg = config.formatMsg(key, seq+1, secr.id,
                          int(time.time() * 1000),
                          'sha256', box, None)
    # logger.info(msg)
    sig = base64.b64encode(secr.sign(msg.encode('utf8'))).decode('ascii') +\
          '.sig.ed25519'
    msg = msg[:-2] + ',\n  "signature": "%s"\n}' % sig
    # logger.info(msg)

    jmsg = json.loads(msg)
    if not 'author' in jmsg or not 'signature' in jmsg:
            raise ValueError
    s = base64.b64decode( jmsg['signature'] )
    i = msg.find(',\n  "signature":')
    m = (msg[:i] + '\n}').encode('utf8')
    if not config.verify_signature(jmsg['author'], m, s):
        logger.info("  invalid signature")
    else:
        logger.info("  valid signature")

    withKeys = False
    if withKeys:
        h = hashlib.sha256(msg.encode('utf8')).digest()
        msg = { 'key' : '%' + base64.b64encode(h).decode('ascii') + '.sha256',
                'value': json.loads(msg),
                'timestamp': int(time.time() * 1000) }
        # logger.info(json.dumps(msg, indent=2))
    else:
        msg = json.loads(msg)

    # logger.info("put msg into queue")
    asyncio.ensure_future(net.my_feed_send_queue.put(msg)) # 

# ----------------------------------------------------------------------

def init():
    global the_db

    # logger.info("surcity app_core loading")
    the_db = db.SURFCITY_DB()

# ----------------------------------------------------------------------

if __name__ == '__main__':
    print("nothing to see here")

# eof
