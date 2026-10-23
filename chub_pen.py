# -*- coding: utf-8 -*-
"""
================================================================================
 ClassHub · chub_pen —— 云笔助手面板（自绘窗口）
================================================================================
把「中育云笔助手」的连接界面整个画出来：本机 IP、超大连接码、两个功能项、
右下角二维码、底部版本号。窗口自己画（无系统边框），任务栏上有自己的图标。

连接码来自 Log.txt（复用 chub_zy 的解析：关键词行优先，否则取最后四个数字）。
没检测到中育课堂助手在跑时，会先把它拉起来，等一会儿再读日志。

配色是【保感知亮度】模型：沿拟合出的渐变形状，把两端的亮度对齐参考图
（亮端 L=155 在中下部、暗端 L=101 在四周，即"上深下浅"），再用目标亮度反解
色相下的 S/V。这样拨色相不会让整个界面忽深忽浅。

默认关闭。勾选后托盘菜单可开面板。
"""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
import traceback

try:
    from PIL import Image, ImageDraw, ImageFont

    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

import chub_core as core
import chub_zy as zy_mod
from chub_core import CFG, log

APP_TITLE = "中育云笔助手"

# ---------------------------------------------------------------- 配置读写
def cfg(key, default=None):
    """面板配置统一放在 pen.* 下，默认全部关闭 / 中性值"""
    return CFG.get("pen." + key, default)


def local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        best = s.getsockname()[0]
        s.close()
        if best and not best.startswith("127."):
            return best
    except Exception:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return "127.0.0.1"


def zy_exe_path() -> str:
    return os.path.join(zy_mod.app_dir(), zy_mod.app_exe())


# ==============================================================================
THEME = {
    "hue": float(cfg("hue", 205.0)),           # 色相角：190=偏青，205=蓝，215=偏蓝紫
    # 两端的【目标感知亮度】(0-255)，从参考图回归而来，是最可靠的信息
    "center_L": 155.0,      # 亮端 = 渐变中心 = 画面中下部（"下浅"）
    "edge_L": 101.0,        # 暗端 = 四周边缘 = 画面上部（"上深"）
    "depth": float(cfg("depth", 0.0)),   # 整体深浅微调：-60 ~ +60，直接加到亮度上
    "sat": float(cfg("sat", 0.0)),       # 饱和度微调：-40 ~ +40
    # 饱和度基准（参考图实测，反解时作为上限）
    "center_s": 0.982,
    "edge_s": 0.966,

    "bg_center_at": (0.482, 0.635),   # 渐变中心（相对宽、高）
    "bg_radius": 2.31,                # 归一化距离 → 过渡进度
    "bg_power": 1.89,                 # 渐变曲线（>1：中心大片保持亮，外围才快速变暗）

    # 标题栏：实测在 y 0.064~0.126 这条带上（不在窗口最顶端，上面还有一条背景带）
    "title_top": 0.064,
    "title_bottom": 0.126,
    "title_bar": (13, 118, 196),      # 实测色相 205°，蓝色本来就是对的
    "title_text": (255, 255, 255),

    "text": (255, 255, 255),
    "sub_text": (214, 236, 252),      # 说明文字（偏蓝的浅色）
    "foot_text": (186, 220, 248),     # 底部版本号 / 设备串

    "feat_green": (50, 202, 170),     # 功能项圆标
    "feat_glyph": (255, 255, 255),

    "btn_hover_min": (63, 169, 220),
    "btn_hover_close": (224, 67, 67),
    "btn_glyph": (255, 255, 255),

    "status_text": (255, 224, 138),
    "qr_ink": (11, 58, 90),
}

def _rgb_of(hue_deg: float, s: float, v: float) -> tuple:
    import colorsys

    r, g, b = colorsys.hsv_to_rgb(max(0.0, min(1.0, hue_deg / 360.0)),
                                  max(0.0, min(1.0, s)),
                                  max(0.0, min(1.0, v)))
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def _lum(rgb) -> float:
    """感知亮度（Rec.709）。RGB 与 v 成正比，所以亮度也与 v 成正比。"""
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def solve_for_L(hue_deg: float, s_base: float, target_L: float,
                sat_k: float = 1.0) -> tuple:
    """在给定色相下，求感知亮度刚好等于 target_L 的颜色。

    优先保持饱和度、压明度；若明度拉满仍不够亮（蓝/紫在高饱和时就是这么暗），
    就逐步降饱和度来提亮 —— 这样换个色相不会让整个界面突然变深。
    """
    target_L = max(0.0, min(255.0, float(target_L)))
    s = max(0.05, min(1.0, s_base * sat_k))
    lmax = _lum(_rgb_of(hue_deg, s, 1.0))
    if lmax <= 0:
        return (0, 0, 0)
    if lmax < target_L:
        # 明度拉满还不够亮 → 降饱和度（往白里掺）。饱和度越低越亮，二分找临界值
        lo, hi = 0.06, s
        for _ in range(40):
            mid = (lo + hi) / 2.0
            if _lum(_rgb_of(hue_deg, mid, 1.0)) < target_L:
                hi = mid
            else:
                lo = mid
        s, v = lo, 1.0
    else:
        v = target_L / lmax          # 亮度与 v 线性，一步到位
    return _rgb_of(hue_deg, s, v)


def compute_bg_colors() -> tuple:
    """按当前 色相 / 深浅 / 饱和度 算出渐变两端 RGB（保感知亮度）。"""
    hue = float(THEME.get("hue", 205.0))
    depth = float(THEME.get("depth", 0.0))
    sat_k = 1.0 + float(THEME.get("sat", 0.0)) / 100.0
    c = solve_for_L(hue, THEME.get("center_s", 0.982),
                    THEME.get("center_L", 152.0) + depth, sat_k)
    e = solve_for_L(hue, THEME.get("edge_s", 0.966),
                    THEME.get("edge_L", 100.0) + depth, sat_k)
    return c, e


