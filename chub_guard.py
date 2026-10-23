# -*- coding: utf-8 -*-
"""
================================================================================
 ClassHub · chub_guard —— 开机启动 / 守护 / 防 TaskKill 程序守护器
================================================================================
三件事：

1) launch：开机批量启动软件，每项可单独关掉，支持后台静默启动
2) watch ：守护项 —— 软件被关掉后，等 N 秒自动重新打开
3) protect：防 TaskKill 守护器 —— 盯住一个指定的目标程序，被结束就立刻重启；
            可选"双进程互保"，再开一个伙伴进程盯着本程序，本程序被杀就拉起来

说明白一点：软件层面挡不住管理员权限的 taskkill /F（那是系统级终止），
能做的是"被杀后 1-2 秒内自动拉起来"，再配合双进程互保提高存活率。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

import chub_core as core
from chub_core import (AppItem, CFG, HAVE_PSUTIL, IS_WINDOWS, log, popen_hidden,
                       run_hidden)

if HAVE_PSUTIL:
    psutil = core.psutil


# ==============================================================================
# 一、开机启动 / 守护
# ==============================================================================
class LaunchGuard(threading.Thread):
    """一个线程干两件事：启动时批量拉起 launch 项；之后循环守护 watch 项。"""

    def __init__(self):
        super().__init__(daemon=True, name="LaunchGuard")
        self.stop_event = threading.Event()
        self.paused = threading.Event()          # set() = 暂停守护
        self.launch_items: list = []
        self.watch_items: list = []
        self.reload()

    # ---------- 配置 ----------
    def reload(self):
        self.launch_items = [AppItem.from_dict(d, "launch")
                             for d in CFG.get("launch.items", []) or []]
        self.watch_items = [AppItem.from_dict(d, "watch")
                            for d in CFG.get("watch.items", []) or []]

    def save_items(self):
        CFG.set("launch.items", [i.to_dict() for i in self.launch_items])
        CFG.set("watch.items", [i.to_dict() for i in self.watch_items])
        CFG.save()

    # ---------- 启动 ----------
    def launch(self, item: AppItem, reason: str = "", force: bool = True,
               running: set = None) -> bool:
        if not item.path or not os.path.isfile(item.path):
            log("[%s] 路径无效或文件不存在：%s" % (item.name, item.path))
            item.status = "路径无效"
            item.ever_seen = True
            return False
        if not force:
            names = running if running is not None else core.enum_process_names()
            if item.match_names() & names:
                item.status = "运行中"
                item.ever_seen = True
                return True
        if item.delay > 0:
            time.sleep(item.delay)
        try:
            proc = popen_hidden([item.path] + core.split_args(item.args),
                                cwd=item.workdir or str(os.path.dirname(item.path)),
                                show=item.show_flag())
            item.last_launch = time.time()
            item.dead_since = None
            item.status = "运行中（刚启动）"
            item.ever_seen = True
            log("[%s] 已启动%s pid=%s" % (item.name,
                                       "（%s）" % reason if reason else "", proc.pid))
            return True
        except Exception as e:
            log("[%s] 启动失败：%s" % (item.name, e))
            item.status = "启动失败"
            item.ever_seen = True
            return False

    def launch_all(self) -> int:
        """按顺序启动所有启用的 launch 项，返回启动数量"""
        interval = float(CFG.get("launch.interval", 1.0) or 0)
        restore = bool(CFG.get("launch.restore_focus", True))
        show_desk = bool(CFG.get("launch.show_desktop_after", False))
        hwnd = core.get_foreground_hwnd() if restore else None
        running = core.enum_process_names()
        targets = [i for i in self.launch_items if i.enabled]
        log("开始批量启动（%d 项）……" % len(targets))
        for item in targets:
            if self.stop_event.is_set():
                break
            self.launch(item, force=False, running=running)
            if interval > 0:
                time.sleep(interval)
            if item.show_desktop == 1:
                time.sleep(0.8)
                core.show_desktop()
        if show_desk or restore:
            time.sleep(1.0)
        if restore and hwnd:
            core.restore_foreground(hwnd)
        if show_desk:
            core.show_desktop()
        log("批量启动完成")
        return len(targets)

    def stop(self, item: AppItem) -> bool:
        ok = True
        for name in item.match_names():
            cmd = ["taskkill", "/IM", name, "/F"]
            try:
                r = run_hidden(cmd)
                if r.returncode != 0:
                    ok = False
            except Exception as e:
                ok = False
                log("[%s] 结束 %s 失败：%s" % (item.name, name, e))
        item.status = "已停止"
        item.dead_since = None
        return ok

    # ---------- 守护循环 ----------
    def run(self):
        if CFG.get("launch.enable", False):
            self.launch_all()
        interval = max(1.0, float(CFG.get("watch.check_interval", 3) or 3))
        while not self.stop_event.is_set():
            try:
                if CFG.get("watch.enable", False) and not self.paused.is_set():
                    self._guard_once()
            except Exception as e:
                log("守护循环异常：%s" % e)
            self.stop_event.wait(interval)

    def _guard_once(self):
        running = core.enum_process_names()
        now = time.time()
        for item in self.watch_items:
            alive = bool(item.match_names() & running)
            if not item.enabled:
                item.status = "已停用"
                item.dead_since = None
                continue
            if self.paused.is_set():
                item.status = "守护已暂停"
                continue
            if alive:
                item.status = "运行中（守护中）"
                item.ever_seen = True
                item.dead_since = None
                continue
            if not item.ever_seen and item.start_when_missing:
                log("[%s] 当前未运行，按配置立即启动" % item.name)
                self.launch(item, reason="首次检测未运行")
                continue
            if item.dead_since is None:
                item.dead_since = now
                log("[%s] 检测到已关闭，将在 %.0f 秒后自动重启"
                    % (item.name, item.restart_delay))
            left = item.restart_delay - (now - item.dead_since)
            if left <= 0:
                log("[%s] 等待结束，正在自动重启" % item.name)
                self.launch(item, reason="守护自动重启")
                item.dead_since = None
            else:
                item.status = "等待重启（%.0fs）" % left

    def shutdown(self):
        self.stop_event.set()


# ==============================================================================
# 二、防 TaskKill 程序守护器
# ==============================================================================
def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if HAVE_PSUTIL:
        try:
            if psutil.pid_exists(pid):
                p = psutil.Process(pid)
                return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
        except Exception:
            return False
    if IS_WINDOWS:
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
        except Exception:
            pass
    return False


class ProtectEngine(threading.Thread):
    """盯住一个目标程序，被结束就重启。"""

    def __init__(self):
        super().__init__(daemon=True, name="Protect")
        self.stop_event = threading.Event()
        self.proc = None
        self.count = 0
        self.status = "未启动"
        self._install_ctrl_handler()

    # ---------- 忽略 Ctrl+C / Ctrl+Break ----------
    def _install_ctrl_handler(self):
        if not IS_WINDOWS or not CFG.get("protect.ignore_ctrl", True):
            return
        try:
            import ctypes
            from ctypes import wintypes

            CTRL_HANDLER = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

            def handler(ctrl_type):
                if ctrl_type in (0, 1):        # CTRL_C_EVENT, CTRL_BREAK_EVENT
                    log("收到控制台中断信号，已忽略")
                    return True
                return False

            self._ctrl_ref = CTRL_HANDLER(handler)     # 必须留住引用，防止被回收
            ctypes.windll.kernel32.SetConsoleCtrlHandler(self._ctrl_ref, True)
        except Exception:
            pass

    # ---------- 目标 ----------
    def target_cmd(self) -> list:
        target = (CFG.get("protect.target", "") or "").strip()
        if not target:
            return []
        return [target] + core.split_args(CFG.get("protect.args", ""))

    def target_names(self) -> set:
        raw = CFG.get("protect.target", "") or ""
        return {os.path.basename(raw).strip().lower()} if raw else set()

    def start_target(self) -> bool:
        cmd = self.target_cmd()
        if not cmd:
            self.status = "未配置目标程序"
            return False
        try:
            self.proc = popen_hidden(cmd, cwd=CFG.get("protect.workdir", "") or None,
                                     show=core.SW_SHOWNORMAL)
            self.count += 1
            self.status = "已启动（第 %d 次）" % self.count
            log("守护器启动目标程序：%s" % " ".join(cmd))
            return True
        except Exception as e:
            self.status = "启动失败：%s" % e
            log("守护器启动目标失败：%s" % e)
            return False

    def stop_target(self) -> bool:
        ok = True
        for name in self.target_names():
            ok &= core.kill_by_name(name, True)
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.proc = None
        self.status = "已停止目标"
        return ok

    def alive(self) -> bool:
        if self.proc is not None and self.proc.poll() is None:
            return True
        # 目标可能是外部启动的，进程名在也当作活着
        return core.process_alive(self.target_names()) if self.target_names() else False

    def run(self):
        delay = max(0.5, float(CFG.get("protect.restart_delay", 2) or 2))
        max_restart = int(CFG.get("protect.max_restart", 0) or 0)
        log("程序守护器已启动，目标：%s" % (CFG.get("protect.target", "") or "（未配置）"))
        if not CFG.get("protect.target", ""):
            self.status = "未配置目标程序"
            return
        # 目标已经在跑就先附着，不再开一份
        if self.alive():
            self.status = "目标已在运行（已接管监控）"
            log("目标程序已在运行，守护器接管监控，不重复启动")
        else:
            self.start_target()
        while not self.stop_event.is_set():
            try:
                if not self.alive():
                    if max_restart and self.count >= max_restart:
                        self.status = "已达最大重启次数 %d，停止守护" % max_restart
                        log(self.status)
                        break
                    log("目标程序已退出，%.1f 秒后重启" % delay)
                    self.status = "等待重启"
                    if self.stop_event.wait(delay):
                        break
                    self.start_target()
            except Exception as e:
                log("守护器异常：%s" % e)
            self.stop_event.wait(1.0)
        log("程序守护器已停止")

    def shutdown(self):
        self.stop_event.set()


# ==============================================================================
# 三、双进程互保（伙伴进程）
# ==============================================================================
def self_command() -> str:
    """重新拉起本程序的命令行"""
    if core.is_frozen():
        return '"%s"' % sys.executable
    return '"%s" "%s"' % (sys.executable, os.path.abspath(sys.argv[0]))


def start_buddy() -> int:
    """启动伙伴进程：它盯着本进程，本进程没了就把本程序重新拉起来。

    返回伙伴进程 PID（失败返回 0）。
    """
    try:
        cmd = ([sys.executable] if core.is_frozen()
               else [sys.executable, os.path.abspath(sys.argv[0])])
        cmd += ["--buddy", str(os.getpid()), "--relaunch", self_command()]
        si = subprocess.STARTUPINFO() if IS_WINDOWS else None
        if si is not None:
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = core.SW_HIDE
        p = subprocess.Popen(cmd, startupinfo=si, close_fds=True)
        log("已启动伙伴进程 pid=%s（双进程互保）" % p.pid)
        return p.pid
    except Exception as e:
        log("启动伙伴进程失败：%s" % e)
        return 0


def buddy_loop(watch_pid: int, relaunch: str) -> int:
    """伙伴进程主体：盯着 watch_pid，没了就执行 relaunch，然后自己退出。"""
    log("伙伴进程已启动，盯住 pid=%s" % watch_pid)
    waited = 0.0
    while waited < 5:
        if not pid_alive(watch_pid):
            break
        time.sleep(0.5)
        waited += 0.5
    while pid_alive(watch_pid):
        time.sleep(2.0)
    log("主进程已消失，伙伴进程重新拉起：%s" % relaunch)
    try:
        subprocess.Popen(relaunch, shell=True)
    except Exception as e:
        log("重新拉起失败：%s" % e)
    time.sleep(3.0)
    return 0
