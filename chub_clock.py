# -*- coding: utf-8 -*-
"""
================================================================================
 ClassHub · chub_clock —— 计时器浮窗（⑧）
================================================================================
一个独立小浮窗，显示正计时或倒计时，精确到秒。

- 正计时：从 00:00:00 开始往上走，显示已过时长
- 倒计时：从设定时长往下走，归零触发动作（提示 / 关机 / 锁屏 / 重新开始）

默认关闭，勾上才显示。浮窗可拖动位置，位置记进配置。
"""

from __future__ import annotations

import math
import os
import re
import threading
import time
from datetime import datetime, timedelta

from chub_core import CFG, log


# ==============================================================================
# 一、时间计算（纯逻辑，可独立测试）
# ==============================================================================
def fmt_seconds(sec: float, show_seconds: bool = True) -> str:
    """把秒数格式化成 HH:MM:SS（或 HH:MM）。负数按 0 处理。"""
    try:
        sec = float(sec)
    except Exception:
        sec = 0.0
    if sec < 0:
        sec = 0.0
    total = int(sec)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if show_seconds:
        return "%02d:%02d:%02d" % (h, m, s)
    # 不显示秒时向上取整到分钟（还有 30 秒也算 1 分钟）
    if total % 60:
        m += 1
        if m >= 60:
            m -= 60
            h += 1
    return "%02d:%02d" % (h, m)


