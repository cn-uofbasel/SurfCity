#!/usr/bin/env python3

# surfcity/surfcity_net.py - the SSB protocol

# 2018-08-31 (c) <christian.tschudin@unibas.ch>
# June 2017  (c) Pedro Ferreira <pedro@dete.st>
#            https://github.com/pferreir/pyssb

import asyncio
import base64
import hashlib
import inspect
import json
import os
import socket
import struct
import sys
import time
import traceback

from ssb.rpc.muxrpc import MuxRPCAPI, MuxRPCAPIException, MuxRPCRequest
from ssb.rpc.packet_stream import PacketStream, PSMessage, PSMessageType
from ssb.shs.network import SHSClient, SHSServer

import ssb.local.config

import logging
logger = logging.getLogger('ssb_app_net')

api = MuxRPCAPI()
my_feed_id = None
my_feed_send_queue = None

# ---------------------------------------------------------------------------

def init(feedID, send_queue):
    global my_feed_id, my_feed_send_queue
    my_feed_id = feedID
    my_feed_send_queue = send_queue

async def connect(host, port, feedID, keypair):
    # from ssb-caps.js: 
    #   Buffer('1KHLiKZvAvjbY1ziZEHMXawbCEIM6qwjCDm3VYRan/s=', 'base64')
    appKey = base64.b64decode('1KHLiKZvAvjbY1ziZEHMXawbCEIM6qwjCDm3VYRan/s=')
    client = SHSClient(host, port, keypair, base64.b64decode(feedID[1:-8]),
                       application_key=appKey)
    packet_stream = PacketStream(client)
    await client.open()

    s = client.writer._protocol._stream_reader._transport._extra['socket']
    if sys.platform == 'darwin':
        TCP_KEEPALIVE = 0x10
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        s.setsockopt(socket.IPPROTO_TCP, TCP_KEEPALIVE, 2) # after_idle_sec
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5) # interval_sec
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
    elif sys.platform == 'linux':
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 2) # after_idle_sec
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5) # interval_sec
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5) # max_fails
    
    api.add_connection(packet_stream)
    return api

def disconnect():
    api.connection.disconnect()
    
async def get_msgs(msgName, limit=1):
    # print(f"me requesting msg {msgName}..")
    # msgs = []
    async for reply in api.call('createHistoryStream', [{
            'id': msgName[0],
            'seq': msgName[1],
            'limit': limit,
            'live': False,
            'keys': True
    }], 'source'):
        # print('RESPONSE:', reply.req)
        yield reply.data
    return # msgs

watch_list = {} # feedid ~ MuxRPCHandler

async def do_cb(feedid, handler, cb):
    watch_list[feedid] = handler
    async for reply in handler:
        try:
            cb(reply.data)
        except Exception as e:
            logger.info("** do_cb: exception %s", str(e))
            logger.info(traceback.format_exc())
    del watch_list[feedid]

def start_feed_watching(msgName, cb):
    if msgName[0] in watch_list:
        return
    handler = api.call('createHistoryStream', [{
            'id': msgName[0],
            'seq': msgName[1],
            'live': True,
            'keys': True
    }], 'source')
    asyncio.ensure_future(do_cb(msgName[0], handler, cb))

async def stop_feed_watching(msgName):
    feedID = msgName[0]
    if not feedID in watch_list:
        return
    handler = watch_list[feedID] # MuxRPC
    handler.send(True, end_err = True, req = - watch_list[feedID].req)

# ---------------------------------------------------------------------------

def my_notify(connection, req_msg, m):
    logger.info("app_net: my_notify()")
    a = req_msg.body['args'][0]
    if 'key' in a and a['key']:
        connection.send(m, req = - req_msg.req)
    else:
        connection.send(m['value'], req = - req_msg.req)

drainers = {}

async def drain(connection, req):
    global my_feed_send_queue
    while True:
        logger.info("drain loop")
        msg = await my_feed_send_queue.get()
        logger.info("drain loop woke up")
        try:
            connection.send(msg, stream=True, req = -req)
        except:
            s = traceback.format_exc()
            logger.info(s)
            

