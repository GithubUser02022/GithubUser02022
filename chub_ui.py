# -*- coding: utf-8 -*-
"""
================================================================================
 ClassHub · chub_ui —— 设置窗口（tkinter）
================================================================================
托盘菜单里点『设置…』打开。八个标签页，一个软件里全部功能都在这里调：

    常规 · 课件同步 · 开机启动&守护 · 文件关联 · 定时任务 · 程序守护器
    · 中育助手 · 日志

所有改动点『保存』后才写入 config.json 并生效；默认全部关闭。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import chub_assoc as assoc_mod
import chub_core as core
import chub_sync as sync_mod
import chub_tasks as tasks_mod
import chub_pen as pen_mod
import chub_zy as zy_mod
from chub_core import (BASE, CFG, CONFIG_PATH, LOG_PATH, PORTABLE,
                       AppItem, AssocItem, TaskItem, log)

_ROOT = None          # 已存在的设置窗口（单例）
_WIN = None


def focus_existing():
    if _ROOT is None:
        return
    try:
        _ROOT.after(0, lambda: (_ROOT.deiconify(), _ROOT.lift(), _ROOT.attributes("-topmost", True)))
    except Exception:
        pass


def open_settings(app):
    if _ROOT is not None:
        focus_existing()
        return
    SettingsWindow(app)


# ==============================================================================
# 高分屏 / 低分屏自适应
# ==============================================================================
# 4K 屏上不处理的话窗口和字会小得看不清；这里统一按系统 DPI 放大，
# 同时保证在 1366x768 这类小屏上不会大到出屏。
def ensure_dpi_aware() -> float:
    """声明 DPI 感知并返回缩放系数（必须在 tkinter 建窗口之前调用）。

    4K 屏常见 150% → 1.5，200% → 2.0；普通 1080p 是 1.0。
    """
    scale = 1.0
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
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)     # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        if dpi and 96 <= dpi <= 480:
            scale = max(1.0, round(dpi / 96.0, 2))
    except Exception:
        pass
    return scale


def apply_tk_scaling(root, scale: float):
    """让 Tk 按 DPI 缩放（字体与控件内置尺寸跟着放大）"""
    try:
        root.tk.call("tk", "scaling", scale)
    except Exception:
        pass
    try:
        ttk.Style().configure("Treeview", rowheight=max(20, int(22 * scale)))
    except Exception:
        pass


def set_window_icon(root, ico_path: str = "", pil_img=None):
    """给窗口设图标：任务栏和标题栏都会显示它。

    优先用已存在的 .ico；没有就现场生成一个（窗口本来就有任务栏条目，
    不设的话会显示 Tk 那个默认羽毛图标）。
    """
    try:
        import os

        path = ico_path
        if not path or not os.path.isfile(path):
            try:
                import ClassHub

                path = ClassHub.export_icon(os.path.join(os.path.dirname(
                    os.path.abspath(ClassHub.__file__)), "icon.ico"))
                path = os.path.join(os.path.dirname(os.path.abspath(
                    ClassHub.__file__)), "icon.ico")
            except Exception:
                path = ""
        if path and os.path.isfile(path):
            try:
                root.iconbitmap(path)
                return True
            except Exception:
                pass
    except Exception:
        pass
    try:
        from PIL import ImageTk

        img = pil_img
        if img is None:
            try:
                import ClassHub

                img = ClassHub.make_icon(64)
            except Exception:
                return False
        photo = ImageTk.PhotoImage(img)
        root._icon_ref = photo          # 必须持有引用，否则会被回收
        root.iconphoto(True, photo)
        return True
    except Exception:
        return False


def ui_scale(root, dpi_scale: float) -> float:
    """最终缩放系数。

    三种来源，优先级从高到低：
      ① 手动指定（config.json 的 shell.ui_scale，>0 就用它）
      ② 系统 DPI 缩放（4K@150% → 1.5）
      ③ 屏幕本身很大（3840 宽 → 按屏宽给到 2.4）

    ②③ 取大的那个。大屏就算系统设成 100%，960px 的窗口也小得可怜。
    """
    try:
        manual = float(CFG.get("shell.ui_scale", 0.0) or 0.0)
    except Exception:
        manual = 0.0
    if manual > 0:
        return round(max(0.5, min(3.0, manual)), 2)

    try:
        sw = root.winfo_screenwidth()
    except Exception:
        sw = 1920
    # 屏幕越大给越多：1080p=1.0  1440p≈1.33  3440≈1.9  4K=2.4
    by_screen = max(1.0, min(2.4, (sw / 1920.0) ** 1.15))
    return round(max(dpi_scale, by_screen), 2)


def fit_window(root, base_w: int, base_h: int, scale: float) -> tuple:
    """基准尺寸 × 缩放，再夹进屏幕范围，顺带返回居中坐标"""
    try:
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
    except Exception:
        sw, sh = 1920, 1080
    w = int(base_w * scale)
    h = int(base_h * scale)
    w = min(w, int(sw * 0.92))
    h = min(h, int(sh * 0.88))
    w = max(w, min(int(sw * 0.62), 900))
    h = max(h, min(int(sh * 0.62), 600))
    return w, h, max(0, int((sw - w) / 2)), max(0, int((sh - h) * 0.42))


# ==============================================================================
# 通用表单对话框
# ==============================================================================
class FormDialog:
    """字段驱动的小表单。fields = [(标签, 键, 类型, 选项)]，类型：
    text / int / float / bool / combo / file / dir
    """

    def __init__(self, parent, title: str, fields: list, values: dict):
        self.result = None
        self.vars = {}
        top = tk.Toplevel(parent)
        self.top = top
        top.title(title)
        top.transient(parent)
        top.grab_set()
        top.resizable(False, False)

        frm = ttk.Frame(top, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")

        row = 0
        for label, key, kind, options in fields:
            ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=3)
            val = values.get(key, "")
            if kind == "bool":
                v = tk.BooleanVar(value=bool(val))
                ttk.Checkbutton(frm, variable=v).grid(row=row, column=1, sticky="w", pady=3)
            elif kind == "combo":
                v = tk.StringVar(value=str(val))
                box = ttk.Combobox(frm, textvariable=v, width=28, state="readonly",
                                   values=list(options or []))
                box.grid(row=row, column=1, sticky="w", pady=3)
                if str(val) not in (options or []):
                    box.set(list(options or [])[0] if options else "")
            elif kind in ("file", "dir"):
                v = tk.StringVar(value=str(val))

                def pick(_v=v, _k=kind):
                    p = (filedialog.askopenfilename(title="选择程序",
                                                   filetypes=[("程序", "*.exe"), ("所有文件", "*.*")])
                         if _k == "file" else filedialog.askdirectory(title="选择文件夹"))
                    if p:
                        _v.set(p)

                ttk.Entry(frm, textvariable=v, width=34).grid(row=row, column=1, sticky="w", pady=3)
                ttk.Button(frm, text="…", width=3, command=pick).grid(row=row, column=2, pady=3)
            else:
                v = tk.StringVar(value=str(val))
                ttk.Entry(frm, textvariable=v, width=36).grid(row=row, column=1,
                                                              columnspan=2, sticky="w", pady=3)
            self.vars[key] = (v, kind)
            row += 1

        if isinstance(values.get("_hint"), str) and values["_hint"]:
            ttk.Label(frm, text=values["_hint"], foreground="#666",
                      wraplength=420, justify="left").grid(row=row, column=0, columnspan=3,
                                                           sticky="w", pady=(6, 0))
            row += 1

        def ok():
            out = {}
            for key, (v, kind) in self.vars.items():
                raw = v.get()
                if kind == "bool":
                    out[key] = bool(raw)
                elif kind == "int":
                    try:
                        out[key] = int(float(str(raw)))
                    except Exception:
                        out[key] = 0
                elif kind == "float":
                    try:
                        out[key] = float(str(raw))
                    except Exception:
                        out[key] = 0.0
                else:
                    out[key] = str(raw).strip()
            self.result = out
            top.destroy()

        def cancel():
            self.result = None
            top.destroy()

        btns = ttk.Frame(frm)
        btns.grid(row=row + 1, column=0, columnspan=3, pady=(12, 0))
        ttk.Button(btns, text="确定", width=10, command=ok).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", width=10, command=cancel).pack(side="left", padx=4)
        top.protocol("WM_DELETE_WINDOW", cancel)
        top.wait_window()


# ==============================================================================
# 设置窗口主体
# ==============================================================================
class SettingsWindow:
    """原来的文字版设置（八个标签页）。

    两种用法：
        SettingsWindow(app)                      独立窗口（tk.Tk）
        SettingsWindow(app, parent=f, embedded=True)   嵌进别人给的容器里（新设置中心的
                                                       『首选项』页就是这么用的）
    嵌入式下不建 Tk、不跑 mainloop、不接管关闭协议，只负责把内容铺进 parent。
    """

    def __init__(self, app, parent=None, embedded: bool = False):
        global _ROOT, _WIN
        self.app = app
        self.embedded = bool(embedded)
        self.launch_items = [AppItem.from_dict(d, "launch")
                             for d in CFG.get("launch.items", []) or []]
        self.watch_items = [AppItem.from_dict(d, "watch")
                            for d in CFG.get("watch.items", []) or []]
        self.assoc_items = [AssocItem.from_dict(d)
                            for d in CFG.get("assoc.items", []) or []]
        self.task_items = [TaskItem.from_dict(d)
                           for d in CFG.get("tasks.items", []) or []]

        # ---- 高分屏 / 低分屏自适应：必须在建窗口之前声明 DPI 感知 ----
        self.scale = ensure_dpi_aware()

        if self.embedded:
            # 容器由调用方给；self.root 仍指向顶层窗口（弹子对话框要用它当父窗口）
            container = parent
            self.root = container.winfo_toplevel()
        else:
            root = tk.Tk()
            _ROOT = root
            _WIN = self
            self.root = root
            root.title("ClassHub 课堂助手套件 —— 设置")
            set_window_icon(root)
            self.scale = ui_scale(root, self.scale)
            apply_tk_scaling(root, self.scale)
            gw, gh, gx, gy = fit_window(root, 960, 680, self.scale)
            root.geometry("%dx%d+%d+%d" % (gw, gh, gx, gy))
            root.minsize(int(760 * self.scale), int(520 * self.scale))
            container = root

        nb = ttk.Notebook(container)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        self._build_general(nb)
        self._build_sync(nb)
        self._build_boot(nb)
        self._build_assoc(nb)
        self._build_tasks(nb)
        self._build_protect(nb)
        self._build_zy(nb)
        self._build_pen(nb)
        self._build_log(nb)

        bottom = ttk.Frame(container)
        bottom.pack(fill="x", padx=8, pady=(0, 8))
        self.hint = tk.StringVar(value="提示：所有开关默认关闭，改完点『保存』才生效")
        ttk.Label(bottom, textvariable=self.hint, foreground="#666").pack(side="left")
        if not self.embedded:
            ttk.Button(bottom, text="打开日志", command=self.open_log).pack(side="right", padx=3)
            ttk.Button(bottom, text="配置目录", command=self.open_dir).pack(side="right", padx=3)
            ttk.Button(bottom, text="取消", command=self.close).pack(side="right", padx=3)
        ttk.Button(bottom, text="保存", command=self.save).pack(side="right", padx=3)

        if not self.embedded:
            root = self.root
            root.protocol("WM_DELETE_WINDOW", self.close)
            try:
                root.mainloop()
            finally:
                _ROOT = None
                _WIN = None

    # ------------------------------------------------------------ 小工具
    def close(self):
        if self.embedded:
            return          # 嵌入式：由外层容器决定何时销毁，别把整个设置中心关了
        try:
            self.root.destroy()
        except Exception:
            pass

    def open_log(self):
        core.open_in_explorer(LOG_PATH)

    def open_dir(self):
        core.open_in_explorer(BASE)

    def _tab(self, nb, text):
        """建一个标签页。注意：ttk.Notebook 只接受它的直接子部件当标签页，
        所以外面套一层 Frame 给 Notebook，真正的内容放在里面这层。"""
        outer = ttk.Frame(nb)
        inner = ttk.Frame(outer, padding=10)
        inner.pack(fill="both", expand=True)
        nb.add(outer, text=text)
        return inner

    # ============================================================ ① 常规
    def _build_general(self, nb):
        f = self._tab(nb, "① 常规")

        self.v_app_name = tk.StringVar(value=CFG.get("app_name", "ClassHub"))
        self.v_notify = tk.BooleanVar(value=bool(CFG.get("notify", False)))
        self.v_autostart = tk.BooleanVar(value=core.get_autostart())
        self.v_start_min = tk.BooleanVar(value=bool(CFG.get("start_minimized", True)))

        r = 0
        ttk.Label(f, text="托盘显示名称").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_app_name, width=30).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Checkbutton(f, text="复制成功时显示气泡提示（默认关，保持静默）",
                        variable=self.v_notify).grid(row=r, column=0, columnspan=3, sticky="w", pady=3)
        r += 1
        ttk.Checkbutton(f, text="开机自动启动本程序（写 HKCU Run 项，默认关）",
                        variable=self.v_autostart).grid(row=r, column=0, columnspan=3, sticky="w", pady=3)
        r += 1
        ttk.Checkbutton(f, text="启动后只显示托盘图标", variable=self.v_start_min).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=3)
        r += 1

        ttk.Separator(f).grid(row=r, column=0, columnspan=3, sticky="ew", pady=10)
        r += 1
        ttk.Label(f, text="各功能模块总开关（默认全关，勾了才干活）",
                  font=("Microsoft YaHei UI", 9, "bold")).grid(row=r, column=0, columnspan=3, sticky="w")
        r += 1

        self.v_en = {}
        mods = [
            ("sync.enable", "课件同步（放映/打开的 PPT、Word、PDF）"),
            ("launch.enable", "开机批量启动软件"),
            ("watch.enable", "守护：软件被关掉后自动重开"),
            ("assoc.enable", "文件关联（会改注册表，默认不碰）"),
            ("tasks.enable", "定时任务（含定时关机）"),
            ("protect.enable", "程序守护器（防 TaskKill）"),
            ("zy.enable", "中育课堂助手小工具"),
            ("pen.enable", "云笔助手面板（自绘窗口）"),
        ]
        for key, text in mods:
            v = tk.BooleanVar(value=bool(CFG.get(key, False)))
            self.v_en[key] = v
            ttk.Checkbutton(f, text=text, variable=v).grid(row=r, column=0, columnspan=3,
                                                           sticky="w", pady=2)
            r += 1

        ttk.Separator(f).grid(row=r, column=0, columnspan=3, sticky="ew", pady=10)
        r += 1
        where = "配置保存在程序同目录：%s" % BASE if PORTABLE else \
                "程序目录不可写，配置保存在：%s" % BASE
        ttk.Label(f, text=where, foreground="#888", wraplength=700, justify="left").grid(
            row=r, column=0, columnspan=3, sticky="w")
        r += 1
        ttk.Label(f, text="配置文件：%s" % CONFIG_PATH, foreground="#888",
                  wraplength=700, justify="left").grid(row=r, column=0, columnspan=3, sticky="w")

    def _sync_sib(self):
        """勾了"递归"就自动勾上"拷同目录文件"（递归包含它）"""
        try:
            if self.v_sib_rec.get():
                self.v_sib.set(True)
        except Exception:
            pass

    # ============================================================ ② 课件同步
    def _build_sync(self, nb):
        f = self._tab(nb, "② 课件同步")

        self.v_dest = tk.StringVar(value=CFG.get("sync.dest") or core.default_dest())
        self.v_sub = tk.StringVar(value=CFG.get("sync.subfolder_mode", "none"))
        self.v_interval = tk.StringVar(value=str(CFG.get("sync.interval", 5)))
        self.v_min = tk.StringVar(value=str(CFG.get("sync.min_size_kb", 0)))
        self.v_exists = tk.StringVar(value=CFG.get("sync.exists_policy", "rename"))
        self.v_ppt = tk.BooleanVar(value=bool(CFG.get("sync.enable_ppt", False)))
        self.v_ppt_mode = tk.StringVar(value=CFG.get("sync.ppt_mode", "slideshow"))
        self.v_doc = tk.BooleanVar(value=bool(CFG.get("sync.enable_doc", False)))
        self.v_pdf = tk.BooleanVar(value=bool(CFG.get("sync.enable_pdf", False)))
        self.v_deep = tk.BooleanVar(value=bool(CFG.get("sync.deep_scan", False)))
        self.v_usb = tk.BooleanVar(value=bool(CFG.get("sync.enable_usb", False)))
        self.v_usb_int = tk.StringVar(value=str(CFG.get("sync.usb_interval", 60)))
        self.v_usb_max = tk.StringVar(value=str(CFG.get("sync.usb_max_files", 3000)))
        self.v_usb_size = tk.StringVar(value=str(CFG.get("sync.usb_max_size_mb", 200)))
        self.v_usb_depth = tk.StringVar(value=str(CFG.get("sync.usb_max_depth", 8)))
        self.v_usb_sub = tk.StringVar(value=CFG.get("sync.usb_subfolder", "label"))
        self.v_sib = tk.BooleanVar(value=bool(CFG.get("sync.copy_siblings", False)))
        self.v_sib_rec = tk.BooleanVar(value=bool(CFG.get("sync.copy_siblings_recursive", False)))
        self.v_sib_max = tk.StringVar(value=str(CFG.get("sync.siblings_max_files", 200)))
        self.v_sib_size = tk.StringVar(value=str(CFG.get("sync.siblings_max_size_mb", 200)))
        self.v_sib_sub = tk.BooleanVar(value=bool(CFG.get("sync.siblings_use_subfolder", True)))
        self.v_ue = tk.BooleanVar(value=bool(CFG.get("usb_export.enable", False)))
        self.v_ue_file = tk.StringVar(value=CFG.get("usb_export.trigger_file", "f"))
        self.v_ue_hidden = tk.BooleanVar(value=bool(CFG.get("usb_export.require_hidden", True)))
        self.v_ue_val = tk.StringVar(value=str(CFG.get("usb_export.trigger_value", "1")))
        self.v_ue_sub = tk.StringVar(value=CFG.get("usb_export.dest_subfolder", "课件"))
        self.v_ue_int = tk.StringVar(value=str(CFG.get("usb_export.interval", 10)))
        self.v_ue_max = tk.StringVar(value=str(CFG.get("usb_export.max_files", 5000)))
        self.v_ue_size = tk.StringVar(value=str(CFG.get("usb_export.max_size_mb", 500)))
        self.v_ue_total = tk.StringVar(value=str(CFG.get("usb_export.max_total_mb", 0)))
        self.v_ue_ow = tk.BooleanVar(value=bool(CFG.get("usb_export.overwrite", False)))
        self.v_ue_once = tk.BooleanVar(value=bool(CFG.get("usb_export.once_per_insert", True)))

        r = 0
        ttk.Label(f, text="保存到文件夹").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.v_dest, width=44).grid(row=r, column=1, sticky="w")

        def pick_dest():
            d = filedialog.askdirectory(initialdir=self.v_dest.get() or "D:\\")
            if d:
                self.v_dest.set(d)

        ttk.Button(f, text="浏览…", width=8, command=pick_dest).grid(row=r, column=2, pady=3)
        r += 1
        ttk.Label(f, text="子文件夹").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Combobox(f, textvariable=self.v_sub, width=12, state="readonly",
                     values=["none", "date", "source", "type"]).grid(row=r, column=1, sticky="w")
        ttk.Label(f, text="none=平铺  date=按日期  source=按来源文件夹  type=按类型").grid(
            row=r, column=2, sticky="w")
        r += 1
        ttk.Label(f, text="检测间隔（秒）").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.v_interval, width=10).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="忽略小于（KB）").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.v_min, width=10).grid(row=r, column=1, sticky="w")
        ttk.Label(f, text="0 = 不限制").grid(row=r, column=2, sticky="w")
        r += 1
        ttk.Label(f, text="同名文件").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Combobox(f, textvariable=self.v_exists, width=14, state="readonly",
                     values=["rename", "rename_always", "overwrite", "skip"]).grid(
            row=r, column=1, sticky="w")
        ttk.Label(f, text="rename=内容变了才另存(2)   rename_always=同名就另存"
                          "   overwrite=覆盖   skip=跳过").grid(row=r, column=2, sticky="w")
        r += 1
        ttk.Label(f, text="　（老师更新了课件：选 rename 就会自动存成「xxx (2)」）",
                  fg="#888", font=("Microsoft YaHei UI", 8)).grid(
            row=r, column=1, columnspan=2, sticky="w")
        r += 1

        ttk.Separator(f).grid(row=r, column=0, columnspan=3, sticky="ew", pady=8)
        r += 1
        ttk.Label(f, text="顺便拷同目录（默认全关）",
                  font=("Microsoft YaHei UI", 9, "bold")).grid(
            row=r, column=0, columnspan=3, sticky="w")
        r += 1
        ttk.Checkbutton(f, text="复制该文件同目录下的所有文件（只这一层，不进子文件夹）",
                        variable=self.v_sib).grid(row=r, column=0, columnspan=3,
                                                  sticky="w", pady=2)
        r += 1
        ttk.Checkbutton(f, text="连同子文件夹一起递归拷（拷全部文件，保留目录结构）",
                        variable=self.v_sib_rec, command=self._sync_sib).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=2)
        r += 1
        ttk.Checkbutton(f, text="放进「目标/源文件夹名/」子目录（推荐，避免平铺重名）",
                        variable=self.v_sib_sub).grid(row=r, column=0, columnspan=3,
                                                      sticky="w", pady=2)
        r += 1
        for label, var, note in (
            ("　单次最多拷（个）", self.v_sib_max, "防止一个目录几百个文件把程序拖慢"),
            ("　单文件上限（MB）", self.v_sib_size, "超过就跳过"),
        ):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=2)
            ttk.Entry(f, textvariable=var, width=10).grid(row=r, column=1, sticky="w")
            ttk.Label(f, text=note).grid(row=r, column=2, sticky="w")
            r += 1
        ttk.Label(f, text="　说明：抓到课件时，顺手把同一个文件夹里的其他文件也拷走。"
                          "勾第二项时会自动勾上第一项。",
                  fg="#888", font=("Microsoft YaHei UI", 8)).grid(
            row=r, column=1, columnspan=2, sticky="w")
        r += 1

        ttk.Separator(f).grid(row=r, column=0, columnspan=3, sticky="ew", pady=8)
        r += 1
        ttk.Label(f, text="抓哪些文件", font=("Microsoft YaHei UI", 9, "bold")).grid(
            row=r, column=0, columnspan=3, sticky="w")
        r += 1
        ttk.Checkbutton(f, text="PowerPoint / WPS 演示", variable=self.v_ppt).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=2)
        r += 1
        ttk.Label(f, text="　PPT 抓取时机").grid(row=r, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.v_ppt_mode, width=14, state="readonly",
                     values=["slideshow", "open"]).grid(row=r, column=1, sticky="w")
        ttk.Label(f, text="slideshow=只在放映时拷  open=打开就拷").grid(row=r, column=2, sticky="w")
        r += 1
        ttk.Checkbutton(f, text="Word / WPS 文档（打开就抓）", variable=self.v_doc).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=2)
        r += 1
        ttk.Checkbutton(f, text="PDF（阅读器或浏览器里打开的）", variable=self.v_pdf).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=2)
        r += 1
        ttk.Checkbutton(f, text="PDF 深度扫描（扫全部进程，更全但更慢）", variable=self.v_deep).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=2)
        r += 1

        ttk.Separator(f).grid(row=r, column=0, columnspan=3, sticky="ew", pady=8)
        r += 1
        ttk.Label(f, text="U 盘模式（全盘扫描，默认关）",
                  font=("Microsoft YaHei UI", 9, "bold")).grid(row=r, column=0, columnspan=3, sticky="w")
        r += 1
        ttk.Checkbutton(f, text="U 盘模式：插上 U 盘自动拷里面的 PPT / Word / PDF",
                        variable=self.v_usb).grid(row=r, column=0, columnspan=3, sticky="w", pady=2)
        r += 1
        for label, var, note in (
            ("　重扫间隔（秒）", self.v_usb_int, "同一个盘多久再扫一次"),
            ("　单次最多拷（个）", self.v_usb_max, "防止超大移动硬盘把程序卡死"),
            ("　单文件上限（MB）", self.v_usb_size, "超过就跳过"),
            ("　最多翻几层", self.v_usb_depth, "文件夹深度"),
        ):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=2)
            ttk.Entry(f, textvariable=var, width=10).grid(row=r, column=1, sticky="w")
            ttk.Label(f, text=note).grid(row=r, column=2, sticky="w")
            r += 1
        ttk.Label(f, text="　U 盘文件放哪").grid(row=r, column=0, sticky="w", pady=2)
        ttk.Combobox(f, textvariable=self.v_usb_sub, width=12, state="readonly",
                     values=["label", "tree", "none"]).grid(row=r, column=1, sticky="w")
        ttk.Label(f, text="label=按U盘名  tree=保留U盘内目录  none=平铺").grid(row=r, column=2, sticky="w")
        r += 1

        ttk.Separator(f).grid(row=r, column=0, columnspan=3, sticky="ew", pady=8)
        r += 1
        ttk.Label(f, text="U 盘导出（电脑 → U 盘，默认关）",
                  font=("Microsoft YaHei UI", 9, "bold")).grid(
            row=r, column=0, columnspan=3, sticky="w")
        r += 1
        ttk.Checkbutton(f, text="U 盘根目录有隐藏触发文件时，把课件文件夹拷到 U 盘",
                        variable=self.v_ue).grid(row=r, column=0, columnspan=3,
                                                 sticky="w", pady=2)
        r += 1
        ttk.Label(f, text="　触发文件名").grid(row=r, column=0, sticky="w", pady=2)
        ttk.Entry(f, textvariable=self.v_ue_file, width=10).grid(row=r, column=1, sticky="w")
        ttk.Label(f, text="默认 f　U 盘根目录下，内容 1 就触发").grid(row=r, column=2, sticky="w")
        r += 1
        ttk.Checkbutton(f, text="必须是隐藏文件（attrib +h f）",
                        variable=self.v_ue_hidden).grid(row=r, column=0, columnspan=3,
                                                        sticky="w", pady=2)
        r += 1
        ttk.Label(f, text="　触发内容").grid(row=r, column=0, sticky="w", pady=2)
        ttk.Entry(f, textvariable=self.v_ue_val, width=10).grid(row=r, column=1, sticky="w")
        ttk.Label(f, text="留空 = 任何非空内容都触发").grid(row=r, column=2, sticky="w")
        r += 1
        ttk.Label(f, text="　拷到 U 盘的").grid(row=r, column=0, sticky="w", pady=2)
        ttk.Entry(f, textvariable=self.v_ue_sub, width=14).grid(row=r, column=1, sticky="w")
        ttk.Label(f, text="子文件夹名，留空 = U 盘根目录").grid(row=r, column=2, sticky="w")
        r += 1
        for label, var, note in (
            ("　检查间隔（秒）", self.v_ue_int, "多久看一眼有没有触发文件"),
            ("　单次最多拷（个）", self.v_ue_max, "上限保护"),
            ("　单文件上限（MB）", self.v_ue_size, "超过就跳过"),
            ("　总量上限（MB）", self.v_ue_total, "0 = 不限制"),
        ):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=2)
            ttk.Entry(f, textvariable=var, width=10).grid(row=r, column=1, sticky="w")
            ttk.Label(f, text=note).grid(row=r, column=2, sticky="w")
            r += 1
        ttk.Checkbutton(f, text="同名直接覆盖（不勾 = 已有的跳过）",
                        variable=self.v_ue_ow).grid(row=r, column=0, columnspan=3,
                                                    sticky="w", pady=2)
        r += 1
        ttk.Checkbutton(f, text="同一个盘每次插入只导一次（拔掉重插才会再导）",
                        variable=self.v_ue_once).grid(row=r, column=0, columnspan=3,
                                                      sticky="w", pady=2)
        r += 1
        ttk.Label(f, text="　用法：U 盘根目录建一个文件 f，内容写 1，然后 attrib +h f。"
                          "插上来就自动把课件拷进 U 盘的「课件」文件夹。",
                  fg="#888", font=("Microsoft YaHei UI", 8)).grid(
            row=r, column=1, columnspan=2, sticky="w")
        r += 1
        ttk.Button(f, text="立即导出课件到 U 盘",
                   command=lambda: self.app.on_export_usb(True)).grid(
            row=r, column=1, sticky="w", pady=4)
        r += 1

        btns = ttk.Frame(f)
        btns.grid(row=r, column=0, columnspan=3, sticky="w", pady=10)
        ttk.Button(btns, text="立即检查一次", command=lambda: self.app.on_scan_now()).pack(side="left", padx=3)
        ttk.Button(btns, text="立即扫一次 U 盘", command=lambda: self.app.on_scan_usb(True)).pack(side="left", padx=3)
        ttk.Button(btns, text="打开课件文件夹", command=lambda: self.app.on_open_dest()).pack(side="left", padx=3)
        ttk.Button(btns, text="清空复制记录", command=lambda: self.app.on_clear_records()).pack(side="left", padx=3)

    # ============================================================ ③ 开机启动 & 守护
    def _build_boot(self, nb):
        f = self._tab(nb, "③ 开机启动 & 守护")

        self.v_launch_int = tk.StringVar(value=str(CFG.get("launch.interval", 1.0)))
        self.v_launch_desk = tk.BooleanVar(value=bool(CFG.get("launch.show_desktop_after", False)))
        self.v_launch_focus = tk.BooleanVar(value=bool(CFG.get("launch.restore_focus", True)))
        self.v_watch_int = tk.StringVar(value=str(CFG.get("watch.check_interval", 3)))
        self.v_watch_delay = tk.StringVar(value=str(CFG.get("watch.restart_delay", 30)))

        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text="启动间隔（秒）").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(top, textvariable=self.v_launch_int, width=8).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(top, text="全部启动完显示桌面", variable=self.v_launch_desk).grid(
            row=0, column=2, sticky="w", padx=10)
        ttk.Checkbutton(top, text="启动完把焦点还回原窗口", variable=self.v_launch_focus).grid(
            row=0, column=3, sticky="w")
        ttk.Label(top, text="守护检测间隔（秒）").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(top, textvariable=self.v_watch_int, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(top, text="默认重启延迟（秒）").grid(row=1, column=2, sticky="w", padx=10)
        ttk.Entry(top, textvariable=self.v_watch_delay, width=8).grid(row=1, column=3, sticky="w")

        paned = ttk.PanedWindow(f, orient=tk.VERTICAL)
        paned.pack(fill="both", expand=True, pady=8)

        # ---- 启动项 ----
        box1 = ttk.LabelFrame(paned, text="开机启动项 [Launch]（开机后自动打开，可单独关掉）", padding=6)
        paned.add(box1, weight=1)
        self.tree_launch = self._mk_tree(box1, ("名称", "启用", "程序", "状态"))
        b1 = ttk.Frame(box1)
        b1.pack(fill="x", pady=4)
        ttk.Button(b1, text="新增", command=lambda: self._edit_app("launch")).pack(side="left", padx=2)
        ttk.Button(b1, text="编辑", command=lambda: self._edit_app("launch", False)).pack(side="left", padx=2)
        ttk.Button(b1, text="删除", command=lambda: self._del_app("launch")).pack(side="left", padx=2)
        ttk.Button(b1, text="启用/停用", command=lambda: self._toggle_app("launch")).pack(side="left", padx=2)
        ttk.Button(b1, text="立即启动", command=lambda: self._launch_one("launch")).pack(side="left", padx=2)
        ttk.Button(b1, text="全部启动", command=lambda: self.app.on_launch_all()).pack(side="left", padx=2)

        # ---- 守护项 ----
        box2 = ttk.LabelFrame(paned, text="守护项 [Watch]（关掉 N 秒后自动重新打开）", padding=6)
        paned.add(box2, weight=1)
        self.tree_watch = self._mk_tree(box2, ("名称", "启用", "程序", "进程名", "状态"))
        b2 = ttk.Frame(box2)
        b2.pack(fill="x", pady=4)
        ttk.Button(b2, text="新增", command=lambda: self._edit_app("watch")).pack(side="left", padx=2)
        ttk.Button(b2, text="编辑", command=lambda: self._edit_app("watch", False)).pack(side="left", padx=2)
        ttk.Button(b2, text="删除", command=lambda: self._del_app("watch")).pack(side="left", padx=2)
        ttk.Button(b2, text="启用/停用", command=lambda: self._toggle_app("watch")).pack(side="left", padx=2)
        ttk.Button(b2, text="立即启动", command=lambda: self._launch_one("watch")).pack(side="left", padx=2)
        ttk.Button(b2, text="暂停/继续守护", command=lambda: self.app.on_toggle_pause_guard()).pack(side="left", padx=2)
        ttk.Button(b2, text="结束选中", command=lambda: self._stop_one("watch")).pack(side="left", padx=2)

        ttk.Label(f, text="提示：守护项最容易填错的是『进程名』——去任务管理器详细信息里看真实的 .exe 名。",
                  foreground="#888").pack(anchor="w")
        self._fill_app_trees()

    def _mk_tree(self, parent, cols):
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=6)
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=120 if c not in ("程序",) else 260)
        tree.pack(fill="both", expand=True)
        return tree

    def _fill_app_trees(self):
        for tree, items, extra in ((self.tree_launch, self.launch_items, False),
                                   (self.tree_watch, self.watch_items, True)):
            for i in tree.get_children():
                tree.delete(i)
            for it in items:
                if extra:      # 守护项多一列"进程名"
                    vals = (it.name, "是" if it.enabled else "否", it.path,
                            it.process, it.status)
                else:
                    vals = (it.name, "是" if it.enabled else "否", it.path, it.status)
                tree.insert("", "end", values=vals)

    def _selected(self, kind):
        tree = self.tree_launch if kind == "launch" else self.tree_watch
        items = self.launch_items if kind == "launch" else self.watch_items
        sel = tree.selection()
        if not sel:
            return None, None
        idx = tree.index(sel[0])
        if 0 <= idx < len(items):
            return items[idx], tree
        return None, tree

    def _edit_app(self, kind, new: bool = True):
        item, tree = self._selected(kind)
        if new or item is None:
            item = AppItem(kind=kind, name="新项%d" % (len(self.launch_items if kind == "launch"
                                                      else self.watch_items) + 1))
        fields = [
            ("名称", "name", "text", None),
            ("程序路径", "path", "file", None),
            ("启动参数", "args", "text", None),
            ("工作目录（可空）", "workdir", "dir", None),
            ("启用", "enabled", "bool", None),
            ("启动方式", "background", "combo", ["1=后台最小化不抢焦点", "0=正常前台", "2=完全隐藏"]),
            ("启动前延迟（秒）", "delay", "float", None),
        ]
        if kind == "watch":
            fields += [
                ("进程名（留空取文件名）", "process", "text", None),
                ("关闭后多少秒重启", "restart_delay", "float", None),
                ("程序初启时没运行就立刻拉起", "start_when_missing", "bool", None),
            ]
        vals = item.to_dict()
        vals["_hint"] = ("启动方式填 1 最省心：最小化启动、不抢前台焦点。"
                         if kind == "launch" else
                         "进程名很关键：填错会一直重复启动。任务管理器 → 详细信息里看真实进程名。")
        dlg = FormDialog(self.root, "编辑%s项" % ("启动" if kind == "launch" else "守护"), fields, vals)
        if not dlg.result:
            return
        data = dict(dlg.result)
        bg = str(data.get("background", "1"))
        data["background"] = int(bg.split("=")[0]) if "=" in bg else int(bg or 1)
        new_item = AppItem.from_dict(data, kind)
        lst = self.launch_items if kind == "launch" else self.watch_items
        if new:
            lst.append(new_item)
        else:
            _, tree2 = self._selected(kind)
            if tree2 is not None and tree2.selection():
                lst[tree2.index(tree2.selection()[0])] = new_item
        self._fill_app_trees()

    def _del_app(self, kind):
        item, tree = self._selected(kind)
        if item is None:
            return
        lst = self.launch_items if kind == "launch" else self.watch_items
        idx = tree.index(tree.selection()[0])
        if 0 <= idx < len(lst):
            lst.pop(idx)
        self._fill_app_trees()

    def _toggle_app(self, kind):
        item, _ = self._selected(kind)
        if item is None:
            return
        item.enabled = not item.enabled
        self._fill_app_trees()

    def _launch_one(self, kind):
        item, _ = self._selected(kind)
        if item is None:
            return
        self.app.guard.launch(item, force=True)
        self._fill_app_trees()

    def _stop_one(self, kind):
        item, _ = self._selected(kind)
        if item is None:
            return
        self.app.guard.stop(item)
        self._fill_app_trees()

    # ============================================================ ④ 文件关联
    def _build_assoc(self, nb):
        f = self._tab(nb, "④ 文件关联")

        self.v_assoc_delay = tk.StringVar(value=str(CFG.get("assoc.delay", 8)))
        self.v_assoc_auto = tk.BooleanVar(value=bool(CFG.get("assoc.apply_on_start", False)))

        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Checkbutton(top, text="程序启动时自动应用（默认关）", variable=self.v_assoc_auto).pack(side="left")
        ttk.Label(top, text="　开机后延迟（秒）").pack(side="left")
        ttk.Entry(top, textvariable=self.v_assoc_delay, width=8).pack(side="left")
        ttk.Label(top, text="　等系统就绪再改，避免抢在 Explorer 前面").pack(side="left")

        self.tree_assoc = ttk.Treeview(f, columns=("名称", "启用", "扩展名", "打开程序", "当前打开程序"),
                                       show="headings", height=10)
        for c, w in (("名称", 130), ("启用", 50), ("扩展名", 160), ("打开程序", 230), ("当前打开程序", 150)):
            self.tree_assoc.heading(c, text=c)
            self.tree_assoc.column(c, width=w)
        self.tree_assoc.pack(fill="both", expand=True, pady=8)

        b = ttk.Frame(f)
        b.pack(fill="x")
        ttk.Button(b, text="新增", command=lambda: self._edit_assoc(True)).pack(side="left", padx=2)
        ttk.Button(b, text="编辑", command=lambda: self._edit_assoc(False)).pack(side="left", padx=2)
        ttk.Button(b, text="删除", command=self._del_assoc).pack(side="left", padx=2)
        ttk.Button(b, text="启用/停用", command=self._toggle_assoc).pack(side="left", padx=2)
        ttk.Button(b, text="立即应用选中", command=lambda: self._apply_assoc(False)).pack(side="left", padx=2)
        ttk.Button(b, text="立即应用全部", command=lambda: self._apply_assoc(True)).pack(side="left", padx=2)
        ttk.Button(b, text="还原选中", command=self._revert_assoc).pack(side="left", padx=2)
        ttk.Button(b, text="刷新状态", command=self._fill_assoc_tree).pack(side="left", padx=2)

        ttk.Label(f, text="原理（都在 HKEY_CURRENT_USER 下，不需管理员）：删掉 UserChoice → "
                          "写自己的 ProgId → 扩展名指向它 → 广播刷新。",
                  foreground="#888", wraplength=800, justify="left").pack(anchor="w", pady=4)
        self._fill_assoc_tree()

    def _fill_assoc_tree(self):
        for i in self.tree_assoc.get_children():
            self.tree_assoc.delete(i)
        for it in self.assoc_items:
            cur = "—"
            if it.exts():
                try:
                    info = assoc_mod.query_assoc(it.exts()[0])
                    cur = assoc_mod.describe_command(info.get("command"))
                    if info.get("locked"):
                        cur += "（被用户选择锁定）"
                except Exception:
                    cur = "查询失败"
            self.tree_assoc.insert("", "end", values=(it.name, "是" if it.enabled else "否",
                                                      it.ext, it.exe, cur))

    def _sel_assoc(self):
        sel = self.tree_assoc.selection()
        if not sel:
            return None
        idx = self.tree_assoc.index(sel[0])
        return self.assoc_items[idx] if 0 <= idx < len(self.assoc_items) else None

    def _edit_assoc(self, new: bool = True):
        item = None if new else self._sel_assoc()
        if new or item is None:
            item = AssocItem(name="新关联%d" % (len(self.assoc_items) + 1))
        fields = [
            ("名称", "name", "text", None),
            ("扩展名（多个用分号）", "ext", "combo", list(assoc_mod.EXT_PRESETS.values())),
            ("用哪个程序打开", "exe", "file", None),
            ("参数（一般别动）", "args", "text", None),
            ("启用", "enabled", "bool", None),
        ]
        vals = item.to_dict()
        vals["_hint"] = "扩展名可以直接在下拉里选常用组合，也可以自己写，比如 .pptx;.ppt"
        dlg = FormDialog(self.root, "编辑文件关联", fields, vals)
        if not dlg.result:
            return
        new_item = AssocItem.from_dict(dlg.result)
        if new:
            self.assoc_items.append(new_item)
        else:
            idx = self.tree_assoc.index(self.tree_assoc.selection()[0])
            self.assoc_items[idx] = new_item
        self._fill_assoc_tree()

    def _del_assoc(self):
        it = self._sel_assoc()
        if it is None:
            return
        idx = self.tree_assoc.index(self.tree_assoc.selection()[0])
        self.assoc_items.pop(idx)
        self._fill_assoc_tree()

    def _toggle_assoc(self):
        it = self._sel_assoc()
        if it is None:
            return
        it.enabled = not it.enabled
        self._fill_assoc_tree()

    def _apply_assoc(self, all_items: bool):
        targets = self.assoc_items if all_items else ([self._sel_assoc()] if self._sel_assoc() else [])
        targets = [t for t in targets if t and t.enabled]
        if not targets:
            messagebox.showinfo("文件关联", "没有可应用的启用项")
            return
        ok = 0
        for t in targets:
            good, msg = assoc_mod.apply_assoc(t)
            ok += 1 if good else 0
            t.status = "已应用" if good else msg
        self.app.save_assoc_backups(self.assoc_items)
        self._fill_assoc_tree()
        messagebox.showinfo("文件关联", "已应用 %d/%d 项" % (ok, len(targets)))

    def _revert_assoc(self):
        it = self._sel_assoc()
        if it is None:
            return
        assoc_mod.revert_assoc(it)
        self.app.save_assoc_backups(self.assoc_items)
        self._fill_assoc_tree()

    # ============================================================ ⑤ 定时任务
    def _build_tasks(self, nb):
        f = self._tab(nb, "⑤ 定时任务")

        self.v_task_int = tk.StringVar(value=str(CFG.get("tasks.check_interval", 20)))
        self.v_warn = tk.StringVar(value=str(CFG.get("tasks.shutdown_warn", 60)))
        self.v_wake = tk.BooleanVar(value=bool(CFG.get("tasks.enable_wake", False)))

        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text="检查间隔（秒）").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.v_task_int, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(top, text="　关机缓冲（秒）").grid(row=0, column=2, sticky="w")
        ttk.Entry(top, textvariable=self.v_warn, width=8).grid(row=0, column=3, sticky="w")
        ttk.Checkbutton(top, text="允许定时唤醒（实验性，仅睡眠/休眠有效）",
                        variable=self.v_wake).grid(row=0, column=4, sticky="w")

        self.tree_task = ttk.Treeview(f, columns=("名称", "启用", "动作", "计划", "下次执行", "状态"),
                                      show="headings", height=10)
        for c, w in (("名称", 130), ("启用", 50), ("动作", 90), ("计划", 170), ("下次执行", 150), ("状态", 140)):
            self.tree_task.heading(c, text=c)
            self.tree_task.column(c, width=w)
        self.tree_task.pack(fill="both", expand=True, pady=8)

        b = ttk.Frame(f)
        b.pack(fill="x")
        ttk.Button(b, text="新增", command=lambda: self._edit_task(True)).pack(side="left", padx=2)
        ttk.Button(b, text="编辑", command=lambda: self._edit_task(False)).pack(side="left", padx=2)
        ttk.Button(b, text="删除", command=self._del_task).pack(side="left", padx=2)
        ttk.Button(b, text="启用/停用", command=self._toggle_task).pack(side="left", padx=2)
        ttk.Button(b, text="立即执行", command=self._run_task).pack(side="left", padx=2)
        ttk.Button(b, text="刷新", command=self._fill_task_tree).pack(side="left", padx=2)

        p = ttk.Frame(f)
        p.pack(fill="x", pady=6)
        ttk.Label(p, text="电源快捷：").pack(side="left")
        for text, kind in (("60 秒后关机", "shutdown60"), ("立刻关机", "shutdown"), ("重启", "reboot"),
                           ("睡眠", "sleep"), ("休眠", "hibernate"), ("锁屏", "lock"),
                           ("取消关机", "cancel")):
            ttk.Button(p, text=text, command=lambda k=kind: self.app.on_power(k)).pack(side="left", padx=2)

        ttk.Label(f, text="计划写法：daily 每天 / weekly 每周（周几填 3,5 或 周三,周五）/ "
                          "interval 每隔（50d、12h、30m，纯数字按分钟）/ once 指定日期时间",
                  foreground="#888", wraplength=800, justify="left").pack(anchor="w")
        self._fill_task_tree()

    def _fill_task_tree(self):
        for i in self.tree_task.get_children():
            self.tree_task.delete(i)
        for t in self.task_items:
            self.tree_task.insert("", "end", values=(
                t.name, "是" if t.enabled else "否", t.action_label(), t.schedule_text(),
                tasks_mod.describe_next(t) if t.next_run else "—", t.status))

    def _sel_task(self):
        sel = self.tree_task.selection()
        if not sel:
            return None
        idx = self.tree_task.index(sel[0])
        return self.task_items[idx] if 0 <= idx < len(self.task_items) else None

    def _edit_task(self, new: bool = True):
        item = None if new else self._sel_task()
        if new or item is None:
            item = TaskItem(name="新任务%d" % (len(self.task_items) + 1))
        fields = [
            ("名称", "name", "text", None),
            ("动作", "action", "combo", ["launch=启动软件", "shutdown=关机", "reboot=重启",
                                         "sleep=睡眠", "hibernate=休眠", "lock=锁屏"]),
            ("计划", "schedule", "combo", ["daily=每天", "weekly=每周几", "interval=每隔",
                                           "once=指定时刻一次"]),
            ("程序路径（动作=launch 时必填）", "path", "file", None),
            ("启动参数", "args", "text", None),
            ("时间 HH:MM", "time", "text", None),
            ("日期 YYYY-MM-DD（once 用）", "date", "text", None),
            ("周几（weekly 用，1=周一…7=周日）", "weekdays", "text", None),
            ("间隔（interval 用，如 50d / 12h / 30m）", "interval", "text", None),
            ("错过了就补做一次", "catch_up", "bool", None),
            ("定时唤醒（需电源设置允许）", "wake", "bool", None),
            ("启用", "enabled", "bool", None),
        ]
        vals = item.to_dict()
        vals["_hint"] = "例子：每天 23:30 关机 —— 动作 shutdown，计划 daily，时间 23:30"
        dlg = FormDialog(self.root, "编辑定时任务", fields, vals)
        if not dlg.result:
            return
        d = dict(dlg.result)
        for k in ("action", "schedule"):
            if "=" in str(d.get(k, "")):
                d[k] = str(d[k]).split("=")[0]
        new_item = TaskItem.from_dict(d)
        if new:
            self.task_items.append(new_item)
        else:
            idx = self.tree_task.index(self.tree_task.selection()[0])
            self.task_items[idx] = new_item
        self._fill_task_tree()

    def _del_task(self):
        if self._sel_task() is None:
            return
        idx = self.tree_task.index(self.tree_task.selection()[0])
        self.task_items.pop(idx)
        self._fill_task_tree()

    def _toggle_task(self):
        t = self._sel_task()
        if t is None:
            return
        t.enabled = not t.enabled
        self._fill_task_tree()

    def _run_task(self):
        t = self._sel_task()
        if t is None:
            return
        warn = float(CFG.get("tasks.shutdown_warn", 60) or 60)
        result = tasks_mod.run_action(t, warn)
        messagebox.showinfo("定时任务", "执行结果：%s" % result)

    # ============================================================ ⑥ 程序守护器
    def _build_protect(self, nb):
        f = self._tab(nb, "⑥ 程序守护器")

        self.v_p_target = tk.StringVar(value=CFG.get("protect.target", ""))
        self.v_p_args = tk.StringVar(value=CFG.get("protect.args", ""))
        self.v_p_workdir = tk.StringVar(value=CFG.get("protect.workdir", ""))
        self.v_p_delay = tk.StringVar(value=str(CFG.get("protect.restart_delay", 2)))
        self.v_p_max = tk.StringVar(value=str(CFG.get("protect.max_restart", 0)))
        self.v_p_mutual = tk.BooleanVar(value=bool(CFG.get("protect.mutual", False)))
        self.v_p_ctrl = tk.BooleanVar(value=bool(CFG.get("protect.ignore_ctrl", True)))
        self.v_p_status = tk.StringVar(value="状态：%s" % (self.app.protect.status
                                                       if self.app.protect else "未启动"))

        r = 0
        ttk.Label(f, text="要守护的程序").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_p_target, width=48).grid(row=r, column=1, sticky="w")

        def pick_exe():
            p = filedialog.askopenfilename(title="选择要守护的程序",
                                           filetypes=[("程序", "*.exe"), ("所有文件", "*.*")])
            if p:
                self.v_p_target.set(p)

        ttk.Button(f, text="浏览…", width=8, command=pick_exe).grid(row=r, column=2)
        r += 1
        ttk.Label(f, text="启动参数").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_p_args, width=48).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="工作目录（可空）").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_p_workdir, width=48).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="重启延迟（秒）").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_p_delay, width=10).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="最大重启次数（0=不限）").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_p_max, width=10).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Checkbutton(f, text="双进程互保：再开一个伙伴进程盯着本程序，本程序被杀就拉起来",
                        variable=self.v_p_mutual).grid(row=r, column=0, columnspan=3, sticky="w", pady=3)
        r += 1
        ttk.Checkbutton(f, text="忽略 Ctrl+C / Ctrl+Break（防止控制台里被中断）",
                        variable=self.v_p_ctrl).grid(row=r, column=0, columnspan=3, sticky="w", pady=3)
        r += 1

        b = ttk.Frame(f)
        b.grid(row=r, column=0, columnspan=3, sticky="w", pady=8)
        ttk.Button(b, text="立即启动目标程序", command=lambda: self.app.on_protect_start()).pack(side="left", padx=3)
        ttk.Button(b, text="停止目标程序", command=lambda: self.app.on_protect_stop()).pack(side="left", padx=3)
        ttk.Button(b, text="刷新状态", command=self._refresh_protect).pack(side="left", padx=3)
        r += 1
        ttk.Label(f, textvariable=self.v_p_status, foreground="#333").grid(
            row=r, column=0, columnspan=3, sticky="w")
        r += 1
        ttk.Label(f, text="说清楚：软件层面挡不住管理员权限的 taskkill /F（系统级终止）。"
                          "能做的是被杀后 1~2 秒自动拉起，双进程互保可以再提高存活率。",
                  foreground="#888", wraplength=800, justify="left").grid(
            row=r, column=0, columnspan=3, sticky="w", pady=6)

    def _refresh_protect(self):
        st = self.app.protect.status if self.app.protect else "未启动"
        self.v_p_status.set("状态：%s" % st)

    # ============================================================ ⑦ 中育助手
    def _build_zy(self, nb):
        f = self._tab(nb, "⑦ 中育助手")

        self.v_z_log = tk.StringVar(value=CFG.get("zy.log_path", ""))
        self.v_z_dir = tk.StringVar(value=CFG.get("zy.app_dir", ""))
        self.v_z_exe = tk.StringVar(value=CFG.get("zy.app_exe", "CloudRoom.Main.exe"))
        self.v_z_int = tk.StringVar(value=str(CFG.get("zy.refresh_interval", 5)))
        self.v_z_wait = tk.StringVar(value=str(CFG.get("zy.wait_seconds", 8)))
        self.v_z_auto = tk.BooleanVar(value=bool(CFG.get("zy.auto_start_zy", False)))
        self.v_z_overlay = tk.BooleanVar(value=bool(CFG.get("zy.show_overlay", False)))
        self.v_z_num = tk.StringVar(value="课堂号：%s" % zy_mod.read_number())

        r = 0
        ttk.Label(f, text="Log.txt 路径").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_z_log, width=52).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="中育课堂助手目录").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_z_dir, width=52).grid(row=r, column=1, sticky="w")

        def pick_dir():
            p = filedialog.askdirectory(title="选择中育课堂助手安装目录")
            if p:
                self.v_z_dir.set(p)

        ttk.Button(f, text="浏览…", width=8, command=pick_dir).grid(row=r, column=2)
        r += 1
        ttk.Label(f, text="主程序名").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_z_exe, width=24).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="刷新间隔（秒）").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_z_int, width=10).grid(row=r, column=1, sticky="w")
        ttk.Label(f, text="　启动后等待（秒）").grid(row=r, column=2, sticky="w")
        ttk.Entry(f, textvariable=self.v_z_wait, width=10).grid(row=r, column=3, sticky="w")
        r += 1
        ttk.Checkbutton(f, text="启用中育助手时自动重启一次它（结束进程→删日志→重开）",
                        variable=self.v_z_auto).grid(row=r, column=0, columnspan=3, sticky="w", pady=3)
        r += 1
        ttk.Checkbutton(f, text="常驻显示课堂号浮窗（左上角，可拖动，ESC 隐藏）",
                        variable=self.v_z_overlay).grid(row=r, column=0, columnspan=3, sticky="w", pady=3)
        r += 1

        b = ttk.Frame(f)
        b.grid(row=r, column=0, columnspan=3, sticky="w", pady=8)
        ttk.Button(b, text="重启中育助手", command=lambda: self.app.on_zy_restart()).pack(side="left", padx=3)
        ttk.Button(b, text="显示/隐藏浮窗", command=lambda: self.app.on_zy_overlay()).pack(side="left", padx=3)
        ttk.Button(b, text="读一次课堂号", command=self._read_num).pack(side="left", padx=3)
        ttk.Button(b, text="打开安装目录", command=lambda: zy_mod.open_zy_dir()).pack(side="left", padx=3)
        r += 1
        ttk.Label(f, textvariable=self.v_z_num, font=("Consolas", 14, "bold"),
                  foreground="blue").grid(row=r, column=0, columnspan=3, sticky="w", pady=6)
        r += 1
        ttk.Label(f, text="课堂号取自 Log.txt 第 3 行末尾 4 位数字；若含有小数点则改取第 4 行（与原脚本一致）。",
                  foreground="#888", wraplength=800, justify="left").grid(
            row=r, column=0, columnspan=3, sticky="w")

    def _read_num(self):
        info = zy_mod.read_info()
        code = info.get("code") or "----"
        extra = info.get("ip") or ""
        tail = "　来源：%s" % (info.get("src") or "—")
        if extra:
            tail = "　IP：%s" % extra + tail
        self.v_z_num.set("课堂号：%s%s" % (code, tail))

    # ============================================================ ⑧ 云笔助手面板
    def _build_pen(self, nb):
        f = self._tab(nb, "⑧ 云笔面板")

        self.v_p_auto = tk.BooleanVar(value=bool(CFG.get("pen.auto_start_zy", True)))
        self.v_p_wait = tk.StringVar(value=str(CFG.get("pen.wait_seconds", 8.0)))
        self.v_p_int = tk.StringVar(value=str(CFG.get("pen.refresh_interval", 3.0)))
        self.v_p_ratio = tk.StringVar(value=str(CFG.get("pen.height_ratio", 0.62)))
        self.v_p_top = tk.BooleanVar(value=bool(CFG.get("pen.topmost", False)))
        self.v_p_hue = tk.DoubleVar(value=float(CFG.get("pen.hue", 205.0)))
        self.v_p_depth = tk.DoubleVar(value=float(CFG.get("pen.depth", 0.0)))
        self.v_p_sat = tk.DoubleVar(value=float(CFG.get("pen.sat", 0.0)))
        self.v_p_preview = tk.StringVar(value="")

        r = 0
        ttk.Checkbutton(f, text="打开面板时，若中育课堂助手没在运行就先启动它",
                        variable=self.v_p_auto).grid(row=r, column=0, columnspan=4,
                                                     sticky="w", pady=3)
        r += 1
        ttk.Checkbutton(f, text="面板置顶显示", variable=self.v_p_top).grid(
            row=r, column=0, columnspan=4, sticky="w", pady=3)
        r += 1
        ttk.Label(f, text="启动后等待（秒）").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_p_wait, width=8).grid(row=r, column=1, sticky="w")
        ttk.Label(f, text="　刷新间隔（秒）").grid(row=r, column=2, sticky="w")
        ttk.Entry(f, textvariable=self.v_p_int, width=8).grid(row=r, column=3, sticky="w")
        r += 1
        ttk.Label(f, text="窗口高度占屏比").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_p_ratio, width=8).grid(row=r, column=1, sticky="w")
        ttk.Label(f, text="　（0.3 ~ 0.9，越大窗口越大）").grid(row=r, column=2,
                                                              columnspan=2, sticky="w")
        r += 1

        ttk.Separator(f, orient="horizontal").grid(row=r, column=0, columnspan=4,
                                                   sticky="ew", pady=8)
        r += 1
        ttk.Label(f, text="配色（保感知亮度：亮端 L=155 在中下部、暗端 L=101 在四周）",
                  foreground="#555").grid(row=r, column=0, columnspan=4, sticky="w")
        r += 1
        for label, var, lo, hi in (("色相（190偏青 / 205蓝 / 215蓝紫）", self.v_p_hue, 188, 218),
                                   ("深浅（-60更深 ~ +60更浅）", self.v_p_depth, -60, 60),
                                   ("饱和度（-40更灰 ~ +40更艳）", self.v_p_sat, -40, 40)):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Scale(f, from_=lo, to=hi, orient="horizontal", variable=var,
                      length=280, command=lambda *_: self._pen_preview()).grid(
                row=r, column=1, columnspan=3, sticky="w")
            r += 1
        ttk.Label(f, textvariable=self.v_p_preview, font=("Consolas", 10)).grid(
            row=r, column=0, columnspan=4, sticky="w", pady=4)
        r += 1

        b = ttk.Frame(f)
        b.grid(row=r, column=0, columnspan=4, sticky="w", pady=8)
        ttk.Button(b, text="打开 / 关闭面板",
                   command=lambda: self.app.on_pen_toggle()).pack(side="left", padx=3)
        ttk.Button(b, text="恢复默认配色", command=self._pen_reset).pack(side="left", padx=3)
        ttk.Button(b, text="应用配色到已打开的面板",
                   command=self._pen_apply).pack(side="left", padx=3)
        r += 1
        ttk.Label(f, text="面板默认关闭（pen.enable=False）。勾选后托盘菜单『⑦ 云笔助手面板』可随时开关。\n"
                          "面板自身右键菜单里也有『调整配色…』，可实时预览。",
                  foreground="#888", wraplength=820, justify="left").grid(
            row=r, column=0, columnspan=4, sticky="w")
        self._pen_preview()

    def _pen_preview(self):
        """按当前滑块算出两端颜色并显示（不改全局 THEME）"""
        try:
            old = (pen_mod.THEME["hue"], pen_mod.THEME["depth"], pen_mod.THEME["sat"])
            pen_mod.THEME["hue"] = float(self.v_p_hue.get())
            pen_mod.THEME["depth"] = float(self.v_p_depth.get())
            pen_mod.THEME["sat"] = float(self.v_p_sat.get())
            c, e = pen_mod.compute_bg_colors()
            pen_mod.THEME["hue"], pen_mod.THEME["depth"], pen_mod.THEME["sat"] = old
            self.v_p_preview.set("中心 rgb%s 亮度%.0f    边缘 rgb%s 亮度%.0f    色相 %.0f°"
                                 % (c, pen_mod._lum(c), e, pen_mod._lum(e),
                                    float(self.v_p_hue.get())))
        except Exception:
            pass

    def _pen_reset(self):
        self.v_p_hue.set(205.0)
        self.v_p_depth.set(0.0)
        self.v_p_sat.set(0.0)
        self._pen_preview()

    def _pen_apply(self):
        """把配色写进配置，并立即作用到已打开的面板"""
        CFG.set("pen.hue", float(self.v_p_hue.get()))
        CFG.set("pen.depth", float(self.v_p_depth.get()))
        CFG.set("pen.sat", float(self.v_p_sat.get()))
        pen_mod.sync_theme_from_cfg()
        try:
            for p in list(pen_mod._PANELS.values()):
                p.renderer._bg_key = None
                p.draw()
        except Exception:
            pass
        self.hint.set("配色已应用到已打开的面板；点『保存』才会写入 config.json")

    # ============================================================ ⑨ 日志
    def _build_log(self, nb):
        f = self._tab(nb, "⑨ 日志")
        self.log_text = tk.Text(f, wrap="word", height=24, font=("Consolas", 10))
        self.log_text.pack(fill="both", expand=True)
        sc = ttk.Scrollbar(self.log_text)
        sc.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=sc.set)
        sc.config(command=self.log_text.yview)

        b = ttk.Frame(f)
        b.pack(fill="x", pady=6)
        ttk.Button(b, text="刷新", command=self._fill_log).pack(side="left", padx=3)
        ttk.Button(b, text="用记事本打开", command=lambda: core.open_in_explorer(LOG_PATH)).pack(side="left", padx=3)
        self.v_autorefresh = tk.BooleanVar(value=True)
        ttk.Checkbutton(b, text="自动刷新（每 3 秒）", variable=self.v_autorefresh).pack(side="left", padx=10)
        self._fill_log()
        self._tick_log()

    def _fill_log(self):
        try:
            self.log_text.delete("1.0", "end")
            self.log_text.insert("end", "\n".join(core.recent_logs(300)))
            self.log_text.see("end")
        except Exception:
            pass

    def _tick_log(self):
        try:
            if self.v_autorefresh.get():
                self._fill_log()
            self.root.after(3000, self._tick_log)
        except Exception:
            pass

    # ============================================================ 保存
    def save(self):
        try:
            # 常规
            CFG.set("app_name", self.v_app_name.get().strip() or "ClassHub")
            CFG.set("notify", bool(self.v_notify.get()))
            CFG.set("start_minimized", bool(self.v_start_min.get()))
            core.set_autostart(bool(self.v_autostart.get()))
            CFG.set("autostart", bool(self.v_autostart.get()))
            for key, v in self.v_en.items():
                CFG.set(key, bool(v.get()))

            # 课件同步
            dest = self.v_dest.get().strip()
            if not dest:
                messagebox.showwarning("ClassHub", "请选择一个课件保存文件夹")
                return
            CFG.set("sync.dest", dest)
            CFG.set("sync.subfolder_mode", self.v_sub.get())
            CFG.set("sync.interval", self._num(self.v_interval.get(), 5, 1))
            CFG.set("sync.min_size_kb", self._num(self.v_min.get(), 0, 0))
            CFG.set("sync.exists_policy", self.v_exists.get())
            CFG.set("sync.copy_siblings", bool(self.v_sib.get()))
            CFG.set("sync.copy_siblings_recursive", bool(self.v_sib_rec.get()))
            CFG.set("sync.siblings_use_subfolder", bool(self.v_sib_sub.get()))
            CFG.set("sync.siblings_max_files", self._num(self.v_sib_max.get(), 200, 1))
            CFG.set("sync.siblings_max_size_mb", self._num(self.v_sib_size.get(), 200, 0))
            CFG.set("usb_export.enable", bool(self.v_ue.get()))
            CFG.set("usb_export.trigger_file", (self.v_ue_file.get() or "f").strip())
            CFG.set("usb_export.require_hidden", bool(self.v_ue_hidden.get()))
            CFG.set("usb_export.trigger_value", (self.v_ue_val.get() or "").strip())
            CFG.set("usb_export.dest_subfolder", (self.v_ue_sub.get() or "").strip())
            CFG.set("usb_export.interval", self._num(self.v_ue_int.get(), 10, 3))
            CFG.set("usb_export.max_files", self._num(self.v_ue_max.get(), 5000, 1))
            CFG.set("usb_export.max_size_mb", self._num(self.v_ue_size.get(), 500, 0))
            CFG.set("usb_export.max_total_mb", self._num(self.v_ue_total.get(), 0, 0))
            CFG.set("usb_export.overwrite", bool(self.v_ue_ow.get()))
            CFG.set("usb_export.once_per_insert", bool(self.v_ue_once.get()))
            CFG.set("sync.enable_ppt", bool(self.v_ppt.get()))
            CFG.set("sync.ppt_mode", self.v_ppt_mode.get())
            CFG.set("sync.enable_doc", bool(self.v_doc.get()))
            CFG.set("sync.enable_pdf", bool(self.v_pdf.get()))
            CFG.set("sync.deep_scan", bool(self.v_deep.get()))
            CFG.set("sync.enable_usb", bool(self.v_usb.get()))
            CFG.set("sync.usb_interval", self._num(self.v_usb_int.get(), 60, 10))
            CFG.set("sync.usb_max_files", self._num(self.v_usb_max.get(), 3000, 1))
            CFG.set("sync.usb_max_size_mb", self._num(self.v_usb_size.get(), 200, 0))
            CFG.set("sync.usb_max_depth", self._num(self.v_usb_depth.get(), 8, 1))
            CFG.set("sync.usb_subfolder", self.v_usb_sub.get())
            if CFG.get("sync.enable_usb"):
                sync_mod.USB_SCANNED.clear()

            # 开机启动 & 守护
            CFG.set("launch.interval", self._fnum(self.v_launch_int.get(), 1.0))
            CFG.set("launch.show_desktop_after", bool(self.v_launch_desk.get()))
            CFG.set("launch.restore_focus", bool(self.v_launch_focus.get()))
            CFG.set("watch.check_interval", self._fnum(self.v_watch_int.get(), 3.0))
            CFG.set("watch.restart_delay", self._fnum(self.v_watch_delay.get(), 30.0))
            CFG.set("launch.items", [i.to_dict() for i in self.launch_items])
            CFG.set("watch.items", [i.to_dict() for i in self.watch_items])

            # 文件关联
            CFG.set("assoc.apply_on_start", bool(self.v_assoc_auto.get()))
            CFG.set("assoc.delay", self._fnum(self.v_assoc_delay.get(), 8.0))
            CFG.set("assoc.items", [i.to_dict() for i in self.assoc_items])

            # 定时任务
            CFG.set("tasks.check_interval", self._fnum(self.v_task_int.get(), 20.0))
            CFG.set("tasks.shutdown_warn", self._fnum(self.v_warn.get(), 60.0))
            CFG.set("tasks.enable_wake", bool(self.v_wake.get()))
            CFG.set("tasks.items", [i.to_dict() for i in self.task_items])

            # 程序守护器
            CFG.set("protect.target", self.v_p_target.get().strip())
            CFG.set("protect.args", self.v_p_args.get().strip())
            CFG.set("protect.workdir", self.v_p_workdir.get().strip())
            CFG.set("protect.restart_delay", self._fnum(self.v_p_delay.get(), 2.0))
            CFG.set("protect.max_restart", self._num(self.v_p_max.get(), 0, 0))
            CFG.set("protect.mutual", bool(self.v_p_mutual.get()))
            CFG.set("protect.ignore_ctrl", bool(self.v_p_ctrl.get()))

            # 中育助手
            CFG.set("zy.log_path", self.v_z_log.get().strip())
            CFG.set("zy.app_dir", self.v_z_dir.get().strip())
            CFG.set("zy.app_exe", self.v_z_exe.get().strip() or "CloudRoom.Main.exe")
            CFG.set("zy.refresh_interval", self._num(self.v_z_int.get(), 5, 1))
            CFG.set("zy.wait_seconds", self._fnum(self.v_z_wait.get(), 8.0))

            # 云笔助手面板
            CFG.set("pen.auto_start_zy", bool(self.v_p_auto.get()))
            CFG.set("pen.wait_seconds", self._fnum(self.v_p_wait.get(), 8.0))
            CFG.set("pen.refresh_interval", self._fnum(self.v_p_int.get(), 3.0))
            CFG.set("pen.height_ratio",
                    min(0.9, max(0.3, self._fnum(self.v_p_ratio.get(), 0.62))))
            CFG.set("pen.topmost", bool(self.v_p_top.get()))
            CFG.set("pen.hue", float(self.v_p_hue.get()))
            CFG.set("pen.depth", float(self.v_p_depth.get()))
            CFG.set("pen.sat", float(self.v_p_sat.get()))
            pen_mod.sync_theme_from_cfg()
            CFG.set("zy.auto_start_zy", bool(self.v_z_auto.get()))
            CFG.set("zy.show_overlay", bool(self.v_z_overlay.get()))

            self.app.apply_config()
            self.hint.set("已保存并生效 —— %s" % CONFIG_PATH)
            log("设置已保存")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))
            log("设置保存失败：%s" % e)

    @staticmethod
    def _num(raw, default: int, lo: int) -> int:
        try:
            return max(lo, int(float(str(raw))))
        except Exception:
            return default

    @staticmethod
    def _fnum(raw, default: float) -> float:
        try:
            return float(str(raw))
        except Exception:
            return default
