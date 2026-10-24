# -*- coding: utf-8 -*-
"""
================================================================================
 ClassHub · chub_core —— 公共基础层
================================================================================
整个套件只有这一份配置：config.json，放在程序本体（exe / .py）的同一目录下；
目录不可写（例如放在 Program Files）时自动退回 %APPDATA%\\ClassHub。

这一层提供：
    * 路径与目录探测（便携优先）
    * Config 配置类：支持 "sync.enable" 这种点号路径读写，缺失自动用默认值补
    * 日志：写 sync.log，同时保留最近若干行给界面显示
    * Windows 小工具：进程枚举、显示桌面、注册表开机自启、静默执行命令
    * 数据结构：AppItem / AssocItem / TaskItem
    * 时间解析：parse_time / parse_interval / parse_weekdays

依赖全部可选：没装 pywin32 / psutil 时程序照样能跑，只是相应能力下降。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta

# ---------------------------------------------------------------- 可选依赖
try:
    import win32com.client
    import win32gui
    import winreg

    HAVE_WIN32 = True
except Exception:  # 非 Windows 或未安装 pywin32
    win32com = None
    win32gui = None
    winreg = None
    HAVE_WIN32 = False

try:
    import psutil

    HAVE_PSUTIL = True
except Exception:
    psutil = None
    HAVE_PSUTIL = False


APP_ID = "ClassHub"
APP_CONTRIBUTORS = ["GithubUser02022", "HappyCode"]
APP_NAME_CN = "课堂助手套件"
APP_VERSION = "1.6.1"
APP_RELEASE_DATE = "2026-10-22"
APP_AUTHOR = "Hy4 preview"

# ---- 界面主题（个性化页可调，只对设置窗口本身生效）----
SHELL_THEME = {
    "hue": 205.0,          # 强调色色相（度）：197=天蓝，205=蓝
    "depth": 0.0,          # 深浅 -60 ~ +60
    "sat": 0.0,            # 饱和度 -40 ~ +40
    "radius": 18.0,        # 窗口圆角半径（像素，按 DPI 缩放）
    "style": "auto",       # auto=跟随系统 / light=浅色 / dark=深色
    "ui_scale": 0.0,      # 界面缩放，0=自动（按屏幕和 DPI 算）；手动就填 0.5~3.0
    "page_bg": "",        # 页面背景色（留空=跟随明暗主题），如 #101014 / rgb(20,20,26)
    "page_fg": "",        # 页面文字色（留空=跟随明暗主题）
    "backdrop": "mica",   # 背景材质：mica 云母（任务管理器用的）/ acrylic / none / auto
}
IS_WINDOWS = os.name == "nt"

# 窗口显示方式
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWNOACTIVATE = 4
SW_SHOWMINNOACTIVE = 7


# ==============================================================================
# 一、路径与目录
# ==============================================================================

def is_frozen() -> bool:
    """是否被 PyInstaller 打包成了 exe"""
    return bool(getattr(sys, "frozen", False))


def exe_dir() -> str:
    """程序本体所在目录（打包后是 exe 所在目录，源码模式是 .py 所在目录）"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def writable(path: str) -> bool:
    try:
        probe = os.path.join(path, ".classhub_wtest")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("1")
        os.remove(probe)
        return True
    except Exception:
        return False


def fallback_dir() -> str:
    root = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(root, APP_ID)
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        path = os.path.expanduser("~")
    return path


def pick_base() -> tuple[str, bool]:
    """优先程序同目录（便携），不可写才退回 APPDATA。返回 (目录, 是否便携)"""
    cand = exe_dir()
    if writable(cand):
        return cand, True
    return fallback_dir(), False


BASE, PORTABLE = pick_base()
CONFIG_PATH = os.path.join(BASE, "config.json")
COPIED_PATH = os.path.join(BASE, "copied.json")
STATE_PATH = os.path.join(BASE, "state.json")
LOG_PATH = os.path.join(BASE, "sync.log")


