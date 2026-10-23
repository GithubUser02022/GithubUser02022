# -*- coding: utf-8 -*-
"""
================================================================================
 ClassHub · chub_assoc —— 文件关联（默认打开方式）
================================================================================
把 .pptx 这类文件的默认打开程序改成你指定的那个（比如从 WPS 改成 Office
PowerPoint）。适合装了冰点还原 / 影子系统的机器：还原一次，程序改回来一次。

全部操作都在 HKEY_CURRENT_USER 下完成，不需要管理员权限。
默认关闭：不勾选、不点"立即应用"就绝不动注册表。

四步（顺序不能乱）：
    ① 删掉 Explorer 的 UserChoice（它会盖过我们的设置，是最大障碍）
    ② 在 HKCU\\Software\\Classes\\<ProgId>\\shell\\open\\command 写打开命令
    ③ 把扩展名的默认值指向这个 ProgId
    ④ 广播 SHCNE_ASSOCCHANGED 通知资源管理器刷新
"""

from __future__ import annotations

import os
import re

import chub_core as core
from chub_core import HAVE_WIN32, log

winreg = core.winreg

HKCU = winreg.HKEY_CURRENT_USER if HAVE_WIN32 else None
HKCR = winreg.HKEY_CLASSES_ROOT if HAVE_WIN32 else None
CLASSES = r"Software\Classes"
FILEEXTS = (r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts")
PROGID_PREFIX = "ClassHub.Assoc"

SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST = 0x0000


def available() -> bool:
    return HAVE_WIN32


def notify_shell() -> None:
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST,
                                             None, None)
    except Exception:
        pass


# ---------------------------------------------------------------- 查询
def _read_default(key_root, sub: str):
    if not HAVE_WIN32:
        return None
    try:
        with winreg.OpenKey(key_root, sub) as k:
            v, _ = winreg.QueryValueEx(k, "")
            return str(v)
    except Exception:
        return None


def progid_command(progid: str):
    if not progid or not HAVE_WIN32:
        return None
    for root, sub in ((HKCU, "%s\\%s\\shell\\open\\command" % (CLASSES, progid)),
                      (HKCR, "%s\\shell\\open\\command" % progid)):
        try:
            with winreg.OpenKey(root, sub) as k:
                v, _ = winreg.QueryValueEx(k, "")
                return str(v)
        except Exception:
            continue
    return None


def query_assoc(ext: str) -> dict:
    """查询某扩展名当前的打开方式"""
    if not ext.startswith("."):
        ext = "." + ext
    res = {"ext": ext, "userchoice": None, "progid": None, "source": "",
           "command": None, "locked": False}
    if not HAVE_WIN32:
        return res
    try:
        with winreg.OpenKey(HKCU, "%s\\%s\\UserChoice" % (FILEEXTS, ext)) as k:
            try:
                res["userchoice"] = winreg.QueryValueEx(k, "ProgId")[0]
            except Exception:
                res["userchoice"] = winreg.QueryValueEx(k, "")[0]
    except Exception:
        res["userchoice"] = None

    res["progid"] = _read_default(HKCU, "%s\\%s" % (CLASSES, ext))
    res["source"] = "用户级(HKCU)" if res["progid"] else ""
    if not res["progid"]:
        res["progid"] = _read_default(HKCR, ext)
        res["source"] = "系统级(HKCR)" if res["progid"] else ""

    effective = res["userchoice"] or res["progid"]
    res["command"] = progid_command(effective)
    res["locked"] = bool(res["userchoice"])
    return res


def describe_command(command) -> str:
    if not command:
        return "（未知）"
    m = re.search(r'"([^"]+\.exe)"', command, re.I) or re.search(r"(\S+\.exe)", command, re.I)
    if m:
        return os.path.basename(m.group(1))
    return command[:60]