def apply_theme():
    """把算出来的颜色写回 THEME"""
    c, e = compute_bg_colors()
    THEME["bg_center"], THEME["bg_edge"] = c, e
    return c, e


def sync_theme_from_cfg():
    """设置窗口改了配色后，同步进 THEME 并立即生效"""
    THEME["hue"] = float(cfg("hue", 205.0))
    THEME["depth"] = float(cfg("depth", 0.0))
    THEME["sat"] = float(cfg("sat", 0.0))
    return apply_theme()


apply_theme()


# ==============================================================================
# 字体：按字形"实际墨迹高度"拟合
# ==============================================================================
_FONT_DIRS = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
              os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "Fonts"),
              "/usr/share/fonts", "/usr/local/share/fonts",
              os.path.expanduser("~/.fonts")]
_FONT_CACHE: dict = {}


def _glob_font(names) -> str:
    """在字体根目录里往下翻几层找（Linux 上没有统一的 Fonts 目录）"""
    for root in _FONT_DIRS:
        if not os.path.isdir(root):
            continue
        base_depth = root.count(os.sep)
        for dirpath, _dirs, files in os.walk(root):
            if dirpath.count(os.sep) - base_depth > 4:
                _dirs[:] = []
                continue
            for n in names:
                if n in files:
                    return os.path.join(dirpath, n)
    return ""


def find_font(names) -> str:
    for d in _FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    return _glob_font(names)


FONT_LATIN = find_font(["arial.ttf", "arialbd.ttf", "segoeui.ttf", "seguisb.ttf",
                        "tahoma.ttf", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf",
                        "Arimo-Regular.ttf", "micross.ttf"])
FONT_CJK = find_font(["msyh.ttc", "msyhbd.ttc", "simhei.ttf", "deng.ttf",
                      "dengb.ttf", "NotoSansCJK-Regular.ttc",
                      "NotoSansCJK-VF.otf.ttc", "NotoSansSC-Regular.otf",
                      "wqy-zenhei.ttc", "AlibabaPuHuiTi-2-55-Regular.ttf"])
FONT_CJK_BOLD = find_font(["msyhbd.ttc", "simhei.ttf", "dengb.ttf",
                           "NotoSansCJK-Bold.ttc", "NotoSansCJK-VF.otf.ttc",
                           "AlibabaPuHuiTi-2-75-SemiBold.ttf"]) or FONT_CJK


def fit_font(target_px: float, sample: str = "0", path: str = "",
             index: int = 0) -> ImageFont.FreeTypeFont:
    """让 sample 的实际墨迹高度等于 target_px。

    Tk 的 font.metrics("linespace") 含行距（数字字形只占其中约七成），
    拿它当字高会让数字明显偏小 —— 这里直接用 getbbox 量墨迹。
    """
    path = path or FONT_LATIN
    key = (path, index, round(target_px, 1), sample)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    if not path:
        f = ImageFont.load_default()
        _FONT_CACHE[key] = f
        return f

    size = max(4, int(round(target_px * 1.35)))
    font = None
    for _ in range(30):
        try:
            f = ImageFont.truetype(path, size, index=index)
        except Exception:
            f = ImageFont.truetype(path, size)
        b = f.getbbox(sample)
        h = (b[3] - b[1]) or 1
        font = f
        if abs(h - target_px) <= max(0.6, target_px * 0.012):
            break
        nxt = int(round(size * target_px / h))
        nxt = max(4, min(nxt, size + 200))
        if nxt == size:
            break
        size = nxt
    _FONT_CACHE[key] = font
    return font


def text_px(draw, xy, text, font, fill, anchor=None):
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)

# ==============================================================================
# 图标
# ==============================================================================
def icon_from_exe(path: str, size: int = 64):
    if not os.path.isfile(path) or not HAVE_PIL:
        return None
    try:
        import win32gui
        import win32ui
        import win32con

        large, small = win32gui.ExtractIconEx(path, 0)
        if not large:
            return None
        hicon = large[0]
        hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
        hbmp = win32ui.CreateBitmap()
        hbmp.CreateCompatibleBitmap(hdc, size, size)
        dc = hdc.CreateCompatibleDC()
        dc.SelectObject(hbmp)
        win32gui.DrawIconEx(dc.GetHandleOutput(), 0, 0, hicon, size, size,
                            0, 0, win32con.DI_NORMAL)
        bits = hbmp.GetBitmapBits(True)
        img = Image.frombuffer("RGBA", (size, size), bits, "raw", "BGRA", 0, 1)
        for hh in list(large) + list(small):
            try:
                win32gui.DestroyIcon(hh)
            except Exception:
                pass
        return img
    except Exception:
        return None