def default_dest() -> str:
    """D 盘存在就用 D:\\课件，否则退回『文档\\课件』"""
    try:
        if os.path.exists("D:\\"):
            return "D:\\课件"
    except Exception:
        pass
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(docs if os.path.isdir(docs) else os.path.expanduser("~"), "课件")


# ==============================================================================
# 二、默认配置（所有开关默认关闭）
# ==============================================================================

DEFAULT_CONFIG: dict = {
    # ---- 全局 ----
    "app_name": APP_NAME_CN,      # 托盘显示名称
    "shell": dict(SHELL_THEME),   # 设置窗口的个性化（圆角、配色），不影响托盘
    "autostart": False,           # 本程序开机自启（默认关）
    "notify": False,              # 气泡提示（默认关，保持静默）
    "start_minimized": True,      # 启动后只留托盘图标

    # ---- 课件同步 ----
    "sync": {
        "enable": False,          # 总开关，默认关
        "dest": "",               # 留空 = 自动（D:\\课件 或 文档\\课件）
        "subfolder_mode": "none",  # none / date / source / type
        "interval": 5,
        "min_size_kb": 0,
        # rename=内容变了才另存(2) / rename_always=同名就另存 / overwrite=覆盖 / skip=跳过
        "exists_policy": "rename",
        "skip_if_exists": True,
        "log_duplicate_skip": False,
        # —— 顺便拷同目录（默认全关）——
        "copy_siblings": False,          # 把抓到的文件所在目录下的其他文件也拷走
        "copy_siblings_recursive": False,  # 上面勾了之后：连子文件夹一起递归拷
        "siblings_max_files": 200,        # 单次最多拷多少个，防止拷爆
        "siblings_max_size_mb": 200,      # 单个文件超过这个大小跳过（MB）
        "siblings_use_subfolder": True,   # 放进「目标/源文件夹名/」子目录，避免平铺撞名
        "enable_ppt": False,
        "ppt_mode": "slideshow",    # slideshow / open
        "enable_doc": False,
        "enable_pdf": False,
        "deep_scan": False,
        "enable_usb": False,
        "usb_interval": 60,
        "usb_max_files": 3000,
        "usb_max_size_mb": 200,
        "usb_max_depth": 8,
        "usb_subfolder": "label",   # label / tree / none
        "siblings_use_subfolder": True,   # 放进「目标/源文件夹名/」子目录，避免平铺撞名
    },

    # ---- U 盘导出：U 盘根目录放个隐藏文件就触发（默认关）----
    "usb_export": {
        "enable": False,              # 总开关，默认关
        "trigger_file": "f",          # U 盘根目录里的触发文件名
        "require_hidden": True,       # 必须是隐藏文件（attrib +h f）
        "trigger_value": "1",         # 文件内容要等于它；留空 = 任何非空内容都触发
        "dest_subfolder": "课件",      # 拷到 U 盘的哪个子文件夹；留空 = U 盘根目录
        "interval": 10,               # 每隔多少秒看一眼有没有触发文件
        "max_files": 5000,            # 单次最多拷多少个
        "max_size_mb": 500,           # 单个文件超过这个大小跳过（MB）
        "max_total_mb": 0,            # 总量上限（MB），0 = 不限制
        "overwrite": False,           # 同名覆盖；否则跳过已有的
        "once_per_insert": True,      # 同一个盘每次插入只导一次（拔掉重插才会再导）
        "no_trigger_file_no_log": False,  # 勾上后：没带触发文件的盘一行日志都不记
    },

    # ---- 开机批量启动 ----
    "launch": {
        "enable": False,
        "interval": 1.0,
        "show_desktop_after": False,
        "restore_focus": True,
        "items": [],
    },

    # ---- 守护（关掉 N 秒后自动重开）----
    "watch": {
        "enable": False,
        "check_interval": 3.0,
        "restart_delay": 30.0,
        "items": [],
    },

    # ---- 文件关联（默认不碰注册表）----
    "assoc": {
        "enable": False,
        "apply_on_start": False,
        "delay": 8.0,
        "items": [],
    },

    # ---- 定时任务 ----
    "tasks": {
        "enable": False,
        "check_interval": 20.0,
        "shutdown_warn": 60.0,
        "enable_wake": False,
        "items": [],
    },

    # ---- 防 TaskKill 程序守护器 ----
    "protect": {
        "enable": False,
        "target": "",             # 要守护的程序（完整路径，或能直接启动的命令）
        "args": "",
        "workdir": "",
        "attach": True,           # 目标已在运行就接管监控，不重复启动
        "restart_delay": 2.0,
        "max_restart": 0,         # 0 = 无限
        "mutual": False,          # 双进程互保：再开一个伙伴进程盯着本程序
        "ignore_ctrl": True,      # 忽略 Ctrl+C / Ctrl+Break
    },

    # ---- 中育课堂助手小工具 ----
    "zy": {
        "enable": False,
        "log_path": r"C:\Program Files\Ezy\中育课堂助手\logs\Log.txt",
        "app_dir": r"C:\Program Files\Ezy\中育课堂助手",
        "app_exe": "CloudRoom.Main.exe",
        "refresh_interval": 5,
        "show_overlay": False,     # 是否常驻显示课堂号浮窗
        "auto_start_zy": False,    # 启用时是否自动重启一次中育课堂助手
        "wait_seconds": 8.0,       # 启动中育助手后，等多少秒再读日志文件
    },

    # ---- 云笔助手面板（自绘窗口，仿中育云笔助手连接界面）----
    # ⑧ 计时器：正计时 / 倒计时，精确到秒
    "clock": {
        "enable": False,          # 总开关，默认关
        "mode": "stopwatch",      # stopwatch 正计时 / countdown 倒计时
        "show_seconds": True,     # 精确到秒
        "countdown_seconds": 3600.0,  # 倒计时时长（秒），countdown 模式用
        "countdown_target": "",   # 或指定时刻（如 18:30 / 2026-10-22 18:30），留空用上面时长
        "auto_restart": False,    # 倒计时归零后自动重新开始
        "on_zero": "none",        # 归零动作：none / message / shutdown / lock
        "format": "%H:%M:%S",     # 显示格式
        "topmost": True,          # 浮窗置顶
        "x": 0,                   # 浮窗位置（0=屏幕右下角）
        "y": 0,
        "font_size": 48,          # 字号
        "opacity": 0.92,          # 不透明度
    },

    "pen": {
        "enable": False,          # 总开关，默认关：不勾就完全不动
        "auto_start_zy": True,    # 打开面板时，中育没在跑就先启动它
                                  # （这是面板的核心行为；但面板本身默认关，所以不会自动发生）
        "wait_seconds": 8.0,      # 启动中育后等多少秒再读日志
        "refresh_interval": 3.0,  # 每隔多少秒重读一次日志
        "height_ratio": 0.62,     # 窗口高度占屏幕可用高度的比例
        "topmost": False,         # 是否置顶
        # 配色（保感知亮度模型）：亮端 L=155 在中下部、暗端 L=101 在四周
        "hue": 205.0,             # 色相：190=偏青，205=蓝，215=偏蓝紫
        "depth": 0.0,             # 整体深浅 -60(更深) ~ +60(更浅)
        "sat": 0.0,               # 饱和度 -40(更灰) ~ +40(更艳)
    },
}


