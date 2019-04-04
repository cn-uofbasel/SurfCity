#!/usr/bin/env python3

import asyncio
import kivy
kivy.require('1.10.0')
# kivy.Logger.disabled = True
import logging
import threading
import traceback

from kivy.app import App
from kivy.core.window import Window
from kivy.properties import ObjectProperty, BooleanProperty, NumericProperty
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.scrollview import ScrollView

CONST_start_size = (350, 600)

the_loop = asyncio.get_event_loop()
quit_flag = False

app = None
import surfcity.app.db   as db
import surfcity.app.net  as net

the_public = None

# ----------------------------------------------------------------------

# Create both screens. Please note the root.manager.current: this is how
# you can control the ScreenManager from kv. Each screen has by default a
# property manager that gives you the instance of the ScreenManager used.
Builder.load_string("""
<PublicScreen>:
    id: publ
    threads: threads
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint: 1,None
            # size: (self.size[0], 90)
            # size_hint_y : 0.07
            height: 80
            RoundedButtonRed:
                text: 'Public'
            RoundedButtonWhite:
                text: 'Private'
                on_press: root.goto('private')
            RoundedButtonWhite:
                text: 'Menu'
                on_press: root.goto('menu')
        Label:
            size_hint: 1,None
            text_size: (self.size[0], None)
            height: 60
            # size: (self.size[0]-10, 50)
            # size_hint_y : 0.03
            padding: (20,0)
            canvas.before:
                Color:
                    rgba: .8,.2,.2,1
                Rectangle:
                    pos: self.pos
                    size: self.size
            color: 0,0,0,1
            text: 'List of public threads'
            
        ScrollView:
            id: threads
            # gl: gl
            # size_hint: 1,1
            bar_width: 40
            effect_cls: "ScrollEffect"
            scroll_type: ['bars']
            background_normal: ''
            background_color: (.8,.8,.8,1)
            GridLayout:
                size_hint_y: None
                # height: self.minimum_height
                id: glayout
                cols: 1
                spacing: 10
                canvas.before:
                    Color:
                        rgba: .8,.8,.8,1
                    Rectangle:
                        pos: self.pos
                        size: self.size


#        RecycleView:
#            row_controller: row_controller
#            bar_width: 20
#            effect_cls: "ScrollEffect"
#            scroll_type: ['bars']
#            id: rv
#            viewclass: 'MyThreadListEntry'
#            RecycleBoxLayout:
#                id: row_controller
#                default_size_hint: 1, None
#                size_hint: 1, None
#                height: self.minimum_height
#                orientation: 'vertical'

<PrivateScreen>:
    id: priv
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y : 0.07
            RoundedButtonWhite:
                text: 'Public'
                on_press: root.goto('public')
            RoundedButtonGreen:
                text: 'Private'
            RoundedButtonWhite:
                text: 'Menu'
                on_press: root.goto('menu')
        BoxLayout:
            Label:
                size_hint: 1, 1
                color: 1,0,0,1
                text: 'something'
                canvas.before:
                    Color:
                        rgba: 1,1,1,1
                    Rectangle:
                        pos: self.pos
                        size: self.size

<MenuScreen>:
    id: menu
    BoxLayout:
        orientation: 'vertical'
        BoxLayout:
            size_hint_y : 0.07
            RoundedButtonWhite:
                text: 'Public'
                on_press: root.goto('public')
            RoundedButtonWhite:
                text: 'Private'
                on_press: root.goto('private')
            RoundedButtonOrange:
                text: 'Menu'
        BoxLayout:
            Label:
                size_hint: 1, 1
                color: 1,0,0,1
                text: 'something'
                canvas.before:
                    Color:
                        rgba: 1,1,1,1
                    Rectangle:
                        pos: self.pos
                        size: self.size


<MyThreadListEntry@GridLayout>:
    size_hint_y: None
    cols: 1
    spacing: 0
    background_normal: ''
    # background_color: (.7,.7,.9,1) if self.ind%2==0 else (.9,.7,.7,1)
    # on_release:
    #     root.print_data(self.ind)
    #     root.print_data(self.pos)
    #     root.dump_tree()


<Subject@Label>
    size_hint_y: None
    font_name: 'Arial Bold'
    font_size: '14sp'
    height: 30 # int(1.2*self.texture_size[1])
    # background_normal: ''
    # background_color: (.7,.7,.9,1)
    bcolor: (1,1,1,1)
    padding: (20,0)
    # size: (self.size[0],20)
    # pos: self.pos
    text_size: (self.width, None)
    color: (1,0,0,1)

<Synopsis@Label>
    size_hint : 1,None
    font_name: 'Arial'
    font_size: '12sp'
    height: 30 # int(1.2*self.texture_size[1])
    # background_normal: ''
    # background_color: (.9,.7,.7,1)
    bcolor: (1,1,1,1)
    padding: (20,0)
    # size: (self.parent.size[0],20)
    # pos: self.pos
    text_size: (self.width, None)
    color: (0,1,0,1)

<RoundedButtonRed@Button>:
    background_color: 0,0,0,0  # the last zero is the critical on, make invisible
    canvas.before:
        Color:
            rgba: (.8,.2,.2,1) if self.state=='normal' else (0,.7,.7,1)  # visual feedback of press
        RoundedRectangle:
            pos: (self.pos[0]+5, self.pos[1] - 10)
            size: (self.size[0]-10, self.size[1])
            radius: [10,]

<RoundedButtonGreen@Button>:
    background_color: 0,0,0,0  # the last zero is the critical on, make invisible
    canvas.before:
        Color:
            rgba: (.2,.7,.4,1) if self.state=='normal' else (0,.7,.7,1)  # visual feedback of press
        RoundedRectangle:
            pos: (self.pos[0]+5, self.pos[1] - 10)
            size: (self.size[0]-10, self.size[1])
            radius: [10,]

<RoundedButtonOrange@Button>:
    background_color: 0,0,0,0  # the last zero is the critical on, make invisible
    canvas.before:
        Color:
            rgba: (.7,.5,0,1) if self.state=='normal' else (0,.7,.7,1)  # visual feedback of press
        RoundedRectangle:
            pos: (self.pos[0]+5, self.pos[1] - 10)
            size: (self.size[0]-10, self.size[1])
            radius: [10,]

<RoundedButtonWhite@Button>:
    background_color: 0,0,0,0  # the last zero is the critical on, make invisible
    canvas.before:
        Color:
            rgba: (.8,.8,.8,1) if self.state=='normal' else (0,.7,.7,1)  # visual feedback of press
        RoundedRectangle:
            pos: (self.pos[0]+5, self.pos[1] - 10)
            size: (self.size[0]-10, self.size[1])
            radius: [10,]

<ScrollableLabel>:
    GridLayout:
        cols: 1
        size_hint_y: None
        height: self.minimum_height
        canvas:
            Color:
                rgba: (1, 0, 0, .5) # DarkOliveGreen
            Rectangle:
                size: self.size
                pos: self.pos
        Label:
            id: bust
            text: 'a string that is long ' * 10
            font_size: 50
            text_size: self.width, None
            size_hint_y: None
            height: self.texture_size[1]
            canvas:
                Color:
                    rgba: (0, 1, 0, .5) # DarkOliveGreen
                Rectangle:
                    size: self.size
                    pos: self.pos
        Label:
            text: '2 strings that are long ' * 10
            text_size: self.width, None
            size_hint_y: None
            height: self.texture_size[1]
        Button:
            text: 'just testing'
""")