def parse_target(text: str, now: datetime = None):
    """解析倒计时目标时刻。支持：

        18:30              今天/明天的 18:30（已过则算明天）
        2026-10-22 18:30   指定日期时刻
        2026-10-22         当天 00:00

    解析不了返回 None。
    """
    if not text or not str(text).strip():
        return None
    text = str(text).strip()
    now = now or datetime.now()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})"
                 r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh = int(m.group(4) or 0)
        mm = int(m.group(5) or 0)
        ss = int(m.group(6) or 0)
        try:
            return datetime(y, mo, d, hh, mm, ss)
        except Exception:
            return None
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", text)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        ss = int(m.group(3) or 0)
        if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
            return None
        t = now.replace(hour=hh, minute=mm, second=ss, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        return t
    return None


def countdown_total(cfg: dict = None) -> float:
    """倒计时的总时长（秒）。

    优先用 countdown_target（指定时刻），否则用 countdown_seconds（时长）。
    """
    cfg = cfg if cfg is not None else CFG.section("clock")
    t = parse_target(str(cfg.get("countdown_target", "") or ""))
    if t is not None:
        try:
            return max(0.0, (t - datetime.now()).total_seconds())
        except Exception:
            pass
    try:
        return max(0.0, float(cfg.get("countdown_seconds", 3600.0) or 0.0))
    except Exception:
        return 3600.0


def compute_display(cfg: dict = None, started_at: float = None) -> tuple:
    """算出当前该显示什么。返回 (文本, 是否归零)。

    正计时：(已过时长, False)
    倒计时：(剩余时长, 剩余<=0)
    """
    cfg = cfg if cfg is not None else CFG.section("clock")
    show_sec = bool(cfg.get("show_seconds", True))
    mode = str(cfg.get("mode", "stopwatch") or "stopwatch").lower()
    now = time.time()
    try:
        start = float(started_at if started_at is not None
                      else cfg.get("_started_at", now) or now)
    except Exception:
        start = now

    if mode == "countdown":
        total = countdown_total(cfg)
        left = total - (now - start)
        if left <= 0:
            return (fmt_seconds(0.0, show_sec), True)
        # 向上取整：设 60 秒，一开始显示 00:01:00，过满 1 秒才变 00:00:59。
        # 直接截断的话，刚设好就显示 59，看着像少了一秒。
        return (fmt_seconds(math.ceil(left), show_sec), False)
    return (fmt_seconds(now - start, show_sec), False)


# ==============================================================================
# 二、浮窗
# ==============================================================================
class ClockOverlay:
    """计时器浮窗。自己的 Tk 线程，不占用主窗口。"""

    def __init__(self):
        self.root = None
        self.thread = None
        self.running = False
        self.started_at = time.time()
        self._fired = False          # 倒计时归零动作只触发一次

    # ------------------------------------------------------------ 显示
    def show(self):
        if self.running:
            return
        self.running = True
        self.started_at = time.time()
        self._fired = False
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       name="ClockOverlay")
        self.thread.start()
        log("计时器浮窗已启动（%s）" % CFG.get("clock.mode", "stopwatch"))

    def hide(self):
        self.running = False
        try:
            if self.root:
                self.root.after(0, self.root.destroy)
        except Exception:
            pass
        self.root = None

    def restart(self):
        """重新开始计时（正计时归零 / 倒计时重置）"""
        self.started_at = time.time()
        self._fired = False

    # ------------------------------------------------------------ 线程
    def _run(self):
        try:
            import tkinter as tk

            root = tk.Tk()
            self.root = root
            root.title("ClassHub 计时器")
            root.overrideredirect(True)
            try:
                root.attributes("-topmost", bool(CFG.get("clock.topmost", True)))
                root.attributes("-alpha", float(CFG.get("clock.opacity", 0.92)))
            except Exception:
                pass

            bg = str(CFG.get("clock.bg", "#101014") or "#101014")
            fg = str(CFG.get("clock.fg", "#FFFFFF") or "#FFFFFF")
            root.configure(bg=bg)

            size = max(12, int(CFG.get("clock.font_size", 48) or 48))
            lbl = tk.Label(root, text="00:00:00", bg=bg, fg=fg,
                           font=("Consolas", size, "bold"), padx=18, pady=10)
            lbl.pack()

            mode_lbl = tk.Label(root, text="", bg=bg, fg=fg,
                                font=("Microsoft YaHei UI", max(8, size // 5)))
            mode_lbl.pack(pady=(0, 8))

            self._place(root, lbl)
            self._bind_drag(root, lbl, mode_lbl)

            def tick():
                if not self.running:
                    return
                try:
                    text, zero = compute_display(CFG.section("clock"),
                                                 self.started_at)
                    lbl.configure(text=text)
                    mode = str(CFG.get("clock.mode", "stopwatch"))
                    mode_lbl.configure(text="倒计时" if mode == "countdown" else "正计时")
                    if zero:
                        self._on_zero()
                except Exception:
                    pass
                try:
                    root.after(200, tick)
                except Exception:
                    pass

            root.after(0, tick)
            root.mainloop()
        except Exception:
            import traceback

            log("计时器浮窗异常：\n" + traceback.format_exc())
        finally:
            self.running = False

    def _place(self, root, lbl):
        """定位：配置里有坐标就用，否则右下角"""
        try:
            root.update_idletasks()
            w = root.winfo_width() or 260
            h = root.winfo_height() or 90
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            x = int(CFG.get("clock.x", 0) or 0)
            y = int(CFG.get("clock.y", 0) or 0)
            if not x and not y:
                x, y = sw - w - 24, sh - h - 60
            root.geometry("%dx%d+%d+%d" % (w, h, max(0, x), max(0, y)))
        except Exception:
            pass

    def _bind_drag(self, root, *widgets):
        """拖动浮窗，松手记位置"""
        state = {"x": 0, "y": 0}

        def start(e):
            state["x"], state["y"] = e.x, e.y

        def move(e):
            try:
                nx = root.winfo_pointerx() - state["x"]
                ny = root.winfo_pointery() - state["y"]
                root.geometry("+%d+%d" % (max(0, nx), max(0, ny)))
            except Exception:
                pass

        def drop(_=None):
            try:
                CFG.set("clock.x", int(root.winfo_x()))
                CFG.set("clock.y", int(root.winfo_y()))
                CFG.save()
            except Exception:
                pass

        for w in (root,) + tuple(widgets):
            w.bind("<Button-1>", start)
            w.bind("<B1-Motion>", move)
            w.bind("<ButtonRelease-1>", drop)

    # ------------------------------------------------------------ 归零动作
    def _on_zero(self):
        if self._fired:
            return
        self._fired = True
        action = str(CFG.get("clock.on_zero", "none") or "none").lower()
        log("倒计时归零，动作：%s" % action)
        try:
            if action == "message":
                self._bubble()
            elif action == "shutdown":
                import chub_tasks as t

                t.do_shutdown(30)
            elif action == "lock":
                import chub_tasks as t

                t.do_lock()
        except Exception:
            import traceback

            log("归零动作失败：\n" + traceback.format_exc())

        if bool(CFG.get("clock.auto_restart", False)):
            self.restart()
            self._fired = False

    def _bubble(self):
        try:
            import tkinter as tk
            from tkinter import messagebox

            if self.root:
                self.root.after(0, lambda: messagebox.showinfo(
                    "ClassHub 计时器", "倒计时结束"))
        except Exception:
            pass


# ==============================================================================
# 三、引擎（主程序里挂一个，跟着配置开关）
# ==============================================================================
class ClockEngine:
    """按配置决定是否显示浮窗。做成后台线程，配置一改就跟上。"""

    def __init__(self, interval: float = 1.0):
        self.interval = max(0.5, float(interval))
        self.overlay = ClockOverlay()
        self._stop = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self._stop.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True,
                                       name="ClockEngine")
        self.thread.start()

    def stop(self):
        self._stop.set()
        self.overlay.hide()

    def is_alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def _loop(self):
        while not self._stop.is_set():
            try:
                on = bool(CFG.get("clock.enable", False))
                if on and not self.overlay.running:
                    self.overlay.show()
                elif not on and self.overlay.running:
                    self.overlay.hide()
            except Exception:
                pass
            self._stop.wait(self.interval)


# ---------------------------------------------------------------- 独立入口
def open_clock():
    """单独开一个计时器（不依赖主程序）"""
    ov = ClockOverlay()
    ov.show()
    try:
        while ov.running:
            time.sleep(1)
    except KeyboardInterrupt:
        ov.hide()


if __name__ == "__main__":
    from chub_core import load_config

    load_config()
    open_clock()
