#!/usr/bin/env python3

# surfcity/app/soliton.py

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
import surfcity.app.net as soliton
import ssb.local.config as config

logger = logging.getLogger('ssb/app/soliton')

class SSB_SOLITON:

    def __init__(self, secr, db):
        self.secr = secr
        self.db   = db

    def whoami(self):
        return self.secr.id

    def wr(self, content):
        seq, key = self.db.get_id_front(self.secr.id)
        msg = config.formatMsg(key, seq+1, self.secr.id,
                          int(time.time() * 1000),
                          'sha256', content, None)
        sig = base64.b64encode(self.secr.sign(msg.encode('utf8'))).decode('ascii') + \
              '.sig.ed25519'
        msg = msg[:-2] + ',\n  "signature": "%s"\n}' % sig

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
        logger.info(f"putting next log extension into the out_queue: {msg}")
        asyncio.ensure_future(net.my_feed_send_queue.put(msg))

    def rd_start(self, start_name, callback=None):
        net.start_feed_watching(start_name,
                                lambda data: self._rx_cb(data, callback))

    def rd_stop(self, callback):
        pass

    async def fetch_by_name(self, msg_name, lim=1):
        msgs = []
        async for mstr in net.get_msgs(msg_name, limit=lim):
            m = self.mstr2dict(mstr)
            if m:
                msgs.append(m)
        return msgs

    def link_to_name(self, msg_link):
        return self.db.get_msg_name(msg_link)

    def log_items(self, feedID, fwd=False, lim=-1):
        pass

    def decrypt(self, box):
        pass

    def mstr2dict(self, mstr):
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
            c = self.secr.unboxPrivateData(c)
            if c != None:
                # logger.info(c)
                try:
                    v['content'] = json.loads(c.decode('utf8'))
                except:
                    v['content'] = '?decoding error?'
            v['private'] = True
        c = v['content']
        if type(c) == dict and c['type'] == 'post':
            self.db.add_msg_link(d['key'], [v['author'], v['sequence']])
        v['raw'] = mstr
        v['key'] = d['key']
        return v


    def _rx_cb(self, data, ntfy=None):
        # logger.info(f" rx_cb {type(data)} <{str(data)[:60]}>")
        try:
            msg = self.mstr2dict(data.decode('utf8'))
            if msg:
                front,_ = self.db.get_id_front(msg['author'])
                if msg['sequence'] == front+1:
                    self.db.update_id_front(msg['author'],
                                           msg['sequence'], msg['key'])
                    ntfy and ntfy(msg) # counter_add(0,1,ntfy)
                    # process_msg(msg, self.secr.id)
                    # output_log(f"{msg['author']}:{msg['sequence']}")
                else:
                    logger.info(f"incoming msg has wrong #{msg['sequence']} vs {front+1}")
                pass
                    
        except Exception as e:
            logger.info(" ** rx_cb exception %s", str(e))
            logger.info(" ** %s", traceback.format_exc())


# ----------------------------------------------------------------------

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

# ----------------------------------------------------------------------

if __name__ == '__main__':
    print("nothing to see here")

# eof