# Declare both screens
class PublicScreen(Screen):

    def __init__(self, **kwargs):
        super(PublicScreen, self). __init__(**kwargs)
        #self.threads.bind(minimum_height=self.threads.setter('height'))
        # for i in range(len(items)):
        #     items[i]['ind'] = i
        # self.ids.rv.data = [item for item in items]

    def goto(self, dest):
        self.manager.current = dest

class PrivateScreen(Screen):

    def __init__(self, **kwargs):
        super(PrivateScreen, self). __init__(**kwargs)
        
    def goto(self, dest):
        self.manager.current = dest

class MenuScreen(Screen):

    def __init__(self, **kwargs):
        super(MenuScreen, self). __init__(**kwargs)

    def goto(self, dest):
        self.manager.current = dest

class Subject(Label):

    pass
#    def __init__(self, t):
#        super(Subject, self).__init__()
#        self.text = t

class Synopsis(Label):

    pass
#    def __init__(self, t):
#        super(Synopsis, self).__init__()
#        self.text = t

class MyThreadListEntry(GridLayout):

    # odd = BooleanProperty(False)
    ind = NumericProperty(0)
    # boxl = ObjectProperty(None)

    def print_data(self,data):
        print(self.ind, data)

    def dump_tree(self):
        tree(0, self)

