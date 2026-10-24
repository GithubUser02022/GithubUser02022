# -*- coding: utf-8 -*-
"""
================================================================================
 ClassHub · chub_shell —— 设置中心（任务管理器式布局）
================================================================================
托盘菜单【设置…】或左键单击图标打开。布局照着任务管理器来：

    ┌──────────────────────────────────────────────┐
    │ ClassHub 设置                      ─   □   ✕ │ ← 自绘标题栏（可拖动）
    ├──────────────────────────────────────────────┤
    │  首选项    个性化    帮助    关于              │ ← 菜单栏（文件/选项/查看 那一排）
    ├──────────────────────────────────────────────┤
    │  常规 │ 课件同步 │ 开机启动 │ 文件关联 │ …    │ ← 选项卡
    ├──────────────────────────────────────────────┤
    │  ┌──────────┐ ┌──────────┐ ┌──────────┐      │
    │  │ 圆角框框 │ │ 圆角框框 │ │ 圆角框框 │      │ ← 主区域
    │  └──────────┘ └──────────┘ └──────────┘      │
    └──────────────────────────────────────────────┘

菜单（首选项 / 个性化 / 帮助 / 关于）决定顶层页面；
「首选项」下面还有一行选项卡，每个选项卡的主区域是若干圆角框框，
框框里直接放圆形复选框、输入框、下拉、按钮。

窗口边框、标题栏、最小化/关闭按钮全部交给 Windows 的 DWM 绘制
（跟任务管理器同一套）：DwmSetWindowAttribute 设置深色标题栏、Win11 圆角、
Mica 云母背景。不自绘，所以不会有错位和死循环。
只有内容区是我们自己画的（菜单栏、选项卡、圆角卡片）。
"""

from __future__ import annotations

import os
import re
import tkinter as tk
from tkinter import ttk

import chub_core as core
import chub_ui as chw_mod
from chub_core import (APP_AUTHOR, APP_CONTRIBUTORS, APP_ID, APP_NAME_CN,
                       APP_RELEASE_DATE,
                       APP_VERSION, CFG, LOG_PATH, AppItem, AssocItem,
                       TaskItem, log)


# ==============================================================================
# 一、配色
# ==============================================================================
def _parse_color(text: str):
    """解析颜色字符串，支持 #RRGGBB / #RGB / rgb(r,g,b) / 颜色名。
    解析不了返回 None。"""
    if not text:
        return None
    t = str(text).strip()
    try:
        if t.startswith("#"):
            h = t[1:]
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            if len(h) == 6:
                return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
            return None
        m = re.match(r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", t, re.I)
        if m:
            return tuple(int(m.group(i)) for i in (1, 2, 3))
    except Exception:
        return None
    # 常见颜色名
    names = {
        "white": (255, 255, 255), "black": (0, 0, 0),
        "gray": (128, 128, 128), "grey": (128, 128, 128),
        "red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
        "yellow": (255, 255, 0), "cyan": (0, 255, 255),
        "magenta": (255, 0, 255), "orange": (255, 165, 0),
        "purple": (128, 0, 128), "pink": (255, 192, 203),
        "darkblue": (0, 0, 139), "lightblue": (173, 216, 230),
        "navy": (0, 0, 128), "teal": (0, 128, 128),
        "silver": (192, 192, 192), "gold": (255, 215, 0),
    }
    return names.get(t.lower())


def _hsv(h, s, v):
    import colorsys

    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0,
                                  max(0.0, min(1.0, s)),
                                  max(0.0, min(1.0, v)))
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def _hex(rgb) -> str:
    return "#%02X%02X%02X" % tuple(int(x) for x in rgb)


def _mix(a, b, k):
    k = max(0.0, min(1.0, k))
    return tuple(int(round(a[i] + (b[i] - a[i]) * k)) for i in range(3))


def _lum(rgb) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def build_palette(dark: bool = False) -> dict:
    """按当前主题算出整套颜色"""
    hue = float(CFG.get("shell.hue", 205.0))
    depth = float(CFG.get("shell.depth", 0.0))
    sat_k = 1.0 + float(CFG.get("shell.sat", 0.0)) / 100.0

    accent = _hsv(hue, max(0.15, min(1.0, 0.78 * sat_k)),
                  max(0.25, min(1.0, (0.88 if dark else 0.82) + depth / 220.0)))
    accent_hi = _hsv(hue, max(0.15, min(1.0, 0.70 * sat_k)),
                     max(0.30, min(1.0, (0.96 if dark else 0.90) + depth / 220.0)))

    if dark:
        bg, card, card_hi = (32, 34, 40), (45, 48, 56), (56, 60, 70)
        title_bg = (26, 28, 34)
        text, sub, line = (238, 240, 245), (160, 168, 182), (66, 70, 80)
    else:
        bg, card, card_hi = (245, 247, 250), (255, 255, 255), (240, 245, 252)
        title_bg = _hsv(hue, max(0.10, min(1.0, 0.55 * sat_k)), 0.98)
        text, sub, line = (32, 34, 40), (110, 118, 130), (222, 228, 236)

    # 自定义页面背景 / 文字色（留空 = 用上面的默认）
    custom_bg = str(CFG.get("shell.page_bg", "") or "").strip()
    custom_fg = str(CFG.get("shell.page_fg", "") or "").strip()
    if custom_bg:
        got = _parse_color(custom_bg)
        if got:
            bg = got
            # 卡片颜色跟着背景走：比背景稍亮（深色模式）或稍白（浅色模式）
            lum = _lum(bg)
            card = _mix(bg, (255, 255, 255), 0.10 if lum < 128 else 0.55)
            card_hi = _mix(bg, (255, 255, 255), 0.18 if lum < 128 else 0.75)
            line = _mix(bg, (255, 255, 255) if lum < 128 else (0, 0, 0), 0.22)
            title_bg = _mix(bg, _hsv(hue, 0.55, 0.9), 0.85)
    if custom_fg:
        got = _parse_color(custom_fg)
        if got:
            text = got
            sub = _mix(got, bg, 0.42)

    return {
        "dark": dark, "hue": hue, "accent": accent, "accent_hi": accent_hi,
        "accent_dim": _mix(accent, card, 0.82), "bg": bg, "card": card,
        "card_hi": card_hi, "title_bg": title_bg, "text": text, "sub": sub,
        "line": line,
        "on_accent": (255, 255, 255) if _lum(accent) < 150 else (24, 26, 32),
        "close": (232, 90, 90), "min": (230, 190, 90),
        "radius": max(0.0, float(CFG.get("shell.radius", 18.0))),
    }


def detect_dark() -> bool:
    """跟随系统明暗：读 Windows 的 AppsUseLightTheme"""
    style = str(CFG.get("shell.style") or "auto").lower()
    if style == "dark":
        return True
    if style == "light":
        return False
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as k:
            v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return int(v) == 0
    except Exception:
        return False


# ==============================================================================
# 二、DWM 原生窗口（跟任务管理器同一套）
# ==============================================================================
# 不再自绘标题栏、不再自己裁剪圆角 —— 窗口边框、标题栏、最小化/关闭按钮
# 全部交给 Windows 画（就是任务管理器用的那套）。这样不会有任何自绘带来的
# 死循环、按钮错位问题。
#
# 通过 DwmSetWindowAttribute 调整三件事：
#   DWMWA_USE_IMMERSIVE_DARK_MODE  (20) 标题栏深色/浅色
#   DWMWA_WINDOW_CORNER_PREFERENCE (33) Win11 圆角（普通窗口本来就有，这里强制）
#   DWMWA_SYSTEMBACKDROP_TYPE      (38) Mica 云母材质（Win11 22H2+）

_DWM_HWND_CACHE = {}


def _get_hwnd(root):
    """拿到真正的顶层窗口句柄。

    Tk 的 winfo_id() 给的是内部客户区子窗口，真正的顶层是它的父窗口。
    """
    if root in _DWM_HWND_CACHE:
        return _DWM_HWND_CACHE[root]
    hwnd = 0
    if os.name == "nt":
        try:
            import ctypes

            root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or 0
            if not hwnd:
                hwnd = root.winfo_id()
        except Exception:
            hwnd = 0
    _DWM_HWND_CACHE[root] = hwnd
    return hwnd


def _dwm_set(hwnd, attr, value):
    """设一个 DWM 属性。返回是否成功"""
    if not hwnd or os.name != "nt":
        return False
    try:
        import ctypes

        v = ctypes.c_int(int(value))
        r = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), ctypes.c_uint(attr),
            ctypes.byref(v), ctypes.sizeof(v))
        return r == 0
    except Exception:
        return False


def apply_dwm(root, dark: bool, backdrop: str = "mica") -> dict:
    """给普通 Tk 窗口套上任务管理器那套外观。

    backdrop: mica（云母，跟任务管理器一样）/ acrylic（亚克力）/ none（纯色）
    返回每个属性是否设置成功，方便排查。
    """
    out = {"hwnd": 0, "dark": False, "corner": False, "backdrop": False}
    hwnd = _get_hwnd(root)
    out["hwnd"] = hwnd
    if not hwnd:
        return out

    # ① 标题栏深色模式（任务管理器跟随系统就是这个）
    out["dark"] = _dwm_set(hwnd, 20, 1 if dark else 0)
    if not out["dark"]:
        out["dark"] = _dwm_set(hwnd, 19, 1 if dark else 0)   # 旧版 Windows 的编号

    # ② Win11 圆角（普通带边框窗口本来就有，这里显式指定）
    if not _dwm_set(hwnd, 33, 2):        # DWMWCP_ROUND
        _dwm_set(hwnd, 33, 3)            # DWMWCP_ROUNDSMALL

    # ③ Mica / Acrylic 背景材质
    bmap = {"mica": 2, "tabbed": 4, "acrylic": 3, "none": 1, "auto": 0}
    out["backdrop"] = _dwm_set(hwnd, 38, bmap.get(str(backdrop).lower(), 2))
    return out


def is_win11() -> bool:
    """粗略判断是不是 Win11（Mica 要 22H2 以上才稳）"""
    if os.name != "nt":
        return False
    try:
        import sys

        return sys.getwindowsversion().build >= 22000
    except Exception:
        return False


# ==============================================================================
# 三、自绘控件
# ==============================================================================
def round_rect(canvas, x0, y0, x1, y1, r, fill="", outline="", width=1):
    """Canvas 上画圆角矩形（tkinter 没现成的，用矩形+四角弧拼）"""
    r = max(0, min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    ids = []
    if r <= 0:
        return [canvas.create_rectangle(x0, y0, x1, y1, fill=fill,
                                        outline=outline, width=width)]
    ids.append(canvas.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill,
                                       outline="", width=0))
    ids.append(canvas.create_rectangle(x0, y0 + r, x1, y1 - r, fill=fill,
                                       outline="", width=0))
    for (ax0, ay0, ax1, ay1, start) in (
            (x0, y0, x0 + 2 * r, y0 + 2 * r, 90),
            (x1 - 2 * r, y0, x1, y0 + 2 * r, 0),
            (x0, y1 - 2 * r, x0 + 2 * r, y1, 180),
            (x1 - 2 * r, y1 - 2 * r, x1, y1, 270)):
        ids.append(canvas.create_arc(ax0, ay0, ax1, ay1, start=start, extent=90,
                                     fill=fill, outline="", width=0))
    if outline and width:
        ids.append(canvas.create_line(x0 + r, y0, x1 - r, y0, fill=outline, width=width))
        ids.append(canvas.create_line(x0 + r, y1, x1 - r, y1, fill=outline, width=width))
        ids.append(canvas.create_line(x0, y0 + r, x0, y1 - r, fill=outline, width=width))
        ids.append(canvas.create_line(x1, y0 + r, x1, y1 - r, fill=outline, width=width))
        for (ax0, ay0, ax1, ay1, start) in (
                (x0, y0, x0 + 2 * r, y0 + 2 * r, 90),
                (x1 - 2 * r, y0, x1, y0 + 2 * r, 0),
                (x0, y1 - 2 * r, x0 + 2 * r, y1, 180),
                (x1 - 2 * r, y1 - 2 * r, x1, y1, 270)):
            ids.append(canvas.create_arc(ax0, ay0, ax1, ay1, start=start, extent=90,
                                         style="arc", outline=outline, width=width))
    return ids