# ==============================================================================
# 三、配置读写
# ==============================================================================

class Config:
    """config.json 的读写封装。

    get / set 支持点号路径，例如 get("sync.enable")；
    读不到就返回默认值，写的时候自动建层级。
    """

    def __init__(self):
        self.data = deepcopy(DEFAULT_CONFIG)
        if not self.data["sync"]["dest"]:
            self.data["sync"]["dest"] = default_dest()
        self._lock = threading.RLock()
        self.load()

    # ---------- 载入 ----------
    def load(self):
        try:
            if os.path.isfile(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if isinstance(saved, dict):
                    self.data = _merge(self.data, saved)
        except Exception as e:
            log("配置文件读取失败（已用默认值）：%s" % e)
        if not self.data.get("sync", {}).get("dest"):
            self.data["sync"]["dest"] = default_dest()

    def save(self):
        with self._lock:
            try:
                tmp = CONFIG_PATH + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
                if os.path.isfile(CONFIG_PATH):
                    os.remove(CONFIG_PATH)
                os.rename(tmp, CONFIG_PATH)
                return True
            except Exception as e:
                log("配置保存失败：%s" % e)
                return False

    # ---------- 点号路径访问 ----------
    def get(self, key: str, default=None):
        cur = self.data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, key: str, value):
        with self._lock:
            parts = key.split(".")
            cur = self.data
            for p in parts[:-1]:
                nxt = cur.get(p)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cur[p] = nxt
                cur = nxt
            cur[parts[-1]] = value

    def toggle(self, key: str) -> bool:
        """切换一个布尔开关，返回切换后的值"""
        new = not bool(self.get(key, False))
        self.set(key, new)
        return new

    def section(self, name: str) -> dict:
        v = self.get(name)
        return v if isinstance(v, dict) else {}

    def raw(self) -> dict:
        return self.data