#    def on_touch_up(self, t):
#       print(self.ind, self.to_local(t.pos[0], t.pos[1]))
#        return False

def mk_threadListEntry(ind, t, txt):
    # m = MyThreadListEntry()
    m = GridLayout(cols=1, size_hint_y=None, spacing=0)
    m.bind(minimum_height=m.setter('height'))
    m.ind = NumericProperty()
    m.ind = ind
    m.thread = ObjectProperty()
    m.thread = t
    l = Button(text=txt[0][1], size_hint_y=None, height=45, padding=(10,10),
               font_size="28", font_name="Arial bold",
               background_normal='',
               background_down='',
               background_color=(.7,.7,.9,1) if ind%2==0 else (.9,.7,.7,1),
               color=(0,0,0,1),
               text_size=(700,50), shorten=True,
                   shorten_from='right')
    l.bind(on_release = (lambda x: print(x.parent.ind)))
    m.add_widget(l)
    g = GridLayout(cols=3, size_hint=(1,None), spacing=0, row_default_height=40)
    g.bind(minimum_height=g.setter('height'))
    m.add_widget(g)
    
    for ln in txt[1:]:
        l = Button(text=' ' + ln[1],size_hint_x=None,
                   font_size="24", background_normal='',
                   background_down='',
                   background_color=(.7,.7,.9,1) if ind%2==0 else (.9,.7,.7,1),
                   color=(0,0,0,1),
                   halign='left', text_size=(120,None), width=140,
                   shorten=True, shorten_from='right')
        # l.bind(on_touch_down = (lambda x,y: True))
        l.bind(on_release = (lambda x: print(x.parent.parent.ind)))
        g.add_widget(l)
        l = Button(text=ln[2],size_hint_x=None, padding_x=5,
                   font_size="24",  font_name="Arial italic",
                   background_normal='', background_down='',
                   background_color=(.7,.7,.9,1) if ind%2==0 else (.9,.7,.7,1),
                   color=(0,0,0,1),
                   halign='left',
                   text_size=(430,None), width=430, shorten=True,
                   shorten_from='right')
        # l.bind(on_touch_down = (lambda x,y: True))
        l.bind(on_release = (lambda x: print(x.parent.parent.ind)))
        g.add_widget(l)
        l = Button(text=' ' + ln[0], size_hint_x=None,
                   font_size="20",
                   background_normal='', background_down='',
                   background_color=(.7,.7,.9,1) if ind%2==0 else (.9,.7,.7,1),
                   color=(0,0,0,1),
                   halign='left',
                   text_size=(130,None), width=130, shorten=True,
                   shorten_from='right')
        # l.bind(on_touch_down = (lambda x,y: True))
        l.bind(on_release = (lambda x: print(x.parent.parent.ind)))
        g.add_widget(l)
    return m
    
    '''
    m = MyThreadListEntry()
    m.ind = ind
    m.thread = t
        # self.ll = self.children[0]
    boxl = m.ids.gl2 # GridLayout(cols=1,size=(700,180),size_hint=(None,None))
    # boxl.bind(minimum_height=boxl.setter('height'))
    boxl.add_widget(Label(text='abcxx', color=(0,0,0,0,1),
                          size_hint=(1,None),height=25))
    # boxl.pos = self.pos
    boxl.add_widget(Subject(text=lines[0]))
    for l in lines[1:]:
        boxl.add_widget(Synopsis(text=l), canvas='after')
    # m.add_widget(boxl)
    return m
    # m.canvas.ask_update()
    '''