class RoundCheck(tk.Frame):
    """自绘圆形复选框：Canvas 画圆圈 + Label 显示文字。

    用 Label 承载文字（而不是在 Canvas 上 create_text）—— Canvas 宽度是
    手算的像素值，算窄了就会把字截掉（这正是"字被截断看着像白块"的来源）。
    Label 有自然宽度，永远不会截。
    """

    def __init__(self, master, text="", variable=None, command=None,
                 size=22, palette=None, base="card", **kw):
        self.pal = palette or build_palette()
        self.size = max(14, int(size))
        self._base_bg = base
        tk.Frame.__init__(self, master,
                          bg=_hex(self.pal.get(base, self.pal["card"])), **kw)
        self.var, self.command, self.text = variable, command, text
        self.hover = False
        self._ids = []

        _bg = _hex(self.pal.get(base, self.pal["card"]))
        self.canvas = tk.Canvas(self, width=self.size + 8, height=self.size + 8,
                                highlightthickness=0, bd=0, bg=_bg)
        self.canvas.pack(side="left")
        self.lbl = tk.Label(self, text=text, bg=_bg,
                            fg=_hex(self.pal["text"]), anchor="w",
                            font=("Microsoft YaHei UI", 10))
        self.lbl.pack(side="left", padx=(4, 0))

        for w in (self, self.canvas, self.lbl):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", lambda e: self._set(True))
            w.bind("<Leave>", lambda e: self._set(False))
        self.draw()
        if self.var is not None:
            try:
                self.var.trace_add("write", lambda *a: self.draw())
            except Exception:
                pass

    def _set(self, v):
        if self.hover != v:
            self.hover = v
            self.draw()

    def _click(self, _=None):
        if self.var is None:
            return
        try:
            self.var.set(not self.var.get())
        except Exception:
            self.var.set(True)
        self.draw()
        if self.command:
            try:
                self.command()
            except Exception:
                pass

    def set_palette(self, pal):
        self.pal = pal
        _bg = _hex(pal.get(self._base_bg, pal["card"]))
        try:
            self.configure(bg=_bg)
            self.canvas.configure(bg=_bg)
            self.lbl.configure(bg=_bg, fg=_hex(pal["text"]))
        except Exception:
            pass
        self.draw()

    def draw(self):
        for i in self._ids:
            try:
                self.canvas.delete(i)
            except Exception:
                pass
        self._ids = []
        pal = self.pal
        try:
            on = bool(self.var.get()) if self.var is not None else False
        except Exception:
            on = False
        _bg = _hex(pal.get(self._base_bg, pal["card"]))
        try:
            self.canvas.configure(bg=_bg)
            self.configure(bg=_bg)
            self.lbl.configure(bg=_bg, fg=_hex(pal["text"]))
        except Exception:
            pass
        s = self.size
        cy = (s + 8) / 2.0
        if on:
            fill, ring = _hex(pal["accent"]), _hex(pal["accent"])
        else:
            fill = _hex(pal["card_hi"]) if self.hover else ""
            ring = _hex(pal["accent"]) if self.hover else _hex(pal["sub"])
        self._ids.append(self.canvas.create_oval(
            2, cy - s / 2.0, 2 + s, cy + s / 2.0, fill=fill, outline=ring, width=2))
        if on:
            cx, k = 2 + s / 2.0, s * 0.22
            lw = max(2, int(s * 0.13))
            self._ids.append(self.canvas.create_line(
                cx - k, cy - k * 0.05, cx - k * 0.15, cy + k * 0.55,
                fill=_hex(pal["on_accent"]), width=lw,
                capstyle="round", joinstyle="round"))
            self._ids.append(self.canvas.create_line(
                cx - k * 0.15, cy + k * 0.55, cx + k * 1.15, cy - k * 0.75,
                fill=_hex(pal["on_accent"]), width=lw,
                capstyle="round", joinstyle="round"))


def _paint_bg(w, pal):
    """按 widget 上记的 _base_bg 标记刷底色。

    平铺页（关于/帮助/个性化/单框选项卡）应该跟页面同色 bg；
    卡片内容区才用 card。不记标记的话，换主题时平铺页会被刷成 card（白的），
    又变成一块"白框"。
    """
    key = getattr(w, "_base_bg", "card")
    try:
        w.configure(bg=_hex(pal.get(key, pal["card"])))
    except Exception:
        pass


def _text_width(text: str, size: int = 10,
                family: str = "Microsoft YaHei UI") -> int:
    """量文字的实际像素宽度（用于给 Canvas 按钮定宽，避免截字）。

    量不到就按中英文混排估算：CJK 约 1.0em，其余约 0.55em。
    """
    try:
        import tkinter.font as _f

        f = _f.Font(family=family, size=int(size))
        return int(f.measure(text)) + 4
    except Exception:
        w = 0.0
        for ch in str(text):
            w += size * (1.0 if ord(ch) > 0x2E80 else 0.55)
        return int(w) + 4


class PillButton(tk.Canvas):
    """胶囊按钮"""

    def __init__(self, master, text="", command=None, kind="normal",
                 w=64, h=30, palette=None, **kw):
        self.pal = palette or build_palette()
        tk.Canvas.__init__(self, master, width=int(w), height=int(h),
                           highlightthickness=0, bd=0,
                           bg=_hex(self.pal["card"]), **kw)
        self.text, self.command, self.kind = text, command, kind
        # 按文字实际宽度定宽 —— 之前固定 w=int(150*s)，
        # 字一大就超出 Canvas 被裁掉（又一处"像白块/截字"的来源）
        self.w = max(int(w), _text_width(text, 10) + int(20))
        self.h = int(h)
        self.hover = False
        self.enabled = True
        self._ids = []
        self.bind("<Button-1>", lambda e: self._fire())
        self.bind("<Enter>", lambda e: self._set(True))
        self.bind("<Leave>", lambda e: self._set(False))
        self.draw()

    def _set(self, v):
        if self.hover != v:
            self.hover = v
            self.draw()

    def _fire(self):
        if not self.enabled:
            return
        if self.command:
            try:
                self.command()
            except Exception:
                import traceback

                log("按钮异常：\n" + traceback.format_exc())

    def set_enabled(self, on: bool):
        self.enabled = bool(on)
        self.draw()

    def set_palette(self, pal):
        self.pal = pal
        self.draw()

    def draw(self):
        for i in self._ids:
            try:
                self.delete(i)
            except Exception:
                pass
        self._ids = []
        pal, w, h = self.pal, self.w, self.h
        if not self.enabled:
            self._ids += round_rect(self, 1, 1, w - 1, h - 1, h / 2.0 - 1,
                                    fill=_hex(pal["card"]),
                                    outline=_hex(pal["line"]), width=1)
            self._ids.append(self.create_text(w / 2.0, h / 2.0, text=self.text,
                                              fill=_hex(pal["sub"]),
                                              font=("Microsoft YaHei UI", 10)))
            return
        if self.kind == "accent":
            base, fg = pal["accent"], pal["on_accent"]
            fill = _hex(_mix(base, (255, 255, 255), 0.16 if self.hover else 0.0))
        elif self.kind == "danger":
            base, fg = pal["close"], (255, 255, 255)
            fill = _hex(_mix(base, (255, 255, 255), 0.20 if self.hover else 0.0))
        else:
            base = pal["card_hi"] if self.hover else pal["card"]
            fg, fill = pal["text"], _hex(base)
        self._ids += round_rect(self, 1, 1, w - 1, h - 1, h / 2.0 - 1,
                                fill=fill, outline=_hex(pal["line"]), width=1)
        self._ids.append(self.create_text(w / 2.0, h / 2.0, text=self.text,
                                          fill=_hex(fg),
                                          font=("Microsoft YaHei UI", 10)))


class Card(tk.Frame):
    """主区域里的圆角框框：标题栏（可折叠）+ 内容区。

    背景圆角用 Canvas 画，但 Canvas 用 place 铺在最底层并 lower()；
    标题栏和内容区是普通 Frame，用 place 摆在上面 —— 它们是后创建的
    子窗口，天然在 Canvas 之上，不会出现"背景盖住内容"的白块。

    （之前把内容放进 Canvas 的 create_window，每次重绘新建的背景矩形
    会落在窗口项之上，浅色模式下卡片底色是纯白，就糊成一片白挡住字。）
    """

    HEAD = 34      # 标题栏高度（基准，乘 scale）

    def __init__(self, master, title="", desc="", palette=None, scale=1.0,
                 collapsible=True, radius=14, **kw):
        self.pal = palette or build_palette()
        self.scale = scale
        self.radius = radius
        self.collapsible = collapsible
        self.title, self.desc = title, desc
        self.open = True
        self._busy = False
        self._h = 0

        tk.Frame.__init__(self, master, bg=_hex(self.pal["bg"]), **kw)
        self.pad = int(10 * scale)
        self.head = int(self.HEAD * scale)

        # ① 背景画布 —— 最先创建 + lower()，保证永远在最底层
        self.bg = tk.Canvas(self, highlightthickness=0, bd=0,
                            bg=_hex(self.pal["bg"]))
        self.bg.place(x=0, y=0, relwidth=1, relheight=1)
        try:
            self.bg.lower()
        except Exception:
            pass

        # ② 标题栏（普通 Frame，在背景之上）
        self.title_bar = tk.Frame(self, bg=_hex(self.pal["card"]))
        self.title_lbl = tk.Label(self.title_bar, bg=_hex(self.pal["card"]),
                                  fg=_hex(self.pal["text"]), anchor="w",
                                  font=("Microsoft YaHei UI", 11, "bold"))
        self.title_lbl.pack(side="left", padx=int(12 * scale))
        self.desc_lbl = tk.Label(self.title_bar, bg=_hex(self.pal["card"]),
                                 fg=_hex(self.pal["sub"]), anchor="e",
                                 font=("Microsoft YaHei UI", 8))
        self.desc_lbl.pack(side="right", padx=int(12 * scale))
        for w in (self.title_bar, self.title_lbl, self.desc_lbl):
            w.bind("<Button-1>", self._hit)

        # ③ 内容区（普通 Frame，在背景之上）
        self.inner = tk.Frame(self, bg=_hex(self.pal["card"]))

        self.bind("<Configure>", lambda e: self._relayout())
        self.inner.bind("<Configure>", lambda e: self._relayout())
        self._paint_title()

    # ---------------------------------------------------------- 内容
    def body(self) -> tk.Frame:
        return self.inner

    def _hit(self, _=None):
        if self.collapsible:
            self.toggle()

    def toggle(self):
        self.open = not self.open
        self._paint_title()
        self._relayout()

    def _paint_title(self):
        arrow = ("▾ " if self.open else "▸ ") if self.collapsible else ""
        try:
            self.title_lbl.configure(text=arrow + self.title)
            self.desc_lbl.configure(text=self.desc or "")
        except Exception:
            pass

    def _relayout(self):
        # update_idletasks 会把 inner 的 Configure 派发出去，那个回调又是
        # _relayout，不挡住就会连环递归（表现是卡死）。
        if self._busy:
            return
        self._busy = True
        try:
            self.update_idletasks()
            w = max(self.winfo_width(), 60)
            h = self.pad * 2 + self.head
            if self.open:
                h += self.inner.winfo_reqheight()
            self._h = h
            self.configure(height=h)

            # 背景重画（在最底层）
            self.bg.configure(width=w, height=h)
            self._draw_bg(w, h)
            try:
                self.bg.lower()
            except Exception:
                pass

            # 标题栏与内容区（后创建，天然在背景之上）
            iw = max(10, w - 2 * self.pad)
            self.title_bar.place(x=self.pad, y=self.pad, width=iw, height=self.head)
            if self.open:
                self.inner.place(x=self.pad + int(8 * self.scale),
                                 y=self.pad + self.head,
                                 width=max(10, iw - int(16 * self.scale)))
            else:
                try:
                    self.inner.place_forget()
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            self._busy = False

    def _draw_bg(self, w, h):
        self.bg.delete("all")
        pal = self.pal
        try:
            self.bg.configure(bg=_hex(pal["bg"]))
        except Exception:
            pass
        round_rect(self.bg, 0, 0, w, h, self.radius * self.scale,
                   fill=_hex(pal["card"]), outline=_hex(pal["line"]), width=1)

    def set_palette(self, pal):
        self.pal = pal
        try:
            self.configure(bg=_hex(pal["bg"]))
            self.title_bar.configure(bg=_hex(pal["card"]))
            self.title_lbl.configure(bg=_hex(pal["card"]), fg=_hex(pal["text"]))
            self.desc_lbl.configure(bg=_hex(pal["card"]), fg=_hex(pal["sub"]))
            self.inner.configure(bg=_hex(pal["card"]))
        except Exception:
            pass
        self._relayout()

# ==============================================================================
# 四、选项声明（菜单 → 选项卡 → 框框 → 复选框…）
# ==============================================================================
# 选项类型：
#   ("check", key, "文字")
#   ("entry", key, "文字", 类型)         类型: text / int / float
#   ("combo", key, "文字", [选项...])
#   ("dir",   key, "文字")
#   ("note",  "说明文字")
#   ("btn",   "按钮文字", 回调名)
#   ("list",  "标题", 列表名)

MODULES = [
    ("课件同步", "①", "老师放映时静默拷走课件", [
        ("check", "sync.enable", "启用课件同步（总开关）"),
    ]),
    ("开机启动 & 守护", "②", "开机批量开软件，关掉自动重开", [
        ("check", "launch.enable", "开机批量启动（总开关）"),
    ]),
    ("文件关联", "③", "每次开机把默认打开方式改回来", [
        ("check", "assoc.enable", "启用文件关联（会改注册表）"),
    ]),
    ("定时任务", "④", "定时启动软件或关机", [
        ("check", "tasks.enable", "启用定时任务"),
    ]),
    ("程序守护器", "⑤", "目标程序被结束就自动拉起", [
        ("check", "protect.enable", "启用程序守护器"),
    ]),
    ("中育课堂助手", "⑥", "读日志取课堂号", [
        ("check", "zy.enable", "启用中育助手模块"),
    ]),
    ("云笔助手面板", "⑦", "仿云笔助手的连接界面", [
        ("check", "pen.enable", "启用云笔面板"),
    ]),
    ("计时器", "⑧", "正计时 / 倒计时，精确到秒", [
        ("check", "clock.enable", "启用计时器浮窗"),
    ]),
]

