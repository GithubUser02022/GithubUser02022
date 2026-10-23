# -*- coding: utf-8 -*-
"""假 tkinter 空跑 ClassHub 设置窗口 + 面板渲染"""
import sys, types, os
tk=types.ModuleType("tkinter"); ttk=types.ModuleType("tkinter.ttk")
fdlg=types.ModuleType("tkinter.filedialog"); msgb=types.ModuleType("tkinter.messagebox")
fontm=types.ModuleType("tkinter.font")
for c in ("VERTICAL","HORIZONTAL","BOTH","X","Y","END","W","E","N","S","LEFT","RIGHT","NW"):
    setattr(tk,c,c.lower())
class Var:
    def __init__(self,v=None,value=None,**kw): self.v=v if v is not None else value
    def get(self): return self.v
    def set(self,v): self.v=v
class Font:
    def __init__(self,*a,**k): pass
    def configure(self,**k): pass
class Style:
    def configure(self,*a,**k): pass
class W:
    def __init__(self,*a,**kw): self.kw=kw; self._geo=None; self._w=300; self._h=76
    def pack(self,*a,**k): pass
    def grid(self,*a,**k): pass
    def config(self,*a,**k): pass
    def configure(self,*a,**k): pass
    def bind(self,*a,**k): pass
    def protocol(self,*a,**k): pass
    def title(self,*a): pass
    def geometry(self,g=None):
        if g: self._geo=g
        return self._geo
    def resizable(self,*a): pass
    def minsize(self,*a): pass
    def attributes(self,*a,**k): pass
    def transient(self,*a): pass
    def grab_set(self,*a): pass
    def withdraw(self): pass
    def deiconify(self): pass
    def lift(self): pass
    def destroy(self): pass
    def quit(self): pass
    def after(self,ms,fn=None): return "0"
    def wait_window(self,*a): pass
    def winfo_x(self): return 0
    def winfo_y(self): return 0
    def winfo_id(self): return 0
    def winfo_screenwidth(self): return 3840
    def winfo_screenheight(self): return 2160
    def add(self,*a,**k): pass
    def insert(self,*a,**k): return "i"
    def delete(self,*a,**k): pass
    def selection(self): return ()
    def get_children(self): return ()
    def index(self,x): return 0
    def heading(self,*a,**k): pass
    def column(self,*a,**k): pass
    def see(self,*a): pass
    def set(self,v): self.v=v
    def yview(self,*a): pass
    def mainloop(self): pass
    def iconbitmap(self,p): self._icon=p
    def iconphoto(self,*a,**k): pass
    def cget(self,k): return 300 if k=="width" else 76
    def create_image(self,*a,**k): return 1
    def create_rectangle(self,*a,**k): return 2
    def create_text(self,*a,**k): return 3
    def clipboard_clear(self): pass
    def clipboard_append(self,*a): pass
class Tk(W):
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw); self.calls=[]
        self.tk=types.SimpleNamespace(call=lambda *a,**k: self.calls.append(a) or "1.0")
class Toplevel(W): pass
class Combobox(W): pass
class Treeview(W): pass
class Notebook(W): pass
class Text(W): pass
for n in ("Frame","Label","Button","Entry","Checkbutton","LabelFrame","PanedWindow",
          "Separator","Scrollbar","Scale","Radiobutton","Menu","Combobox","Spinbox"):
    setattr(ttk,n,Combobox if n=="Combobox" else W)
ttk.Treeview=Treeview; ttk.Notebook=Notebook; ttk.Style=Style
for n in ("Frame","Label","Button","Entry","Checkbutton","Toplevel","Menu","Text","Canvas","Scale"):
    setattr(tk,n,Text if n=="Text" else W)
tk.Tk=Tk; tk.Toplevel=Toplevel
tk.StringVar=tk.BooleanVar=tk.IntVar=Var; tk.DoubleVar=Var
fdlg.askdirectory=lambda *a,**k: ""
fdlg.askopenfilename=lambda *a,**k: ""
msgb.showinfo=msgb.showwarning=msgb.showerror=lambda *a,**k: None
fontm.Font=Font
tk.font=fontm; tk.messagebox=msgb; tk.filedialog=fdlg; tk.ttk=ttk
sys.modules.update({"tkinter":tk,"tkinter.ttk":ttk,"tkinter.filedialog":fdlg,
                    "tkinter.messagebox":msgb,"tkinter.font":fontm})

import chub_core as core, chub_pen as pen, chub_ui
from chub_core import CFG

print("== 默认开关仍然全关 ==")
keys=["autostart","sync.enable","launch.enable","watch.enable","assoc.enable",
      "assoc.apply_on_start","tasks.enable","protect.enable","zy.enable",
      "zy.auto_start_zy","zy.show_overlay","sync.enable_usb","pen.enable","pen.topmost"]
bad=[k for k in keys if CFG.get(k) is not False]
assert not bad, bad
print("  [OK] %d 项全部 False（含新增的 pen.enable）" % len(keys))

print("== 面板配色（保感知亮度）==")
c,e = pen.THEME["bg_center"], pen.THEME["bg_edge"]
print("  中心 rgb%-16s L=%.0f  (参考 155)" % (c, pen._lum(c)))
print("  边缘 rgb%-16s L=%.0f  (参考 101)" % (e, pen._lum(e)))
assert abs(pen._lum(c)-155)<4 and abs(pen._lum(e)-101)<4
print("  [OK] 两端亮度对齐参考图")

print("== 上深下浅 ==")
import numpy as np
img = pen.Renderer().render({"w":1439,"h":1080,"code":"7270","ip":"192.168.243.12",
   "port":"8900","version":"2.1.6.0","device":"","classroom":"","status":"","hover":""})
a=np.asarray(img.convert("RGB")).astype(np.float32)
L=0.2126*a[...,0]+0.7152*a[...,1]+0.0722*a[...,2]
up=np.percentile(L[160:200],25); dn=np.percentile(L[800:840],25)
print("  上部 y=160 L=%.1f   下部 y=800 L=%.1f   (应递增 %.1f)" % (up,dn,dn-up))
assert dn>up, "应该是上深下浅"

print("== 设置窗口（含新标签页）==")
class FakeApp:
    def __init__(self): self.protect=None; self.guard=None; self.overlay=None
    def __getattr__(self,n):
        def f(*a,**k): return None
        return f
win=chub_ui.SettingsWindow(FakeApp())
print("  [OK] scale=%.2f geometry=%s" % (win.scale, win.root.geometry()))
print("  配色预览：%s" % win.v_p_preview.get())
win.v_p_hue.set(190.0); win._pen_preview()
print("  拖到 190°：%s" % win.v_p_preview.get())
assert pen._lum(pen.THEME["bg_center"]) > 150   # 全局 THEME 未被污染
print("  [OK] 预览不改全局 THEME（中心仍 L=%.0f）" % pen._lum(pen.THEME["bg_center"]))
win.v_p_hue.set(205.0); win._pen_preview()
win._pen_apply()
print("  [OK] 应用配色后 hue=%s" % CFG.get("pen.hue"))
win.save()
print("  [OK] 保存成功，pen.height_ratio=%s" % CFG.get("pen.height_ratio"))
for f in ("config.json","copied.json","state.json","sync.log","pen_icon.ico","icon.ico"):
    if os.path.exists(f):
        try: os.remove(f)
        except Exception: pass
print("\nClassHub + 云笔面板 集成测试通过 ✅")
