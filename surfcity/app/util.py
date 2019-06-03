# surfcity/app/util.py

import logging
import re
import time

logger = logging.getLogger('surfcity/app/util')

# ----------------------------------------------------------------------

def text2synopsis(txt,ascii=False):
    txt = ' '.join(txt.split('\n'))
    txt = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'[\1]', txt)
    txt = re.sub(r' +', ' ', txt)
    for c in '\r\b\f\t':
        txt = txt.replace(c, '')
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

# ---------------------------------------------------------------------------

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

def lookup_recpts(secr, app, recpts):
    # recpts is a list of strings each having a single address or name.
    # Addresses/names without an @, or incomplete @-addresses are looked up
    # and returned whether they could be auto-completed. Also, it is made
    # sure that the own address is included and that addresses are only
    # present once
    addr = re.compile(r"(@.{44}.ed25519)")
    good = [secr.id]
    bad = []
    for r in recpts:
        r = r.strip()
        if len(r) == 0:
            continue
        for i in addr.findall(r):
            good.append(i)
            break
        else:
            users = app.the_db.match_about_name(f"^{r[1:]}$"
                                                    if r[0] == '@' else r)
            logger.info(f"users: <{r}> {str(users)}")
            if len(users) == 1:
                good.append(users[0])
            else:
                print(users)
                bad.append(f"? {r}" if len(users) == 0 else f"ambigious {r}")
    good = list(set(good))
    bad = list(set(bad))
    if len(good) + len(bad) == 0:
        bad = ['add one recipient']
    if len(good) + len(bad) >= 8:
        bad = ['max 8 recipients'] + bad
    return (good, bad)

def expand_recpts(app, recpts):
    lst = []
    for r in recpts:
        nm = app.feed2name(r)
        logger.info(f"{nm} / {r}")
        if nm != None:
            nm = f"@{nm if nm[0] != '@' else nm[1:]}" # ]({r})"
        else:
            nm = f"{r[:8]}.."
        lst.append( (nm,r) )
    return lst

# eof