# ----------------------------------------------------------------------

def tree(lvl, node):
    print(' '*(2*lvl), node)
    print(' '*(2*lvl), f"- pos={node.pos} size={node.size}")
    if type(node) is Label or type(node) is Synopsis or type(node) is Subject:
        print(' '*(2*lvl), f"- text={node.text}")
    lvl += 1
    for c in node.children:
        tree(lvl, c)

async def main(sca, secr, args):
    try:
        app.the_db.open(args.db, secr.id)

        host = args.pub.split(':')
        port = 8008 if len(host) < 2 else int(host[1])
        pubID = secr.id if len(host) < 3 else host[2]
        host = host[0]

        if not args.offline:
            net.init(secr.id, None)
            try:
                api = await net.connect(host, port, pubID, secr.keypair)
            except Exception as e:
                error_message = str(e) # traceback.format_exc()
                # urwid.ExitMainLoop()
                logger.info("exc while connecting")
                raise e
            print("connected, scanning will start soon ...")
            asyncio.ensure_future(api)

            await app.scan_my_log(secr, args, print)

        lst = app.mk_thread_list(secr, args, cache_only = args.offline,
                                      extended_network = not args.narrow)
        items = []
        i = 0
        the_public.ids.glayout.bind(minimum_height=the_public.ids.glayout.setter("height"))
        the_public.ids.glayout.add_widget(Label(text="-- newest thread --",
                                                height=40,
                                                size_hint_y=None,
                                                color=(0,0,0,1)))
        for t in lst[:50]:
            _, txt, _ = await app.expand_thread(secr, t, args, True, ascii=True)
            m = mk_threadListEntry(i, t, txt)
            the_public.ids.glayout.add_widget(m)
            i += 1

        the_public.ids.glayout.add_widget(Label(text="-- oldest thread --",
                                                height=40,
                                                size_hint_y=None,
                                                color=(0,0,0,1)))

        print('---')
        # the_public.canvas.ask_update()
        # tree(0, the_public)
        # the_public.ids.rv.data = items
        # print(the_public.ids.rv.ids)
        
        while not quit_flag:
            print('scuttler')
            await asyncio.sleep(1)


    except:
        traceback.print_exc()

    app.the_db.close()
    the_loop.stop()
    sca.end()
    # print("ui_kivy main() ended")

class SurfCityApp(App):

    def build(self):
        global the_public
        self.x = threading.Thread(target=the_loop.run_forever)
        asyncio.set_event_loop(the_loop)

        sm = ScreenManager()
        the_public = PublicScreen(name='public')
        sm.add_widget(the_public)
        sm.add_widget(PrivateScreen(name='private'))
        sm.add_widget(MenuScreen(name='menu'))
        sm.transition = NoTransition()
        Window.size = CONST_start_size

        self.title = "SurfCity - a log-less SSB client"

        asyncio.ensure_future(main(self, self.secr, self.args))
        self.x.start()

        return sm

    def stop(self):
        global quit_flag
        quit_flag = True
        # self.x.join()
        self.end()

    def end(self):
        super(SurfCityApp, self).stop()

def launch(app_core, secr, args):
    global app
    
    app = app_core

    try:
        sc = SurfCityApp()
        sc.secr = secr
        sc.args = args
        sc.run()
    except KeyboardInterrupt:
        pass
    finally:
        sc.stop()

# eof
