# surfcity/__main__.py

import json
import logging
import os
import sys

import ssb.local.config
import surfcity.app.core as app

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
    paa('-ui', choices=['urwid', 'urwid_light', 'urwid_mono',
                        'urwid_amber', 'tty', 'kivy'],
        nargs='?', metavar="USERINTERFACE", default='urwid',
        help='one of: urwid, tty, kivy (default: urwid)')

    args = parser.parse_args()

    print(descr, end='', flush=True)

    # get the user's id and secret from the ~/.ssb directory:
    secr = ssb.local.config.SSB_SECRET(args.secret)
    app.init()
    app.the_db.open(args.db, secr.id)
    id_in_db = app.the_db.get_config('id')
    if id_in_db != secr.id:
        print()
        print(f"ID mismatch error:")
        print(f"- secret is for {secr.id}")
        print(f"- but db created by {id_in_db} ({feed2name(id_in_db)})")
        sys.exit(0)

    if args.cmd:
        if args.cmd == 'stats':
            print("database stats:")
            s = app.the_db.get_stats()
            print(json.dumps(s, indent=4))
        sys.exit(0)

    if 'urwid' in args.ui:
        import surfcity.ui.urwid as ui
        if args.ui == 'urwid_mono':
            setattr(args, 'style', 'mono')
        elif args.ui == 'urwid_amber':
            setattr(args, 'style', 'amber')
        elif args.ui == 'urwid_light':
            setattr(args, 'style', 'light')
        else:
            setattr(args, 'style', 'dark')
    elif args.ui == 'tty':
        import surfcity.ui.tty as ui
    elif args.ui == 'kivy':
        app.the_db.close()
        os.environ['KIVY_NO_ARGS'] = '1'
        import surfcity.ui.kivy as ui

    # logging.basicConfig(filename=f"test-{args.ui}.log",level=logging.INFO)
    ui.launch(app, secr, args)

# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()

# eof