# incoming RPC requests:
@api.define('createHistoryStream')
def create_history_stream(connection, req_msg, sess=None):
    global drainers
    a = req_msg.body['args'][0]
    logger.info('RECV [%d] createHistoryStream id=%s', req_msg.req, a['id'])
    if not my_feed_id or a['id'] != my_feed_id or not my_feed_send_queue:
        connection.send(True, end_err = True, req = - req_msg.req)
        return
    lim = -1 if not 'limit' in a else a['limit']
    seqno = 1 if not 'sequence' in a else a['sequence']
    # connection.send(True, end_err = True, req = - req_msg.req)
    # return
    if True: # while lim != 0:
        # while seq < frontier:
        #   msg =
        #   send()
        #   lim -= 1
        #   if lim == 0:
        #     connection.send(True, end_err = True, req = - req_msg.req)
        #     return
        #   seq += 1
        try:
            # drainers[req_msg.req] = 
            asyncio.ensure_future(drain(connection, req_msg.req)) # drainers[req_msg.req])
        except:
            s = traceback.format_exc()
            logger.info(s)
            '''
        msg = my_feed_from_log(seqno)
        if not msg:
            break
        raw, meta = msg
        if 'key' in a and a['key']:
            connection.send(raw, req = - req_msg.req)
        else:
            connection.send(raw['value'], req = - req_msg.req)
        seqno += 1
        '''
        # lim -= 1
        
    # connection.send(True, end_err = True, req = - req_msg.req)
        
    '''
    i = a['seq']
    while True:
        m = sess.worm.getMsgBySequence(a['id'], i)
        if not m:
            logger.debug("worm has no %s/%d", a['id'], i)
            break
        if 'key' in a and a['key']:
            connection.send(m, req = - req_msg.req)
        else:
            connection.send(m['value'], req = - req_msg.req)
        i += 1
    if a['id'] == sess.id and 'live' in a and a['live']:
        sess.worm.notify_on_extend(lambda e: my_notify(connection, req_msg, e))
    else:
        connection.send(True, end_err = True, req = - req_msg.req)
    '''

@api.define('blobs.createWants')
def blobs_createWants(connection, req_msg, sess=None):
    logger.info('** createWants %s', str(req_msg))
    connection.send(True, end_err = True, req = - req_msg.req)

@api.define('blobs.get')
def blobs_get(connection, req_msg, sess=None):
    a = req_msg.body['args'][0]
    logger.info('RECV [%d] blobs.get %s', req_msg.req, a)
    connection.send(True, end_err = True, req = - req_msg.req)
    '''
    # while True: chunk the data etc
    if sess.worm.blobAvailable(a):
        data = sess.worm.readBlob(a)
        if data:
            connection.send(data,
                            msg_type=ssb.rpc.packet_stream.PSMessageType.BUFFER,
                            req= - req_msg.req)
            connection.send(True, end_err= True, req= - req_msg.req)
            return
        err = "local error"
    else:
        err = "no such blob"
    connection.send({ 'name': 'Error', 'message': err },
                    end_err = True, req= - req_msg.req)
    '''

async def fetch_blob(sess, id):
    logger.info('me fetching blob %s', id)
    data = bytes(0)
    async for msg in api.call('blobs.get', [id], 'source'):
        chunk = msg.data
        logger.debug('RESP: %d (%d bytes)', msg.req, len(chunk))
        if not msg.end_err:
            data += chunk
    nm = hashlib.sha256(data).digest()
    nm = '&' + base64.b64encode(nm).decode('ascii')
    if nm == id:
        sess.worm.writeBlob(data)
    else:
        logger.info('fetchBlob: mismatch %s (%d bytes)', nm, len(data))