# ---------------------------------------------------------------- 写入
def _delete_tree(root, sub: str) -> bool:
    if not HAVE_WIN32:
        return False
    try:
        with winreg.OpenKey(root, sub, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    child = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _delete_tree(root, "%s\\%s" % (sub, child))
        winreg.DeleteKey(root, sub)
        return True
    except FileNotFoundError:
        return True
    except Exception:
        return False


def build_command(exe: str, args: str = '"%1"') -> str:
    exe = exe.strip().strip('"')
    args = (args or '"%1"').strip()
    if "%1" not in args:
        args = '%s "%%1"' % args if args else '"%1"'
    return '"%s" %s' % (exe, args)


def apply_assoc(item: core.AssocItem, backup: bool = True) -> tuple:
    """应用一条文件关联，返回 (是否成功, 说明)"""
    if not HAVE_WIN32:
        return False, "未安装 pywin32，无法修改注册表"
    exts = item.exts()
    if not exts:
        return False, "没有填写扩展名"
    if not item.exe or not os.path.isfile(item.exe):
        return False, "程序文件不存在：%s" % item.exe

    ok_all, done = True, []
    for ext in exts:
        try:
            if backup and not item.original:
                cur = query_assoc(ext)
                item.original = cur.get("command") or ""
                item.original_progid = cur.get("progid") or ""
                if cur.get("userchoice"):
                    item.original_progid = cur["userchoice"]

            progid = item.progid_for(ext)

            # ① 删掉 UserChoice
            _delete_tree(HKCU, "%s\\%s\\UserChoice" % (FILEEXTS, ext))

            # ② 写我们自己的 ProgId
            with winreg.CreateKeyEx(HKCU, "%s\\%s" % (CLASSES, progid), 0,
                                    winreg.KEY_WRITE) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ,
                                  "%s（由 %s 管理）" % (item.name, PROGID_PREFIX))
            with winreg.CreateKeyEx(HKCU, "%s\\%s\\shell\\open\\command" % (CLASSES, progid),
                                    0, winreg.KEY_WRITE) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ,
                                  build_command(item.exe, item.args))
            with winreg.CreateKeyEx(HKCU, "%s\\%s\\DefaultIcon" % (CLASSES, progid),
                                    0, winreg.KEY_WRITE) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, '"%s",0' % item.exe)

            # ③ 指向我们的 ProgId
            with winreg.CreateKeyEx(HKCU, "%s\\%s" % (CLASSES, ext), 0,
                                    winreg.KEY_WRITE) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, progid)

            try:
                with winreg.CreateKeyEx(HKCU, "%s\\%s\\OpenWithProgids" % (CLASSES, ext),
                                        0, winreg.KEY_WRITE) as k:
                    winreg.SetValueEx(k, progid, 0, winreg.REG_NONE, b"")
            except Exception:
                pass
            done.append(ext)
        except Exception as exc:
            ok_all = False
            log("[%s] 设置 %s 关联失败：%s" % (item.name, ext, exc))

    notify_shell()
    if ok_all:
        item.status = "已应用"
        log("[%s] 已把 %s 的默认打开方式改为 %s" % (item.name, "、".join(done),
                                          os.path.basename(item.exe)))
        return True, "已应用：" + "、".join(done)
    item.status = "部分失败"
    return False, "部分扩展名设置失败，详见日志"


def revert_assoc(item: core.AssocItem) -> tuple:
    """还原一条文件关联"""
    if not HAVE_WIN32:
        return False, "未安装 pywin32，无法修改注册表"
    ok_all = True
    for ext in item.exts():
        try:
            progid = item.progid_for(ext)
            if item.original_progid:
                with winreg.CreateKeyEx(HKCU, "%s\\%s" % (CLASSES, ext), 0,
                                        winreg.KEY_WRITE) as k:
                    winreg.SetValueEx(k, "", 0, winreg.REG_SZ, item.original_progid)
            else:
                _delete_tree(HKCU, "%s\\%s" % (CLASSES, ext))
            if progid.startswith(PROGID_PREFIX) or progid.startswith("ClassHub.Assoc"):
                _delete_tree(HKCU, "%s\\%s" % (CLASSES, progid))
        except Exception as exc:
            ok_all = False
            log("[%s] 还原 %s 失败：%s" % (item.name, ext, exc))
    notify_shell()
    item.status = "已还原" if ok_all else "还原失败"
    log("[%s] 已还原默认打开方式" % item.name)
    return ok_all, "已还原"


# ---------------------------------------------------------------- 候选程序
CANDIDATES = {
    "POWERPNT.EXE": "Office PowerPoint",
    "WINWORD.EXE": "Office Word",
    "EXCEL.EXE": "Office Excel",
    "OUTLOOK.EXE": "Office Outlook",
    "wpp.exe": "WPS 演示",
    "wps.exe": "WPS 文字",
    "et.exe": "WPS 表格",
    "AcroRd32.exe": "Adobe Acrobat Reader",
    "Acrobat.exe": "Adobe Acrobat",
    "msedge.exe": "Microsoft Edge",
    "chrome.exe": "Google Chrome",
    "firefox.exe": "Firefox",
    "SumatraPDF.exe": "SumatraPDF",
    "PotPlayerMini64.exe": "PotPlayer",
    "PotPlayerMini.exe": "PotPlayer",
    "vlc.exe": "VLC",
    "wmplayer.exe": "Windows Media Player",
    "mspaint.exe": "画图",
    "notepad++.exe": "Notepad++",
    "Code.exe": "VS Code",
    "Photoshop.exe": "Photoshop",
}

EXT_PRESETS = {
    "PPT 演示文稿": ".pptx;.ppt;.ppsx;.pps;.potx;.pot",
    "Word 文档": ".docx;.doc;.rtf;.wps",
    "Excel 表格": ".xlsx;.xls;.csv;.et",
    "PDF 文档": ".pdf",
    "图片": ".jpg;.jpeg;.png;.gif;.bmp;.webp",
    "音视频": ".mp4;.mkv;.avi;.mov;.mp3;.flac;.wav",
    "压缩包": ".zip;.rar;.7z",
    "文本文件": ".txt;.log;.md;.ini",
}


def scan_candidates() -> list:
    """扫描注册表 App Paths，找出常见程序的实际安装路径 [(路径, 显示名)]"""
    found: list = []
    if not HAVE_WIN32:
        return found
    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    for exe_name, label in CANDIDATES.items():
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, "%s\\%s" % (base, exe_name)) as k:
                    v, _ = winreg.QueryValueEx(k, "")
                    path = str(v).strip().strip('"')
                    if path and os.path.isfile(path):
                        found.append((path, label))
                        break
            except Exception:
                continue
    return found