def _merge(base: dict, new: dict) -> dict:
    """用 new 覆盖 base，dict 递归合并，list 整体替换"""
    out = deepcopy(base)
    for k, v in (new or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


CFG = Config()


# ==============================================================================
# 四、运行状态（state.json）：任务上次执行时间等
# ==============================================================================

_state_lock = threading.Lock()


def load_state() -> dict:
    try:
        if os.path.isfile(STATE_PATH):
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {}


def save_state(state: dict):
    try:
        with _state_lock:
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log("运行状态保存失败：%s" % e)


# ==============================================================================
# 五、日志
# ==============================================================================

_log_lock = threading.Lock()
_recent: list[str] = []
MAX_RECENT = 400


def log_debug(msg: str):
    """内部细节，写日志但不刷屏（配置/互斥量这类非关键提示）"""
    try:
        with _log_lock:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write("[%s] %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def log(msg: str):
    line = "[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg)
    try:
        with _log_lock:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write("[%s] %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
            _recent.append(line)
            if len(_recent) > MAX_RECENT:
                del _recent[:-MAX_RECENT]
    except Exception:
        pass
    try:
        print(line)
    except Exception:
        pass


def recent_logs(n: int = 200) -> list[str]:
    with _log_lock:
        return list(_recent[-n:])


# ==============================================================================
# 六、Windows 小工具
# ==============================================================================

def enum_process_names() -> set[str]:
    """枚举当前所有进程的可执行文件名（小写）。用 EnumProcesses，比 tasklist 轻。"""
    names: set[str] = set()
    if not IS_WINDOWS:
        return names
    try:
        psapi = ctypes.windll.psapi
        k32 = ctypes.windll.kernel32
        DWORD = ctypes.wintypes.DWORD
        arr = (DWORD * 8192)()
        needed = DWORD()
        if not psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed)):
            return names
        count = needed.value // ctypes.sizeof(DWORD)
        BUF = 1024
        buf = ctypes.create_unicode_buffer(BUF)
        size = DWORD(BUF)
        for i in range(count):
            pid = arr[i]
            if not pid:
                continue
            handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                continue
            try:
                size.value = BUF
                if psapi.GetProcessImageFileNameW(handle, buf, ctypes.byref(size)):
                    names.add(os.path.basename(buf.value).lower())
            finally:
                k32.CloseHandle(handle)
    except Exception:
        # 兜底：用 psutil 或 tasklist
        if HAVE_PSUTIL:
            try:
                for p in psutil.process_iter(["name"]):
                    nm = (p.info.get("name") or "").lower()
                    if nm:
                        names.add(nm)
            except Exception:
                pass
    return names


def process_alive(names: set[str]) -> bool:
    if not names:
        return False
    return bool(names & enum_process_names())


def kill_by_name(name: str, force: bool = True) -> bool:
    """按进程名结束进程（taskkill /IM）"""
    if not name:
        return False
    cmd = ["taskkill", "/IM", name] + (["/F"] if force else [])
    try:
        r = run_hidden(cmd)
        return r.returncode == 0
    except Exception as e:
        log("结束进程 %s 失败：%s" % (name, e))
        return False


def run_hidden(cmd) -> subprocess.CompletedProcess:
    """无窗口执行命令"""
    si = subprocess.STARTUPINFO() if IS_WINDOWS else None
    if si is not None:
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = SW_HIDE
    return subprocess.run(cmd, startupinfo=si, capture_output=True,
                          text=True, shell=isinstance(cmd, str))


def popen_hidden(cmd, cwd=None, show: int = SW_SHOWMINNOACTIVE):
    """后台启动一个程序，返回 Popen 对象"""
    si = subprocess.STARTUPINFO() if IS_WINDOWS else None
    if si is not None:
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = show
    return subprocess.Popen(cmd, cwd=cwd, startupinfo=si, close_fds=True)


def show_desktop() -> bool:
    """显示桌面（等同按 Win+D）"""
    try:
        import win32com.client  # noqa: F401
        win32com.client.Dispatch("Shell.Application").ToggleDesktop()
        return True
    except Exception:
        pass
    if not IS_WINDOWS:
        return False
    try:
        user32 = ctypes.windll.user32
        VK_LWIN, VK_D, KEYUP = 0x5B, 0x44, 0x0002
        user32.keybd_event(VK_LWIN, 0, 0, 0)
        user32.keybd_event(VK_D, 0, 0, 0)
        user32.keybd_event(VK_D, 0, KEYUP, 0)
        user32.keybd_event(VK_LWIN, 0, KEYUP, 0)
        return True
    except Exception:
        return False


def get_foreground_hwnd():
    if not IS_WINDOWS:
        return None
    try:
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return None


def restore_foreground(hwnd):
    if not hwnd or not IS_WINDOWS:
        return
    try:
        user32 = ctypes.windll.user32
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


# ---- 本程序开机自启（HKCU Run，不需管理员）----
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_command() -> str:
    if is_frozen():
        return '"%s"' % sys.executable
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(cand):
            exe = cand
    return '"%s" "%s"' % (exe, os.path.abspath(sys.argv[0] if not is_frozen() else sys.executable))


def get_autostart() -> bool:
    if not HAVE_WIN32:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            v, _ = winreg.QueryValueEx(key, APP_ID)
            return bool(v)
    except Exception:
        return False


def set_autostart(enable: bool) -> bool:
    if not HAVE_WIN32:
        log("未安装 pywin32，无法设置开机自启")
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, autostart_command())
                log("已写入开机自启：%s" % autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_ID)
                    log("已取消开机自启")
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        log("开机自启设置失败：%s" % e)
        return False