'''
async def request_log_feed(sess, id, seq, end_after_sync=False):
    logger.info('me requesting feed %s / %d..', id, seq)
    async for msg in api.call('createHistoryStream', [{
        'id': id,
        'seq': seq,
        # 'live': False,
        'live': not end_after_sync,
        'keys': False
    }], 'source'):
        logger.debug('RESPONSE: %d', msg.req)
        # print(type(msg.body))
        # print(msg.body)
        d = json.loads(msg.data)
        if type(d) == dict:
            _, seq = sess.worm._getMaxSeq(d['author'])
            if seq+1 != d['sequence']:
                print('seq gap:', d['sequence'], 'instead of', seq+1)
            else:
                logger.debug('* seq %s / %d', d['author'], d['sequence'])
                jmsg = ssb.local.worm.formatMsg(d['previous'] if 'previous' in d else None,
                                                d['sequence'], d['author'],
                                                d['timestamp'], d['hash'],
                                                d['content'], d['signature'])
                # print(jmsg)
                key = sess.worm.appendToLog(jmsg)
                if key:
                    # sess.last.set_last_seq(d['author'], seq+1, key)
                    sess.worm._updateMaxSeq(d['author'], key, seq+1)
                else:
                    print("appendToLog failed, invalid signature?")
                    print(msg.data)
                    print(jmsg)
                    if 'text' in d['content']:
                        print(type(d['content']['text']))
                        print(d['content']['text'])
        elif d == True:
            logger.info("end of worm updating")
            sess.worm.flush()
        else:
            logger.debug("%s", str(msg))
'''

# ---------------------------------------------------------------------------

'''
# client behavior
async def become_client(sess, end_after_sync=False):
    logger.info('me starting to talk to the new peer')
    # fname = os.path.join(sess.worm._logDname, 'friends.json')
    ids = []
    # if os.path.isfile(fname):
    #     with open(fname, "r") as f:
    #         friends = json.load(f)
    #         ids += [ id for (id,flag) in friends['value'][sess.id].items() \
    #                                      if flag ]
    if not sess.id in ids: # add our id in case we lost our log
        ids.append(sess.id)
    for id in ids:
        await request_log_feed(sess, id, sess.worm._getMaxSeq(id)[1] + 1,
                               end_after_sync)
    logger.info('end of become_client code')

# server behavior
async def on_connect(conn, sess):
    packet_stream = PacketStream(conn)
    api.add_connection(packet_stream)

    logger.info('incoming new peer detected')
    ensure_future(become_client(sess))

    try:
        async for req_msg in packet_stream:
            logger.debug("incoming peer request %d", req_msg.req)

            nm = '.'.join(req_msg.body['name'])
            handler = api.handlers.get(nm)
            if not handler:
                packet_stream.send({'name': 'Error',
                                    'message': 'no such method ' + nm,
                                    'stack': ''}, end_err = True,
                                   req = - req_msg.req)
            else:
                handler(packet_stream, req_msg, sess)
    except Exception as e:
        logger.info("lost connecton? %s", str(e))
'''

# ---------------------------------------------------------------------------

'''
async def main(args, sess):

    if args.port: # become a server, discard -peer option
        logger.info("main(): behaving as a SSB server")
        server = SHSServer('127.0.0.1', int(args.port), sess.secr.keypair,
                           sess=sess)
        server.on_connect(on_connect)
        await server.listen()
        logger.info("end of server init, my ID is " + sess.id)
    else:
        logger.info("main(): behaving as a SSB client")
        if args.peer:
            p = args.peer.split(':')
            host, port, peer_id = (p[0], int(p[1]), p[2])
        else:
            host, port, peer_id = ('127.0.0.1', 8008, sess.peer_id)
        client = SHSClient(host, port, sess.secr.keypair,
                           base64.b64decode(peer_id[1:-8]))
        packet_stream = PacketStream(client)
        await client.open()
        api.add_connection(packet_stream, sess)
        if args.sync:
            fu = ensure_future(api)
            await become_client(sess, end_after_sync=True)
            fu.cancel()
        else:
            await gather(ensure_future(api), become_client(sess))

        logger.info("end of main()")

# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='SSB peer -- sync logs')
    parser.add_argument('-port',
                        help="local port (i.e. become a server)")
    parser.add_argument('peer', nargs='?',
                        help="remote's ip:port:id (default is localhost:8008:default_id")
    parser.add_argument('-user', type=str, nargs='?', dest='username',
                        help='username (default is ~/.ssb user)')
    args = parser.parse_args()

    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.DEBUG) # INFO)

    sess = SSB_SESSION(args.username)

    theLoop = get_event_loop()
    theLoop.run_until_complete(main(args, sess))
    if args.port:
        theLoop.run_forever()
    theLoop.close()

'''

# eof
