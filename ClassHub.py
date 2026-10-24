#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
================================================================================
 ClassHub（课堂助手套件）—— 主程序：托盘图标 + 右键菜单 + 后台调度
================================================================================
一个托盘图标，把下面这些功能收在一起（全部默认关闭，需要哪个开哪个）：

    ① 课件同步     放映/打开的 PPT、Word、PDF 静默复制到目标文件夹；U 盘模式
    ② 开机启动     开机批量拉起软件，可后台静默
    ③ 守护         软件被关掉 N 秒后自动重开
    ④ 文件关联     开机自动把 .pptx 等交给指定程序打开（对付还原软件）
    ⑤ 定时任务     每天/每周/每隔 N 天 启动软件或关机/重启/睡眠/休眠/锁屏
    ⑥ 程序守护器   防 TaskKill：目标程序被结束就自动重启，可双进程互保
    ⑦ 中育助手     重启中育课堂助手、读课堂号、左上角浮窗显示

配置就一个文件：config.json，跟程序本体在同一目录。
所有开关默认关闭，尤其是开机自启和写注册表这类动作，不勾就不做。
"""

from __future__ import annotations

import os
import sys
import threading
import time
import traceback

import chub_core as core
from chub_core import (BASE, CFG, COPIED_PATH, CONFIG_PATH, LOG_PATH, PORTABLE,
                       log)

try:
    import pystray
    from pystray import MenuItem as Item

    HAVE_TRAY = True
except Exception:
    HAVE_TRAY = False

# 图标只用到 PIL，别跟托盘绑在一起 —— 没装 pystray 也要能生成窗口图标
try:
    from PIL import Image, ImageDraw

    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

import chub_assoc as assoc_mod
import chub_guard as guard_mod
import chub_sync as sync_mod
import chub_tasks as tasks_mod
import chub_pen as pen_mod
import chub_zy as zy_mod
import chub_clock as clock_mod

APP_ID = core.APP_ID
VERSION = "1.0"


# ---------------------------------------------------------------- 图标
def make_icon(size: int = 64):
    if not HAVE_PIL:
        return None
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, size - 3, size - 3], radius=int(size * 0.22),
                        fill=(37, 99, 235, 255))
    m = size // 8
    d.rectangle([m + 2, m + 3, size // 2 - 2, size - m - 3], fill=(255, 255, 255, 240))
    d.rectangle([size // 2 + 1, m + 3, size - m - 3, size - m - 3], fill=(226, 238, 255, 240))
    d.rectangle([size // 2 - 2, m + 2, size // 2 + 1, size - m - 2], fill=(30, 64, 175, 255))
    return img


def export_icon(path: str = "icon.ico") -> bool:
    """把程序图标写成 .ico（窗口标题栏 / 任务栏用）。只依赖 pillow。"""
    if not HAVE_PIL:
        return False
    try:
        img = make_icon(256)
        if img is None:
            return False
        img.save(path, format="ICO",
                            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 主程序
class App:
    def __init__(self):
        self.icon = None
        self.total = len(core.load_json_dict(COPIED_PATH))
        self.stop = threading.Event()
        self.settings_open = False
        self.usb_busy = False
        self.export_busy = False
        self.force_next = False

        self.guard = guard_mod.LaunchGuard()
        self.protect = None
        self.scheduler = None
        self.overlay = zy_mod.ZyOverlay()
        self.clock = clock_mod.ClockEngine()
        self.buddy_pid = 0
        self._services_started = False

    # ============================================================ 服务启停
    def start_services(self):
        """按当前配置把该跑的后台线程拉起来"""
        # ① 课件同步：由主循环负责（下面 loop）
        # ② 开机启动 & ③ 守护
        if (CFG.get("launch.enable", False) or CFG.get("watch.enable", False)) \
                and not self.guard.is_alive():
            self.guard = guard_mod.LaunchGuard()
            self.guard.start()

        # ④ 文件关联（开机自动应用）
        if CFG.get("assoc.enable", False) and CFG.get("assoc.apply_on_start", False):
            threading.Thread(target=self._apply_assoc_delayed, daemon=True,
                             name="AssocApply").start()

        # ⑤ 定时任务
        if CFG.get("tasks.enable", False) and (self.scheduler is None or not self.scheduler.is_alive()):
            self.scheduler = tasks_mod.Scheduler(
                lambda: self.task_items(),
                lambda: CFG.section("tasks"),
                float(CFG.get("tasks.check_interval", 20) or 20))
            self.scheduler.start()

        # ⑥ 防 TaskKill 守护器
        if CFG.get("protect.enable", False) and (self.protect is None or not self.protect.is_alive()):
            self.protect = guard_mod.ProtectEngine()
            self.protect.start()
            if CFG.get("protect.mutual", False) and not self.buddy_pid:
                self.buddy_pid = guard_mod.start_buddy()

        # ⑦ 中育助手：没在跑就拉起来，等一会儿再读日志取连接码
        if CFG.get("zy.enable", False):
            if CFG.get("zy.auto_start_zy", False):
                threading.Thread(target=zy_mod.restart_zy, daemon=True, name="ZyRestart").start()
            else:
                threading.Thread(target=zy_mod.ensure_running, daemon=True,
                                 name="ZyEnsure").start()
            if CFG.get("zy.show_overlay", False):
                self.overlay.show()

        # ⑧ 计时器：勾选了才显示浮窗
        if CFG.get("clock.enable", False) and (self.clock is None or not self.clock.is_alive()):
            self.clock = clock_mod.ClockEngine()
            self.clock.start()

        # ⑨ 云笔助手面板：勾选了才开
        if CFG.get("pen.enable", False):
            threading.Thread(target=pen_mod.PenPanel.open, daemon=True,
                             name="PenOpen").start()
        self._services_started = True

    def reload_services(self):
        """设置保存后把新勾选的模块拉起来。

        各模块的启动判断本身是幂等的（线程活着就不重复起），
        所以直接再走一遍 start_services 即可。
        """
        try:
            self.start_services()
            log("已按新配置刷新服务")
        except Exception:
            log("刷新服务失败：\n" + traceback.format_exc())

    def on_clock_restart(self):
        """重新开始计时"""
        try:
            if getattr(self, "clock", None):
                self.clock.overlay.restart()
                log("计时器已重新开始")
        except Exception:
            pass

    def task_items(self):
        """定时任务列表（配置 → 对象），带简单缓存，避免每轮重建丢状态"""
        if not hasattr(self, "_task_cache"):
            self._task_cache = []
        raw = CFG.get("tasks.items", []) or []
        cur = {t.name: t for t in self._task_cache}
        out = []
        for d in raw:
            name = str(d.get("name", ""))
            if name in cur:
                t = cur[name]
                # 用配置刷新可变字段，保留运行期状态
                new = core.TaskItem.from_dict(d)
                new.next_run, new.last_run, new.status = t.next_run, t.last_run, t.status
                out.append(new)
            else:
                out.append(core.TaskItem.from_dict(d))
        self._task_cache = out
        return out

    def _apply_assoc_delayed(self):
        delay = float(CFG.get("assoc.delay", 8) or 0)
        if self.stop.wait(delay):
            return
        self.apply_all_assoc()

    def apply_all_assoc(self):
        items = [core.AssocItem.from_dict(d) for d in CFG.get("assoc.items", []) or []]
        items = [i for i in items if i.enabled]
        if not items:
            return 0
        ok = 0
        for it in items:
            try:
                good, msg = assoc_mod.apply_assoc(it)
                ok += 1 if good else 0
            except Exception as e:
                log("应用关联异常：%s" % e)
        # 把备份写回配置，方便以后还原
        self.save_assoc_backups(items)
        log("文件关联应用完毕（%d/%d 成功）" % (ok, len(items)))
        return ok

    def revert_all_assoc(self):
        items = [core.AssocItem.from_dict(d) for d in CFG.get("assoc.items", []) or []]
        for it in items:
            try:
                assoc_mod.revert_assoc(it)
            except Exception as e:
                log("还原关联异常：%s" % e)
        self.save_assoc_backups(items)
        log("文件关联已全部还原")

    def save_assoc_backups(self, items):
        raw = CFG.get("assoc.items", []) or []
        by_name = {i.name: i for i in items}
        for d in raw:
            it = by_name.get(str(d.get("name", "")))
            if it:
                d["original"] = it.original
                d["original_progid"] = it.original_progid
        CFG.set("assoc.items", raw)
        CFG.save()

    def restart_service(self, kind: str):
        """设置改了之后，按需重启某个服务"""
        if kind == "tasks":
            if CFG.get("tasks.enable", False):
                if self.scheduler and self.scheduler.is_alive():
                    self.scheduler.reload_state()
                else:
                    self.start_services()
            elif self.scheduler:
                self.scheduler.stop_event.set()
                self.scheduler = None
        elif kind == "protect":
            if CFG.get("protect.enable", False):
                if self.protect is None or not self.protect.is_alive():
                    self.start_services()
            elif self.protect:
                self.protect.shutdown()
                self.protect = None
        elif kind == "guard":
            self.start_services()
        elif kind == "zy":
            if CFG.get("zy.enable", False):
                if CFG.get("zy.show_overlay", False):
                    self.overlay.show()
                else:
                    self.overlay.hide()
                if CFG.get("zy.auto_start_zy", False):
                    threading.Thread(target=zy_mod.restart_zy, daemon=True).start()
                else:
                    threading.Thread(target=zy_mod.ensure_running, daemon=True).start()
            else:
                self.overlay.hide()

    def apply_config(self):
        """设置窗口保存后调用：写盘 + 重新拉起需要的服务"""
        CFG.save()
        self.guard.reload()
        self.restart_service("tasks")
        self.restart_service("protect")
        self.restart_service("guard")
        self.restart_service("zy")
        self.refresh_menu()
        self.refresh_title()

    # ============================================================ 菜单动作
    def toast(self, msg: str):
        if CFG.get("notify", False) and self.icon:
            try:
                self.icon.notify(msg, CFG.get("app_name", APP_ID))
            except Exception:
                pass

    def on_open_dest(self):
        path = sync_mod.dest_root()
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
        core.open_in_explorer(path)

    def on_scan_now(self):
        threading.Thread(target=self._scan_thread, args=(True,), daemon=True).start()

    def on_scan_usb(self, force: bool = True):
        if self.usb_busy:
            return
        threading.Thread(target=self._usb_thread, args=(force,), daemon=True).start()

    def _scan_thread(self, force: bool):
        try:
            new_files = sync_mod.scan_once(force=force or self.force_next)
            self.force_next = False
            if new_files:
                self.total += len(new_files)
                self.toast("已复制 %d 个文件" % len(new_files))
            self.refresh_title()
        except Exception:
            log("扫描异常：\n" + traceback.format_exc())

    def _usb_thread(self, force: bool):
        self.usb_busy = True
        try:
            new_files = sync_mod.scan_usb_once(force=force)
            if new_files:
                self.total += len(new_files)
                self.toast("从 U 盘复制了 %d 个文件" % len(new_files))
            self.refresh_title()
        except Exception:
            log("U 盘扫描异常：\n" + traceback.format_exc())
        finally:
            self.usb_busy = False
        self.export_busy = False

    def on_export_usb(self, force: bool = True):
        if self.export_busy:
            return
        threading.Thread(target=self._export_thread, args=(force,),
                         daemon=True).start()

    def _export_thread(self, force: bool):
        self.export_busy = True
        try:
            cnt, target, msg = sync_mod.check_usb_export(force=force)
            if cnt:
                self.toast("已导出 %d 个文件到 U 盘" % cnt)
            elif force:
                self.toast("没有可导出的 U 盘（%s）" % (msg or "没插带触发文件的盘"))
        except Exception:
            log("U 盘导出异常：\n" + traceback.format_exc())
        finally:
            self.export_busy = False

    def on_clear_records(self):
        sync_mod.clear_records()
        self.total = 0
        self.refresh_title()

    def on_toggle(self, key: str, rescan: bool = True):
        new = CFG.toggle(key)
        CFG.save()
        log("开关 %s → %s" % (key, "开" if new else "关"))
        if key == "usb_export.enable" and new:
            sync_mod.USB_EXPORT_SCANNED.clear()
            sync_mod.EXPORTED_DRIVES.clear()
            self.on_export_usb(True)
        if key.startswith("sync."):
            if key == "sync.enable_usb" and new:
                sync_mod.USB_SCANNED.clear()
                self.on_scan_usb(True)
            elif rescan:
                self.on_scan_now()
        if key == "tasks.enable":
            self.restart_service("tasks")
        if key == "protect.enable":
            self.restart_service("protect")
        if key == "launch.enable" or key == "watch.enable":
            self.restart_service("guard")
        if key == "pen.enable":
            if CFG.get("pen.enable", False):
                threading.Thread(target=pen_mod.PenPanel.open, daemon=True).start()
            else:
                pen_mod.PenPanel.close_all()
        if key == "zy.enable":
            self.restart_service("zy")
        self.refresh_menu()

    def on_toggle_ppt_mode(self):
        CFG.set("sync.ppt_mode",
                "open" if CFG.get("sync.ppt_mode", "slideshow") == "slideshow" else "slideshow")
        CFG.save()
        log("PPT 抓取模式改为：%s" % ("打开就拷" if CFG.get("sync.ppt_mode") == "open" else "只在放映时拷"))
        self.on_scan_now()
        self.refresh_menu()

    def on_toggle_notify(self):
        CFG.toggle("notify")
        CFG.save()
        self.refresh_menu()

    def on_toggle_autostart(self):
        new = not core.get_autostart()
        core.set_autostart(new)
        CFG.set("autostart", new)
        CFG.save()
        self.refresh_menu()

    def on_launch_all(self):
        threading.Thread(target=lambda: self.guard.launch_all(), daemon=True).start()

    def on_toggle_pause_guard(self):
        if self.guard.paused.is_set():
            self.guard.paused.clear()
            log("守护已继续")
        else:
            self.guard.paused.set()
            log("守护已暂停（期间不会自动重启软件）")
        self.refresh_menu()

    def on_apply_assoc(self):
        threading.Thread(target=self.apply_all_assoc, daemon=True).start()

    def on_revert_assoc(self):
        threading.Thread(target=self.revert_all_assoc, daemon=True).start()

    def on_check_tasks(self):
        if self.scheduler and self.scheduler.is_alive():
            threading.Thread(target=self.scheduler.tick, daemon=True).start()
        else:
            log("定时任务未启用，先在菜单里打开『启用定时任务』")

    def on_cancel_shutdown(self):
        tasks_mod.cancel_shutdown()

    def on_power(self, kind: str):
        warn = float(CFG.get("tasks.shutdown_warn", 60) or 60)
        if kind == "cancel":
            tasks_mod.cancel_shutdown()
        elif kind == "shutdown60":
            tasks_mod.do_shutdown(60, "ClassHub 快捷关机")
        elif kind == "shutdown":
            tasks_mod.do_shutdown(0, "ClassHub 快捷关机")
        elif kind == "reboot":
            tasks_mod.do_reboot(warn, "ClassHub 快捷重启")
        elif kind == "sleep":
            tasks_mod.do_sleep()
        elif kind == "hibernate":
            tasks_mod.do_hibernate()
        elif kind == "lock":
            tasks_mod.do_lock()

    def on_protect_start(self):
        if self.protect is None or not self.protect.is_alive():
            self.protect = guard_mod.ProtectEngine()
            self.protect.start()
        else:
            self.protect.start_target()

    def on_protect_stop(self):
        if self.protect:
            self.protect.stop_target()

    def on_zy_restart(self):
        def _run():
            ok, msg = zy_mod.restart_zy()
            time.sleep(2.0)
            self.overlay.refresh_now()
            self.toast("中育助手：" + msg)

        threading.Thread(target=_run, daemon=True).start()

    def on_pen_toggle(self):
        """打开 / 关闭云笔助手面板"""
        if pen_mod.PenPanel.is_open():
            ok, msg = pen_mod.PenPanel.close_all()
        else:
            if not CFG.get("pen.enable", False):
                CFG.set("pen.enable", True)
                CFG.save()
                log("云笔助手面板已启用")
                self.update_menu()
            ok, msg = pen_mod.PenPanel.open()
        log(msg)
        if CFG.get("notify", False):
            self.notify(msg)

    def on_pen_theme(self):
        """打开面板的配色对话框（面板没开就先开）"""
        if not pen_mod.PenPanel.is_open():
            pen_mod.PenPanel.open()
            for _ in range(50):
                time.sleep(0.1)
                if pen_mod.PenPanel.is_open() and list(pen_mod._PANELS.values()):
                    break
        try:
            for p in list(pen_mod._PANELS.values()):
                p.show_theme_dialog()
                break
        except Exception as e:
            log("打开配色对话框失败：%s" % e)

    def on_zy_overlay(self):
        if self.overlay.visible:
            self.overlay.hide()
        else:
            self.overlay.show()

    def on_settings(self):
        if self.settings_open:
            self._focus_settings()
            return
        threading.Thread(target=self._settings_thread, daemon=True, name="SettingsUI").start()

    def _focus_settings(self):
        for mod, fn in (("chub_shell", "focus_shell"), ("chub_ui", "focus_existing")):
            try:
                m = __import__(mod)
                if getattr(m, fn)():
                    return
            except Exception:
                pass

    def _settings_thread(self):
        self.settings_open = True
        try:
            import chub_shell

            chub_shell.open_shell(self)
        except Exception:
            log("设置窗口异常：\n" + traceback.format_exc())
        finally:
            self.settings_open = False

    def on_open_log(self):
        core.open_in_explorer(LOG_PATH)

    def on_open_config(self):
        core.open_in_explorer(BASE)

    def on_edit_config(self):
        core.open_in_explorer(CONFIG_PATH)

    def on_about(self):
        self.toast("ClassHub %s —— 配置：%s" % (VERSION, BASE))

    def on_quit(self):
        log("退出程序")
        self.stop.set()
        try:
            if self.protect:
                self.protect.shutdown()
        except Exception:
            pass
        try:
            if getattr(self, "clock", None):
                self.clock.stop()
        except Exception:
            pass
        try:
            self.overlay.close()
        except Exception:
            pass
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass

    # ============================================================ 主循环
    def loop(self):
        while not self.stop.is_set():
            try:
                if CFG.get("sync.enable", False):
                    self._scan_thread(False)
                if CFG.get("sync.enable", False) and CFG.get("sync.enable_usb", False) \
                        and not self.usb_busy:
                    self.on_scan_usb(False)
                if CFG.get("usb_export.enable", False) and not self.export_busy:
                    self.on_export_usb(False)
            except Exception:
                log("主循环异常：\n" + traceback.format_exc())
            self.stop.wait(max(1.0, float(CFG.get("sync.interval", 5) or 5)))

    # ============================================================ 托盘
    def refresh_title(self):
        if not self.icon:
            return
        try:
            self.icon.title = "%s - 已同步 %d 个文件" % (CFG.get("app_name", APP_ID), self.total)
        except Exception:
            pass

    def refresh_menu(self):
        if not self.icon:
            return
        try:
            self.icon.menu = self.build_menu()
        except Exception:
            pass
        self.refresh_title()

    def _chk(self, key):
        return lambda *a: bool(CFG.get(key, False))

    def build_menu(self):
        sync_menu = pystray.Menu(
            Item("启用课件同步（总开关）", lambda *a: self.on_toggle("sync.enable"),
                 checked=self._chk("sync.enable")),
            Item("抓 PowerPoint / WPS 演示", lambda *a: self.on_toggle("sync.enable_ppt"),
                 checked=self._chk("sync.enable_ppt")),
            Item("抓 Word / WPS 文档", lambda *a: self.on_toggle("sync.enable_doc"),
                 checked=self._chk("sync.enable_doc")),
            Item("抓 PDF（阅读器/浏览器）", lambda *a: self.on_toggle("sync.enable_pdf"),
                 checked=self._chk("sync.enable_pdf")),
            Item(lambda *a: "PPT：%s" % ("打开就拷" if CFG.get("sync.ppt_mode") == "open"
                                       else "只在放映时拷"),
                 lambda *a: self.on_toggle_ppt_mode()),
            pystray.Menu.SEPARATOR,
            Item("U 盘模式（插上就自动拷）", lambda *a: self.on_toggle("sync.enable_usb"),
                 checked=self._chk("sync.enable_usb")),
            Item("立即扫一次 U 盘", lambda *a: self.on_scan_usb(True)),
            pystray.Menu.SEPARATOR,
            Item("U 盘导出（插带隐藏文件 f 的盘就拷出课件）",
                 lambda *a: self.on_toggle("usb_export.enable"),
                 checked=self._chk("usb_export.enable")),
            Item("立即导出课件到 U 盘", lambda *a: self.on_export_usb(True)),
            Item("清空复制记录", lambda *a: self.on_clear_records()),
        )

        boot_menu = pystray.Menu(
            Item("开机批量启动（总开关）", lambda *a: self.on_toggle("launch.enable"),
                 checked=self._chk("launch.enable")),
            Item("立即启动全部", lambda *a: self.on_launch_all()),
            pystray.Menu.SEPARATOR,
            Item("守护：关掉后自动重开", lambda *a: self.on_toggle("watch.enable"),
                 checked=self._chk("watch.enable")),
            Item(lambda *a: "暂停守护" if not self.guard.paused.is_set() else "继续守护",
                 lambda *a: self.on_toggle_pause_guard()),
        )

        assoc_menu = pystray.Menu(
            Item("启用文件关联（会改注册表）", lambda *a: self.on_toggle("assoc.enable"),
                 checked=self._chk("assoc.enable")),
            Item("立即应用全部", lambda *a: self.on_apply_assoc()),
            Item("全部还原", lambda *a: self.on_revert_assoc()),
        )

        task_menu = pystray.Menu(
            Item("启用定时任务", lambda *a: self.on_toggle("tasks.enable"),
                 checked=self._chk("tasks.enable")),
            Item("立即检查一次", lambda *a: self.on_check_tasks()),
            pystray.Menu.SEPARATOR,
            Item("60 秒后关机", lambda *a: self.on_power("shutdown60")),
            Item("立刻关机", lambda *a: self.on_power("shutdown")),
            Item("重启", lambda *a: self.on_power("reboot")),
            Item("睡眠", lambda *a: self.on_power("sleep")),
            Item("休眠", lambda *a: self.on_power("hibernate")),
            Item("锁屏", lambda *a: self.on_power("lock")),
            Item("取消待执行的关机", lambda *a: self.on_cancel_shutdown()),
        )

        protect_menu = pystray.Menu(
            Item("启用守护器（防 TaskKill）", lambda *a: self.on_toggle("protect.enable"),
                 checked=self._chk("protect.enable")),
            Item("立即启动目标程序", lambda *a: self.on_protect_start()),
            Item("停止目标程序", lambda *a: self.on_protect_stop()),
        )

        zy_menu = pystray.Menu(
            Item("启用中育助手小工具", lambda *a: self.on_toggle("zy.enable"),
                 checked=self._chk("zy.enable")),
            Item("重启中育助手并刷新课堂号", lambda *a: self.on_zy_restart()),
            Item(lambda *a: "隐藏课堂号浮窗" if self.overlay.visible else "显示课堂号浮窗",
                 lambda *a: self.on_zy_overlay()),
        )

        pen_menu = pystray.Menu(
            Item("启用云笔助手面板", lambda *a: self.on_toggle("pen.enable"),
                 checked=self._chk("pen.enable")),
            Item(lambda *a: "关闭面板" if pen_mod.PenPanel.is_open() else "打开面板",
                 lambda *a: self.on_pen_toggle()),
            Item("调整配色…", lambda *a: self.on_pen_theme()),
        )

        return pystray.Menu(
            Item("打开课件文件夹", lambda *a: self.on_open_dest()),
            Item("立即检查一次", lambda *a: self.on_scan_now()),
            pystray.Menu.SEPARATOR,
            Item("① 课件同步 ▸", sync_menu),
            Item("② 开机启动 & 守护 ▸", boot_menu),
            Item("③ 文件关联 ▸", assoc_menu),
            Item("④ 定时任务 ▸", task_menu),
            Item("⑤ 程序守护器（防 TaskKill）▸", protect_menu),
            Item("⑥ 中育课堂助手 ▸", zy_menu),
            Item("⑦ 云笔助手面板 ▸", pen_menu),
            pystray.Menu.SEPARATOR,
            Item("显示气泡提示", lambda *a: self.on_toggle_notify(),
                 checked=self._chk("notify")),
            Item("开机自动启动（本程序）", lambda *a: self.on_toggle_autostart(),
                 checked=lambda *a: core.get_autostart()),
            Item("设置…", lambda *a: self.on_settings(), default=True),
            pystray.Menu.SEPARATOR,
            Item("查看日志", lambda *a: self.on_open_log()),
            Item("打开配置目录", lambda *a: self.on_open_config()),
            Item("编辑 config.json", lambda *a: self.on_edit_config()),
            Item("关于", lambda *a: self.on_about()),
            Item("退出", lambda *a: self.on_quit()),
        )

    def run(self):
        log("启动：%s（%s）" % (APP_ID, "打包后的 EXE" if core.is_frozen() else "Python 脚本"))
        log("程序位置：%s" % (sys.executable if core.is_frozen() else os.path.abspath(__file__)))
        log("配置位置：%s%s" % (BASE, "" if PORTABLE else "（程序目录不可写，已退回 APPDATA）"))
        if not core.HAVE_WIN32:
            log("提示：未装 pywin32，COM 检测与注册表相关功能不可用")
        if not core.HAVE_PSUTIL:
            log("提示：未装 psutil，进程兜底检测不可用")
        self.start_services()
        threading.Thread(target=self.loop, daemon=True, name="MainLoop").start()

        if not HAVE_TRAY:
            log("缺少 pystray / Pillow，退化为命令行模式（按 Ctrl+C 退出）")
            try:
                while not self.stop.is_set():
                    time.sleep(1)
            except KeyboardInterrupt:
                self.stop.set()
            return

        self.icon = pystray.Icon(APP_ID, make_icon(),
                                 "%s - 已同步 %d 个文件" % (CFG.get("app_name", APP_ID), self.total),
                                 self.build_menu())
        self.icon.run()


# ---------------------------------------------------------------- 入口
def selfcheck() -> int:
    print("运行环境：%s" % ("打包后的 EXE" if core.is_frozen() else "Python 脚本"))
    print("Python：%s" % sys.version.split()[0])
    for name, ok, tip in (
        ("pywin32（COM / 窗口 / 注册表）", core.HAVE_WIN32, "建议安装"),
        ("psutil（进程兜底检测）", core.HAVE_PSUTIL, "建议安装"),
        ("pystray + Pillow（托盘图标）", HAVE_TRAY, "必装，否则没有托盘图标"),
    ):
        print("  [%s] %s%s" % ("√" if ok else "×", name, "" if ok else "  <- " + tip))
    try:
        import tkinter  # noqa: F401  (只检查是否可用)
        print("  [√] tkinter（设置窗口）")
    except Exception:
        print("  [×] tkinter（设置窗口）")
    print("配置目录：%s%s" % (BASE, "" if PORTABLE else "（不可写，已退回 APPDATA）"))
    print("配置文件：%s" % CONFIG_PATH)
    print("日志文件：%s" % LOG_PATH)
    print("课件保存位置：%s" % sync_mod.dest_root())
    print("开机自启：%s" % ("已开启" if core.get_autostart() else "未开启（默认关闭）"))
    try:
        u = sync_mod.list_removable_drives()
        print("可移动磁盘：%s" % ("、".join(u) if u else "无"))
    except Exception as e:
        print("可移动磁盘检测失败：%s" % e)
    print("当前能抓到的文件：")
    try:
        found = sync_mod.detect_files()
        if found:
            for p, k in found:
                print("  [%s] %s" % (sync_mod.KIND_NAMES.get(k, k), p))
        else:
            print("  无（没打开对应文件，或对应抓取开关没开）")
    except Exception as e:
        print("  检测失败：%s" % e)
    return 0


SINGLE_PORT = 47621      # 单实例用的本地通知端口（只在 127.0.0.1 上监听）


def _show_existing():
    """被第二次启动时调用：把已运行的实例的设置窗口弹出来"""
    try:
        import chub_ui

        try:
            import chub_shell

            chub_shell.open_shell(_InstHolder.app)
        except Exception:
            try:
                import chub_ui

                chub_ui.open_settings(_InstHolder.app)
            except Exception:
                pass
    except Exception:
        pass


class _InstHolder:
    """给激活回调用的小程序引用"""
    app = None


def main():
    args = sys.argv[1:]
    # ---- 单实例：已经在跑就别再开一份 ----
    if "--buddy" not in args and "--check" not in args and "--make-icon" not in args:
        si = core.SingleInstance(APP_ID, SINGLE_PORT)
        if not si.acquire():
            si.notify()
            print("ClassHub 已经在运行了（任务栏托盘里有图标），不会再开第二份。")
            sys.exit(0)
        _si = si
    if "--make-icon" in args:
        sys.exit(0 if export_icon() else 1)
    if "--check" in args:
        sys.exit(selfcheck())
    if "--buddy" in args:
        # 伙伴进程模式：盯住主进程，主进程没了就把它重新拉起来
        pid = 0
        relaunch = ""
        for i, a in enumerate(args):
            if a == "--buddy" and i + 1 < len(args):
                pid = int(args[i + 1])
            if a == "--relaunch" and i + 1 < len(args):
                relaunch = args[i + 1]
        sys.exit(guard_mod.buddy_loop(pid, relaunch))

    app = App()
    _InstHolder.app = app
    try:
        _si.start_listener(_show_existing)
    except Exception:
        pass
    app.run()


if __name__ == "__main__":
    main()