def open_in_explorer(path: str):
    """用资源管理器打开目录 / 用记事本打开文件"""
    try:
        if os.path.isdir(path):
            os.startfile(path)  # noqa: S606
        elif os.path.isfile(path):
            subprocess.Popen(["notepad.exe", path])
        else:
            subprocess.Popen(["explorer", os.path.dirname(path) or "."])
    except Exception:
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        except Exception:
            pass


# ==============================================================================
# 七、数据结构
# ==============================================================================

@dataclass
class AppItem:
    """开机启动项（kind=launch）/ 守护项（kind=watch）"""

    kind: str = "launch"
    name: str = ""
    path: str = ""
    args: str = ""
    workdir: str = ""
    enabled: bool = True
    background: int = 1          # 0=前台 1=最小化不抢焦点 2=完全隐藏
    delay: float = 0.0
    process: str = ""            # 存活检测用进程名，留空取 exe 文件名
    restart_delay: float = 30.0
    start_when_missing: bool = True
    show_desktop: int = -1

    # 运行期状态
    dead_since: float | None = None
    status: str = "未运行"
    ever_seen: bool = False
    last_launch: float = 0.0

    def match_names(self) -> set[str]:
        raw = self.process.strip() or os.path.basename(self.path or "")
        return {p.strip().lower() for p in raw.split(";") if p.strip()}

    def show_flag(self) -> int:
        return {0: SW_SHOWNORMAL, 1: SW_SHOWMINNOACTIVE, 2: SW_HIDE}.get(
            self.background, SW_SHOWMINNOACTIVE)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "path": self.path, "args": self.args,
            "workdir": self.workdir, "enabled": self.enabled,
            "background": self.background, "delay": self.delay,
            "process": self.process, "restart_delay": self.restart_delay,
            "start_when_missing": self.start_when_missing,
            "show_desktop": self.show_desktop,
        }

    @staticmethod
    def from_dict(d: dict, kind: str = "launch") -> "AppItem":
        return AppItem(
            kind=kind,
            name=str(d.get("name", "")),
            path=str(d.get("path", "")),
            args=str(d.get("args", "")),
            workdir=str(d.get("workdir", "")),
            enabled=bool(d.get("enabled", True)),
            background=int(d.get("background", 1) or 0),
            delay=float(d.get("delay", 0) or 0),
            process=str(d.get("process", "")),
            restart_delay=float(d.get("restart_delay", 30) or 30),
            start_when_missing=bool(d.get("start_when_missing", True)),
            show_desktop=int(d.get("show_desktop", -1)),
        )


