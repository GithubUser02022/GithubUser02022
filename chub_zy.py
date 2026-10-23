# -*- coding: utf-8 -*-
"""
================================================================================
 ClassHub · chub_zy —— 中育课堂助手小工具
================================================================================
原脚本做的事，这里全保留，做成可开关的一个模块：

    1. 重启中育课堂助手：结束 CloudRoom.Main.exe → 删掉旧的 Log.txt → 重新打开
    2. 从 Log.txt 里读出课堂号（原脚本取第 3 行末尾 4 位数字；若含小数点则取第 4 行）
    3. 左上角一个小浮窗把这个号顶在屏幕上（置顶、可拖动、ESC 退出）

默认关闭，勾选并点一次才会动。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time

import chub_core as core
from chub_core import CFG, log


# ---------------------------------------------------------------- 读取课堂号
def log_path() -> str:
    return (CFG.get("zy.log_path") or "").strip()


def app_dir() -> str:
    return (CFG.get("zy.app_dir") or "").strip()


def app_exe() -> str:
    return (CFG.get("zy.app_exe") or "CloudRoom.Main.exe").strip()


# ---- 日志解析（新版：连接码 = 日志里的"最后四个数字"）----
# 日志每行形如：
#   2026-10-14 11:53:40.9584||INFO||CloudRoom.HardwareModule...||udp广播服务启动成功。本机IP地址是:192.168.243.12
#   2026-10-14 11:53:40.9620||INFO||...||192.168.243.12::8900
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?")
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_PORT_RE = re.compile(r"::(\d{2,5})\b")
_DATE_RE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}")
_TIME_RE = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?")
_JSON_RE = re.compile(r"\{.*\}")
# 关键词行优先（"连接码：7270" / "connectCode":7270 / pin=8899 …）
_KEY_RES = (
    re.compile(r"(?:连接码|连接代码|投屏码|配对码|课堂号|云笔|笔助手|投屏)[^0-9]{0,8}(\d{4})"),
    re.compile(r"(?:pin|code|room|paircode|castcode|linkcode)[\"'=:\s]{1,4}(\d{4})", re.I),
)


def _ip_candidates(line: str) -> list:
    """行里像局域网 IP 的地址（排除版本号 2.1.6.0、127.x、0.0.0.0）"""
    out = []
    for m in _IP_RE.finditer(line):
        ip = m.group(0)
        if all(len(x) <= 1 for x in ip.split(".")):      # 2.1.6.0 → 版本号
            continue
        if ip.startswith("127.") or ip in ("0.0.0.0", "255.255.255.255"):
            continue
        out.append(ip)
    return out


def _clean_body(line: str) -> str:
    """剥掉时间戳、IP、端口、日期、时刻，只留"有信息量"的部分"""
    b = _TS_RE.sub("", line)
    b = _IP_RE.sub(" ", b)
    b = _PORT_RE.sub(" ", b)
    b = _DATE_RE.sub(" ", b)
    return _TIME_RE.sub(" ", b)


def _find4(body: str) -> str:
    """最后一组"独立的"4 位数字。

    前后都不能是字母/数字/日期分隔符，所以 secretKey、deviceNumber 这类
    十六进制串里的数字片段不会被误当成连接码。
    """
    nums = re.findall(r"(?<![0-9A-Za-z\-:./_])(\d{4})(?![0-9A-Za-z\-:./_])", body)
    return nums[-1] if nums else ""


def extract_info(text: str) -> dict:
    """从日志文本里解析出连接码 / IP / 端口 / 版本 / 设备号 / 教室名"""
    info = {"code": "", "ip": "", "port": "", "version": "",
            "device": "", "classroom": "", "src": ""}
    if not text:
        return info
    lines = [l for l in text.splitlines() if l.strip()]

    # IP：优先"本机IP地址是:xxx"那行，否则取最后一次出现的 IP
    for line in reversed(lines):
        if re.search(r"(本机\s*ip|ip\s*地址|ipaddress|localip)", line, re.I):
            cand = _ip_candidates(line)
            if cand:
                info["ip"] = cand[0]
                break
    if not info["ip"]:
        for line in reversed(lines):
            cand = _ip_candidates(line)
            if cand:
                info["ip"] = cand[0]
                break
    for line in reversed(lines):
        p = _PORT_RE.search(line)
        if p:
            info["port"] = p.group(1)
            break

    # 版本 / 设备号 / 教室名：JSON 那行
    for line in reversed(lines):
        m = _JSON_RE.search(line)
        if not m:
            continue
        try:
            res = (json.loads(m.group(0)) or {}).get("result") or {}
            info["version"] = str(res.get("version") or "")
            info["device"] = str(res.get("deviceNumber") or "")
            info["classroom"] = str(res.get("classroomName") or "")
        except Exception:
            pass
        if info["version"] or info["device"]:
            break

    # 连接码：① 关键词行  ② 最后四个数字  ③ 兜底
    for line in reversed(lines):
        body = _clean_body(line)
        for rx in _KEY_RES:
            m = rx.search(body)
            if m:
                info["code"], info["src"] = m.group(1), "关键词行"
                return info
    for line in reversed(lines):
        hit = _find4(_clean_body(line))
        if hit:
            info["code"], info["src"] = hit, "最后四个数字"
            return info
    hit = _find4(" ".join(_clean_body(l) for l in lines))
    if hit:
        info["code"], info["src"] = hit, "兜底"
    return info


def read_info() -> dict:
    path = log_path()
    if not path or not os.path.isfile(path):
        info = extract_info("")
        info["src"] = "日志不存在"
        return info
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return extract_info(f.read())
    except Exception as e:
        info = extract_info("")
        info["src"] = "读取失败：%s" % e
        return info


def read_number(path: str = "") -> str:
    """连接码（课堂号）。取不到就返回占位，方便界面直接显示"""
    info = read_info() if not path else extract_info(open(path, "r", encoding="utf-8",
                                                          errors="ignore").read()
                                                     if os.path.isfile(path) else "")
    return info.get("code") or "----"


# ---------------------------------------------------------------- 进程状态
def is_running() -> bool:
    """中育课堂助手在不在跑"""
    exe = app_exe()
    if not exe:
        return False
    if core.HAVE_PSUTIL:
        try:
            for p in core.psutil.process_iter(["name"]):
                if (p.info.get("name") or "").lower() == exe.lower():
                    return True
        except Exception:
            pass
    try:
        r = core.run_hidden(["tasklist", "/FI", "IMAGENAME eq " + exe])
        return exe.lower() in (r.stdout or "").lower()
    except Exception:
        return False


def start_zy() -> tuple:
    """把中育课堂助手拉起来。返回 (是否成功, 说明)"""
    d = app_dir()
    exe = app_exe()
    path = os.path.join(d, exe) if d else ""
    if not path or not os.path.isfile(path):
        return False, "找不到程序：%s" % (path or exe)
    try:
        core.popen_hidden([path], cwd=d, show=core.SW_SHOWNORMAL)
        log("中育助手：已启动 %s" % path)
        return True, "已启动"
    except Exception as e:
        return False, "启动失败：%s" % e


def ensure_running(wait_seconds: float = 0) -> tuple:
    """没在跑就启动它，等一会儿再读日志。返回 (状态说明, 解析结果 dict)"""
    wait = wait_seconds or float(CFG.get("zy.wait_seconds", 8) or 8)
    if not is_running():
        ok, msg = start_zy()
        if not ok:
            return msg, read_info()
        log("中育助手：等待 %.0f 秒后再读日志" % wait)
        time.sleep(wait)
        return "已启动并等待 %.0f 秒" % wait, read_info()
    return "已在运行", read_info()


# ---------------------------------------------------------------- 重启中育助手
def restart_zy() -> tuple:
    """结束进程 → 删 Log.txt → 重新启动。返回 (是否成功, 说明)"""
    exe = app_exe()
    d = app_dir()
    ok = True
    msg = []

    if exe:
        try:
            r = core.run_hidden(["taskkill", "/im", exe, "/f"])
            msg.append("已结束 %s" % exe if r.returncode == 0 else "没有正在运行的 %s" % exe)
        except Exception as e:
            ok = False
            msg.append("结束进程失败：%s" % e)

    lp = log_path()
    if lp and os.path.exists(lp):
        try:
            os.remove(lp)
            msg.append("已删除旧日志")
        except Exception as e:
            ok = False
            msg.append("删除日志失败：%s" % e)

    if d and os.path.isdir(d):
        try:
            full = os.path.join(d, exe)
            if os.path.isfile(full):
                core.popen_hidden([full], cwd=d, show=core.SW_SHOWNORMAL)
                msg.append("已重新启动 %s" % exe)
            else:
                # 目录存在但 exe 名对不上：用资源管理器打开目录，交给用户
                core.open_in_explorer(d)
                ok = False
                msg.append("目录里没找到 %s，已打开目录请手动启动" % exe)
        except Exception as e:
            ok = False
            msg.append("启动失败：%s" % e)
    else:
        ok = False
        msg.append("程序目录不存在：%s" % d)

    wait = float(CFG.get("zy.wait_seconds", 8) or 8)
    log("中育助手：%s；等待 %.0f 秒后读连接码" % ("；".join(msg), wait))
    time.sleep(wait)
    info = read_info()
    if info.get("code"):
        msg.append("连接码 %s（%s）" % (info["code"], info["src"]))
    log("中育助手：%s" % "；".join(msg))
    return ok, "；".join(msg)


def open_zy_dir():
    d = app_dir()
    if d and os.path.isdir(d):
        core.open_in_explorer(d)
    else:
        log("中育助手目录不存在：%s" % d)


# ---------------------------------------------------------------- 课堂号浮窗
class ZyOverlay(threading.Thread):
    """左上角常驻小浮窗，显示课堂号。跑在自己的线程里（Tk 要求）。"""

    def __init__(self):
        super().__init__(daemon=True, name="ZyOverlay")
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.root = None
        self.var = None
        self.visible = False

    # ---------- 线程里建窗口 ----------
    def run(self):
        try:
            import tkinter as tk
        except Exception:
            log("无法打开课堂号浮窗：缺少 tkinter")
            return
        try:
            root = tk.Tk()
            self.root = root
            self.var = tk.StringVar(value=read_number())
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.configure(bg="#f0f0f0")
            root.geometry("300x80+10+10")

            frame = tk.Frame(root, bg="#f0f0f0")
            frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            tk.Label(frame, textvariable=self.var, font=("Arial", 28, "bold"),
                     fg="blue", bg="#f0f0f0", padx=10, pady=5).pack(expand=True)
            tk.Label(frame, text=" ", font=("Arial", 8), fg="gray",
                     bg="#f0f0f0").pack()

            start = {"x": 0, "y": 0}

            def on_click(e):
                start["x"], start["y"] = e.x, e.y

            def on_drag(e):
                root.geometry("+%d+%d" % (root.winfo_x() + e.x - start["x"],
                                          root.winfo_y() + e.y - start["y"]))

            root.bind("<Escape>", lambda e: self.hide())
            root.bind("<Button-1>", on_click)
            root.bind("<B1-Motion>", on_drag)

            root.withdraw()
            self.ready.set()
            root.mainloop()
        except Exception as e:
            log("课堂号浮窗异常：%s" % e)
        finally:
            self.root = None
            self.visible = False

    # ---------- 对外控制（线程安全靠 after 投递到 Tk 线程）----------
    def _post(self, fn):
        if self.root is None or not self.ready.is_set():
            return
        try:
            self.root.after(0, fn)
        except Exception:
            pass

    def show(self):
        def _do():
            try:
                self.root.deiconify()
                self.root.attributes("-topmost", True)
                self.visible = True
                self._tick()
            except Exception:
                pass

        if self.root is None:
            if not self.is_alive():
                self.start()
            self.ready.wait(5)
        self._post(_do)

    def hide(self):
        def _do():
            try:
                self.root.withdraw()
            except Exception:
                pass
            self.visible = False

        self._post(_do)

    def _tick(self):
        """每 N 秒刷新一次课堂号"""
        if self.root is None or not self.visible:
            return
        try:
            interval = max(1, int(CFG.get("zy.refresh_interval", 5) or 5))
            self.var.set(read_number())
            self.root.after(interval * 1000, self._tick)
        except Exception:
            pass

    def refresh_now(self):
        self._post(lambda: self.var.set(read_number()))

    def close(self):
        def _do():
            try:
                self.root.quit()
                self.root.destroy()
            except Exception:
                pass

        self.visible = False
        self._post(_do)