SYNC_CARDS = [
    ("保存位置", "拷到哪里、怎么分目录", [
        ("btn", "打开课件文件夹", "open_dest"),
        ("dir", "sync.dest", "保存到文件夹"),
        ("combo", "sync.subfolder_mode", "子文件夹", ["none", "date", "source", "type"]),
        ("note", "none=平铺  date=按日期  source=按来源文件夹  type=按类型"),
        ("entry", "sync.interval", "检测间隔（秒）", "int"),
        ("entry", "sync.min_size_kb", "忽略小于（KB）", "float"),
    ]),
    ("同名文件", "老师更新了课件怎么办", [
        ("combo", "sync.exists_policy", "策略",
         ["rename", "rename_always", "overwrite", "skip"]),
        ("check", "sync.skip_if_exists", "内容一样就跳过（不攒重复副本）"),
        ("note", "rename=内容变了才另存成「课件 (2)」   rename_always=同名就另存"),
        ("note", "比对的是 大小 + 修改时间，改几页字也能认出来。"),
    ]),
    ("抓哪些文件", "", [
        ("check", "sync.enable_ppt", "PowerPoint / WPS 演示"),
        ("combo", "sync.ppt_mode", "PPT 时机", ["slideshow", "open"]),
        ("check", "sync.enable_doc", "Word / WPS 文档"),
        ("check", "sync.enable_pdf", "PDF"),
        ("check", "sync.deep_scan", "PDF 深度扫描（更全但更慢）"),
    ]),
    ("顺便拷同目录", "默认全关", [
        ("check", "sync.copy_siblings", "复制同目录下的所有文件（只这一层）"),
        ("check", "sync.copy_siblings_recursive", "连同子文件夹一起递归拷"),
        ("check", "sync.siblings_use_subfolder", "放进「目标/源文件夹名/」子目录"),
        ("entry", "sync.siblings_max_files", "单次最多拷（个）", "int"),
        ("entry", "sync.siblings_max_size_mb", "单文件上限（MB）", "float"),
    ]),
    ("U 盘模式（U盘 → 电脑）", "默认关", [
        ("check", "sync.enable_usb", "插上 U 盘自动拷里面的课件"),
        ("entry", "sync.usb_interval", "重扫间隔（秒）", "int"),
        ("entry", "sync.usb_max_files", "单次最多拷（个）", "int"),
        ("entry", "sync.usb_max_size_mb", "单文件上限（MB）", "float"),
        ("entry", "sync.usb_max_depth", "最多翻几层", "int"),
        ("combo", "sync.usb_subfolder", "拷出来怎么放", ["label", "tree", "none"]),
    ]),
    ("U 盘导出（电脑 → U 盘）", "默认关", [
        ("check", "usb_export.enable", "插带隐藏触发文件的 U 盘就拷出课件"),
        ("entry", "usb_export.trigger_file", "触发文件名", "text"),
        ("check", "usb_export.require_hidden", "必须是隐藏文件（attrib +h）"),
        ("entry", "usb_export.trigger_value", "触发内容（留空=任意非空）", "text"),
        ("entry", "usb_export.dest_subfolder", "拷到 U 盘的", "text"),
        ("entry", "usb_export.interval", "检查间隔（秒）", "int"),
        ("check", "usb_export.once_per_insert", "每次插入只导一次"),
        ("check", "usb_export.overwrite", "同名直接覆盖"),
        ("btn", "立即导出课件到 U 盘", "export_usb"),
    ]),
]

BOOT_CARDS = [
    ("批量启动", "开机依次把软件打开", [
        ("check", "launch.enable", "启用批量启动"),
        ("entry", "launch.interval", "启动间隔（秒）", "float"),
        ("check", "launch.show_desktop_after", "启动完显示桌面"),
        ("check", "launch.restore_focus", "启动完归还焦点"),
        ("list", "启动项", "launch"),
    ]),
    ("守护", "软件被关掉后自动重开", [
        ("check", "watch.enable", "启用守护"),
        ("entry", "watch.check_interval", "检查间隔（秒）", "float"),
        ("entry", "watch.restart_delay", "关掉后多久重开（秒）", "float"),
        ("list", "守护项", "watch"),
    ]),
]

ASSOC_CARDS = [
    ("文件关联", "全在 HKEY_CURRENT_USER，不需要管理员", [
        ("check", "assoc.enable", "启用文件关联"),
        ("check", "assoc.apply_on_start", "启动时自动应用一遍"),
        ("entry", "assoc.delay", "启动后延迟（秒）", "float"),
        ("list", "关联规则", "assoc"),
    ]),
]

TASK_CARDS = [
    ("定时任务", "每天 / 每周几 / 每隔 N", [
        ("check", "tasks.enable", "启用定时任务"),
        ("entry", "tasks.check_interval", "检查间隔（秒）", "float"),
        ("entry", "tasks.shutdown_warn", "关机前缓冲（秒）", "float"),
        ("check", "tasks.enable_wake", "允许定时唤醒（需管理员）"),
        ("list", "任务", "tasks"),
    ]),
    ("电源", "立即执行", [
        ("btn", "60 秒后关机", "shutdown60"),
        ("btn", "立刻关机", "shutdown"),
        ("btn", "重启", "reboot"),
        ("btn", "取消关机", "cancel_shutdown"),
        ("btn", "锁屏", "lock"),
    ]),
]

PROTECT_CARDS = [
    ("守护目标", "", [
        ("check", "protect.enable", "启用程序守护器"),
        ("entry", "protect.target", "要守护的程序", "text"),
        ("entry", "protect.args", "启动参数", "text"),
        ("entry", "protect.workdir", "工作目录", "text"),
    ]),
    ("行为", "", [
        ("check", "protect.attach", "目标已在运行就接管监控"),
        ("entry", "protect.restart_delay", "被杀后多久拉起（秒）", "float"),
        ("entry", "protect.max_restart", "最多重启几次（0=不限）", "int"),
        ("check", "protect.mutual", "双进程互保"),
        ("check", "protect.ignore_ctrl", "忽略 Ctrl+C / Ctrl+Break"),
        ("note", "挡不住管理员权限的 taskkill /F。能做到的是被杀后 1~2 秒自动拉起。"),
    ]),
]

ZY_CARDS = [
    ("中育课堂助手", "读日志取课堂号", [
        ("check", "zy.enable", "启用中育助手模块"),
        ("dir", "zy.app_dir", "程序目录"),
        ("entry", "zy.app_exe", "程序文件名", "text"),
        ("entry", "zy.refresh_interval", "刷新间隔（秒）", "int"),
        ("entry", "zy.wait_seconds", "启动后等待（秒）", "float"),
        ("check", "zy.auto_start_zy", "启用时自动重启一次中育助手"),
        ("check", "zy.show_overlay", "显示课堂号浮窗"),
    ]),
]

PEN_CARDS = [
    ("云笔助手面板", "仿云笔助手的连接界面", [
        ("check", "pen.enable", "启用云笔面板"),
        ("check", "pen.topmost", "窗口置顶"),
        ("entry", "pen.height_ratio", "窗口高度占屏比", "float"),
        ("entry", "pen.refresh_interval", "刷新间隔（秒）", "float"),
        ("check", "pen.auto_start_zy", "打开面板时中育没在跑就先启动"),
        ("entry", "pen.wait_seconds", "启动中育后等待（秒）", "float"),
        ("note", "面板也可作为独立软件单独运行（云笔面板目录）。"),
    ]),
]

CLOCK_CARDS = [
    ("计时器", "正计时 / 倒计时，精确到秒", [
        ("check", "clock.enable", "启用计时器浮窗"),
        ("combo", "clock.mode", "模式", ["stopwatch", "countdown"]),
        ("check", "clock.show_seconds", "精确到秒"),
        ("check", "clock.topmost", "浮窗置顶"),
        ("btn", "重新开始计时", "clock_restart"),
    ]),
    ("倒计时设置", "countdown 模式用", [
        ("entry", "clock.countdown_seconds", "时长（秒）", "float"),
        ("entry", "clock.countdown_target", "或指定时刻（18:30）", "text"),
        ("combo", "clock.on_zero", "归零时", ["none", "message", "shutdown", "lock"]),
        ("check", "clock.auto_restart", "归零后自动重新开始"),
        ("note", "指定时刻填了就优先用它；留空用上面的时长。"),
    ]),
    ("外观", "", [
        ("entry", "clock.font_size", "字号", "int"),
        ("entry", "clock.opacity", "不透明度 0.3~1.0", "float"),
        ("entry", "clock.bg", "背景色", "text"),
        ("entry", "clock.fg", "文字色", "text"),
        ("note", "浮窗可以拖动，位置会自动记下来。"),
    ]),
]

LOG_CARDS = [
    ("日志", "排查问题第一步就是看它", [
        ("btn", "打开日志文件", "open_log"),
        ("btn", "打开配置目录", "open_dir"),
        ("btn", "立即检查一次", "scan_now"),
        ("btn", "清空复制记录", "clear_records"),
        ("note", "配置和日志就在程序同一个文件夹：config.json / sync.log"),
    ]),
]

MENU_PAGES = {
    "首选项": {
        # 常规页特殊：不画框框，直接 7 个复选框平铺（见 _render_prefs）
        "常规": [("m%d" % i, t, d, opts) for i, (t, g, d, opts) in enumerate(MODULES)],
        "课件同步": [("s%d" % i, t, d, opts) for i, (t, d, opts) in enumerate(SYNC_CARDS)],
        # 开机启动&守护 + 定时任务 + 程序守护器 合并
        "启动与守护": (
            [("b%d" % i, t, d, opts) for i, (t, d, opts) in enumerate(BOOT_CARDS)]
            + [("t%d" % i, t, d, opts) for i, (t, d, opts) in enumerate(TASK_CARDS)]
            + [("p%d" % i, t, d, opts) for i, (t, d, opts) in enumerate(PROTECT_CARDS)]
        ),
        "文件关联": [("a%d" % i, t, d, opts) for i, (t, d, opts) in enumerate(ASSOC_CARDS)],
        # 中育助手 + 云笔面板 合并
        "中育 & 云笔": (
            [("z%d" % i, t, d, opts) for i, (t, d, opts) in enumerate(ZY_CARDS)]
            + [("n%d" % i, t, d, opts) for i, (t, d, opts) in enumerate(PEN_CARDS)]
        ),
        "计时器": [("k%d" % i, t, d, opts) for i, (t, d, opts) in enumerate(CLOCK_CARDS)],
    },
    "个性化": {
        "颜色": [],
        "缩放": [],
        "其它": [],
    },
    "帮助": {
        "怎么用": [],
        "源码": [],
        "日志": [],
        "关于 ClassHub": [],
    },
}

# ==============================================================================
# 五、列表编辑器（启动项 / 守护项 / 关联 / 任务）
# ==============================================================================
LIST_FIELDS = {
    "launch": ("启动项", [
        ("名称", "name", "text", None),
        ("程序路径", "path", "file", None),
        ("参数", "args", "text", None),
        ("工作目录", "workdir", "dir", None),
        ("启用", "enabled", "bool", None),
        ("启动方式 0前台/1后台/2隐藏", "background", "int", None),
        ("延迟（秒）", "delay", "float", None),
        ("进程名（存活检测）", "process", "text", None),
    ]),
    "watch": ("守护项", [
        ("名称", "name", "text", None),
        ("程序路径", "path", "file", None),
        ("参数", "args", "text", None),
        ("工作目录", "workdir", "dir", None),
        ("启用", "enabled", "bool", None),
        ("启动方式 0前台/1后台/2隐藏", "background", "int", None),
        ("延迟（秒）", "delay", "float", None),
        ("进程名（最关键，填错会一直重复启动）", "process", "text", None),
        ("关掉后多久重开（秒）", "restart_delay", "float", None),
        ("没在跑就启动", "start_when_missing", "bool", None),
    ]),
    "assoc": ("关联规则", [
        ("扩展名（如 .pptx）", "ext", "text", None),
        ("程序路径", "path", "file", None),
        ("ProgId（留空自动生成）", "progid", "text", None),
        ("启用", "enabled", "bool", None),
    ]),
    "tasks": ("定时任务", [
        ("名称", "name", "text", None),
        ("动作 launch/shutdown/reboot/sleep/hibernate/lock", "action", "combo",
         ["launch", "shutdown", "reboot", "sleep", "hibernate", "lock"]),
        ("程序路径（action=launch 时）", "path", "file", None),
        ("参数", "args", "text", None),
        ("计划 daily/weekly/interval/once", "schedule", "combo",
         ["daily", "weekly", "interval", "once"]),
        ("时间或间隔（08:00 / 30m / 12h / 3d）", "value", "text", None),
        ("星期（weekly 用，如 1,3,5）", "weekdays", "text", None),
        ("开机补做", "catch_up", "bool", None),
        ("启用", "enabled", "bool", None),
    ]),
}


def mk_entry(master, textvariable, width=18, palette=None, scale=1.0,
             show=None, fill=False):
    """创建一个输入框。

    之前直接用 tk.Entry(bg=..., highlightthickness=1, relief="flat")，
    在 Windows 上 Tk 的 highlight 环 / 3D 边框会用系统色（常是白的）去画，
    widget 周围就出现一圈白块 —— 这也是"填空区域有白块"的来源。

    现在改成：外层 Frame 当边框（颜色明确），内层 Entry 关掉所有自绘边框
    （bd=0 / highlightthickness=0 / relief=flat），这样屏幕上出现的每一块
    颜色都是我们指定的，不会出现系统默认白。
    """
    pal = palette or build_palette()
    border = tk.Frame(master, bg=_hex(pal["line"]))
    kw = dict(textvariable=textvariable, width=width,
              bg=_hex(pal["card_hi"]), fg=_hex(pal["text"]),
              insertbackground=_hex(pal["text"]),      # 光标
              selectbackground=_hex(pal["accent"]),
              selectforeground=_hex(pal["on_accent"]),
              relief="flat", bd=0, highlightthickness=0,
              font=("Microsoft YaHei UI", 9))
    if show:
        kw["show"] = show
    e = tk.Entry(border, **kw)
    e.pack(padx=1, pady=1, ipady=max(1, int(2 * scale)),
           fill="x" if fill else None, expand=bool(fill))
    e._border = border
    return e


def style_combo(palette=None):
    """ttk.Combobox 用主题配置（ttk 不认 bg/fg 关键字，直接设会被忽略或画成白的）"""
    pal = palette or build_palette()
    try:
        st = ttk.Style()
        st.configure("CH.TCombobox",
                     fieldbackground=_hex(pal["card_hi"]),
                     background=_hex(pal["card"]),
                     foreground=_hex(pal["text"]),
                     borderwidth=1, relief="flat",
                     arrowcolor=_hex(pal["text"]),
                     insertcolor=_hex(pal["text"]))
        st.map("CH.TCombobox",
               fieldbackground=[("readonly", _hex(pal["card_hi"])),
                                ("disabled", _hex(pal["card"]))],
               foreground=[("readonly", _hex(pal["text"])),
                           ("disabled", _hex(pal["sub"]))],
               arrowcolor=[("disabled", _hex(pal["sub"]))])
        return "CH.TCombobox"
    except Exception:
        return "TCombobox"


