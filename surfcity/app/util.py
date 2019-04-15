# surfcity/app/util.py

import logging
import re

logger = logging.getLogger('ssb_app_util')

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

def expand_recpts(secr, app, recpts):
    lst = []
    for r in recpts:
        nm = app.feed2name(r)
        logger.info(f"{nm} / {r} / {secr.id}")
        # if not nm and secr.id in r:
        #     nm = 'me'
        if nm != None:
            nm = f"@{nm if nm[0] != '@' else nm[1:]}" # ]({r})"
        else:
            nm = ''
        lst.append( (nm,r) )
    return lst

# eof