@dataclass
class AssocItem:
    """文件关联项：把某些扩展名交给指定程序打开"""

    name: str = ""
    ext: str = ""
    exe: str = ""
    args: str = '"%1"'
    enabled: bool = True
    progid: str = ""
    original: str = ""
    original_progid: str = ""
    status: str = "未应用"

    def exts(self) -> list[str]:
        out: list[str] = []
        for e in re.split(r"[;,\s]+", (self.ext or "").strip()):
            if not e:
                continue
            e = e if e.startswith(".") else "." + e
            if e not in out:
                out.append(e)
        return out

    def progid_for(self, ext: str) -> str:
        return self.progid.strip() or "%s.Assoc%s" % (APP_ID, ext)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "ext": self.ext, "exe": self.exe,
            "args": self.args, "enabled": self.enabled, "progid": self.progid,
            "original": self.original, "original_progid": self.original_progid,
        }

    @staticmethod
    def from_dict(d: dict) -> "AssocItem":
        return AssocItem(
            name=str(d.get("name", "")),
            ext=str(d.get("ext", "")),
            exe=str(d.get("exe", "") or d.get("path", "")),
            args=str(d.get("args", '"%1"') or '"%1"'),
            enabled=bool(d.get("enabled", True)),
            progid=str(d.get("progid", "")),
            original=str(d.get("original", "")),
            original_progid=str(d.get("original_progid", "")),
        )