def style_scrollbar(palette=None):
    """滚动条也配一下，免得是白的"""
    pal = palette or build_palette()
    try:
        st = ttk.Style()
        st.configure("CH.Vertical.TScrollbar",
                     background=_hex(pal["card_hi"]),
                     troughcolor=_hex(pal["bg"]),
                     borderwidth=0, arrowcolor=_hex(pal["sub"]))
        return "CH.Vertical.TScrollbar"
    except Exception:
        return "Vertical.TScrollbar"


class ListEditor:
    """Listbox + 新增/编辑/删除。数据存在 self.items（dataclass 列表）"""

    def __init__(self, master, kind: str, items: list, palette):
        self.kind = kind
        self.items = list(items)
        self.pal = palette
        title, self.fields = LIST_FIELDS[kind]
        self.cls = {"launch": AppItem, "watch": AppItem,
                    "assoc": AssocItem, "tasks": TaskItem}[kind]

        f = tk.Frame(master, bg=_hex(palette["card"]))
        self.frame = f
        # 同样关掉 Tk 自绘边框（highlight 环会用系统色画，常是白的），
        # 外面套一个 Frame 当边框，颜色完全可控
        lb_border = tk.Frame(f, bg=_hex(palette["line"]))
        lb_border.pack(fill="x", pady=(0, 6))
        lb = tk.Listbox(lb_border, height=5, width=52,
                        bg=_hex(palette["card_hi"]), fg=_hex(palette["text"]),
                        selectbackground=_hex(palette["accent"]),
                        selectforeground=_hex(palette["on_accent"]),
                        relief="flat", bd=0, highlightthickness=0,
                        font=("Microsoft YaHei UI", 9))
        lb.pack(padx=1, pady=1, fill="x")
        lb.pack(fill="x", pady=(0, 6))
        self.lb = lb

        bar = tk.Frame(f, bg=_hex(palette["card"]))
        bar.pack(fill="x")
        self.btns = []
        for txt, cmd in (("新增", self.add), ("编辑", self.edit),
                         ("删除", self.remove)):
            b = PillButton(bar, text=txt, w=66, h=28, palette=palette, command=cmd)
            b.configure(bg=_hex(palette["card"]))
            b.pack(side="left", padx=3)
            self.btns.append(b)
        self.refresh()

    def refresh(self):
        self.lb.delete(0, "end")
        for it in self.items:
            name = getattr(it, "name", "") or getattr(it, "ext", "") or "(未命名)"
            flag = "" if getattr(it, "enabled", True) else "  [已停用]"
            self.lb.insert("end", "%s%s" % (name, flag))

    def _dialog(self, values=None):
        try:
            import chub_ui

            dlg = chub_ui.FormDialog(self.frame.winfo_toplevel(),
                                     "%s" % LIST_FIELDS[self.kind][0],
                                     self.fields, values or {})
            self.frame.wait_window(dlg.top)
            return dlg.result
        except Exception:
            import traceback

            log("列表编辑对话框失败：\n" + traceback.format_exc())
            return None

    def _make(self, d: dict):
        if self.kind == "launch":
            o = AppItem.from_dict(d, "launch")
        elif self.kind == "watch":
            o = AppItem.from_dict(d, "watch")
        elif self.kind == "assoc":
            o = AssocItem.from_dict(d)
        else:
            o = TaskItem.from_dict(d)
        return o

    def add(self):
        r = self._dialog({})
        if r:
            self.items.append(self._make(r))
            self.refresh()

    def edit(self):
        i = self.lb.curselection()
        if not i:
            return
        idx = int(i[0])
        cur = self.items[idx]
        r = self._dialog(cur.to_dict() if hasattr(cur, "to_dict") else dict(cur.__dict__))
        if r:
            self.items[idx] = self._make(r)
            self.refresh()

    def remove(self):
        i = self.lb.curselection()
        if not i:
            return
        try:
            self.items.pop(int(i[0]))
        except Exception:
            pass
        self.refresh()


# ==============================================================================
# 六、帮助内容
# ==============================================================================
HELP_PAGES = [
    ("总览", [
        "ClassHub 把这几件事合到了一个托盘图标里：",
        "",
        "① 课件同步 —— 老师一放映，静默把课件拷到 D:\\课件",
        "② 开机启动 & 守护 —— 开机批量开软件，关掉自动重开",
        "③ 文件关联 —— 每次开机把 .pptx 的默认打开方式改回来",
        "④ 定时任务 —— 每天/每周几/每隔 N 天，启动软件或关机",
        "⑤ 程序守护器 —— 目标程序被结束就自动拉起（防 taskkill）",
        "⑥ 中育助手 —— 读日志取课堂号，浮窗显示",
        "⑦ 云笔面板 —— 仿云笔助手的连接界面（也可单独运行）",
        "",
        "所有开关默认都是关的，不勾就不会做任何事。",
    ]),
    ("三步跑起来", [
        "1. 装 Python 3.10+（安装时务必勾选 Add python.exe to PATH）",
        "2. 双击 1_安装依赖.bat（只需做一次）",
        "3. 双击 2_启动(静默).bat",
        "",
        "右下角出现蓝色小书本图标就生效了。",
        "右键图标有菜单；左键单击图标直接打开这个设置窗口。",
        "",
        "想开机自动启动：右键图标 → 勾选「开机自动启动」。",
        "想停掉：右键图标 → 退出，或双击 4_停止.bat。",
    ]),
    ("课件同步", [
        "默认只在放映时拷 PPT。老师只是打开没放映的话，",
        "把「PPT 抓取时机」改成 open（打开就拷）。",
        "",
        "抓 Word / PDF 是「打开就抓」，不想要就取消勾选。",
        "",
        "保存位置：D:\\课件（没有 D 盘就自动用「文档\\课件」）。",
        "",
        "排查第一步永远是：立即检查一次 → 打开日志，",
        "看日志里有没有「已复制」。",
    ]),
    ("同名文件 (2)", [
        "老师更新了课件，希望存成新版本而不是覆盖 —— 用「同名文件」策略。",
        "",
        "rename（默认）：比对 大小 + 修改时间。",
        "  内容变了 → 另存成「课件 (2)」",
        "  内容一样 → 跳过，不攒重复副本",
        "",
        "rename_always：只要同名就另存，不做比较。",
        "overwrite：直接覆盖。",
        "skip：有同名就跳过。",
    ]),
    ("顺便拷同目录", [
        "抓到课件时，顺手把同一个文件夹里的其他文件也拷走。",
        "",
        "□ 复制该文件同目录下的所有文件",
        "    只拷这一层的直接子文件，不进子文件夹。",
        "",
        "□ 连同子文件夹一起递归拷",
        "    拷全部文件（含子文件夹里的），保留目录结构。",
        "",
        "默认放在「目标文件夹 / 源文件夹名 /」下，来源清楚也不撞名。",
        "上限：单次 200 个、单文件 200 MB。",
    ]),
    ("U 盘模式（U盘 → 电脑）", [
        "默认关闭。勾上后，插上 U 盘自动拷里面的 PPT / Word / PDF。",
        "",
        "认的是系统判定为「可移动磁盘」的设备；",
        "手机 MTP 模式、部分读卡器不会被识别成盘符，这种扫不到。",
        "",
        "拷过的按「路径+大小+修改时间」记指纹，拔了再插不会重复拷。",
    ]),
    ("U 盘导出（电脑 → U 盘）", [
        "方向跟 U 盘模式相反：插 U 盘，把课件文件夹拷进 U 盘。",
        "",
        "在 U 盘根目录放一个隐藏文件：",
        "    echo 1 > E:\\f",
        "    attrib +h E:\\f",
        "",
        "（懒得敲命令就双击 6_制作U盘导出触发文件.bat）",
        "",
        "插上就自动把课件拷到「U盘:\\课件\\」。",
        "内容是 0 / off / 空文件不触发，方便临时关掉。",
        "同一个盘每次插入只导一次，拔掉重插才会再导。",
    ]),
    ("开机启动 & 守护", [
        "启动项：开机批量启动软件，每项可单独关掉。",
        "启动方式 1 = 后台静默启动（最小化、不抢焦点）。",
        "",
        "守护项：软件被关掉后，等 N 秒自动重新打开。",
        "",
        "最容易填错的是进程名 —— 去任务管理器 → 详细信息里看",
        "真实的进程名（带 .exe），填错了会一直重复启动。",
    ]),
    ("文件关联", [
        "解决「冰点还原把默认打开方式还原回去」的问题：",
        "程序每次启动都自动帮你改一遍。",
        "",
        "全在 HKEY_CURRENT_USER 下操作，不需要管理员权限。",
        "",
        "关键是删掉 Explorer 的 UserChoice —— 它会盖过其它所有设置。",
        "",
        "部分 UWP 应用（照片、电影和电视）只能通过系统设置改。",
    ]),
    ("定时任务", [
        "动作：launch 启动 / shutdown 关机 / reboot 重启",
        "      sleep 睡眠 / hibernate 休眠 / lock 锁屏",
        "",
        "计划：daily 每天 / weekly 每周几 / interval 每隔 N / once 指定时刻",
        "",
        "间隔写法：30m 分钟、12h 小时、50d 天、2w 周。",
        "",
        "开机补做：开机发现今天那个点已经过了，立刻补做一次。",
        "关机前默认留 60 秒缓冲，可以取消。",
    ]),
    ("程序守护器", [
        "守护一个指定程序，它被结束就自动拉起。",
        "",
        "说清楚能挡什么：挡不住管理员权限的 taskkill /F，",
        "能做到的是「被杀之后 1~2 秒内自动拉起来」。",
        "",
        "可选「双进程互保」：额外开一个伙伴进程盯着本程序。",
        "",
        "想正常退出：先在托盘菜单里关掉这个开关。",
    ]),
    ("计时器", [
        "新模块：一个独立小浮窗，显示正计时或倒计时，精确到秒。",
        "",
        "模式：",
        "  stopwatch 正计时 —— 从 00:00:00 往上走",
        "  countdown 倒计时 —— 从设定时长往下走",
        "",
        "倒计时可填：",
        "  时长（秒）—— 比如 3600 = 一小时",
        "  或指定时刻 —— 比如 18:30（填了优先用这个）",
        "",
        "归零时可选：什么都不做 / 弹提示 / 关机 / 锁屏",
        "还可以勾「归零后自动重新开始」，做成循环计时。",
        "",
        "浮窗可以拖动位置，位置会自动记下来。",
        "默认关闭，勾上才显示。",
    ]),
    ("排查与常见问题", [
        "图标出来了但没拷到东西：",
        "  立即检查一次 → 打开日志，看有没有「已复制」。",
        "",
        "老师用管理员权限开的 PowerPoint：",
        "  本程序也要右键「以管理员身份运行」才能连上。",
        "",
        "杀软报警：PyInstaller 打包的 exe 容易被启发式引擎误报。",
        "  打包时用选项 2（文件夹版）误报率低很多。",
        "",
        "日志和配置就在程序同一个文件夹里：",
        "  config.json / copied.json / sync.log",
    ]),
]

PRESETS = {
    "经典蓝": (205, 0, 0),
    "天蓝": (197, 0, 0),
    "深蓝": (215, -8, 6),
    "青": (188, 0, 0),
    "紫": (258, 0, -6),
    "石墨": (210, -18, -28),
}


