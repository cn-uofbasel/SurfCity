# surfcity/__main__.py

import json
import logging
import os
import sys

import ssb.local.config
import surfcity.app.core as app_core

descr = "SurfCity - a log-less SSB client"

def main(args=None):
    import argparse

    if args is None:
        args = sys.argv[1:]
    def paa(*args, **kwargs):
        parser.add_argument(*args, **kwargs)

    parser = argparse.ArgumentParser(description=descr)
    paa('-offline', action='store_true',
        help="work fully offline, some msgs will not show up")
    paa('cmd', choices=['stats', 'purge', 'reset'], nargs='?',
        help="('purge' and 'reset' not implemented yet)")
    paa('-nocatchup', action='store_true',
        help="do not catchup on old messages")
    paa('-noextend', action='store_true',
        help="do not extend current frontier")
    paa('-narrow', action='store_true',
        help="only check with peers you directly follow")
    paa('-attn_msg', type=int, metavar='DAYS', default=14,
        help='attention window for messages in days (default: 14)')
    paa('-attn_thr', type=int, metavar='DAYS', default=70,
        help='attention window for threads in days (default: 70)')
    paa('-nr_msg', type=int, metavar='N', default=2,
        help='number of newest msgs/thread to summarize (default: 2)')
    paa('-nr_thr', type=int, metavar='N', default=200,
        help='number of newest threads to load (default: 200)')
    paa('-max_msg', type=int, metavar='N', default=5000,
        help='max number of msgs to cache (default: 2000, not implemented')
    paa('-max_thr', type=int, metavar='N', default=5000,
        help='max number of threads to cache (default: 8000, not implemented')
    paa('-secret', type=str, metavar='PATH',
        help='file with the SSB credentials (default: ~/.ssb/secret)')
    paa('-db', type=str, metavar='PATH',
        default=os.path.expanduser('~/.ssb/surfcity.sqlite'),
        help="SurfCity's database (default: ~/.ssb/surfcity.sqlite)")
    paa('-pub', type=str, metavar="host:port:pubID or 'any'",
        default='127.0.0.1',
        help="access pub (default: 'localhost:8008:<yourID>')")
    paa('-ui', choices=['terminal_dark', 'terminal_light',
                        'terminal_amber', 'terminal_green', 'terminal_mono',
                        'tty', 'kivy'],
        nargs='?', metavar="USERINTERFACE", default='terminal_light',
        help='one of: tty, terminal_dark, terminal_light, terminal_amber, terminal_green, terminal_mono, kivy (default: terminal_light)')
    paa('-dbg', action='store_true',
        help="write debug information to a file 'test-XXX.log'")

    args = parser.parse_args()

    # print(descr, end='', flush=True)

    # get the user's id and secret from the ~/.ssb directory:
    secr = ssb.local.config.SSB_SECRET(args.secret)
    app_core.init(secr)
    app_core.the_db.open(args.db, secr.id)
    id_in_db = app_core.the_db.get_config('id')
    if id_in_db != secr.id:
        print()
        print(f"ID mismatch error:")
        print(f"- secret is for {secr.id}")
        print(f"- but db was created by {id_in_db} '{app_core.feed2name(id_in_db)}'")
        sys.exit(0)

    if args.cmd:
        print()
        if args.cmd == 'stats':
            print("database stats:")
            s = app_core.the_db.get_stats()
            print(json.dumps(s, indent=4))
            print("known pubs:")
            for pubID, pub in app_core.the_db.list_pubs().items():
                print(f"  {pub['host']}:{pub['port']}:", "\n     ", pubID)
        sys.exit(0)

    if 'terminal' in args.ui:
        import surfcity.ui.urwid as ui
        if '_' in args.ui:
            setattr(args, 'style', args.ui[args.ui.index('_') + 1:])
        else:
            setattr(args, 'style', 'light')
    elif args.ui == 'tty':
        import surfcity.ui.tty as ui
    elif args.ui == 'kivy':
        app_core.the_db.close()
        os.environ['KIVY_NO_ARGS'] = '1'
        import surfcity.ui.kivy as ui

    if args.dbg:
        logging.basicConfig(filename=f"test-{args.ui}.log",level=logging.INFO)
    ui.launch(app_core, secr, args)

# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()

# eof