@dataclass
class TaskItem:
    """定时任务项"""

    name: str = ""
    action: str = "launch"       # launch/shutdown/reboot/sleep/hibernate/lock
    schedule: str = "daily"      # daily/weekly/interval/once
    path: str = ""
    args: str = ""
    workdir: str = ""
    background: int = 1
    enabled: bool = True
    time_str: str = "00:00"
    date_str: str = ""
    weekdays: str = ""
    interval_str: str = ""
    catch_up: bool = False
    wake: bool = False
    wake_set: bool = False

    next_run: datetime | None = None
    last_run: datetime | None = None
    status: str = "等待中"

    ACTION_LABEL = {"launch": "启动软件", "shutdown": "关机", "reboot": "重启",
                    "sleep": "睡眠", "hibernate": "休眠", "lock": "锁屏"}

    def action_label(self) -> str:
        return self.ACTION_LABEL.get(self.action, self.action)

    def schedule_text(self) -> str:
        s = self.schedule
        if s == "daily":
            return "每天 %s" % self.time_str
        if s == "weekly":
            return "每周 %s %s" % (self.weekdays or "?", self.time_str)
        if s == "interval":
            return "每 %s 执行一次" % (self.interval_str or "?")
        if s == "once":
            return "%s %s 执行一次" % (self.date_str, self.time_str)
        return s

    def to_dict(self) -> dict:
        return {
            "name": self.name, "action": self.action, "schedule": self.schedule,
            "path": self.path, "args": self.args, "workdir": self.workdir,
            "background": self.background, "enabled": self.enabled,
            "time": self.time_str, "date": self.date_str, "weekdays": self.weekdays,
            "interval": self.interval_str, "catch_up": self.catch_up, "wake": self.wake,
        }

    @staticmethod
    def from_dict(d: dict) -> "TaskItem":
        return TaskItem(
            name=str(d.get("name", "")),
            action=str(d.get("action", "launch")).lower(),
            schedule=str(d.get("schedule", "daily")).lower(),
            path=str(d.get("path", "")),
            args=str(d.get("args", "")),
            workdir=str(d.get("workdir", "")),
            background=int(d.get("background", 1) or 0),
            enabled=bool(d.get("enabled", True)),
            time_str=str(d.get("time", "00:00")),
            date_str=str(d.get("date", "")),
            weekdays=str(d.get("weekdays", "")),
            interval_str=str(d.get("interval", "")),
            catch_up=bool(d.get("catch_up", False)),
            wake=bool(d.get("wake", False)),
        )


# ==============================================================================
# 八、时间解析
# ==============================================================================

def parse_time(s: str, default: tuple = (0, 0)) -> tuple:
    """把 "14:30" / "14:30:00" / "14时30" 解析成 (时, 分)"""
    s = (s or "").strip()
    m = re.match(r"^(\d{1,2})\s*[:：时]\s*(\d{1,2})", s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return h, mi
    return default


def parse_interval(s: str, default_minutes: float = 60.0) -> timedelta:
    """把 "50d" "12h" "30m" "90" 解析成 timedelta（纯数字按分钟算）"""
    s = str(s or "").strip().lower()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(s|m|h|d|w|秒|分|小时|天|周)?$", s)
    if m:
        n = float(m.group(1))
        unit = m.group(2) or ""
        table = {"": timedelta(minutes=n), "s": timedelta(seconds=n),
                 "m": timedelta(minutes=n), "h": timedelta(hours=n),
                 "d": timedelta(days=n), "w": timedelta(weeks=n),
                 "秒": timedelta(seconds=n), "分": timedelta(minutes=n),
                 "小时": timedelta(hours=n), "天": timedelta(days=n),
                 "周": timedelta(weeks=n)}
        return table.get(unit, timedelta(minutes=default_minutes))
    return timedelta(minutes=default_minutes)


_WD_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}
_WD_EN = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7}


def parse_weekdays(s: str) -> set:
    out = set()
    for part in re.split(r"[,，;；\s]+", (s or "").strip()):
        if not part:
            continue
        low = part.lower()
        if low.isdigit():
            n = int(low)
            if 1 <= n <= 7:
                out.add(n)
            continue
        if low.startswith("周") or low.startswith("星期"):
            cn = part[-1]
            if cn in _WD_CN:
                out.add(_WD_CN[cn])
            continue
        for k, v in _WD_EN.items():
            if low.startswith(k):
                out.add(v)
                break
    return out


def weekday_cn(n: int) -> str:
    return "一二三四五六日"[n - 1] if 1 <= n <= 7 else "?"


# ==============================================================================
# 九、其它小工具
# ==============================================================================