# ==============================================================================
# 七、主窗口（系统标题栏 + 菜单栏 + 选项卡 + 主区域）
# ==============================================================================
class ShellWindow:
    """任务管理器式布局：

        ┌────────────────────────────────────────┐
        │ ClassHub 设置              ─   □   ✕   │ ← Windows 画的（DWM）
        ├────────────────────────────────────────┤
        │  首选项   个性化   帮助   关于          │ ← 菜单栏（文件/选项/查看 那排）
        ├────────────────────────────────────────┤
        │ 常规 │课件同步│开机启动│文件关联│…      │ ← 选项卡
        ├────────────────────────────────────────┤
        │ ┌──────────┐ ┌──────────┐              │
        │ │▾ 课件同步 │ │▾ 开机启动 │              │ ← 主区域：圆角框框
        │ │ ☑ 启用…  │ │ ☐ 启用…  │              │
        │ └──────────┘ └──────────┘              │
        ├────────────────────────────────────────┤
        │ 提示文字                 [应用] [退出…] │
        └────────────────────────────────────────┘

    标题栏、最小化/关闭按钮全交给系统 —— 不自绘，就不会有错位和死循环。
    """

    def __init__(self, app):
        global _SHELL_ROOT, _SHELL_WIN
        self.app = app
        self.pal = build_palette(detect_dark())
        self.bindings = []
        self.editors = {}
        self._cards = []
        self._ctl_widgets = []
        self._theme_job = ""

        try:
            import chub_ui as chw

            self.scale = chw.ensure_dpi_aware()
        except Exception:
            self.scale = 1.0
            chw = None

        root = tk.Tk()
        _SHELL_ROOT = root
        _SHELL_WIN = self
        self.root = root
        root.title("ClassHub 课堂助手套件 —— 设置")
        try:
            if chw:
                chw.set_window_icon(root)
                self.scale = chw.ui_scale(root, self.scale)
                chw.apply_tk_scaling(root, self.scale)
        except Exception:
            pass

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        w = int(min(1060 * self.scale, sw * 0.94))
        h = int(min(720 * self.scale, sh * 0.90))
        root.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2),
                                       max(0, int((sh - h) * 0.42))))
        root.configure(bg=_hex(self.pal["bg"]))

        # ---- DWM：让系统按任务管理器那套来画（深色标题栏 + 圆角 + Mica）----
        self.dwm = apply_dwm(root, self.pal["dark"],
                             CFG.get("shell.backdrop", "mica"))

        self.menu = "首选项"
        self.tab = "常规"

        self._build_menubar(root)
        self._build_tabbar(root)
        self._build_main(root)
        self._build_status(root)

        # 关键：首屏必须主动渲染一次。
        # 之前只搭了骨架没填内容，表现就是"打开是白的，
        # 点一下别的选项卡再点回来才有东西"。
        self.render_main()
        try:
            root.update_idletasks()
            self.render_main()      # 宽度出来后再排一次，卡片才知道该多宽
        except Exception:
            pass

        root.protocol("WM_DELETE_WINDOW", self.close)
        try:
            root.mainloop()
        finally:
            _SHELL_ROOT = None
            _SHELL_WIN = None

    # ------------------------------------------------------------ 菜单栏
    def _build_menubar(self, root):
        """任务管理器「文件 / 选项 / 查看」那一排。

        按钮从 MENU_PAGES 动态取，不再写死 —— 之前写死成
        ("首选项","个性化","帮助","关于")，把「关于」并进帮助后按钮没跟着删，
        留了个点了没反应的死按钮。
        """
        pal = self.pal
        s = self.scale
        bar = tk.Frame(root, bg=_hex(pal["bg"]), height=int(36 * s))
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)
        self.menubar = bar
        self.menu_btns = {}
        for name in MENU_PAGES.keys():
            b = tk.Label(bar, text=name, bg=_hex(pal["bg"]), fg=_hex(pal["text"]),
                         padx=int(14 * s), pady=int(6 * s),
                         font=("Microsoft YaHei UI", 10))
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, n=name: self.set_menu(n))
            b.bind("<Enter>", lambda e, n=name: self._menu_hover(n, True))
            b.bind("<Leave>", lambda e, n=name: self._menu_hover(n, False))
            self.menu_btns[name] = b
        self._paint_menubar()

    def _menu_hover(self, name, on):
        if self.menu == name:
            return
        pal = self.pal
        try:
            self.menu_btns[name].configure(
                bg=_hex(pal["card_hi"] if on else pal["bg"]))
        except Exception:
            pass

    def _paint_menubar(self):
        pal = self.pal
        for name, b in self.menu_btns.items():
            sel = (name == self.menu)
            try:
                b.configure(bg=_hex(pal["accent"] if sel else pal["bg"]),
                            fg=_hex(pal["on_accent"] if sel else pal["text"]))
            except Exception:
                pass

    def set_menu(self, name):
        if name not in MENU_PAGES:
            return
        self.menu = name
        if self.tab not in MENU_PAGES[name]:
            self.tab = list(MENU_PAGES[name].keys())[0]
        self._paint_menubar()
        self._build_tabbar_items()
        self.render_main()

    # ------------------------------------------------------------ 选项卡行
    def _build_tabbar(self, root):
        pal = self.pal
        s = self.scale
        bar = tk.Frame(root, bg=_hex(pal["bg"]), height=int(34 * s))
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)
        self.tabbar = bar
        self.tab_btns = {}
        self._build_tabbar_items()

    def _build_tabbar_items(self):
        for w in self.tabbar.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        self.tab_btns = {}
        pal = self.pal
        s = self.scale
        for name in MENU_PAGES[self.menu]:
            b = tk.Label(self.tabbar, text=name, bg=_hex(pal["bg"]),
                         fg=_hex(pal["sub"]), padx=int(13 * s), pady=int(7 * s),
                         font=("Microsoft YaHei UI", 10))
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, n=name: self.set_tab(n))
            self.tab_btns[name] = b
        self._paint_tabbar()

    def _paint_tabbar(self):
        pal = self.pal
        for name, b in self.tab_btns.items():
            sel = (name == self.tab)
            try:
                b.configure(bg=_hex(pal["card"] if sel else pal["bg"]),
                            fg=_hex(pal["accent"] if sel else pal["sub"]),
                            font=("Microsoft YaHei UI", 10,
                                  "bold" if sel else "normal"))
            except Exception:
                pass

    def set_tab(self, name):
        self.tab = name
        self._paint_tabbar()
        self.render_main()

    # ------------------------------------------------------------ 主区域
    def _build_main(self, root):
        pal = self.pal
        wrap = tk.Frame(root, bg=_hex(pal["bg"]))
        wrap.pack(fill="both", expand=True)
        self.main_wrap = wrap

        self.canvas = tk.Canvas(wrap, bg=_hex(pal["bg"]), highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview,
                           style=style_scrollbar(self.pal))
        sb.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=sb.set)

        self.grid = tk.Frame(self.canvas, bg=_hex(pal["bg"]))
        self.cwin = self.canvas.create_window((0, 0), window=self.grid, anchor="nw")

        def on_frame(_=None):
            try:
                self.canvas.configure(scrollregion=self.canvas.bbox("all"))
                self.canvas.itemconfigure(self.cwin, width=self.canvas.winfo_width())
            except Exception:
                pass

        self.grid.bind("<Configure>", on_frame)
        self.canvas.bind("<Configure>", on_frame)

        # 滚轮：绑在 canvas 上的话，鼠标停在卡片/复选框/输入框等子控件上时
        # 事件不会冒泡到 canvas，就滚不动（只能拖进度条）。改成全局绑定，
        # 再判断鼠标是不是落在主区域里 —— 是才滚，否则让控件自己处理。
        self._wheel_binds = []
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.root.bind_all(seq, self._on_wheel)
            self._wheel_binds.append(seq)

    def _unbind_wheel(self):
        """窗口销毁前解绑，避免重复绑定越滚越快"""
        for seq in getattr(self, "_wheel_binds", []):
            try:
                self.root.unbind_all(seq)
            except Exception:
                pass
        self._wheel_binds = []

    def _is_over_main(self, e) -> bool:
        """鼠标是否落在主区域（canvas 或其任一子孙）上"""
        try:
            w = self.root.winfo_containing(e.x_root, e.y_root)
        except Exception:
            return False
        if w is None:
            return False
        cur = w
        for _ in range(64):                 # 防死循环
            try:
                if cur is self.canvas or str(cur) == str(self.canvas):
                    return True
            except Exception:
                return False
            # 往上走一层：优先用 .master，退回 winfo_parent + nametowidget
            nxt = None
            try:
                nxt = getattr(cur, "master", None)
            except Exception:
                nxt = None
            if nxt is None:
                try:
                    parent = cur.winfo_parent()
                    if parent:
                        nxt = self.root.nametowidget(parent)
                except Exception:
                    nxt = None
            if nxt is None:
                return False
            cur = nxt
        return False

    def _on_wheel(self, e):
        try:
            if not self._is_over_main(e):
                return                      # 不在主区域，交给控件自己滚
            widget = None
            try:
                widget = self.root.winfo_containing(e.x_root, e.y_root)
            except Exception:
                pass
            # 自己能滚的控件（源码页的 Text、列表框）让它自己滚，别抢
            if widget is not None:
                cls = widget.winfo_class()
                if cls in ("Text", "Listbox", "Treeview", "Entry", "Spinbox"):
                    return
            if getattr(e, "delta", 0):
                self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            elif getattr(e, "num", 0) == 4:
                self.canvas.yview_scroll(-1, "units")
            elif getattr(e, "num", 0) == 5:
                self.canvas.yview_scroll(1, "units")
        except Exception:
            pass
        return "break"

    def render_main(self):
        for w in self.grid.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        self.bindings = []
        self.editors = {}
        self._cards = []
        self._ctl_widgets = []

        s = self.scale
        cols = 2 if self.menu == "首选项" else 1
        for i in range(cols):
            self.grid.columnconfigure(i, weight=1)

        if self.menu == "个性化":
            self._render_personal()
        elif self.menu == "帮助":
            self._render_help()
        else:
            self._render_prefs(cols)

        try:
            self.canvas.yview_moveto(0)
            self.canvas.update_idletasks()
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except Exception:
            pass

    def _combo_style(self):
        try:
            return style_combo(self.pal)
        except Exception:
            return "TCombobox"

    # ------------------------------------------------------------ 首选项
    def _render_prefs(self, cols):
        """框框数量 <= 1 时不再画框框，直接平铺。

        「常规」页更进一步：7 个模块各只有一个总开关，
        不画框框也没有折叠箭头，就是 7 行复选框（带编号和说明）。
        """
        s = self.scale
        cards = MENU_PAGES[self.menu][self.tab]

        # ---- 常规页：7 行复选框，直接平铺 ----
        if self.menu == "首选项" and self.tab == "常规":
            holder = tk.Frame(self.grid, bg=_hex(self.pal["bg"]))
            holder._base_bg = "bg"
            holder.grid(row=0, column=0, sticky="ew",
                        padx=int(10 * s), pady=int(8 * s))
            self._ctl_widgets.append(holder)
            hd = tk.Frame(holder, bg=_hex(self.pal["bg"]))
            hd._base_bg = "bg"
            hd.pack(fill="x", padx=int(12 * s), pady=(int(10 * s), int(6 * s)))
            tk.Label(hd, text="功能模块总开关", bg=_hex(self.pal["bg"]),
                     fg=_hex(self.pal["text"]),
                     font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
            tk.Label(hd, text="默认全部关闭", bg=_hex(self.pal["bg"]),
                     fg=_hex(self.pal["sub"]),
                     font=("Microsoft YaHei UI", 8)).pack(side="right")
            self._ctl_widgets.append(hd)
            for title, glyph, desc, opts in MODULES:
                row = tk.Frame(holder, bg=_hex(self.pal["bg"]))
                row._base_bg = "bg"
                row.pack(fill="x", padx=int(12 * s), pady=int(2 * s))
                self._ctl_widgets.append(row)
                tk.Label(row, text=glyph, width=3, anchor="w",
                         bg=_hex(self.pal["bg"]), fg=_hex(self.pal["accent"]),
                         font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
                for spec in opts:
                    if spec[0] == "check":
                        v = tk.BooleanVar(value=bool(CFG.get(spec[1], False)))
                        ck = RoundCheck(row, text=spec[2], variable=v,
                                        palette=self.pal, size=int(22 * s),
                                        base="bg")
                        ck.pack(anchor="w")
                        self.bindings.append((spec[1], "bool", v))
                        self._ctl_widgets.append(ck)
                if desc:
                    tk.Label(row, text=desc, bg=_hex(self.pal["bg"]),
                             fg=_hex(self.pal["sub"]),
                             font=("Microsoft YaHei UI", 8)).pack(
                        anchor="w", padx=int(30 * s))
            return

        if len(cards) <= 1:
            for _, title, desc, opts in cards:
                holder = tk.Frame(self.grid, bg=_hex(self.pal["bg"]))
                holder._base_bg = "bg"
                holder.grid(row=0, column=0, sticky="ew",
                            padx=int(10 * s), pady=int(8 * s))
                self._ctl_widgets.append(holder)
                if title:
                    th = tk.Frame(holder, bg=_hex(self.pal["card"]))
                    th.pack(fill="x", padx=int(12 * s),
                            pady=(int(10 * s), int(4 * s)))
                    tk.Label(th, text=title, bg=_hex(self.pal["card"]),
                             fg=_hex(self.pal["text"]),
                             font=("Microsoft YaHei UI", 12,
                                   "bold")).pack(side="left")
                    if desc:
                        tk.Label(th, text=desc, bg=_hex(self.pal["card"]),
                                 fg=_hex(self.pal["sub"]),
                                 font=("Microsoft YaHei UI", 8)).pack(side="right")
                    self._ctl_widgets.append(th)
                self._fill_into(holder, opts, base_key="bg")
            return

        for i, (_, title, desc, opts) in enumerate(cards):
            card = Card(self.grid, title=title, desc=desc, palette=self.pal,
                        scale=s, collapsible=True)
            card.grid(row=i // cols, column=i % cols, sticky="ew",
                      padx=int(10 * s), pady=int(8 * s))
            self._cards.append(card)
            self._fill_into(card.body(), opts, base_key="card")

    def _fill_into(self, body, opts, base_key="card"):
        """把选项塞进容器（Card 的内容区，或平铺容器）。

        base_key 是这一行的底色：
            "card" -> 卡片内容区（有圆角背景）
            "bg"   -> 平铺，跟页面同色，看不出"框"

        行布局要点：标签用自然宽度（不设固定字符数），输入框 fill="x" 吃掉
        剩余空间 —— 这样无论缩放多大，输入框都不会太短也不会撑爆一行。
        """
        s = self.scale
        pal = self.pal
        bg = _hex(pal[base_key])
        pad = int(12 * s)

        def row_frame():
            f = tk.Frame(body, bg=bg)
            f._base_bg = base_key
            f.pack(fill="x", padx=pad, pady=int(3 * s))
            self._ctl_widgets.append(f)
            return f

        def label(parent, text, width=None):
            kw = dict(text=text, anchor="w", bg=bg, fg=_hex(pal["text"]),
                      font=("Microsoft YaHei UI", 9))
            if width:
                kw["width"] = width
            lb = tk.Label(parent, **kw)
            lb.pack(side="left")
            return lb

        for spec in opts:
            kind = spec[0]
            if kind == "check":
                _, key, text = spec
                v = tk.BooleanVar(value=bool(CFG.get(key, False)))
                ck = RoundCheck(body, text=text, variable=v, palette=pal,
                                size=int(22 * s), base=base_key)
                ck.configure(bg=bg)
                ck.pack(anchor="w", padx=pad, pady=int(3 * s), fill="x")
                self.bindings.append((key, "bool", v))
                self._ctl_widgets.append(ck)
            elif kind == "entry":
                _, key, text, vtype = spec
                row = row_frame()
                label(row, text)
                v = tk.StringVar(value=str(CFG.get(key, "")))
                mk_entry(row, v, width=18, palette=pal, scale=s,
                         fill=True)._border.pack(side="left", fill="x",
                                                 expand=True, padx=(int(8 * s), 0))
                self.bindings.append((key, vtype, v))
            elif kind == "combo":
                _, key, text, values = spec
                row = row_frame()
                label(row, text)
                v = tk.StringVar(value=str(CFG.get(key, "")))
                box = ttk.Combobox(row, textvariable=v, width=16,
                                   state="readonly", values=list(values),
                                   style=self._combo_style())
                box.pack(side="left", padx=(int(8 * s), 0))
                if str(CFG.get(key, "")) not in values:
                    box.set(values[0] if values else "")
                self.bindings.append((key, "text", v))
            elif kind == "dir":
                _, key, text = spec
                row = row_frame()
                label(row, text)
                v = tk.StringVar(value=str(CFG.get(key, "") or core.default_dest()))

                def pick(_v=v):
                    from tkinter import filedialog

                    p = filedialog.askdirectory(title="选择文件夹")
                    if p:
                        _v.set(p)

                mk_entry(row, v, width=30, palette=pal, scale=s,
                         fill=True)._border.pack(side="left", fill="x",
                                                 expand=True, padx=(int(8 * s), 0))
                b = PillButton(row, text="浏览…", w=int(58 * s), h=int(24 * s),
                               palette=pal, command=pick)
                b.configure(bg=bg)
                b.pack(side="left", padx=int(5 * s))
                self.bindings.append((key, "text", v))
                self._ctl_widgets.append(b)
            elif kind == "note":
                nt = tk.Label(body, text=spec[1], bg=bg, fg=_hex(pal["sub"]),
                              justify="left", anchor="w",
                              wraplength=int(360 * s),
                              font=("Microsoft YaHei UI", 8))
                nt._base_bg = base_key
                nt.pack(anchor="w", padx=int(13 * s), pady=int(2 * s), fill="x")
                self._ctl_widgets.append(nt)
            elif kind == "btn":
                row = row_frame()
                b = PillButton(row, text=spec[1], w=int(150 * s), h=int(28 * s),
                               palette=pal, command=self._action(spec[2]))
                b.configure(bg=bg)
                b._base_bg = base_key
                b.pack(anchor="w")
                self._ctl_widgets.append(b)
            elif kind == "list":
                _, title, lname = spec
                ed = ListEditor(body, lname, self._load_items(lname), self.pal)
                ed.frame._base_bg = base_key
                ed.frame.pack(fill="x", padx=pad, pady=int(4 * s))
                self.editors[lname] = ed
                self._ctl_widgets.append(ed.frame)

    def _load_items(self, lname):
        path = {"launch": "launch.items", "watch": "watch.items",
                "assoc": "assoc.items", "tasks": "tasks.items"}[lname]
        out = []
        for d in CFG.get(path, []) or []:
            try:
                if lname == "launch":
                    out.append(AppItem.from_dict(d, "launch"))
                elif lname == "watch":
                    out.append(AppItem.from_dict(d, "watch"))
                elif lname == "assoc":
                    out.append(AssocItem.from_dict(d))
                else:
                    out.append(TaskItem.from_dict(d))
            except Exception:
                continue
        return out

    def _action(self, name):
        def run():
            app = self.app
            try:
                if name == "open_dest":
                    import chub_sync

                    core.open_in_explorer(chub_sync.dest_root())
                elif name == "open_log":
                    core.open_in_explorer(LOG_PATH)
                elif name == "open_dir":
                    core.open_in_explorer(core.BASE)
                elif name == "scan_now":
                    if app:
                        app.on_scan_now()
                elif name == "clear_records":
                    if app:
                        app.on_clear_records()
                elif name == "export_usb":
                    if app:
                        app.on_export_usb(True)
                elif name == "clock_restart":
                    if app:
                        app.on_clock_restart()
                elif name == "shutdown60":
                    self._power("shutdown", 60)
                elif name == "shutdown":
                    self._power("shutdown", 0)
                elif name == "reboot":
                    self._power("reboot", 0)
                elif name == "cancel_shutdown":
                    self._power("cancel", 0)
                elif name == "lock":
                    self._power("lock", 0)
            except Exception:
                import traceback

                log("按钮动作失败：\n" + traceback.format_exc())

        return run

    def _power(self, action, delay):
        try:
            import chub_tasks as t

            if action == "cancel":
                t.cancel_shutdown()
            elif action == "lock":
                t.do_lock()
            elif action == "reboot":
                t.do_reboot(max(0, int(delay)))
            else:
                t.do_shutdown(max(0, int(delay)))
        except Exception:
            import traceback

            log("电源操作失败：\n" + traceback.format_exc())

    def _plain_container(self):
        """关于 / 帮助 / 个性化 这三个页面下面只有一个区块，
        就别再套一层框框了 —— 直接平铺在内容区里。"""
        s = self.scale
        holder = tk.Frame(self.grid, bg=_hex(self.pal["bg"]))
        holder._base_bg = "bg"
        holder.grid(row=0, column=0, sticky="ew",
                    padx=int(10 * s), pady=int(8 * s))
        self._ctl_widgets.append(holder)
        return holder

    # ------------------------------------------------------------ 个性化
    def _render_personal(self):
        """个性化拆成三个子选项卡：颜色 / 缩放 / 其它"""
        s = self.scale
        pal = self.pal
        body = self._plain_container()

        self.v_hue = tk.DoubleVar(value=float(CFG.get("shell.hue", 205.0)))
        self.v_depth = tk.DoubleVar(value=float(CFG.get("shell.depth", 0.0)))
        self.v_sat = tk.DoubleVar(value=float(CFG.get("shell.sat", 0.0)))
        self.v_radius = tk.DoubleVar(value=float(CFG.get("shell.radius", 18.0)))
        self.v_style = tk.StringVar(value=str(CFG.get("shell.style", "auto")))
        self.v_backdrop = tk.StringVar(value=str(CFG.get("shell.backdrop", "mica")))
        self.v_scale = tk.DoubleVar(value=float(CFG.get("shell.ui_scale", 0.0)))
        self.v_page_bg = tk.StringVar(value=str(CFG.get("shell.page_bg", "") or ""))
        self.v_page_fg = tk.StringVar(value=str(CFG.get("shell.page_fg", "") or ""))

        self._section_head(body, "个性化",
                           {"颜色": "强调色、深浅、饱和度",
                            "缩放": "界面缩放，大屏友好",
                            "其它": "明暗、背景材质、自定义背景色"}.get(self.tab, ""))

        def head(text, sub=""):
            f = tk.Frame(body, bg=_hex(pal["bg"]))
            f._base_bg = "bg"
            f.pack(fill="x", padx=int(12 * s), pady=(int(8 * s), int(4 * s)))
            tk.Label(f, text=text, bg=_hex(pal["bg"]), fg=_hex(pal["text"]),
                     font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
            if sub:
                tk.Label(f, text=sub, bg=_hex(pal["bg"]), fg=_hex(pal["sub"]),
                         font=("Microsoft YaHei UI", 8)).pack(side="right")
            self._ctl_widgets.append(f)
            return f

        def slider(label, var, lo, hi, hint="", step=1, cmd=None):
            f = tk.Frame(body, bg=_hex(pal["bg"]))
            f._base_bg = "bg"
            f.pack(fill="x", padx=int(12 * s), pady=int(3 * s))
            tk.Label(f, text=label, width=10, anchor="w", bg=_hex(pal["bg"]),
                     fg=_hex(pal["text"]),
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            tk.Scale(f, from_=lo, to=hi, orient="horizontal", variable=var,
                     length=int(260 * s), resolution=step, showvalue=True,
                     command=cmd or (lambda *_: self.on_theme_change())).pack(
                side="left")
            if hint:
                tk.Label(f, text=hint, fg=_hex(pal["sub"]), bg=_hex(pal["bg"]),
                         font=("Microsoft YaHei UI", 8)).pack(side="left")
            self._ctl_widgets.append(f)
            return f

        def color_row(label, var, hint=""):
            f = tk.Frame(body, bg=_hex(pal["bg"]))
            f._base_bg = "bg"
            f.pack(fill="x", padx=int(12 * s), pady=int(3 * s))
            tk.Label(f, text=label, width=10, anchor="w", bg=_hex(pal["bg"]),
                     fg=_hex(pal["text"]),
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            v = var
            mk_entry(f, v, width=14, palette=pal, scale=s,
                     fill=True)._border.pack(side="left", fill="x", expand=True,
                                             padx=(int(8 * s), 0))
            b = PillButton(f, text="预览", w=int(58 * s), h=int(24 * s),
                           palette=pal, command=lambda: self.on_theme_change())
            b.configure(bg=_hex(pal["bg"]))
            b.pack(side="left", padx=int(5 * s))
            self._ctl_widgets.append(b)
            if hint:
                tk.Label(f, text=hint, bg=_hex(pal["bg"]), fg=_hex(pal["sub"]),
                         font=("Microsoft YaHei UI", 8)).pack(side="left",
                                                              padx=int(6 * s))
            self._ctl_widgets.append(f)
            return f

        # ================================ 颜色 ================================
        if self.tab == "颜色":
            head("强调色", "改的是按钮、选项卡、复选框")
            slider("色相", self.v_hue, 188, 260, "← 青 蓝 紫 →")
            slider("深浅", self.v_depth, -60, 60, "深 ←→ 浅")
            slider("饱和度", self.v_sat, -40, 40, "灰 ←→ 艳")
            slider("卡片圆角", self.v_radius, 0, 32, "0 = 直角")

            pf = tk.Frame(body, bg=_hex(pal["bg"]))
            pf._base_bg = "bg"
            pf.pack(fill="x", padx=int(12 * s), pady=int(6 * s))
            tk.Label(pf, text="预设", width=10, anchor="w", bg=_hex(pal["bg"]),
                     fg=_hex(pal["text"]),
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            for name in PRESETS:
                b = PillButton(pf, text=name, w=int(80 * s), h=int(28 * s),
                               palette=pal, command=lambda n=name: self.preset(n))
                b.configure(bg=_hex(pal["bg"]))
                b.pack(side="left", padx=3)
                self._ctl_widgets.append(b)

            self.prev_c = tk.Canvas(body, height=int(54 * s),
                                    highlightthickness=0, bd=0,
                                    bg=_hex(pal["bg"]))
            self.prev_c._base_bg = "bg"
            self.prev_c.pack(fill="x", padx=int(12 * s), pady=int(8 * s))
            self._draw_preview()

        # ================================ 缩放 ================================
        elif self.tab == "缩放":
            head("界面缩放", "0 = 自动")

            scf = tk.Frame(body, bg=_hex(pal["bg"]))
            scf._base_bg = "bg"
            scf.pack(fill="x", padx=int(12 * s), pady=int(3 * s))
            tk.Label(scf, text="缩放系数", width=10, anchor="w",
                     bg=_hex(pal["bg"]), fg=_hex(pal["text"]),
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            sc = tk.Scale(scf, from_=0.0, to=3.0, orient="horizontal",
                          variable=self.v_scale, length=int(240 * s),
                          resolution=0.1, showvalue=True,
                          command=lambda *_: self._update_scale_hint())
            sc.pack(side="left")
            self.scale_hint = tk.Label(scf, text="", bg=_hex(pal["bg"]),
                                       fg=_hex(pal["sub"]),
                                       font=("Microsoft YaHei UI", 8))
            self.scale_hint.pack(side="left", padx=int(6 * s))
            self._ctl_widgets.append(scf)
            self._update_scale_hint()

            af = tk.Frame(body, bg=_hex(pal["bg"]))
            af._base_bg = "bg"
            af.pack(fill="x", padx=int(12 * s), pady=int(8 * s))
            for txt, cmd, kd in (("应用缩放", self.apply_scale, "accent"),
                                 ("缩放自动", self.reset_scale, "normal")):
                b = PillButton(af, text=txt, w=int(96 * s), h=int(30 * s),
                               kind=kd, palette=pal, command=cmd)
                b.configure(bg=_hex(pal["bg"]))
                b.pack(side="left", padx=4)
                self._ctl_widgets.append(b)

            for ln in ("改缩放会重建界面（约 0.3 秒），窗口尺寸也跟着变。",
                       "自动算法：1920→1.0×  2560→1.39×  3440→1.96×  4K→2.22×"):
                tk.Label(body, text=ln, bg=_hex(pal["bg"]), fg=_hex(pal["sub"]),
                         justify="left", anchor="w", wraplength=int(420 * s),
                         font=("Microsoft YaHei UI", 8)).pack(
                    anchor="w", padx=int(13 * s), pady=int(2 * s))

        # ================================ 其它 ================================
        else:
            head("明暗主题")
            stf = tk.Frame(body, bg=_hex(pal["bg"]))
            stf._base_bg = "bg"
            stf.pack(fill="x", padx=int(12 * s), pady=int(4 * s))
            tk.Label(stf, text="明暗", width=10, anchor="w",
                     bg=_hex(pal["bg"]), fg=_hex(pal["text"]),
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            for label, val in (("跟随系统", "auto"), ("浅色", "light"),
                               ("深色", "dark")):
                tk.Radiobutton(stf, text=label, variable=self.v_style, value=val,
                               bg=_hex(pal["bg"]), fg=_hex(pal["text"]),
                               selectcolor=_hex(pal["card_hi"]),
                               activebackground=_hex(pal["card"]),
                               font=("Microsoft YaHei UI", 9),
                               command=self.on_theme_change).pack(
                    side="left", padx=int(6 * s))
            self._ctl_widgets.append(stf)

            head("背景材质")
            bdf = tk.Frame(body, bg=_hex(pal["bg"]))
            bdf._base_bg = "bg"
            bdf.pack(fill="x", padx=int(12 * s), pady=int(4 * s))
            tk.Label(bdf, text="材质", width=10, anchor="w",
                     bg=_hex(pal["bg"]), fg=_hex(pal["text"]),
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            box = ttk.Combobox(bdf, textvariable=self.v_backdrop,
                               state="readonly", width=14,
                               style=self._combo_style(),
                               values=["mica", "tabbed", "acrylic", "none",
                                       "auto"])
            box.pack(side="left")
            box.bind("<<ComboboxSelected>>", lambda e: self.on_theme_change())
            tk.Label(bdf, text="mica=云母（任务管理器用的），Win11 22H2+ 有效",
                     bg=_hex(pal["bg"]), fg=_hex(pal["sub"]),
                     font=("Microsoft YaHei UI", 8)).pack(side="left",
                                                          padx=int(8 * s))
            self._ctl_widgets.append(bdf)

            head("自定义颜色", "留空 = 跟随明暗主题")
            color_row("页面背景", self.v_page_bg, "如 #101014")
            color_row("页面文字", self.v_page_fg, "如 #FFFFFF")

            cf = tk.Frame(body, bg=_hex(pal["bg"]))
            cf._base_bg = "bg"
            cf.pack(fill="x", padx=int(12 * s), pady=int(6 * s))
            for txt, cmd in (("常用深色", lambda: self._pick_bg("#101014", "#FFFFFF")),
                             ("常用浅色", lambda: self._pick_bg("#F5F7FA", "#202228")),
                             ("清空(跟随主题)", lambda: self._pick_bg("", ""))):
                b = PillButton(cf, text=txt, w=int(104 * s), h=int(28 * s),
                               palette=pal, command=cmd)
                b.configure(bg=_hex(pal["bg"]))
                b.pack(side="left", padx=3)
                self._ctl_widgets.append(b)

        # ---- 底部按钮 ----
        acts = tk.Frame(body, bg=_hex(pal["bg"]))
        acts._base_bg = "bg"
        acts.pack(fill="x", padx=int(12 * s), pady=int(10 * s))
        for txt, cmd, kd in (("应用并保存", self.apply_theme, "accent"),
                             ("恢复默认", self.reset_theme, "normal")):
            b = PillButton(acts, text=txt, w=int(110 * s), h=int(30 * s),
                           kind=kd, palette=pal, command=cmd)
            b.configure(bg=_hex(pal["bg"]))
            b.pack(side="left", padx=4)
            self._ctl_widgets.append(b)

        tk.Label(body,
                 text="窗口边框、标题栏、最小化/关闭按钮由 Windows 绘制（DWM），"
                      "这里改的只是内容区。",
                 bg=_hex(pal["bg"]), fg=_hex(pal["sub"]), justify="left",
                 anchor="w", wraplength=int(420 * s),
                 font=("Microsoft YaHei UI", 8)).pack(
            anchor="w", padx=int(13 * s), pady=int(4 * s))

    def _section_head(self, body, title, sub=""):
        s = self.scale
        pal = self.pal
        f = tk.Frame(body, bg=_hex(pal["bg"]))
        f._base_bg = "bg"
        f.pack(fill="x", padx=int(12 * s), pady=(int(10 * s), int(4 * s)))
        tk.Label(f, text=title, bg=_hex(pal["bg"]), fg=_hex(pal["text"]),
                 font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        if sub:
            tk.Label(f, text=sub, bg=_hex(pal["bg"]), fg=_hex(pal["sub"]),
                     font=("Microsoft YaHei UI", 8)).pack(side="right")
        self._ctl_widgets.append(f)
        return f

    def _pick_bg(self, bg, fg):
        """一键设置页面配色"""
        self.v_page_bg.set(bg)
        self.v_page_fg.set(fg)
        self.on_theme_change()

    def _draw_preview(self):
        c = getattr(self, "prev_c", None)
        if c is None:
            return
        pal = self.pal
        s = self.scale
        c.delete("all")
        c.configure(bg=_hex(pal["bg"]))
        w = c.winfo_width() or 520
        round_rect(c, 4, 6, min(w - 8, 560), int(46 * s),
                   max(0, float(self.v_radius.get()) * s * 0.7),
                   fill=_hex(pal["accent"]), outline="")
        c.create_text(20, int(26 * s), anchor="w",
                      text="预览：按钮、选项卡、卡片都会用这个颜色",
                      fill=_hex(pal["on_accent"]),
                      font=("Microsoft YaHei UI", 10))

    def on_theme_change(self):
        """拖滑块会连续触发，合并到 60ms 后再整体重绘一次，避免拖动卡顿"""
        self._write_theme()
        try:
            self._draw_preview()
        except Exception:
            pass
        try:
            if self._theme_job:
                self.root.after_cancel(self._theme_job)
        except Exception:
            pass
        try:
            self._theme_job = self.root.after(60, self._do_refresh)
        except Exception:
            self._do_refresh()

    def _do_refresh(self):
        self._theme_job = ""
        self.refresh_palette()

    def _update_scale_hint(self):
        v = float(getattr(self, "v_scale", tk.DoubleVar()).get() or 0.0)
        try:
            if v <= 0:
                auto = chw_mod.ui_scale(self.root, self._dpi_scale())
                self.scale_hint.configure(text="自动 → %.2f×" % auto)
            else:
                self.scale_hint.configure(text="手动 %.1f×" % v)
        except Exception:
            pass

    def _dpi_scale(self):
        try:
            return chw_mod.ensure_dpi_aware()
        except Exception:
            return 1.0

    def reset_scale(self):
        self.v_scale.set(0.0)
        self._update_scale_hint()
        self.apply_scale()

    def apply_scale(self):
        """改缩放：重算系数 → 重设 tk scaling → 按新系数重建界面。

        不销毁窗口（避免嵌套 mainloop），只把四大块（菜单栏 / 选项卡栏 /
        主区域 / 状态栏）拆掉重建，间距、字号、窗口尺寸就都按新系数来了。
        """
        CFG.set("shell.ui_scale", float(self.v_scale.get()))
        CFG.save()
        try:
            self.scale = chw_mod.ui_scale(self.root, self._dpi_scale())
            chw_mod.apply_tk_scaling(self.root, self.scale)
        except Exception:
            pass
        # 窗口尺寸跟着变
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            w = int(min(1060 * self.scale, sw * 0.94))
            h = int(min(720 * self.scale, sh * 0.90))
            self.root.geometry("%dx%d+%d+%d" % (
                w, h, max(0, (sw - w) // 2), max(0, int((sh - h) * 0.42))))
        except Exception:
            pass
        # 拆掉四大块重建
        try:
            self._unbind_wheel()
            for attr in ("menubar", "tabbar", "main_wrap", "status_bar"):
                w = getattr(self, attr, None)
                if w is not None:
                    try:
                        w.destroy()
                    except Exception:
                        pass
                setattr(self, attr, None)
            self._build_menubar(self.root)
            self._build_tabbar(self.root)
            self._build_main(self.root)
            self._build_status(self.root)
            self.pal = build_palette(detect_dark())
            self.render_main()
            self.root.update_idletasks()
            self.render_main()
            log("界面缩放已应用：%.2f×" % self.scale)
            self.hint.set("界面缩放 %.2f×（已保存）" % self.scale)
        except Exception:
            import traceback

            log("重建界面失败：\n" + traceback.format_exc())

    def _write_theme(self):
        if hasattr(self, "v_scale"):
            CFG.set("shell.ui_scale", float(self.v_scale.get()))
        if hasattr(self, "v_hue"):
            CFG.set("shell.hue", float(self.v_hue.get()))
            CFG.set("shell.depth", float(self.v_depth.get()))
            CFG.set("shell.sat", float(self.v_sat.get()))
            CFG.set("shell.radius", float(self.v_radius.get()))
            CFG.set("shell.style", self.v_style.get())
        if hasattr(self, "v_backdrop"):
            CFG.set("shell.backdrop", self.v_backdrop.get())
        if hasattr(self, "v_page_bg"):
            CFG.set("shell.page_bg", str(self.v_page_bg.get()).strip())
            CFG.set("shell.page_fg", str(self.v_page_fg.get()).strip())

    def refresh_palette(self):
        """换色：整套内容区跟着变（只重画已有部件，不重建）"""
        self.pal = build_palette(detect_dark())
        pal = self.pal
        try:
            self.root.configure(bg=_hex(pal["bg"]))
            self.menubar.configure(bg=_hex(pal["bg"]))
            self.tabbar.configure(bg=_hex(pal["bg"]))
            self.grid.configure(bg=_hex(pal["bg"]))
            self.main_wrap.configure(bg=_hex(pal["bg"]))
            self.canvas.configure(bg=_hex(pal["bg"]))
            self.status_bar.configure(bg=_hex(pal["bg"]))
        except Exception:
            pass
        # DWM 标题栏也跟着变深色/浅色
        try:
            apply_dwm(self.root, pal["dark"], CFG.get("shell.backdrop", "mica"))
        except Exception:
            pass
        for w in list(self._ctl_widgets) + list(self._cards):
            try:
                if hasattr(w, "set_palette"):
                    w.set_palette(pal)
                else:
                    w.configure(bg=_hex(pal["bg"]))
            except Exception:
                pass
        self._paint_menubar()
        self._paint_tabbar()
        try:
            self._draw_preview()
        except Exception:
            pass

    def preset(self, name):
        h, d, sa = PRESETS.get(name, (205, 0, 0))
        self.v_hue.set(float(h))
        self.v_depth.set(float(d))
        self.v_sat.set(float(sa))
        self.on_theme_change()

    def apply_theme(self):
        self._write_theme()
        self.refresh_palette()
        CFG.save()
        log("个性化已保存：色相 %.0f° 卡片圆角 %.0f 风格 %s 材质 %s"
            % (self.v_hue.get(), self.v_radius.get(), self.v_style.get(),
               CFG.get("shell.backdrop", "mica")))

    def reset_theme(self):
        for k, v in core.SHELL_THEME.items():
            CFG.set("shell." + k, v)
        CFG.set("shell.backdrop", "mica")
        CFG.set("shell.page_bg", "")
        CFG.set("shell.page_fg", "")
        self.v_hue.set(core.SHELL_THEME["hue"])
        self.v_depth.set(core.SHELL_THEME["depth"])
        self.v_sat.set(core.SHELL_THEME["sat"])
        self.v_radius.set(core.SHELL_THEME["radius"])
        self.v_style.set("auto")
        self.v_backdrop.set("mica")
        if hasattr(self, "v_page_bg"):
            self.v_page_bg.set("")
            self.v_page_fg.set("")
        self.on_theme_change()

    # ------------------------------------------------------------ 帮助
    def _render_help(self):
        """帮助拆成四个子选项卡：怎么用 / 源码 / 日志 / 关于 ClassHub"""
        if self.tab == "源码":
            self._render_source()
        elif self.tab == "日志":
            self._render_log()
        elif self.tab == "关于 ClassHub":
            self._render_about()
        else:
            self._render_usage()

    # ------------------------------------------------------------ 怎么用
    def _render_usage(self):
        s = self.scale
        pal = self.pal
        self.help_idx = getattr(self, "help_idx", 0)
        body = self._plain_container()
        self._section_head(body, "怎么用", "共 %d 页" % len(HELP_PAGES))

        head = tk.Frame(body, bg=_hex(pal["bg"]))
        head._base_bg = "bg"
        head.pack(fill="x", padx=int(12 * s), pady=(int(10 * s), int(6 * s)))
        self.help_var = tk.StringVar()
        titles = [t for t, _ in HELP_PAGES]
        self.help_var.set(titles[self.help_idx])
        box = ttk.Combobox(head, textvariable=self.help_var, state="readonly",
                           values=titles, width=28, style=self._combo_style())
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", self._help_jump)
        self.help_lbl = tk.Label(head, text="", bg=_hex(pal["bg"]),
                                 fg=_hex(pal["sub"]),
                                 font=("Microsoft YaHei UI", 9))
        self.help_lbl.pack(side="right")
        self._ctl_widgets.append(head)

        self.help_c = tk.Canvas(body, height=int(300 * s), highlightthickness=0,
                                bd=0, bg=_hex(pal["bg"]))
        self.help_c._base_bg = "bg"
        self.help_c.pack(fill="x", padx=int(12 * s))

        foot = tk.Frame(body, bg=_hex(pal["bg"]))
        foot._base_bg = "bg"
        foot.pack(fill="x", padx=int(12 * s), pady=int(8 * s))
        self.help_prev = PillButton(foot, text="← 上一页", w=int(96 * s),
                                    h=int(30 * s), palette=pal,
                                    command=lambda: self.help_goto(-1))
        self.help_next = PillButton(foot, text="下一页 →", w=int(96 * s),
                                    h=int(30 * s), kind="accent", palette=pal,
                                    command=lambda: self.help_goto(1))
        for b in (self.help_prev, self.help_next):
            b.configure(bg=_hex(pal["bg"]))
            b._base_bg = "bg"
            b.pack(side="left", padx=4)
        self._ctl_widgets.extend([self.help_prev, self.help_next])
        self._help_render()

    def _help_jump(self, _=None):
        titles = [t for t, _ in HELP_PAGES]
        try:
            self.help_idx = titles.index(self.help_var.get())
        except Exception:
            return
        self._help_render()

    def help_goto(self, delta):
        self.help_idx = max(0, min(len(HELP_PAGES) - 1,
                                   getattr(self, "help_idx", 0) + delta))
        self._help_render()

    def _help_render(self):
        c = self.help_c
        pal = self.pal
        s = self.scale
        c.delete("all")
        c.configure(bg=_hex(pal["bg"]))
        title, lines = HELP_PAGES[self.help_idx]
        c.create_text(2, int(8 * s), anchor="nw", text=title,
                      fill=_hex(pal["accent"]),
                      font=("Microsoft YaHei UI", 14, "bold"))
        y = int(40 * s)
        for ln in lines:
            if ln == "":
                y += int(8 * s)
                continue
            if ln.startswith("    "):
                c.create_text(int(22 * s), y, anchor="nw", text=ln.strip(),
                              fill=_hex(_mix(pal["text"], pal["accent"], 0.35)),
                              font=("Consolas", 10))
            else:
                c.create_text(2, y, anchor="nw", text=ln, fill=_hex(pal["text"]),
                              font=("Microsoft YaHei UI", 10))
            y += int(23 * s)
        try:
            c.configure(height=max(int(300 * s), y + int(10 * s)))
        except Exception:
            pass
        titles = [t for t, _ in HELP_PAGES]
        self.help_var.set(titles[self.help_idx])
        self.help_lbl.configure(text="%d / %d" % (self.help_idx + 1, len(HELP_PAGES)))
        self.help_prev.set_enabled(self.help_idx > 0)
        self.help_next.set_enabled(self.help_idx < len(HELP_PAGES) - 1)

    # ------------------------------------------------------------ 源码
    def _render_source(self):
        """源码浏览：左边文件列表，右边看代码，带行号"""
        s = self.scale
        pal = self.pal
        body = self._plain_container()
        root = self._source_root()
        self._section_head(body, "源码",
                           ("目录：" + root) if root else "（没找到源码）")

        files = self._source_files()
        if not files:
            for ln in ("没找到源码文件。",
                       "打包成 EXE 后源码不在程序边上 —— 请用 ",
                       "3_打包成EXE.bat 重新打包，它会自动把 .py 复制到 ",
                       "dist 目录下的「源码」文件夹里。",
                       "",
                       "当前程序目录：" + str(core.BASE)):
                tk.Label(body, text=ln, bg=_hex(pal["bg"]),
                         fg=_hex(pal["sub"]), justify="left", anchor="w",
                         wraplength=int(460 * s),
                         font=("Microsoft YaHei UI", 9)).pack(
                    anchor="w", padx=int(13 * s), pady=int(1 * s))
            b = PillButton(body, text="打开程序文件夹", w=int(130 * s),
                           h=int(30 * s), palette=pal,
                           command=lambda: core.open_in_explorer(core.BASE))
            b.configure(bg=_hex(pal["bg"]))
            b.pack(anchor="w", padx=int(13 * s), pady=int(8 * s))
            self._ctl_widgets.append(b)
            return

        top = tk.Frame(body, bg=_hex(pal["bg"]))
        top._base_bg = "bg"
        top.pack(fill="x", padx=int(12 * s), pady=int(4 * s))
        self.src_var = tk.StringVar(value=files[0])
        box = ttk.Combobox(top, textvariable=self.src_var, state="readonly",
                           values=files, width=22, style=self._combo_style())
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", lambda e: self._src_show())
        b_open = PillButton(top, text="用记事本打开", w=int(112 * s),
                            h=int(26 * s), palette=pal,
                            command=self._src_open)
        b_open.configure(bg=_hex(pal["bg"]))
        b_open.pack(side="left", padx=int(6 * s))
        b_dir = PillButton(top, text="打开文件夹", w=int(96 * s), h=int(26 * s),
                           palette=pal, command=lambda: core.open_in_explorer(
                               root or core.BASE))
        b_dir.configure(bg=_hex(pal["bg"]))
        b_dir.pack(side="left", padx=3)
        self._ctl_widgets.extend([top, b_open, b_dir])

        boxf = tk.Frame(body, bg=_hex(pal["line"]))
        boxf.pack(fill="both", expand=True, padx=int(12 * s), pady=int(6 * s))
        self.src_txt = tk.Text(boxf, wrap="none", height=22,
                               bg=_hex(pal["card_hi"]), fg=_hex(pal["text"]),
                               insertbackground=_hex(pal["text"]),
                               selectbackground=_hex(pal["accent"]),
                               selectforeground=_hex(pal["on_accent"]),
                               relief="flat", bd=0, highlightthickness=0,
                               font=("Consolas", 10))
        self.src_txt.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        sbv = ttk.Scrollbar(boxf, orient="vertical",
                            command=self.src_txt.yview,
                            style=style_scrollbar(pal))
        sbv.pack(side="right", fill="y")
        self.src_txt.configure(yscrollcommand=sbv.set)
        # 只读：只是看，不在这儿改
        self.src_txt.configure(state="disabled")
        self._src_show()

        tk.Label(body,
                 text="提示：这里只能看不能改。要改请用记事本打开，"
                      "改完重启程序生效。",
                 bg=_hex(pal["bg"]), fg=_hex(pal["sub"]), justify="left",
                 anchor="w", wraplength=int(420 * s),
                 font=("Microsoft YaHei UI", 8)).pack(
            anchor="w", padx=int(13 * s), pady=int(4 * s))

    # 源码可能在这些地方找：
    #   源码运行时  ->  BASE（就是 .py 所在目录）
    #   打包成 EXE  ->  BASE\源码\ 或 BASE\internal\（打包脚本复制过去的）
    SRC_SUBDIRS = ("源码", "internal", "src", "source")

    def _source_root(self):
        """找到真正放源码的目录，找不到返回 None"""
        for d in (core.BASE,) + tuple(
                os.path.join(core.BASE, sub) for sub in self.SRC_SUBDIRS):
            try:
                if os.path.isdir(d) and any(
                        f.endswith(".py") and not f.startswith("_")
                        for f in os.listdir(d)):
                    return d
            except Exception:
                continue
        return None

    def _source_files(self):
        """列出源码目录里的 .py 文件。跳过下划线开头的（测试脚本之类）。"""
        root = self._source_root()
        if not root:
            return []
        try:
            names = [f for f in os.listdir(root)
                     if f.endswith(".py") and not f.startswith("_")
                     and os.path.isfile(os.path.join(root, f))]
            return sorted(names)
        except Exception:
            return []

    def _src_path(self):
        """当前选中文件的完整路径"""
        root = self._source_root() or core.BASE
        return os.path.join(root, str(self.src_var.get()))

    def _src_show(self):
        try:
            path = self._src_path()
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except Exception as e:
            raw = "（读取失败：%s）" % e
        try:
            self.src_txt.configure(state="normal")
            self.src_txt.delete("1.0", "end")
            for i, line in enumerate(raw.split("\n"), 1):
                self.src_txt.insert("end", "%5d  %s\n" % (i, line))
            self.src_txt.configure(state="disabled")
            self.src_txt.yview_moveto(0)
        except Exception:
            pass

    def _src_open(self):
        try:
            path = self._src_path()
            import subprocess

            subprocess.Popen(["notepad.exe", path])
        except Exception:
            try:
                core.open_in_explorer(core.BASE)
            except Exception:
                pass

    # ------------------------------------------------------------ 日志
    def _render_log(self):
        s = self.scale
        pal = self.pal
        body = self._plain_container()
        self._section_head(body, "日志", "排查问题第一步就是看它")

        tail = ""
        try:
            with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            tail = "".join(lines[-200:])
        except Exception as e:
            tail = "（读不到日志：%s）" % e

        boxf = tk.Frame(body, bg=_hex(pal["line"]))
        boxf.pack(fill="both", expand=True, padx=int(12 * s), pady=int(6 * s))
        txt = tk.Text(boxf, wrap="none", height=18,
                      bg=_hex(pal["card_hi"]), fg=_hex(pal["text"]),
                      insertbackground=_hex(pal["text"]),
                      relief="flat", bd=0, highlightthickness=0,
                      font=("Consolas", 9))
        txt.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        sbv = ttk.Scrollbar(boxf, orient="vertical", command=txt.yview,
                            style=style_scrollbar(pal))
        sbv.pack(side="right", fill="y")
        txt.configure(yscrollcommand=sbv.set)
        txt.insert("1.0", tail)
        txt.configure(state="disabled")
        try:
            txt.yview_moveto(1)
        except Exception:
            pass

        for title, desc, opts in LOG_CARDS:
            self._fill_into(body, opts, base_key="bg")

    # ------------------------------------------------------------ 关于
    def _render_about(self):
        s = self.scale
        pal = self.pal
        body = self._plain_container()

        head = tk.Canvas(body, height=int(72 * s), highlightthickness=0, bd=0,
                         bg=_hex(pal["bg"]))
        head.pack(fill="x", padx=int(12 * s), pady=(int(6 * s), int(4 * s)))
        head.bind("<Configure>", lambda e: self._about_head(head))
        self._about_head_c = head
        self.root.after_idle(lambda: self._about_head(head))

        rows = [("版本", "%s（build %s）" % (APP_VERSION,
                                            APP_RELEASE_DATE.replace("-", ""))),
                ("发布日期", APP_RELEASE_DATE),
                ("作者", APP_AUTHOR),
                ("程序标识", APP_ID),
                ("贡献者", "、".join(APP_CONTRIBUTORS))]
        for k, v in rows:
            row = tk.Frame(body, bg=_hex(pal["bg"]))
            row._base_bg = "bg"
            row.pack(fill="x", padx=int(12 * s), pady=int(2 * s))
            tk.Label(row, text=k, width=10, anchor="w", bg=_hex(pal["bg"]),
                     fg=_hex(pal["sub"]),
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            tk.Label(row, text=v, anchor="w", bg=_hex(pal["bg"]),
                     fg=_hex(pal["text"]), wraplength=int(400 * s),
                     justify="left",
                     font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
            self._ctl_widgets.append(row)

        tk.Frame(body, height=1, bg=_hex(pal["line"])).pack(
            fill="x", padx=int(12 * s), pady=int(8 * s))
        tk.Label(body,
                 text="Copyright (c) %s  %s.\n保留所有权利。\n\n"
                      "本程序只在本机运行，不联网、不上传、不外发任何数据。\n"
                      "源码可直接查阅（见「源码」子页），功能默认全部关闭，"
                      "由使用者自行决定是否开启。"
                      % (APP_RELEASE_DATE[:4], APP_AUTHOR),
                 bg=_hex(pal["bg"]), fg=_hex(pal["sub"]), justify="left",
                 anchor="w", font=("Microsoft YaHei UI", 9)).pack(
            anchor="w", padx=int(12 * s), pady=int(4 * s))
        self._ctl_widgets.append(body)

    def _about_head(self, c):
        pal = self.pal
        s = self.scale
        c.delete("all")
        w = c.winfo_width() or 520
        round_rect(c, 0, 0, w, int(66 * s), 12 * s, fill=_hex(pal["accent"]),
                   outline="")
        c.create_text(int(16 * s), int(26 * s), anchor="w", text=APP_NAME_CN,
                      fill=_hex(pal["on_accent"]),
                      font=("Microsoft YaHei UI", 18, "bold"))
        c.create_text(int(16 * s), int(50 * s), anchor="w",
                      text="ClassHub · 课堂助手套件",
                      fill=_hex(_mix(pal["on_accent"], pal["accent"], 0.25)),
                      font=("Microsoft YaHei UI", 9))

    # ------------------------------------------------------------ 底部状态栏
    def _build_status(self, root):
        pal = self.pal
        s = self.scale
        bar = tk.Frame(root, bg=_hex(pal["bg"]), height=int(46 * s))
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self.status_bar = bar
        self.hint = tk.StringVar(value="所有开关默认关闭。改完点『应用』保存并生效。")
        tk.Label(bar, textvariable=self.hint, bg=_hex(pal["bg"]),
                 fg=_hex(pal["sub"]),
                 font=("Microsoft YaHei UI", 9)).pack(side="left",
                                                               padx=int(14 * s))
        # 退出设置并保存：保存后关掉窗口（程序还在托盘里跑）
        b_exit = PillButton(bar, text="退出设置并保存", w=int(130 * s),
                            h=int(30 * s), palette=pal, command=self.save_and_close)
        b_exit.configure(bg=_hex(pal["bg"]))
        b_exit.pack(side="right", padx=int(6 * s))
        # 应用：保存但不关窗口
        b_apply = PillButton(bar, text="应用", w=int(80 * s), h=int(30 * s),
                             kind="accent", palette=pal, command=self.save)
        b_apply.configure(bg=_hex(pal["bg"]))
        b_apply.pack(side="right", padx=int(6 * s))
        self._ctl_widgets.extend([b_exit, b_apply])

    # ------------------------------------------------------------ 保存
    def save(self):
        """把界面上的改动写回 config.json 并让服务生效（不关窗口）"""
        for key, kind, var in list(self.bindings):
            try:
                raw = var.get()
                if kind == "bool":
                    CFG.set(key, bool(raw))
                elif kind in ("int", "float"):
                    try:
                        CFG.set(key, int(float(str(raw))) if kind == "int"
                                else float(str(raw)))
                    except Exception:
                        pass
                else:
                    CFG.set(key, str(raw))
            except Exception:
                pass
        for lname, ed in self.editors.items():
            path = {"launch": "launch.items", "watch": "watch.items",
                    "assoc": "assoc.items", "tasks": "tasks.items"}[lname]
            CFG.set(path, [it.to_dict() for it in ed.items
                           if hasattr(it, "to_dict")])
        if self.menu == "个性化":
            self._write_theme()
        CFG.save()
        self.hint.set("已应用并保存到 config.json")
        log("设置已应用并保存")
        try:
            fn = getattr(self.app, "reload_services", None)
            if callable(fn):
                fn()
        except Exception:
            pass

    def save_and_close(self):
        """保存后关掉设置窗口。程序本身继续在托盘运行。"""
        try:
            self.save()
        except Exception:
            pass
        self.close()

    def close(self):
        try:
            self._unbind_wheel()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


_SHELL_ROOT = None
_SHELL_WIN = None


def focus_shell():
    if _SHELL_ROOT is None:
        return False
    try:
        _SHELL_ROOT.after(0, lambda: (
            _SHELL_ROOT.deiconify(), _SHELL_ROOT.lift(),
            _SHELL_ROOT.attributes("-topmost", True)))
        return True
    except Exception:
        return False


def open_shell(app):
    """托盘菜单『设置…』入口。已经开着就激活，不开第二个。
    加载失败自动退回原来的文字版窗口。"""
    if focus_shell():
        return
    try:
        ShellWindow(app)
    except Exception:
        import traceback

        log("设置中心异常，退回文字版：\n" + traceback.format_exc())
        try:
            import chub_ui

            chub_ui.open_settings(app)
        except Exception:
            pass