def draw_fallback_icon(size: int = 256):
    """没抠到真实图标时自己画一个：蓝底 + 白色云 + 一支笔"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.24),
                        fill=(6, 140, 200, 255))
    cx, cy = size * 0.5, size * 0.36
    r = size * 0.12
    for dx, dy, rr in ((-r * 1.15, 0, r), (0, -r * 0.4, r * 1.2), (r * 1.15, 0, r)):
        d.ellipse([cx + dx - rr, cy + dy - rr, cx + dx + rr, cy + dy + rr],
                  fill=(255, 255, 255, 245))
    d.rectangle([cx - r * 2.2, cy, cx + r * 2.2, cy + r], fill=(255, 255, 255, 245))
    w = max(2, int(size * 0.07))
    d.line([size * 0.30, size * 0.80, size * 0.58, size * 0.60],
           fill=(255, 255, 255, 255), width=w)
    d.polygon([(size * 0.58, size * 0.60), (size * 0.76, size * 0.50),
               (size * 0.63, size * 0.72)], fill=(255, 226, 120, 255))
    return img


def get_app_icon(size: int = 64):
    """优先从中育课堂助手的 exe 里抠真实图标，抠不到才自绘"""
    img = icon_from_exe(zy_exe_path(), size)
    if img is not None:
        return img
    try:
        import ClassHub

        mk = getattr(ClassHub, "make_icon", None)
        if mk:
            got = mk(size)
            if got is not None:
                return got
    except Exception:
        pass
    return draw_fallback_icon(size)


def ensure_ico() -> str:
    """生成 .ico 供任务栏 / 窗口标题栏用（放在配置目录，跟随 ClassHub）"""
    path = os.path.join(core.BASE, "pen_icon.ico")
    try:
        if not os.path.isfile(path):
            img = get_app_icon(256)
            img.save(path, format="ICO",
                     sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                            (64, 64), (128, 128), (256, 256)])
    except Exception:
        return ""
    return path if os.path.isfile(path) else ""

# ==============================================================================
# 二维码
# ==============================================================================
def make_qr(text: str, px: int):
    if not HAVE_PIL or px < 8:
        return None
    try:
        import qrcode

        qr = qrcode.QRCode(version=None, box_size=10, border=1,
                           error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#%02X%02X%02X" % THEME["qr_ink"],
                            back_color="white").convert("RGB")
        return img.resize((px, px), Image.NEAREST)
    except Exception:
        n = 25
        img = Image.new("RGB", (px, px), "white")
        d = ImageDraw.Draw(img)
        cell = px / n
        seed = (sum(ord(c) for c in text) or 7) % 97
        for r in range(n):
            for c in range(n):
                if (r * 7 + c * 13 + seed * (r + c)) % 5 < 2:
                    d.rectangle([c * cell, r * cell, (c + 1) * cell, (r + 1) * cell],
                                fill="#%02X%02X%02X" % THEME["qr_ink"])
        for ox, oy in ((0, 0), (n - 7, 0), (0, n - 7)):
            d.rectangle([ox * cell, oy * cell, (ox + 7) * cell, (oy + 7) * cell],
                        fill="white")
            d.rectangle([ox * cell, oy * cell, (ox + 7) * cell, (oy + 7) * cell],
                        outline="#%02X%02X%02X" % THEME["qr_ink"],
                        width=max(1, int(cell)))
            d.rectangle([(ox + 2) * cell, (oy + 2) * cell,
                         (ox + 5) * cell, (oy + 5) * cell],
                        fill="#%02X%02X%02X" % THEME["qr_ink"])
        return img

# ==============================================================================
# 布局比例（全部按参考图量出来）
# ==============================================================================
TITLE_TOP = 0.064          # 标题栏上沿（实测）
TITLE_BOTTOM = 0.126       # 标题栏下沿
ICON_X = 0.055
ICON_S = 0.058             # 图标边长
ICON_TOP = 0.076
TITLE_X = 0.118
TITLE_SIZE = 0.028

IP_X, IP_Y = 0.095, 0.235
IP_SIZE = 0.025
HINT_X, HINT_Y = 0.095, 0.288
HINT_SIZE = 0.019

CODE_Y = 0.486
CODE_SIZE = 0.133          # 大数字"墨迹"高度
CODE_X0, CODE_X1 = 0.278, 0.706

FEAT1_Y, FEAT2_Y = 0.657, 0.755
FEAT_ICON_X0, FEAT_ICON_X1 = 0.113, 0.147
FEAT_TEXT_X = 0.164
FEAT_SIZE = 0.020

QR_X0, QR_X1 = 0.748, 0.928
QR_Y0, QR_Y1 = 0.668, 0.885

FOOT_Y = 0.930
FOOT_X = 0.520
FOOT_SIZE = 0.017

FEATURES = ("投屏APP内容边讲边注", "一键记录电脑屏幕内容")

# ==============================================================================
# 背景
# ==============================================================================
def make_bg(w: int, h: int) -> Image.Image:
    """径向渐变：中心亮青蓝 → 边缘深青蓝"""
    img = Image.new("RGB", (w, h), THEME["bg_edge"])
    try:
        import numpy as np

        cx = THEME["bg_center_at"][0] * w
        cy = THEME["bg_center_at"][1] * h
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        # 归一化分母必须用对角线长度（与拟合时一致），用 max(w,h) 会让外围提前饱和
        maxr = (w ** 2 + h ** 2) ** 0.5
        d = (((xx - cx) ** 2 + (yy - cy) ** 2) ** 0.5) / maxr
        d = np.clip(d * THEME["bg_radius"], 0, 1) ** THEME["bg_power"]
        inner = np.array(THEME["bg_center"], dtype=np.float32)
        outer = np.array(THEME["bg_edge"], dtype=np.float32)
        arr = (inner * (1 - d[..., None]) + outer * d[..., None])
        arr = np.clip(arr, 0, 255).astype(np.uint8)
        return Image.fromarray(arr)
    except Exception:
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, w, h], fill=THEME["bg_center"])
        return img

# ==============================================================================
# 渲染
# ==============================================================================
class Renderer:
    """把当前状态画成一张图。背景和二维码做缓存，文字层每次重画。"""

    def __init__(self):
        self._bg = None
        self._bg_key = None
        self._qr = None
        self._qr_key = None
        self._icon = None
        self._icon_key = None

    # ---------------- 缓存件 ----------------
    def bg(self, w, h):
        key = (w, h, THEME["bg_center"], THEME["bg_edge"])
        if self._bg_key != key:
            self._bg = make_bg(w, h)
            self._bg_key = key
        return self._bg

    def icon(self, side):
        key = int(side)
        if self._icon_key != key:
            try:
                self._icon = get_app_icon(256).resize(
                    (max(8, key), max(8, key)), Image.LANCZOS).convert("RGBA")
            except Exception:
                self._icon = None
            self._icon_key = key
        return self._icon

    def qr(self, text, box):
        key = (text, int(box))
        if self._qr_key != key:
            self._qr = make_qr(text, int(box))
            self._qr_key = key
        return self._qr

    # ---------------- 整张图 ----------------
    def render(self, st: dict) -> Image.Image:
        W, H = int(st["w"]), int(st["h"])
        img = self.bg(W, H).copy()
        d = ImageDraw.Draw(img)

        self._title(d, st, W, H, img)
        self._main(d, st, W, H, img)
        return img

    # ---------------- 标题栏 ----------------
    def _title(self, d, st, W, H, img):
        top_y = int(round(H * THEME["title_top"]))
        bot_y = int(round(H * THEME["title_bottom"]))
        bar = THEME["title_bar"]

        # 硬边矩形 + 上下各 2px 淡出（实测参考图就是硬边，不是大渐变）
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(layer).rectangle([0, top_y, W, bot_y], fill=bar + (255,))
        try:
            import numpy as np

            fade = max(1, int(round(H * 0.0025)))
            a = layer.split()[3]
            arr = np.asarray(a).copy()
            arr[top_y:top_y + fade, :] = np.linspace(0, 255, fade).astype("uint8")[:, None]
            arr[bot_y - fade + 1:bot_y + 1, :] = np.linspace(255, 0, fade).astype("uint8")[:, None]
            layer.putalpha(Image.fromarray(arr))
        except Exception:
            pass
        try:
            img.paste(Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB"),
                      (0, 0))
        except Exception:
            pass
        d = ImageDraw.Draw(img)

        # 图标
        side = int(round(H * ICON_S))
        ico = self.icon(side)
        ix = int(W * ICON_X)
        iy = int(round(H * ICON_TOP))
        if ico is not None:
            try:
                img.paste(ico, (ix, iy), ico)
            except Exception:
                pass
        else:
            d.ellipse([ix, iy, ix + side, iy + side], fill=bar)

        # 标题文字（与图标垂直居中对齐）
        cy = H * (ICON_TOP + ICON_S / 2.0)
        f = fit_font(H * TITLE_SIZE, "中育", FONT_CJK_BOLD)
        d.text((int(W * TITLE_X), int(round(cy))), APP_TITLE,
               font=f, fill=THEME["title_text"], anchor="lm")

        for kind in ("min", "close"):
            self._btn(d, st, W, H, kind)

    def _btn(self, d, st, W, H, kind):
        bw = H * 0.055
        bh = H * 0.048
        cy = H * (THEME["title_top"] + THEME["title_bottom"]) / 2
        y0 = cy - bh / 2
        y1 = cy + bh / 2
        right = W - W * 0.018
        close_x0 = right - bw
        mini_x1 = close_x0 - bw * 0.30
        mini_x0 = mini_x1 - bw
        x0, x1 = (close_x0, right) if kind == "close" else (mini_x0, mini_x1)

        hover = st.get("hover") == kind
        if hover:
            col = (THEME["btn_hover_close"] if kind == "close"
                   else THEME["btn_hover_min"])
            d.rounded_rectangle([x0, y0, x1, y1], radius=bh * 0.22, fill=col)
        # 线条（圆头）
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        lw = max(1.4, bh * 0.085)
        col = THEME["btn_glyph"]
        if kind == "min":
            seg = bw * 0.30
            self._rline(d, (mx - seg, my), (mx + seg, my), lw, col)
        else:
            seg = bw * 0.19
            self._rline(d, (mx - seg, my - seg), (mx + seg, my + seg), lw, col)
            self._rline(d, (mx + seg, my - seg), (mx - seg, my + seg), lw, col)

    @staticmethod
    def _rline(d, p1, p2, width, fill):
        """带圆头的线段，比 ImageDraw.line 的生硬端头自然"""
        d.line([p1, p2], fill=fill, width=int(round(width)))
        r = width / 2.0
        for (x, y) in (p1, p2):
            d.ellipse([x - r, y - r, x + r, y + r], fill=fill)

    # ---------------- 主体 ----------------
    def _main(self, d, st, W, H, img):
        # IP
        f_ip = fit_font(H * IP_SIZE, "本机", FONT_CJK_BOLD)
        d.text((int(W * IP_X), int(round(H * IP_Y))),
               "本机IP地址：%s" % (st.get("ip") or "—"),
               font=f_ip, fill=THEME["text"], anchor="lm")

        f_hint = fit_font(H * HINT_SIZE, "请", FONT_CJK)
        d.text((int(W * HINT_X), int(round(H * HINT_Y))),
               "请使用「云笔助手」App 输入下方连接码连接本电脑",
               font=f_hint, fill=THEME["sub_text"], anchor="lm")

        # 大连接码
        code = (st.get("code") or "----").strip()
        f_code = fit_font(H * CODE_SIZE, "0", FONT_LATIN)
        span = (W * CODE_X1 - W * CODE_X0) / max(1, len(code))
        for i, ch in enumerate(code):
            cx = W * CODE_X0 + span * (i + 0.5)
            d.text((cx, H * CODE_Y), ch, font=f_code,
                   fill=THEME["text"], anchor="mm")

        # 功能项
        f_feat = fit_font(H * FEAT_SIZE, "投屏", FONT_CJK)
        for idx, (y, text) in enumerate(zip((FEAT1_Y, FEAT2_Y), FEATURES)):
            ix0, ix1 = W * FEAT_ICON_X0, W * FEAT_ICON_X1
            iy = H * y
            side = ix1 - ix0
            self._feat_icon(d, ix0, iy - side / 2, ix1, iy + side / 2, idx)
            d.text((int(W * FEAT_TEXT_X), int(round(iy))), text,
                   font=f_feat, fill=THEME["text"], anchor="lm")

        # 二维码
        self._qr_block(img, st, W, H)

        # 底部
        ver = st.get("version") or ""
        dev = st.get("device") or ""
        room = st.get("classroom") or ""
        parts = []
        if ver:
            parts.append("V" + ver)
        if room:
            parts.append("教室 " + room)
        if dev:
            parts.append(dev)
        if parts:
            f_foot = fit_font(H * FOOT_SIZE, "V0", FONT_LATIN)
            d.text((int(W * FOOT_X), int(round(H * FOOT_Y))),
                   "    ".join(parts), font=f_foot,
                   fill=THEME["foot_text"], anchor="lm")

        # 状态提示
        msg = st.get("status") or ""
        if msg:
            f_st = fit_font(H * HINT_SIZE, "正", FONT_CJK)
            d.text((int(W * IP_X), int(round(H * 0.60))), msg,
                   font=f_st, fill=THEME["status_text"], anchor="lm")

    @staticmethod
    def _feat_icon(d, x0, y0, x1, y1, idx):
        """绿色圆标：0=投屏（小屏+底座）  1=录制（同心圆）"""
        d.ellipse([x0, y0, x1, y1], fill=THEME["feat_green"])
        side = x1 - x0
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w = max(1, int(round(side * 0.085)))
        white = THEME["feat_glyph"]
        if idx == 0:
            Renderer._rline(d, (cx - side * 0.26, cy - side * 0.20),
                            (cx + side * 0.26, cy - side * 0.20), w, white)
            Renderer._rline(d, (cx - side * 0.19, cy - side * 0.20),
                            (cx - side * 0.19, cy + side * 0.10), w, white)
            Renderer._rline(d, (cx + side * 0.19, cy - side * 0.20),
                            (cx + side * 0.19, cy + side * 0.10), w, white)
            Renderer._rline(d, (cx - side * 0.19, cy + side * 0.10),
                            (cx + side * 0.19, cy + side * 0.10), w, white)
            Renderer._rline(d, (cx - side * 0.09, cy + side * 0.22),
                            (cx + side * 0.09, cy + side * 0.22), w, white)
            Renderer._rline(d, (cx, cy + side * 0.10), (cx, cy + side * 0.22), w, white)
        else:
            Renderer._rline(d, (cx - side * 0.30, cy), (cx - side * 0.02, cy), w, white)
            d.ellipse([cx + side * 0.02, cy - side * 0.24,
                       cx + side * 0.44, cy + side * 0.24], outline=white, width=w)
            d.ellipse([cx + side * 0.10, cy - side * 0.12,
                       cx + side * 0.36, cy + side * 0.12], fill=white)

    def _qr_block(self, img, st, W, H):
        x0, y0 = W * QR_X0, H * QR_Y0
        x1, y1 = W * QR_X1, H * QR_Y1
        box = int(round(min(x1 - x0, y1 - y0)))
        if box < 8:
            return
        ip = st.get("ip") or local_ip()
        port = st.get("port") or "8900"
        text = str(CFG.get("qr_text", "http://{ip}:{port}/?code={code}")
                   ).format(ip=ip, port=port, code=st.get("code") or "")
        qr = self.qr(text, box)
        if qr is None:
            return
        pad = max(2, int(round(box * 0.055)))
        card = Image.new("RGB", (box + pad * 2, box + pad * 2), "white")
        card.paste(qr, (pad, pad))
        px = int(round((x0 + x1) / 2 - card.width / 2))
        py = int(round((y0 + y1) / 2 - card.height / 2))
        try:
            img.paste(card, (px, py))
        except Exception:
            pass# ==============================================================================
# 窗口
# ==============================================================================
_PANELS: dict = {}          # 当前开着的所有面板
_PEN_LOCK = threading.Lock()
_PEN_THREAD = None


class PenPanel:
    """面板启动器：在独立线程里跑一个 Tk 根窗口（托盘是 pystray，互不干扰）。"""

    @staticmethod
    def open():
        global _PEN_THREAD
        with _PEN_LOCK:
            if _PANELS:
                for p in list(_PANELS.values()):
                    try:
                        p.root.deiconify()
                        p.root.lift()
                        p.refresh(force=True)
                    except Exception:
                        pass
                return True, "面板已打开（已存在实例）"
            _PEN_THREAD = threading.Thread(target=_run_panel, daemon=True,
                                           name="PenPanel")
            _PEN_THREAD.start()
        return True, "面板已打开"

    @staticmethod
    def close_all():
        for p in list(_PANELS.values()):
            try:
                p.quit()
            except Exception:
                pass
        return True, "面板已关闭"

    @staticmethod
    def is_open() -> bool:
        return bool(_PANELS)


def _run_panel():
    try:
        Panel().run()
    except Exception:
        log("云笔面板异常：\n" + traceback.format_exc())

# ==============================================================================
# 七·五、配色调整对话框（实时预览）
# ==============================================================================
class ThemeDialog:
    """三个滑块：色相 / 深浅 / 饱和度。拖动即时作用到面板上。"""

    def __init__(self, panel):
        self.p = panel
        self.win = tk.Toplevel(panel.root)
        self.win.title("调整配色")
        self.win.transient(panel.root)
        self.win.resizable(False, False)
        try:
            self.win.attributes("-topmost", True)
        except Exception:
            pass
        self.win.configure(bg="#F4F6F8")

        sw = 300
        self.swatch = tk.Canvas(self.win, width=sw, height=76,
                                highlightthickness=1, highlightbackground="#CCC")
        self.swatch.pack(padx=12, pady=(12, 6))
        self.swatch_txt = self.swatch.create_text(sw / 2, 38, text="",
                                                  fill="white",
                                                  font=("Consolas", 11, "bold"))

        self.v_hue = tk.DoubleVar(value=THEME["hue"])
        self.v_depth = tk.DoubleVar(value=THEME["depth"])
        self.v_sat = tk.DoubleVar(value=THEME["sat"])

        def slider(label, var, lo, hi, hint):
            f = tk.Frame(self.win, bg="#F4F6F8")
            f.pack(fill="x", padx=12, pady=3)
            tk.Label(f, text=label, width=8, anchor="w", bg="#F4F6F8").pack(side="left")
            tk.Scale(f, from_=lo, to=hi, orient="horizontal", variable=var,
                     length=190, showvalue=True, resolution=1,
                     command=lambda *_: self.on_change()).pack(side="left")
            tk.Label(f, text=hint, fg="#888", bg="#F4F6F8",
                     font=("Microsoft YaHei UI", 8)).pack(side="left")

        slider("色相", self.v_hue, 188, 218, "←青 蓝→")
        slider("深浅", self.v_depth, -60, 60, "深 ←→ 浅")
        slider("饱和度", self.v_sat, -40, 40, "灰 ←→ 艳")

        bar = tk.Frame(self.win, bg="#F4F6F8")
        bar.pack(fill="x", padx=12, pady=10)
        tk.Button(bar, text="恢复默认", command=self.reset).pack(side="left")
        tk.Button(bar, text="取消", command=self.cancel).pack(side="right", padx=4)
        tk.Button(bar, text="确定并保存", command=self.ok).pack(side="right")

        self.prev = (THEME["hue"], THEME["depth"], THEME["sat"])
        self.saved = dict(CFG)
        self.update_swatch()
        self.win.protocol("WM_DELETE_WINDOW", self.cancel)
        try:
            self.win.lift()
        except Exception:
            pass

    def on_change(self):
        THEME["hue"] = float(self.v_hue.get())
        THEME["depth"] = float(self.v_depth.get())
        THEME["sat"] = float(self.v_sat.get())
        apply_theme()
        self.p.renderer._bg_key = None      # 让背景按新颜色重画
        self.p.draw()
        self.update_swatch()

    def update_swatch(self):
        c = THEME["bg_center"]
        e = THEME["bg_edge"]
        try:
            self.swatch.delete("all")
            # 用一小段横向渐变示意两端颜色
            w = int(self.swatch.cget("width"))
            h = int(self.swatch.cget("height"))
            n = 40
            for i in range(n):
                k = i / (n - 1.0)
                col = tuple(int(c[j] + (e[j] - c[j]) * k) for j in range(3))
                self.swatch.create_rectangle(i * w / n, 0, (i + 1) * w / n, h,
                                             fill="#%02X%02X%02X" % col, outline="")
            self.swatch.create_text(
                w / 2, h - 16,
                text="中心 rgb%s 亮%.0f   边缘 rgb%s 亮%.0f   色相 %.0f°"
                     % (c, _lum(c), e, _lum(e), THEME["hue"]),
                fill="white", font=("Consolas", 9))
        except Exception:
            pass

    def reset(self):
        self.v_hue.set(205.0)
        self.v_depth.set(0.0)
        self.v_sat.set(0.0)
        self.on_change()

    def ok(self):
        CFG["pen.hue"] = THEME["hue"]
        CFG["pen.depth"] = THEME["depth"]
        CFG["pen.sat"] = THEME["sat"]
        self.p.save_cfg()
        log("配色已保存：色相 %.0f°  深浅 %+.0f  饱和 %+.0f"
            % (THEME["hue"], THEME["depth"], THEME["sat"]))
        self.win.destroy()

    def cancel(self):
        THEME["hue"], THEME["depth"], THEME["sat"] = self.prev
        apply_theme()
        self.p.renderer._bg_key = None
        self.p.draw()
        self.win.destroy()


# ==============================================================================
# 八、窗口
# ==============================================================================
class Panel:
    def __init__(self):
        self.closed = False
        self.root = tk.Tk()
        _PANELS[id(self)] = self
        self.scale = self._dpi_scale()

        self.W, self.H = self._window_size()
        self.root.overrideredirect(True)
        self.root.configure(bg="#%02X%02X%02X" % THEME["bg_edge"])
        self.root.geometry("%dx%d+%d+%d" % (self.W, self.H, *self._center_pos()))
        if cfg("topmost"):
            self.root.attributes("-topmost", True)

        self.code = "----"
        self.info: dict = {}
        self.status = "正在检测……"
        self.hover = ""
        self.pending_btn = ""
        self.manual_code = None
        self.drag = None
        self.mini_win = None
        self.updates: queue.Queue = queue.Queue()
        self.photo = None
        self.renderer = Renderer()

        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H,
                                highlightthickness=0, bd=0,
                                bg="#%02X%02X%02X" % THEME["bg_edge"])
        self.canvas.pack(fill="both", expand=True)

        self._set_window_icon()
        self._bind_events()
        self.draw()
        self._pump()
        threading.Thread(target=self._boot_worker, daemon=True).start()
        self._schedule_refresh()

    # ------------------------------------------------------------ 尺寸
    def _dpi_scale(self) -> float:
        try:
            import ctypes

            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass
            hdc = ctypes.windll.user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
            ctypes.windll.user32.ReleaseDC(0, hdc)
            if dpi and 96 <= dpi <= 480:
                return max(1.0, round(dpi / 96.0, 2))
        except Exception:
            pass
        return 1.0

    def _window_size(self) -> tuple:
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        h = sh * float(cfg("height_ratio", 0.62) or 0.62)
        h = max(float(cfg("min_height", 520)),
                min(float(cfg("max_height", 1400)), h))
        w = h * float(cfg("window_ratio", 4 / 3) or 4 / 3)
        if w > sw * 0.92:
            w = sw * 0.92
            h = w / float(cfg("window_ratio", 4 / 3) or 4 / 3)
        return int(round(w)), int(round(h))

    def _center_pos(self) -> tuple:
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        return int((sw - self.W) / 2), int((sh - self.H) * 0.42)

    # ------------------------------------------------------------ 任务栏图标
    def _set_window_icon(self):
        """让无边框窗口出现在任务栏，并带上自己的图标"""
        ico = ensure_ico()
        # 1) Tk 图标（任务栏和窗口标题栏都用它）
        try:
            if ico and os.path.isfile(ico):
                self.root.iconbitmap(ico)
        except Exception:
            pass
        try:
            img = get_app_icon(64)
            self._icon_photo = ImageTk.PhotoImage(img)
            self.root.iconphoto(True, self._icon_photo)
        except Exception:
            self._icon_photo = None

        # 2) 加 WS_EX_APPWINDOW，否则 overrideredirect 的窗口不会出现在任务栏
        self._force_taskbar_entry()

    def _force_taskbar_entry(self):
        """无边框（overrideredirect）窗口默认不进任务栏，这里补上扩展样式。

        改完必须让系统重新读一次样式（SWP_FRAMECHANGED），否则不生效。
        """
        try:
            import ctypes

            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER = 0x0001, 0x0002, 0x0004
            SWP_FRAMECHANGED, SWP_SHOWWINDOW = 0x0020, 0x0040
            u = ctypes.windll.user32
            hwnd = self.root.winfo_id()
            handles = [hwnd]
            try:
                parent = u.GetParent(hwnd)
                if parent:
                    handles.append(parent)
            except Exception:
                pass
            for h_ in handles:
                try:
                    style = u.GetWindowLongW(h_, GWL_EXSTYLE)
                    style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
                    u.SetWindowLongW(h_, GWL_EXSTYLE, style)
                    u.SetWindowPos(h_, 0, 0, 0, 0, 0,
                                   SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER |
                                   SWP_FRAMECHANGED | SWP_SHOWWINDOW)
                except Exception:
                    continue
        except Exception:
            pass

    # ------------------------------------------------------------ 事件
    def _bind_events(self):
        c = self.canvas
        c.bind("<ButtonPress-1>", self._on_down)
        c.bind("<B1-Motion>", self._on_move)
        c.bind("<ButtonRelease-1>", self._on_up)
        c.bind("<Motion>", self._on_motion)
        c.bind("<Button-3>", self._on_right)
        c.bind("<Leave>", lambda e: self._set_hover(""))
        self.root.bind("<Escape>", lambda e: self.minimize())
        self.root.bind("<F5>", lambda e: self.refresh(force=True))

    def _btn_rects(self) -> dict:
        bw = self.H * 0.055
        bh = self.H * 0.048
        cy = self.H * (THEME["title_top"] + THEME["title_bottom"]) / 2
        y0 = cy - bh / 2
        y1 = cy + bh / 2
        right = self.W - self.W * 0.018
        close_x0 = right - bw
        mini_x1 = close_x0 - bw * 0.30
        mini_x0 = mini_x1 - bw
        return {"min": (mini_x0, y0, mini_x1, y1),
                "close": (close_x0, y0, right, y1)}

    def _btn_at(self, x, y) -> str:
        for kind, (x0, y0, x1, y1) in self._btn_rects().items():
            if x0 <= x <= x1 and y0 <= y <= y1:
                return kind
        return ""

    def _set_hover(self, v):
        if v != self.hover:
            self.hover = v
            self.draw()

    def _on_down(self, e):
        btn = self._btn_at(e.x, e.y)
        self.pending_btn = btn
        if not btn:
            self.drag = (e.x, e.y)

    def _on_move(self, e):
        if self.drag and not self.pending_btn:
            dx = e.x - self.drag[0]
            dy = e.y - self.drag[1]
            self.root.geometry("+%d+%d" % (self.root.winfo_x() + dx,
                                           self.root.winfo_y() + dy))

    def _on_up(self, e):
        if self.pending_btn and self._btn_at(e.x, e.y) == self.pending_btn:
            if self.pending_btn == "close":
                self.quit()
            else:
                self.minimize()
        self.drag = None
        self.pending_btn = ""

    def _on_motion(self, e):
        self._set_hover(self._btn_at(e.x, e.y))

    def _on_right(self, e):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="复制连接码", command=self.copy_code)
        m.add_command(label="手动输入连接码…", command=self.ask_code)
        m.add_command(label="立即刷新", command=lambda: self.refresh(force=True))
        m.add_separator()
        m.add_command(label="重启中育课堂助手", command=self.restart_app)
        m.add_command(label="打开日志文件", command=self.open_log)
        m.add_separator()
        m.add_command(label="调整配色…", command=self.show_theme_dialog)
        m.add_command(label="诊断信息…", command=self.show_diag)
        m.add_command(label="置顶显示" if not cfg("topmost") else "取消置顶",
                      command=self.toggle_top)
        m.add_command(label="保存配置", command=self.save_cfg)
        m.add_separator()
        m.add_command(label="退出", command=self.quit)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            try:
                m.grab_release()
            except Exception:
                pass

    # ------------------------------------------------------------ 动作
    def copy_code(self):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.code)
        except Exception:
            pass

    def ask_code(self):
        v = simpledialog.askstring("连接码", "手动指定连接码（留空恢复自动检测）：",
                                   initialvalue=self.code, parent=self.root)
        if v is None:
            return
        self.manual_code = (v or "").strip() or None
        self.refresh(force=True)

    def open_log(self):
        p = zy_mod.log_path()
        try:
            if os.path.isfile(p):
                subprocess.Popen(["notepad.exe", p])
            else:
                messagebox.showinfo("日志", "日志文件不存在：\n%s" % p)
        except Exception:
            pass

    def show_theme_dialog(self):
        try:
            ThemeDialog(self)
        except Exception:
            log("打开配色对话框失败：\n" + traceback.format_exc())

    def show_diag(self):
        i = self.info or {}
        msg = ("连接码：%s（来源：%s）\n"
               "IP：%s    端口：%s\n"
               "版本：%s    教室：%s\n"
               "设备号：%s\n\n"
               "日志：%s\n"
               "程序：%s\n"
               "运行状态：%s\n"
               "窗口：%dx%d  缩放：%.2f\n"
               "配色：色相 %.0f°  深浅 %+.0f  饱和 %+.0f\n"
               "渐变：中心 rgb%s 亮%.0f  边缘 rgb%s 亮%.0f") % (
            self.code, i.get("src") or "—", i.get("ip") or local_ip(),
            i.get("port") or "8900", i.get("version") or "—",
            i.get("classroom") or "—", i.get("device") or "—",
            zy_mod.log_path(), zy_exe_path(),
            "已运行" if zy_mod.is_running() else "未运行", self.W, self.H, self.scale,
            THEME["hue"], THEME["depth"], THEME["sat"],
            THEME["bg_center"], _lum(THEME["bg_center"]),
            THEME["bg_edge"], _lum(THEME["bg_edge"]))
        messagebox.showinfo("诊断信息", msg)

    def toggle_top(self):
        CFG["pen.topmost"] = not cfg("topmost")
        self.root.attributes("-topmost", bool(CFG["topmost"]))
        self.save_cfg()

    def save_cfg(self):
        core.save_config()

    def restart_app(self):
        def run():
            self.updates.put(("status", "正在重启中育课堂助手……"))
            try:
                subprocess.run(["taskkill", "/IM", zy_mod.app_exe(), "/F"],
                               capture_output=True)
            except Exception:
                pass
            try:
                if os.path.isfile(zy_mod.log_path()):
                    os.remove(zy_mod.log_path())
            except Exception:
                pass
            ok, msg = zy_mod.start_zy()
            if ok:
                time.sleep(float(cfg("wait_seconds", 8)))
            self.refresh(force=True)

        threading.Thread(target=run, daemon=True).start()

    def minimize(self):
        self.root.withdraw()
        if self.mini_win is not None:
            try:
                self.mini_win.destroy()
            except Exception:
                pass
        m = tk.Toplevel(self.root)
        self.mini_win = m
        m.overrideredirect(True)
        m.attributes("-topmost", True)
        m.configure(bg="#%02X%02X%02X" % THEME["bg_center"])
        w = max(150, int(self.H * 0.20))
        h = max(44, int(self.H * 0.062))
        m.geometry("%dx%d+%d+%d" % (w, h,
                                    self.root.winfo_screenwidth() - w - 30,
                                    self.root.winfo_screenheight() - h - 60))
        cv = tk.Canvas(m, width=w, height=h, highlightthickness=0, bd=0,
                       bg="#%02X%02X%02X" % THEME["bg_center"])
        cv.pack()
        cv.create_rectangle(0, 0, w, h,
                            fill="#%02X%02X%02X" % THEME["bg_center"], outline="")
        cv.create_text(int(h * 0.30), h / 2, anchor="w", text=APP_TITLE,
                       fill="white", font=("Microsoft YaHei UI", max(8, int(h * 0.26))))
        cv.create_text(w - int(h * 0.30), h / 2, anchor="e", text=self.code,
                       fill="white", font=("Arial", max(10, int(h * 0.40)), "bold"))
        cv.bind("<Button-1>", lambda e: self.restore())
        m.bind("<Button-1>", lambda e: self.restore())

    def restore(self):
        try:
            if self.mini_win is not None:
                self.mini_win.destroy()
                self.mini_win = None
        except Exception:
            pass
        try:
            self.root.deiconify()
            self.root.lift()
            self._force_taskbar_entry()
        except Exception:
            pass

    def quit(self):
        """关闭面板（托盘里可以再打开）"""
        self.closed = True
        try:
            if self.mini_win is not None:
                self.mini_win.destroy()
                self.mini_win = None
        except Exception:
            pass
        try:
            self.root.quit()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        try:
            _PANELS.pop(id(self), None)
        except Exception:
            pass

    # ------------------------------------------------------------ 数据
    def _boot_worker(self):
        try:
            if not zy_mod.is_running():
                if CFG.get("auto_start", True):
                    self.updates.put(("status", "未检测到中育课堂助手，正在启动……"))
                    ok, msg = zy_mod.start_zy()
                    if ok:
                        wait = int(float(cfg("wait_seconds", 8)))
                        for i in range(wait):
                            self.updates.put(("status", "已启动，%d 秒后读取连接码……"
                                              % (wait - i)))
                            time.sleep(1.0)
                    else:
                        self.updates.put(("status", msg))
                else:
                    self.updates.put(("status", "中育课堂助手未运行（自动启动已关闭）"))
            else:
                self.updates.put(("status", ""))
        except Exception:
            log("启动流程异常：\n" + traceback.format_exc())
        self.refresh(force=True)

    def refresh(self, force: bool = False):
        info = zy_mod.read_info()
        manual = self.manual_code
        if manual:
            info["code"] = manual
            info["src"] = "手动指定"
        if not info.get("ip"):
            info["ip"] = local_ip()
        if not info.get("port"):
            info["port"] = "8900"
        changed = (info.get("code") != (self.info or {}).get("code")) or force
        self.updates.put(("info", info))
        if changed:
            log("连接码 %s（来源：%s）  IP %s"
                % (info.get("code") or "----", info.get("src"), info.get("ip")))

    def _schedule_refresh(self):
        def tick():
            threading.Thread(target=self.refresh, daemon=True).start()
            self.root.after(int(float(cfg("refresh_interval", 3)) * 1000), tick)

        self.root.after(int(float(cfg("refresh_interval", 3)) * 1000), tick)

    def _pump(self):
        try:
            while True:
                kind, payload = self.updates.get_nowait()
                if kind == "status":
                    self.status = payload
                elif kind == "info":
                    self.info = payload
                    self.code = payload.get("code") or "----"
                    if not payload.get("src", "").startswith("读取失败") and \
                            not payload.get("src", "").startswith("日志不存在"):
                        if self.status and "读取" in self.status:
                            self.status = ""
                self.draw()
        except Exception:
            pass
        self.root.after(120, self._pump)

    # ------------------------------------------------------------ 画
    def draw(self):
        if not (HAVE_PIL and HAVE_TK_IMG):
            return
        if getattr(self, "_draw_failed", 0) >= 3:
            return          # 连续失败就别刷日志了
        try:
            st = {
                "w": self.W, "h": self.H,
                "code": self.code,
                "ip": (self.info or {}).get("ip") or local_ip(),
                "port": (self.info or {}).get("port") or "8900",
                "version": (self.info or {}).get("version") or "",
                "device": (self.info or {}).get("device") or "",
                "classroom": (self.info or {}).get("classroom") or "",
                "status": self.status,
                "hover": self.hover,
            }
            img = self.renderer.render(st)
            self.photo = ImageTk.PhotoImage(img)
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        except Exception:
            self._draw_failed = getattr(self, "_draw_failed", 0) + 1
            if self._draw_failed <= 1:
                log("绘制异常：\n" + traceback.format_exc())

    def run(self):
        self.root.mainloop()