def safe_name(name: str) -> str:
    bad = '<>:"/\\|?*'
    for ch in bad:
        name = name.replace(ch, "_")
    return name.strip().rstrip(".") or "未命名"


def split_args(s: str) -> list:
    """把命令行参数字符串切成列表，失败就原样返回"""
    try:
        return shlex.split(s or "")
    except Exception:
        return [p for p in (s or "").split() if p]


def file_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def file_sig(path: str) -> str:
    try:
        st = os.stat(path)
        return "%d-%d" % (st.st_size, int(st.st_mtime))
    except Exception:
        return "unknown"


def load_json_dict(path: str) -> dict:
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {}


def save_json_dict(path: str, data: dict):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log("写入 %s 失败：%s" % (path, e))


def save_config() -> bool:
    """保存 config.json（面板改配色等地方用）"""
    try:
        return CFG.save()
    except Exception:
        return False


# ==============================================================================
# 单实例：防止程序被开两遍
# ==============================================================================
# 判据优先用 Windows 命名互斥量（进程崩溃时系统自动释放，不会留下"假占用"）；
# 拿不到就退回本地端口。端口还兼做"激活已有实例"的通知通道：第二次启动时
# 让已经在跑的那个把窗口弹出来，而不是默默退出、让人以为没启动。

ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    """用法：

        si = SingleInstance("ClassHub", 47621)
        if not si.acquire():
            si.notify()          # 让已有实例显示窗口
            sys.exit(0)          # 自己退出
        si.start_listener(on_show)
    """

    def __init__(self, app_id: str, port: int = 0):
        self.app_id = app_id
        self.port = port
        self.is_first = False
        self._mutex = None
        self._sock = None
        self._stop = threading.Event()
        self._on_show = None

    # ------------------------------------------------------------ 判据
    def acquire(self) -> bool:
        if IS_WINDOWS:
            try:
                k32 = ctypes.WinDLL("kernel32", use_last_error=True)
                k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.wintypes.BOOL,
                                             ctypes.wintypes.LPCWSTR]
                k32.CreateMutexW.restype = ctypes.wintypes.HANDLE
                h = k32.CreateMutexW(None, True, "Local\%s_SingleInstance" % self.app_id)
                if h:
                    self._mutex = h
                    self.is_first = (ctypes.get_last_error() != ERROR_ALREADY_EXISTS)
                    if self.is_first:
                        self._bind_port()
                    return self.is_first
            except Exception as exc:
                log_debug("创建互斥量失败，退回端口判据：%s" % exc)
        # 非 Windows，或 mutex 没拿到：用端口当判据
        self._bind_port()
        self.is_first = self._sock is not None
        return self.is_first

    def _bind_port(self):
        if not self.port:
            return
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", self.port))
            s.listen(4)
            s.settimeout(0.5)
            self._sock = s
        except Exception:
            self._sock = None

    # ------------------------------------------------------------ 通知
    def start_listener(self, on_show=None):
        """首个实例调用：起一个线程等"第二次启动"的通知"""
        self._on_show = on_show
        if self._sock is None:
            return
        threading.Thread(target=self._serve, daemon=True,
                         name="SingleInstance").start()

    def _serve(self):
        while not self._stop.is_set() and self._sock is not None:
            try:
                conn, _ = self._sock.accept()
            except Exception:
                continue
            try:
                conn.settimeout(1.0)
                try:
                    conn.recv(64)
                except Exception:
                    pass
                conn.close()
            except Exception:
                pass
            if self._on_show:
                try:
                    self._on_show()
                except Exception:
                    pass

    def notify(self) -> bool:
        """第二个实例调用：告诉已在跑的那个"显示窗口"。成功返回 True"""
        if not self.port:
            return False
        try:
            s = socket.create_connection(("127.0.0.1", self.port), timeout=0.8)
            s.sendall(b"show")
            s.close()
            return True
        except Exception:
            return False

    def release(self):
        self._stop.set()
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
