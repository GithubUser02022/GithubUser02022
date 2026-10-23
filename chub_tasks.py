# -*- coding: utf-8 -*-
"""
================================================================================
 ClassHub · chub_tasks —— 定时任务 & 电源动作
================================================================================
每条任务：到了时间就自动执行。
    动作：launch 启动软件 / shutdown 关机 / reboot 重启 / sleep 睡眠 /
          hibernate 休眠 / lock 锁屏
    计划：daily 每天 / weekly 每周几 / interval 每隔 N / once 指定时刻一次

调度器是一个后台线程，默认每 20 秒检查一次；默认关闭，界面/菜单里开启才跑。
关机重启前默认留 60 秒缓冲，期间可以取消。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import threading
import time
from datetime import datetime, timedelta

import chub_core as core
from chub_core import (TaskItem, load_state, log, parse_interval,
                       parse_time, parse_weekdays, popen_hidden, run_hidden,
                       save_state, weekday_cn)

MIN_GAP_SECONDS = 60


# ==============================================================================
# 下次执行时间（纯逻辑）
# ==============================================================================
def compute_next_run(task: TaskItem, now: datetime, last_run: datetime = None):
    if not task.enabled:
        return None
    sched = (task.schedule or "daily").lower()

    if sched == "interval":
        delta = parse_interval(task.interval_str)
        if delta.total_seconds() <= 0:
            return None
        if last_run is None and task.time_str:
            h, mi = parse_time(task.time_str, (-1, -1))
            if 0 <= h <= 23:
                first = now.replace(hour=h, minute=mi, second=0, microsecond=0)
                if first > now:
                    return first
        base = last_run or now
        nxt = base + delta
        while nxt <= now:
            nxt += delta
        return nxt

    if sched == "once":
        try:
            d = datetime.strptime((task.date_str or "").strip(), "%Y-%m-%d")
        except ValueError:
            return None
        h, m = parse_time(task.time_str)
        return d.replace(hour=h, minute=m, second=0, microsecond=0)

    h, m = parse_time(task.time_str)

    if sched == "daily":
        today_point = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if task.catch_up and now >= today_point:
            if not (last_run and last_run.date() >= now.date()):
                return now
        candidate = today_point
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    if sched == "weekly":
        days = parse_weekdays(task.weekdays)
        if not days:
            return None
        if task.catch_up:
            week_start = (now - timedelta(days=now.weekday())).date()
            executed_this_week = bool(last_run and last_run.date() >= week_start)
            for d in sorted(days):
                offset = d - 1 - now.weekday()
                if offset < 0 and not executed_this_week:
                    return now
        for i in range(8):
            day = now + timedelta(days=i)
            if (day.weekday() + 1) in days:
                cand = day.replace(hour=h, minute=m, second=0, microsecond=0)
                if cand > now:
                    return cand
        return None
    return None


# ==============================================================================
# 电源动作
# ==============================================================================
def do_shutdown(warn_seconds: float = 60, comment: str = "") -> str:
    secs = max(0, int(warn_seconds))
    cmd = ["shutdown", "/s", "/t", str(secs)]
    if comment:
        cmd += ["/c", comment[:200]]
    run_hidden(cmd)
    log("已下达关机指令：%d 秒后关机（可用『取消关机』撤销）" % secs)
    return "%d 秒后关机" % secs


def do_reboot(warn_seconds: float = 60, comment: str = "") -> str:
    secs = max(0, int(warn_seconds))
    cmd = ["shutdown", "/r", "/t", str(secs)]
    if comment:
        cmd += ["/c", comment[:200]]
    run_hidden(cmd)
    log("已下达重启指令：%d 秒后重启" % secs)
    return "%d 秒后重启" % secs


def cancel_shutdown() -> bool:
    r = run_hidden(["shutdown", "/a"])
    ok = r.returncode == 0
    log("取消关机：%s" % ("成功" if ok else "没有待执行的关机任务"))
    return ok


def do_sleep() -> str:
    run_hidden(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    log("已执行：睡眠")
    return "已睡眠"


def do_hibernate() -> str:
    run_hidden(["shutdown", "/h"])
    log("已执行：休眠")
    return "已休眠"


def do_lock() -> str:
    run_hidden(["rundll32.exe", "user32.dll,LockWorkStation"])
    log("已执行：锁屏")
    return "已锁屏"


# ==============================================================================
# 定时唤醒（实验性：只在睡眠/休眠下有效，彻底关机唤醒不了）
# ==============================================================================
_wake_timer_handles: list = []


def set_wake_timer(target: datetime) -> bool:
    if not core.IS_WINDOWS:
        return False
    try:
        k32 = ctypes.windll.kernel32
        handle = k32.CreateWaitableTimerW(None, True, None)
        if not handle:
            return False
        epoch_diff = 116444736000000000
        ft = int(target.timestamp() * 10_000_000) + epoch_diff

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.wintypes.DWORD),
                        ("dwHighDateTime", ctypes.wintypes.DWORD)]

        due = FILETIME(ft & 0xFFFFFFFF, ft >> 32)
        ok = k32.SetWaitableTimer(int(handle), ctypes.byref(due), 0, None, None, True)
        if ok:
            _wake_timer_handles.append(int(handle))
            log("已设置唤醒定时器：%s（需处于睡眠/休眠状态才会生效）"
                % target.strftime("%m-%d %H:%M"))
        else:
            k32.CloseHandle(int(handle))
        return bool(ok)
    except Exception:
        return False


# ==============================================================================
# 执行一个任务
# ==============================================================================
def launch_for_task(task: TaskItem) -> bool:
    if not task.path or not os.path.isfile(task.path):
        log("[%s] 路径无效或文件不存在：%s" % (task.name, task.path))
        return False
    try:
        popen_hidden([task.path] + core.split_args(task.args),
                     cwd=task.workdir or os.path.dirname(task.path),
                     show={0: core.SW_SHOWNORMAL, 1: core.SW_SHOWMINNOACTIVE,
                           2: core.SW_HIDE}.get(task.background, core.SW_SHOWMINNOACTIVE))
        log("[%s] 定时任务触发，已启动 %s" % (task.name, task.path))
        return True
    except Exception as e:
        log("[%s] 定时启动失败：%s" % (task.name, e))
        return False


def run_action(task: TaskItem, warn_seconds: float = 60) -> str:
    act = (task.action or "").lower()
    if act == "launch":
        return "已启动" if launch_for_task(task) else "启动失败"
    if act == "shutdown":
        return do_shutdown(warn_seconds, "%s 触发关机" % task.name)
    if act == "reboot":
        return do_reboot(warn_seconds, "%s 触发重启" % task.name)
    if act == "sleep":
        return do_sleep()
    if act == "hibernate":
        return do_hibernate()
    if act == "lock":
        return do_lock()
    log("[%s] 未知动作：%s" % (task.name, act))
    return "未知动作"


# ==============================================================================
# 调度器
# ==============================================================================
class Scheduler(threading.Thread):
    def __init__(self, get_tasks, get_settings, interval: float = 20.0):
        super().__init__(daemon=True, name="Scheduler")
        self.get_tasks = get_tasks
        self.get_settings = get_settings
        self.interval = max(5.0, interval)
        self.stop_event = threading.Event()
        self.state = load_state()
        self._last_state_save = 0.0

    def last_run_of(self, name: str):
        s = self.state.get("task:" + name)
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    def mark_run(self, name: str, when: datetime = None):
        self.state["task:" + name] = (when or datetime.now()).isoformat(timespec="seconds")
        self.persist()

    def persist(self, force: bool = False):
        now = time.time()
        if force or now - self._last_state_save > 5:
            save_state(self.state)
            self._last_state_save = now

    def reload_state(self):
        self.state = load_state()

    def run(self):
        log("定时任务调度器已启动（每 %.0f 秒检查一次）" % self.interval)
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception as e:
                log("调度器异常：%s" % e)
            self.stop_event.wait(self.interval)

    def tick(self):
        now = datetime.now()
        st = self.get_settings() or {}
        wake_enabled = bool(st.get("enable_wake", False))
        warn = float(st.get("shutdown_warn", 60) or 60)

        for t in self.get_tasks():
            if not t.enabled:
                t.next_run = None
                t.status = "已停用"
                continue
            last = self.last_run_of(t.name)
            t.last_run = last
            nxt = compute_next_run(t, now, last)
            t.next_run = nxt
            if nxt is None:
                t.status = "无有效计划"
                continue
            delta = (nxt - now).total_seconds()
            if delta > 1:
                t.status = self._countdown_text(delta)
                if wake_enabled and t.wake and delta <= 150 and not t.wake_set:
                    if set_wake_timer(nxt - timedelta(minutes=1)):
                        t.wake_set = True
                continue
            if last and (now - last).total_seconds() < MIN_GAP_SECONDS:
                t.status = "刚执行过，跳过"
                continue
            log("[%s] 定时任务到点，执行动作：%s" % (t.name, t.action_label()))
            try:
                result = run_action(t, warn)
                t.status = "已执行（%s）" % result
                log("[%s] 执行结果：%s" % (t.name, result))
            except Exception as e:
                t.status = "执行失败"
                log("[%s] 执行失败：%s" % (t.name, e))
            self.mark_run(t.name, now)
            t.wake_set = False
            if (t.schedule or "").lower() == "once":
                t.enabled = False
                log("[%s] 一次性任务已完成，自动停用" % t.name)
        self.persist()

    @staticmethod
    def _countdown_text(seconds: float) -> str:
        if seconds < 60:
            return "即将执行（%ds）" % int(seconds)
        if seconds < 3600:
            return "还有 %02d:%02d" % (int(seconds // 60), int(seconds % 60))
        days = int(seconds // 86400)
        h = int((seconds % 86400) // 3600)
        m = int((seconds % 3600) // 60)
        if days:
            return "还有 %d 天 %02d:%02d" % (days, h, m)
        return "还有 %02d:%02d" % (h, m)


def describe_next(task: TaskItem) -> str:
    if not task.next_run:
        return "—"
    d = task.next_run
    return "%s（周%s）" % (d.strftime("%m-%d %H:%M"), weekday_cn(d.weekday() + 1))
