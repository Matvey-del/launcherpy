import os, re, json, hashlib, shutil, threading, subprocess, ctypes, uuid, math, time, gzip, struct, zipfile, sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, filedialog
import minecraft_launcher_lib as mll
try:
    import minecraft_launcher_lib.runtime as mll_runtime
except Exception:
    mll_runtime = None

# Enable crisp rendering on Windows 10/11 before Tk creates the first window.
def enable_windows_dpi_awareness():
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI awareness
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


enable_windows_dpi_awareness()

# Keep user data in the roaming profile; preserve the existing RedLauncher folder.
ROAMING_DIR = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
APP_DIR = os.path.join(ROAMING_DIR, "RedLauncher")
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
ACCOUNTS_FILE = os.path.join(APP_DIR, "profiles.json")
STATS_FILE = os.path.join(APP_DIR, "stats.json")
DEFAULT_ROOT = os.path.join(APP_DIR, "game")
DEFAULT_VERSION = "1.21.4"
NAV = [("play", "Играть"), ("versions", "Версии"), ("servers", "Серверы"),
       ("mods", "Моды"), ("worlds", "Миры"), ("more", "Ещё")]

LOADER_NAMES = {"vanilla": "Vanilla", "fabric": "Fabric", "forge": "Forge"}

# Monochrome palette: charcoal surfaces, soft greys and clean white accents.
BG = "#111111"
SIDE = "#191919"
PANEL = "#242424"
FIELD = "#303030"
LINE = "#505050"
SHADOW = "#080808"
RED = "#eeeeee"
RED_HI = "#ffffff"
RED_DARK = "#555555"
TEXT = "#f5f5f5"
GREY = "#b8b8b8"
MUTED = "#858585"
FONT = "Segoe UI"

# Profile artwork bundled with the launcher. GIF is supported by Tkinter on Windows 7.
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ASSET_DIR = os.path.join(BASE_DIR, "assets")
AVATAR_FILES = {
    32: os.path.join(ASSET_DIR, "steve_32.gif"),
    34: os.path.join(ASSET_DIR, "steve_34.gif"),
    44: os.path.join(ASSET_DIR, "steve_44.gif"),
}


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def total_ram_mb():
    try:
        class MEMSTAT(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MEMSTAT()
        m.dwLength = ctypes.sizeof(MEMSTAT)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return int(m.ullTotalPhys // (1024 * 1024))
    except Exception:
        return 8192


def hash_password(password, salt=None):
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()
    return salt, digest


def offline_uuid(name):
    """UUID офлайн-игрока, как его считает сам Minecraft (MD5 от 'OfflinePlayer:имя')."""
    md5 = bytearray(hashlib.md5(("OfflinePlayer:" + name).encode("utf-8")).digest())
    md5[6] = (md5[6] & 0x0F) | 0x30
    md5[8] = (md5[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(md5)))


def open_folder(path):
    os.makedirs(path, exist_ok=True)
    try:
        os.startfile(path)
    except Exception:
        pass


JAVA_PATTERNS = [
    r"C:\Program Files\Java\*\bin\javaw.exe",
    r"C:\Program Files (x86)\Java\*\bin\javaw.exe",
    r"C:\Program Files\Eclipse Adoptium\*\bin\javaw.exe",
    r"C:\Program Files (x86)\Eclipse Adoptium\*\bin\javaw.exe",
    r"C:\Program Files\Microsoft\jdk-*\bin\javaw.exe",
    r"C:\Program Files\Zulu\*\bin\javaw.exe",
    r"C:\Program Files\BellSoft\*\bin\javaw.exe",
    r"C:\Program Files\Amazon Corretto\*\bin\javaw.exe",
    os.path.join(APP_DIR, "runtimes", "*", "bin", "javaw.exe"),
]


def find_javas(root=None):
    import glob
    cands = []
    jh = os.environ.get("JAVA_HOME")
    if jh:
        cands.extend([os.path.join(jh, "bin", "javaw.exe"), os.path.join(jh, "bin", "java.exe")])
    for pat in JAVA_PATTERNS:
        cands += glob.glob(pat)
    if root:
        cands += glob.glob(os.path.join(root, "runtime", "**", "bin", "javaw.exe"), recursive=True)
        cands += glob.glob(os.path.join(root, "runtime", "**", "bin", "java.exe"), recursive=True)
    # Also detect Java installed in PATH (common on older Windows installations).
    for exe in ("javaw.exe", "java.exe"):
        found = shutil.which(exe)
        if found:
            cands.append(found)
    seen, result = set(), []
    for c in cands:
        if os.path.isfile(c):
            key = os.path.normcase(os.path.normpath(c))
            if key not in seen:
                seen.add(key)
                result.append(c)
    return result


def mc_version_tuple(version):
    """Extract major/minor/patch from release ids and snapshot ids."""
    match = re.search(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?", str(version or ""))
    if not match:
        return None
    return tuple(int(x or 0) for x in match.groups())


def java_requirement(version, root=None):
    """Return (major, runtime component), using Mojang version JSON when available."""
    # Inspect the selected vanilla version metadata first. This is more reliable than
    # a hardcoded global Java version and also handles future Minecraft releases.
    if root:
        seen = set()
        current = str(version)
        for _ in range(8):
            if not current or current in seen:
                break
            seen.add(current)
            path = os.path.join(root, "versions", current, current + ".json")
            data = load_json(path, {})
            java_data = data.get("javaVersion") or {}
            major = java_data.get("majorVersion")
            component = java_data.get("component")
            try:
                if major:
                    return int(major), component or java_component_for_major(int(major))
            except (TypeError, ValueError):
                pass
            current = data.get("inheritsFrom")

    v = mc_version_tuple(version)
    if not v:
        return 8, "jre-legacy"
    if v >= (26, 1, 0):
        major = 25
    elif v >= (1, 20, 5):
        major = 21
    elif v >= (1, 18, 0):
        major = 17
    elif v >= (1, 17, 0):
        major = 16
    else:
        # The pre-1.17 official launcher runtime is Java 8 (jre-legacy).
        major = 8
    return major, java_component_for_major(major)


def java_component_for_major(major):
    return {
        8: "jre-legacy",
        16: "java-runtime-alpha",
        17: "java-runtime-gamma",
        21: "java-runtime-delta",
        25: "java-runtime-epsilon",
    }.get(int(major))


def java_major(path):
    """Возвращает основную версию Java (8, 17, 21...) или None."""
    checker = os.path.join(os.path.dirname(path), "java.exe")
    if not os.path.isfile(checker):
        checker = path
    try:
        out = subprocess.run([checker, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        text = (out.stderr or "") + (out.stdout or "")
    except Exception:
        return None
    m = re.search(r'version "(\d+)(?:\.(\d+))?', text)
    if not m:
        return None
    major = int(m.group(1))
    if major == 1 and m.group(2):
        major = int(m.group(2))
    return major


def read_tail(path, lines=200):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except Exception:
        return ""


def latest_crash_report(root, started):
    d = os.path.join(root, "crash-reports")
    if not os.path.isdir(d):
        return None
    files = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".txt")]
    files = [f for f in files if os.path.getmtime(f) >= started - 5]
    return max(files, key=os.path.getmtime) if files else None


def build_log_text(root, started):
    parts = []
    out_path = os.path.join(root, "logs", "launcher_output.log")
    if os.path.isfile(out_path) and os.path.getmtime(out_path) >= started - 5:
        parts.append("=== Вывод Java (launcher_output.log) ===\n" + read_tail(out_path, 400))
    crash = latest_crash_report(root, started)
    if crash:
        parts.append("=== Crash report: " + os.path.basename(crash) + " ===\n" + read_tail(crash, 400))
    latest = os.path.join(root, "logs", "latest.log")
    if os.path.isfile(latest) and os.path.getmtime(latest) >= started - 5:
        parts.append("=== logs/latest.log ===\n" + read_tail(latest, 200))
    return "\n".join(parts)


def is_normal_game_exit(code, root, started):
    """True for a normal Minecraft shutdown; noisy auth/Realms errors are not crashes."""
    # A fresh crash report is the strongest signal, even if Java returned code 0.
    if latest_crash_report(root, started):
        return False
    try:
        if int(code) == 0:
            return True
    except (TypeError, ValueError):
        pass
    # The in-game Quit button and the window close button normally write Stopping!
    # before the JVM exits. Ignore unrelated ERROR lines (e.g. offline auth 401).
    latest = os.path.join(root, "logs", "latest.log")
    if os.path.isfile(latest) and os.path.getmtime(latest) >= started - 5:
        tail = read_tail(latest, 160)
        fatal_markers = (
            r"\[main/FATAL\]", r"Exception in thread \"", r"A fatal error has been detected",
            r"The game crashed", r"Uncaught exception", r"Crash report saved",
        )
        if any(re.search(pattern, tail, re.I) for pattern in fatal_markers):
            return False
        if re.search(r"(?m)\bStopping!\s*$", tail):
            return True
    return False


# ---------- servers.dat (NBT) ----------
def _nbt_read(data, pos, tag):
    if tag == 1:
        return struct.unpack_from(">b", data, pos)[0], pos + 1
    if tag == 2:
        return struct.unpack_from(">h", data, pos)[0], pos + 2
    if tag == 3:
        return struct.unpack_from(">i", data, pos)[0], pos + 4
    if tag == 4:
        return struct.unpack_from(">q", data, pos)[0], pos + 8
    if tag == 5:
        return struct.unpack_from(">f", data, pos)[0], pos + 4
    if tag == 6:
        return struct.unpack_from(">d", data, pos)[0], pos + 8
    if tag == 7:
        n = struct.unpack_from(">i", data, pos)[0]
        return None, pos + 4 + n
    if tag == 8:
        n = struct.unpack_from(">H", data, pos)[0]
        pos += 2
        return data[pos:pos + n].decode("utf-8", "replace"), pos + n
    if tag == 9:
        etype = data[pos]
        n = struct.unpack_from(">i", data, pos + 1)[0]
        pos += 5
        out = []
        for _ in range(n):
            v, pos = _nbt_read(data, pos, etype)
            out.append(v)
        return out, pos
    if tag == 10:
        out = {}
        while True:
            t = data[pos]
            pos += 1
            if t == 0:
                return out, pos
            n = struct.unpack_from(">H", data, pos)[0]
            pos += 2
            name = data[pos:pos + n].decode("utf-8", "replace")
            pos += n
            v, pos = _nbt_read(data, pos, t)
            out[name] = v
    if tag == 11:
        n = struct.unpack_from(">i", data, pos)[0]
        return None, pos + 4 + 4 * n
    if tag == 12:
        n = struct.unpack_from(">i", data, pos)[0]
        return None, pos + 4 + 8 * n
    raise ValueError("unknown NBT tag %d" % tag)


def read_servers(root):
    """Список серверов из servers.dat: name, ip, icon (data:image/png;base64,...)."""
    path = os.path.join(root, "servers.dat")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "rb") as f:
            raw = f.read()
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
        # заголовок корневого тега: тип (1 байт), длина имени (2 байта), имя
        name_len = struct.unpack_from(">H", raw, 1)[0]
        top, _ = _nbt_read(raw, 3 + name_len, 10)
        result = []
        for s in top.get("servers", []) or []:
            result.append({"name": s.get("name", ""), "ip": s.get("ip", ""), "icon": s.get("icon", "")})
        return result
    except Exception:
        return []


def server_key(host, port):
    host = host.strip().lower()
    port = str(port).strip()
    return host if port in ("", "25565") else f"{host}:{port}"


def read_new(path, pos):
    if not os.path.isfile(path):
        return "", pos
    size = os.path.getsize(path)
    if size < pos:
        pos = 0
    with open(path, "rb") as f:
        f.seek(pos)
        data = f.read()
    return data.decode("utf-8", "replace"), pos + len(data)


def add_playtime(key, seconds):
    if seconds <= 0:
        return
    stats = load_json(STATS_FILE, {})
    stats[key] = stats.get(key, 0) + seconds
    save_json(STATS_FILE, stats)


def fmt_hours(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h} ч {m} мин"


def dedupe_version_libraries(root, version_id):
    """Убирает дубли библиотек в json версии (например, два asm разных версий).
    Fabric падает с 'duplicate ASM classes', если в classpath попали обе."""
    path = os.path.join(root, "versions", version_id, version_id + ".json")
    data = load_json(path, None)
    if not data or not isinstance(data.get("libraries"), list):
        return

    def ver_key(v):
        return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-+]", v))

    def lib_key(name):
        parts = name.split(":")
        if len(parts) < 3:
            return None, None
        key = (parts[0], parts[1], parts[3] if len(parts) > 3 else "")
        return key, parts[2]

    libs = data["libraries"]
    best = {}
    for lib in libs:
        key, ver = lib_key(lib.get("name", ""))
        if key is None:
            continue
        if key not in best or ver_key(ver) > ver_key(best[key]):
            best[key] = ver
    kept = []
    for lib in libs:
        key, ver = lib_key(lib.get("name", ""))
        if key is None or ver == best[key]:
            kept.append(lib)
    if len(kept) != len(libs):
        backup = path + ".redlauncher.bak"
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
        data["libraries"] = kept
        save_json(path, data)



def _version_tuple(value):
    nums = re.findall(r"\d+", value or "")
    return tuple(int(x) for x in nums) if nums else (0,)


def sanitize_asm_classpath(command):
    """Удаляет конфликтующие версии одного ASM-артефакта из аргумента -cp."""
    cmd = list(command)
    try:
        cp_index = next(i for i, arg in enumerate(cmd) if arg in ("-cp", "-classpath", "--class-path"))
        raw_cp = cmd[cp_index + 1]
    except (StopIteration, IndexError):
        return cmd, []
    entries = raw_cp.split(os.pathsep)
    chosen, removed = {}, []
    for entry in entries:
        norm = entry.replace("\\", "/")
        match = re.search(r"/org/ow2/asm/([^/]+)/([^/]+)/\1-([^/]+)\.jar$", norm, re.I)
        if not match:
            continue
        artifact, folder_version, filename_version = match.groups()
        key = artifact.lower()
        version = filename_version or folder_version
        current = chosen.get(key)
        if current is None or _version_tuple(version) > _version_tuple(current[0]):
            if current is not None:
                removed.append(current[1])
            chosen[key] = (version, entry)
        else:
            removed.append(entry)
    if removed:
        kept = [e for e in entries if e not in removed]
        cmd[cp_index + 1] = os.pathsep.join(kept)
    return cmd, removed


def lerp(a, b, t):
    ra, ga, ba = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    rb, gb, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    return "#%02x%02x%02x" % (int(ra + (rb - ra) * t), int(ga + (gb - ga) * t), int(ba + (bb - ba) * t))


def rrect(c, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def alive(w):
    try:
        return bool(w.winfo_exists())
    except tk.TclError:
        return False


class Panel(tk.Canvas):
    """Скруглённая карточка с мягкой тенью. Содержимое кладётся в .inner."""
    PAD = 12
    SH = 2

    def __init__(self, parent, bg=BG, fill=PANEL, radius=16):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0)
        self.fill = fill
        self.radius = radius
        self.inner = tk.Frame(self, bg=fill)
        self.win = self.create_window(self.PAD, self.PAD, anchor="nw", window=self.inner)
        self._h = 0
        self.bind("<Configure>", lambda e: self._layout())
        self.inner.bind("<Configure>", lambda e: self._layout())

    def _layout(self):
        if not alive(self):
            return
        w = self.winfo_width()
        if w < 60:
            return
        self.itemconfigure(self.win, width=w - 2 * self.PAD)
        h = self.inner.winfo_reqheight() + 2 * self.PAD + self.SH
        if h != self._h:
            self._h = h
            self.config(height=h)
        self.delete("bg")
        r = self.radius
        rrect(self, 5, self.SH + 3, w - 5, h - 1, r, fill="#050505", outline="", tags="bg")
        rrect(self, 2, self.SH, w - 2, h - 3, r, fill=SHADOW, outline="", tags="bg")
        rrect(self, 0, 0, w - 1, h - self.SH - 1, r, fill=self.fill, outline="#66848a", width=1, tags="bg")
        self.tag_lower("bg")


class Btn(tk.Canvas):
    """Скруглённая кнопка с плавной сменой цвета при наведении."""
    STYLES = {
        "primary": ("#eeeeee", "#ffffff", "#111111"),
        "soft": ("#4a4a4a", "#5a5a5a", "#ffffff"),
        "ghost": ("#383838", "#505050", "#eeeeee"),
        "danger": ("#4a3333", "#644444", "#ffffff"),
        "nav": ("#252525", "#3a3a3a", "#b8b8b8"),
        "nav_on": ("#555555", "#666666", "#ffffff"),
    }

    def __init__(self, parent, text, cmd, style="primary", bg=PANEL, size=10, h=34,
                 big=False, pulse=False, stretch=False, width=None, align="center"):
        self.text = text
        self.cmd = cmd
        self.h = 52 if big else h
        self.font = tkfont.Font(family=FONT, size=14 if big else size, weight="bold")
        self.base, self.hover, self.fg = self.STYLES[style]
        self.cur = self.base
        self.align = align
        self.stretch = stretch
        self.pulse = pulse
        self.glow = RED_DARK
        self._t = 0.0
        self._job = None
        natural = self.font.measure(text) + (90 if big else 36)
        self.w = width or natural
        super().__init__(parent, width=self.w, height=self.h, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Enter>", lambda e: self.tween(self.hover))
        self.bind("<Leave>", lambda e: self.tween(self.base))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Configure>", self._on_configure)
        self.paint()
        if pulse:
            self.beat()

    def set_style(self, style):
        self.base, self.hover, self.fg = self.STYLES[style]
        self.tween(self.base)

    def _on_configure(self, e):
        if self.stretch and e.width > 10 and e.width != self.w:
            self.w = e.width
            self.paint()

    def _release(self, e):
        if 0 <= e.x <= self.w and 0 <= e.y <= self.h and self.cmd:
            self.cmd()

    def tween(self, target, steps=7):
        if self._job:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        start = self.cur

        def step(k=1):
            if not alive(self):
                return
            self.cur = lerp(start, target, k / steps)
            self.paint()
            self._job = self.after(14, step, k + 1) if k < steps else None
        step()

    def paint(self):
        if not alive(self):
            return
        self.delete("all")
        w, h = self.w, self.h
        if self.pulse:
            rrect(self, 0, 0, w - 1, h - 1, min(12, h / 2), fill=self.glow, outline="")
            rrect(self, 2, 2, w - 3, h - 3, min(10, (h - 4) / 2), fill=self.cur, outline="")
        else:
            rrect(self, 0, 0, w - 1, h - 1, min(12, h / 2), fill=self.cur, outline="")
        if self.align == "center":
            self.create_text(w / 2, h / 2, text=self.text, fill=self.fg, font=self.font)
        else:
            self.create_text(18, h / 2, text=self.text, fill=self.fg, font=self.font, anchor="w")

    def beat(self):
        if not alive(self):
            return
        self._t += 0.12
        self.glow = lerp(RED_DARK, RED_HI, (math.sin(self._t) + 1) / 2)
        self.paint()
        self.after(50, self.beat)


class Field(tk.Canvas):
    """Поле ввода с рамкой, которая становится красной при фокусе."""
    def __init__(self, parent, show=None, bg=PANEL, h=38):
        super().__init__(parent, height=h, bg=bg, highlightthickness=0, bd=0)
        self.h = h
        self.border = LINE
        self.entry = tk.Entry(self, bg=FIELD, fg=TEXT, insertbackground=RED, relief="flat",
                              font=(FONT, 11), show=show or "", bd=0, highlightthickness=0)
        self.win = self.create_window(12, h // 2, anchor="w", window=self.entry)
        self.entry.bind("<FocusIn>", lambda e: self._set_border(RED))
        self.entry.bind("<FocusOut>", lambda e: self._set_border(LINE))
        self.bind("<Configure>", lambda e: self._paint())
        self.bind("<Button-1>", lambda e: self.entry.focus_set())

    def _set_border(self, color):
        self.border = color
        self._paint()

    def _paint(self):
        if not alive(self):
            return
        w = self.winfo_width()
        if w < 40:
            return
        self.delete("bg")
        self.itemconfigure(self.win, width=w - 24)
        rrect(self, 0, 0, w - 1, self.h - 1, 10, fill=self.border, outline="", tags="bg")
        rrect(self, 1, 1, w - 2, self.h - 2, 9, fill=FIELD, outline="", tags="bg")
        self.tag_lower("bg")

    def get(self):
        return self.entry.get().strip()

    def raw(self):
        return self.entry.get()


class Toggle(tk.Canvas):
    """Переключатель в стиле iOS с анимацией."""
    def __init__(self, parent, var, cmd=None, bg=PANEL):
        super().__init__(parent, width=44, height=24, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.var = var
        self.cmd = cmd
        self.pos = 1.0 if var.get() else 0.0
        self.bind("<Button-1>", self._click)
        self._paint()

    def _click(self, e):
        self.var.set(not self.var.get())
        self._animate(1.0 if self.var.get() else 0.0)
        if self.cmd:
            self.cmd()

    def _animate(self, target, steps=6):
        start = self.pos

        def step(k=1):
            if not alive(self):
                return
            self.pos = start + (target - start) * (k / steps)
            self._paint()
            if k < steps:
                self.after(16, step, k + 1)
        step()

    def _paint(self):
        if not alive(self):
            return
        self.delete("all")
        rrect(self, 0, 0, 43, 23, 11, fill=lerp("#2a2a2a", RED, self.pos), outline="")
        x = 3 + self.pos * 20
        self.create_oval(x, 3, x + 18, 21, fill=TEXT, outline="")


class Slider(tk.Canvas):
    def __init__(self, parent, var, frm, to, step, cmd=None, bg=PANEL):
        super().__init__(parent, height=28, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.var, self.frm, self.to, self.step, self.cmd = var, frm, to, step, cmd
        self.bind("<Configure>", lambda e: self._paint())
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)
        self.var.trace_add("write", lambda *a: self._paint())

    def _drag(self, e):
        pad = 12
        w = self.winfo_width()
        frac = min(1, max(0, (e.x - pad) / max(1, w - 2 * pad)))
        val = int(round((self.frm + frac * (self.to - self.frm)) / self.step) * self.step)
        val = max(self.frm, min(self.to, val))
        if val != self.var.get():
            self.var.set(val)
            if self.cmd:
                self.cmd()

    def _paint(self):
        if not alive(self):
            return
        self.delete("all")
        w = self.winfo_width()
        if w < 40:
            return
        pad, cy = 12, 14
        rrect(self, pad, cy - 3, w - pad, cy + 3, 3, fill=FIELD, outline="")
        frac = (self.var.get() - self.frm) / (self.to - self.frm)
        kx = pad + frac * (w - 2 * pad)
        if kx - pad > 6:
            rrect(self, pad, cy - 3, kx, cy + 3, 3, fill=RED, outline="")
        self.create_oval(kx - 9, cy - 9, kx + 9, cy + 9, fill=TEXT, outline=RED, width=2)


class Progress(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, height=8, bg=BG, highlightthickness=0, bd=0)
        self.value = 0.0
        self.bind("<Configure>", lambda e: self._paint())

    def set(self, v):
        self.value = max(0.0, min(1.0, v))
        self._paint()

    def _paint(self):
        if not alive(self):
            return
        self.delete("all")
        w = self.winfo_width()
        if w < 20:
            return
        rrect(self, 0, 0, w - 1, 7, 3, fill=FIELD, outline="")
        fw = int((w - 1) * self.value)
        if fw > 6:
            rrect(self, 0, 0, fw, 7, 3, fill=RED, outline="")


class Avatar(tk.Canvas):
    """Square Steve profile avatar, shared between account and profile cards."""
    _image_cache = {}

    def __init__(self, parent, letter="?", bg=PANEL, size=44):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, bd=0)
        self._avatar_photo = None
        try:
            # Use the closest bundled size to avoid runtime image scaling on older Tk builds.
            target_size = min(AVATAR_FILES, key=lambda value: abs(value - int(size)))
            image_path = AVATAR_FILES[target_size]
            if image_path not in self._image_cache:
                if not os.path.isfile(image_path):
                    raise IOError("Missing bundled Steve avatar: " + image_path)
                self._image_cache[image_path] = tk.PhotoImage(file=image_path)
            self._avatar_photo = self._image_cache[image_path]
            self.create_image(size / 2, size / 2, image=self._avatar_photo, anchor="center")
            self.create_rectangle(0.5, 0.5, size - 0.5, size - 0.5,
                                  outline=RED, width=1)
        except Exception:
            # Keep the account page usable if somebody accidentally removes the assets folder.
            self.create_rectangle(1, 1, size - 1, size - 1,
                                  fill=RED_DARK, outline=RED, width=1)
            self.create_text(size / 2, size / 2, text=(letter[:1] or "?").upper(),
                             fill=TEXT, font=(FONT, int(size * 0.38), "bold"))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("STIVOX LAUNCHER 3.1 · Minecraft")
        self.geometry("760x520")
        self.minsize(560, 400)
        self.configure(bg=BG)
        self._wallpaper_photo = None
        self._wallpaper_label = None
        self._wallpaper_source = os.path.join(ASSET_DIR, "background.png")
        self.bind("<Configure>", self._resize_wallpaper)

        self.settings = load_json(CONFIG_FILE, {})
        self.settings.setdefault("root", DEFAULT_ROOT)
        self.settings.setdefault("version", DEFAULT_VERSION)
        self.settings.setdefault("ram", min(2048, max(1024, total_ram_mb() - 1536)))
        self.settings.setdefault("snapshots", False)
        self.settings.setdefault("account", None)
        self.settings.setdefault("java", "")
        self.settings.setdefault("java_by_major", {})
        self.settings.setdefault("loader", "vanilla")
        self.settings.setdefault("saved_servers", [])
        self.accounts = load_json(ACCOUNTS_FILE, [])

        ram_limit = max(1024, min(4096, total_ram_mb() - 1024))
        self.settings["ram"] = max(1024, min(int(self.settings.get("ram", 2048)), ram_limit))
        self.ram_var = tk.IntVar(value=self.settings["ram"])
        self.version_cache = None
        self.visible_versions = []
        self.java_cache = None
        self.loader_cache = {}
        self.loader_tab = self.settings["loader"]
        self.game_running = False
        self.launching = False
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.current = None
        self.page = None
        self.outgoing = None
        self.slide_job = None
        self.builders = {"play": self.page_play, "stats": self.page_stats, "accounts": self.page_accounts,
                         "versions": self.page_versions, "mods": self.page_mods,
                         "settings": self.page_settings, "doctor": self.page_doctor,
                         "servers": self.page_servers, "worlds": self.page_worlds, "more": self.page_more}
        self.build_shell()
        self.show_page("play", animate=False)

    # ---------- оболочка ----------
    def _resize_wallpaper(self, event=None):
        # Wallpaper is a real bundled image, scaled to the current window size.
        if event is not None and event.widget is not self:
            return
        try:
            from PIL import Image, ImageTk
            if not os.path.isfile(self._wallpaper_source):
                return
            w, h = max(1, self.winfo_width()), max(1, self.winfo_height())
            image = Image.open(self._wallpaper_source).convert("RGB")
            ratio = max(w / image.width, h / image.height)
            resampling = getattr(Image, "Resampling", Image)
            image = image.resize((int(image.width * ratio), int(image.height * ratio)), resampling.LANCZOS)
            left = max(0, (image.width - w) // 2)
            top = max(0, (image.height - h) // 2)
            image = image.crop((left, top, left + w, top + h))
            self._wallpaper_photo = ImageTk.PhotoImage(image)
            if self._wallpaper_label is None or not alive(self._wallpaper_label):
                self._wallpaper_label = tk.Label(self, image=self._wallpaper_photo, bd=0)
                self._wallpaper_label.place(x=0, y=0, relwidth=1, relheight=1)
                self._wallpaper_label.lower()
            else:
                self._wallpaper_label.configure(image=self._wallpaper_photo)
                self._wallpaper_label.lower()
        except Exception:
            # The launcher remains usable if Pillow is not installed.
            pass

    def build_shell(self):
        """Minimal launcher shell: a single compact panel centered on a dark canvas."""
        self.configure(bg=BG)
        self.nav = {}
        self.header_title = tk.Label(self, text="STIVOX", bg=BG, fg=TEXT,
                                     font=(FONT, 1))
        self.header_meta = tk.Label(self, text="", bg=BG, fg=GREY, font=(FONT, 1))
        self.top_status = tk.Label(self, text="● ГОТОВ", bg=BG, fg=GREY,
                                   font=(FONT, 8, "bold"))
        self.stage = tk.Frame(self, bg=BG)
        self.stage.place(relx=0.5, rely=0.5, anchor="center",
                         relwidth=1, relheight=1)
    def show_page(self, key, animate=True):
        # Secondary destinations live under the "Ещё" section in the bottom dock.
        active_key = key if key in self.nav else "more"
        for k, b in self.nav.items():
            b.set_style("nav_on" if k == active_key else "nav")
        order = [k for k, _ in NAV]
        direction = 1
        if self.current in order and key in order:
            direction = 1 if order.index(key) > order.index(self.current) else -1
        self.current = key
        titles = {"play": "Играть", "stats": "Статистика", "accounts": "Аккаунты",
                  "versions": "Версии игры", "mods": "Моды", "doctor": "Диагностика",
                  "settings": "Настройки", "servers": "Серверы", "worlds": "Миры", "more": "Ещё"}
        self.header_title.config(text=titles.get(key, "STIVOX").upper())
        account = self.current_account()
        name = account["name"] if account else "Без аккаунта"
        self.header_meta.config(text=f"{name}  ·  {self.version_label()}")

        old = self.page
        if self.slide_job:
            try:
                self.after_cancel(self.slide_job)
            except tk.TclError:
                pass
            self.slide_job = None
            if self.outgoing is not None and alive(self.outgoing):
                self.outgoing.destroy()
            self.outgoing = None
            if old is not None and alive(old):
                old.place_configure(x=0)

        new = tk.Frame(self.stage, bg=BG)
        self.builders[key](new)
        self.page = new
        if animate and old is not None and alive(old):
            self.outgoing = old
            new.place(x=28 * direction, y=0, relwidth=1, relheight=1)
            new.lift()
            self._slide(new, old, 28 * direction, 0)
        else:
            if old is not None and alive(old):
                old.destroy()
            new.place(x=0, y=0, relwidth=1, relheight=1)

    def _slide(self, new, old, start, step, steps=12):
        if not (alive(new) and alive(old)):
            self.slide_job = None
            return
        t = (step + 1) / steps
        x = int(start * (1 - (1 - (1 - t) ** 3)))
        new.place_configure(x=x)
        old.place_configure(x=x - start)
        if step + 1 < steps:
            self.slide_job = self.after(14, self._slide, new, old, start, step + 1, steps)
        else:
            self.slide_job = None
            old.destroy()
            self.outgoing = None
            new.place_configure(x=0)

    def heading(self, p, title, sub):
        tk.Label(p, text=title, bg=BG, fg=TEXT, font=(FONT, 14, "bold")).pack(anchor="w")
        tk.Label(p, text=sub, bg=BG, fg=GREY, font=(FONT, 8)).pack(anchor="w", pady=(1, 8))

    def ui(self, fn):
        def run():
            try:
                fn()
            except (tk.TclError, RuntimeError):
                pass
        try:
            self.after(0, run)
        except (tk.TclError, RuntimeError):
            pass

    def set_status(self, text):
        def apply():
            if hasattr(self, "top_status") and alive(self.top_status):
                low = text.lower()
                color = RED if ("ошибка" in low or "не удалось" in low) else ("#e6b65c" if any(x in low for x in ("загруз", "установ", "запуск")) else "#79c99a")
                short = text if len(text) <= 34 else text[:31] + "..."
                self.top_status.config(text="● " + short.upper(), fg=color)
            if hasattr(self, "status") and alive(self.status):
                self.status.config(text=text)
        self.ui(apply)

    def current_account(self):
        return next((a for a in self.accounts if a["name"] == self.settings.get("account")), None)

    def save_settings(self):
        self.settings["ram"] = self.ram_var.get()
        save_json(CONFIG_FILE, self.settings)

    # ---------- Главная ----------
    def page_play(self, p):
        """Single-card start screen inspired by the supplied reference."""
        shell = tk.Frame(p, bg=BG)
        shell.place(relx=0.5, rely=0.5, anchor="center")

        card = tk.Frame(shell, bg="#252525", highlightthickness=1,
                        highlightbackground="#555555", padx=26, pady=22)
        card.pack()

        brand = tk.Label(card, text="STIVOX", bg="#252525", fg="#f2f2f2",
                         font=(FONT, 19, "bold"))
        brand.pack(anchor="center", pady=(0, 13))

        # Account selector.
        accounts = [a.get("name", "") for a in self.accounts if a.get("name")]
        current = self.settings.get("account") or (accounts[0] if accounts else "")
        self.home_account_var = tk.StringVar(value=current)
        self.home_account_box = self._home_combo(card, self.home_account_var,
                                                   accounts or ["Нет аккаунтов"])
        self.home_account_box.pack(fill="x", pady=(0, 7))
        self.home_account_box.bind("<<ComboboxSelected>>", self._home_account_changed)

        # The game version and mod loader are presented together, as in the reference.
        loader = self.settings.get("loader", "vanilla")
        loader_label = LOADER_NAMES.get(loader, "Vanilla")
        version_text = f"{loader_label} {self.settings.get('version', DEFAULT_VERSION)}"
        self.home_version_var = tk.StringVar(value=version_text)
        self.home_version_box = self._home_combo(
            card, self.home_version_var,
            [f"{name} {self.settings.get('version', DEFAULT_VERSION)}"
             for name in LOADER_NAMES.values()])
        self.home_version_box.pack(fill="x", pady=(0, 12))
        self.home_version_box.bind("<<ComboboxSelected>>", self._home_version_changed)

        options = tk.Frame(card, bg="#252525")
        options.pack(fill="x", pady=(0, 9))
        self.delayed_launch_var = tk.BooleanVar(value=bool(self.settings.get("delayed_launch", False)))
        tk.Checkbutton(options, text="Отложенный запуск", variable=self.delayed_launch_var,
                       command=self._save_home_options, bg="#252525", fg="#dddddd",
                       activebackground="#252525", activeforeground="#ffffff",
                       selectcolor="#3a3a3a", font=(FONT, 9), bd=0,
                       highlightthickness=0).pack(anchor="w")
        self.snapshots_var = tk.BooleanVar(value=bool(self.settings.get("snapshots", False)))
        tk.Checkbutton(options, text="Показывать снапшоты", variable=self.snapshots_var,
                       command=self._save_home_snapshots, bg="#252525", fg="#dddddd",
                       activebackground="#252525", activeforeground="#ffffff",
                       selectcolor="#3a3a3a", font=(FONT, 9), bd=0,
                       highlightthickness=0).pack(anchor="w")

        self.home_launch_btn = Btn(card, "ЗАПУСТИТЬ", self._home_launch,
                                   style="primary", bg="#252525", h=47, size=13,
                                   width=236)
        self.home_launch_btn.pack(fill="x", pady=(0, 4))

        actions = tk.Frame(card, bg="#252525")
        actions.pack(fill="x")
        for column in range(4):
            actions.grid_columnconfigure(column, weight=1, uniform="actions")
        for col, (symbol, hint, command) in enumerate([
            ("i", "Информация и аккаунты", lambda: self.show_page("more")),
            ("▰", "Папка Minecraft", lambda: open_folder(self.settings["root"])),
            ("↻", "Версии и загрузчики", lambda: self.show_page("versions")),
            ("☰", "Меню и настройки", self._open_home_menu),
        ]):
            btn = Btn(actions, symbol, command, style="ghost", bg="#252525",
                      h=34, size=13, width=52)
            btn.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 3, 0))
            btn.bind("<Enter>", lambda e, w=btn, t=hint: self._set_home_hint(t))
            btn.bind("<Leave>", lambda e: self._set_home_hint(""))

        self.home_hint = tk.Label(card, text="", bg="#252525", fg="#999999",
                                  font=(FONT, 8))
        self.home_hint.pack(pady=(7, 0))

    def _home_combo(self, parent, variable, values):
        from tkinter import ttk
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Home.TCombobox", fieldbackground="#333333",
                        background="#333333", foreground="#f0f0f0",
                        arrowcolor="#eeeeee", bordercolor="#555555",
                        lightcolor="#555555", darkcolor="#555555",
                        padding=6, font=(FONT, 9))
        style.map("Home.TCombobox",
                  fieldbackground=[("readonly", "#333333")],
                  foreground=[("readonly", "#f0f0f0")],
                  selectbackground=[("readonly", "#444444")],
                  selectforeground=[("readonly", "#ffffff")])
        box = ttk.Combobox(parent, textvariable=variable, values=values,
                           state="readonly", style="Home.TCombobox",
                           font=(FONT, 9))
        return box

    def _set_home_hint(self, value):
        if hasattr(self, "home_hint") and alive(self.home_hint):
            self.home_hint.config(text=value)

    def _home_account_changed(self, event=None):
        name = self.home_account_var.get()
        if any(a.get("name") == name for a in self.accounts):
            self.settings["account"] = name
            self.save_settings()
            self.show_page("play", animate=False)

    def _home_version_changed(self, event=None):
        value = self.home_version_var.get()
        loader_name, _, version = value.partition(" ")
        loader = next((key for key, label in LOADER_NAMES.items()
                       if label == loader_name), "vanilla")
        self.settings["loader"] = loader
        if version.strip():
            self.settings["version"] = version.strip()
        self.save_settings()

    def _save_home_options(self):
        self.settings["delayed_launch"] = bool(self.delayed_launch_var.get())
        self.save_settings()

    def _save_home_snapshots(self):
        self.settings["snapshots"] = bool(self.snapshots_var.get())
        self.save_settings()

    def _home_launch(self):
        self._save_home_options()
        if self.delayed_launch_var.get():
            self.home_launch_btn.config(state="disabled")
            self.home_launch_btn.text = "ЗАПУСК ЧЕРЕЗ 5 СЕК."
            self.home_launch_btn.paint()
            self.after(5000, self._finish_delayed_launch)
        else:
            self.start_game()

    def _finish_delayed_launch(self):
        if hasattr(self, "home_launch_btn") and alive(self.home_launch_btn):
            self.home_launch_btn.config(state="normal")
            self.home_launch_btn.text = "ЗАПУСТИТЬ"
            self.home_launch_btn.paint()
        self.start_game()

    def _open_home_menu(self):
        win = tk.Toplevel(self)
        win.title("STIVOX — меню")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        win.geometry("300x390")
        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{x}+{y}")
        panel = tk.Frame(win, bg="#252525", padx=18, pady=18)
        panel.pack(fill="both", expand=True, padx=12, pady=12)
        tk.Label(panel, text="МЕНЮ", bg="#252525", fg=TEXT,
                 font=(FONT, 13, "bold")).pack(anchor="w", pady=(0, 12))
        entries = [
            ("Настройки", "settings"), ("Аккаунты", "accounts"),
            ("Версии Minecraft", "versions"), ("Серверы", "servers"),
            ("Моды", "mods"), ("Миры и резервные копии", "worlds"),
            ("Диагностика", "doctor"), ("Статистика", "stats"),
        ]
        for title, page in entries:
            Btn(panel, title, lambda key=page: (win.destroy(), self.show_page(key)),
                style="ghost", bg="#252525", h=31, size=9,
                stretch=True).pack(fill="x", pady=2)
        Btn(panel, "НАЗАД К ЗАПУСКУ", lambda: (win.destroy(), self.show_page("play")),
            style="primary", bg="#252525", h=34, size=9,
            stretch=True).pack(fill="x", pady=(10, 0))

    def page_stats(self, p):
        self.heading(p, "Статистика", "Сколько времени ты провёл на серверах")
        stats = load_json(STATS_FILE, {})
        root = self.settings["root"]
        servers = {server_key(*(s["ip"].rsplit(":", 1) if ":" in s["ip"] else (s["ip"], "25565"))): s
                   for s in read_servers(root) if s.get("ip")}
        top = sorted(stats.items(), key=lambda kv: kv[1], reverse=True)[:5]
        total = sum(stats.values())

        tk.Label(p, text=f"Всего в играх: {fmt_hours(total)}", bg=BG, fg=RED,
                 font=(FONT, 11, "bold")).pack(anchor="w", pady=(0, 8))
        if not top:
            tk.Label(p, text="Пока пусто. Зайди на сервер, и время начнёт считаться.",
                     bg=BG, fg=GREY, font=(FONT, 10)).pack(anchor="w", pady=10)
            return

        self._icons = []
        for rank, (key, seconds) in enumerate(top, 1):
            srv = servers.get(key, {})
            name = srv.get("name") or key
            pn = Panel(p)
            pn.pack(fill="x", pady=3)
            r = tk.Frame(pn.inner, bg=PANEL)
            r.pack(fill="x")
            tk.Label(r, text=str(rank), bg=PANEL, fg=GREY, font=(FONT, 12, "bold"), width=2).pack(side="left")
            icon = None
            if srv.get("icon"):
                try:
                    img = tk.PhotoImage(data=srv["icon"].split(",", 1)[-1])
                    self._icons.append(img)
                    icon = img
                except tk.TclError:
                    icon = None
            if icon:
                c = tk.Canvas(r, width=48, height=48, bg=PANEL, highlightthickness=0, bd=0)
                c.create_image(24, 24, image=icon)
                c.pack(side="left", padx=(6, 12))
            else:
                Avatar(r, name).pack(side="left", padx=(6, 12))
            info = tk.Frame(r, bg=PANEL)
            info.pack(side="left", fill="x", expand=True)
            tk.Label(info, text=name, bg=PANEL, fg=TEXT, font=(FONT, 12, "bold")).pack(anchor="w")
            tk.Label(info, text=key, bg=PANEL, fg=GREY, font=(FONT, 9)).pack(anchor="w")
            tk.Label(r, text=fmt_hours(seconds), bg=PANEL, fg=RED, font=(FONT, 11, "bold")).pack(side="right", padx=10)

    def on_close(self):
        if self.game_running:
            close_all = messagebox.askyesno(
                "Лаунчер",
                "Игра запущена. Закрыть лаунчер полностью?\n\n"
                "Да — закрыть. Игра продолжит работать, но логи при вылете не покажутся.\n"
                "Нет — свернуть лаунчер в фон.")
            if not close_all:
                self.withdraw()
                return
        self.destroy()
        os._exit(0)

    # ---------- Вылет / закрытие игры ----------
    def on_game_exit(self, code, root, version, started):
        self.game_running = False
        self.deiconify()
        self.lift()
        self.focus_force()
        if is_normal_game_exit(code, root, started):
            self.set_status("Minecraft закрыт штатно")
            return
        self.show_crash_dialog(code, root, version, started)

    def show_crash_dialog(self, code, root, version, started):
        log_text = build_log_text(root, started)
        win = tk.Toplevel(self, bg=BG)
        win.title("Minecraft")
        win.resizable(False, False)
        win.transient(self)
        win.geometry("660x520")
        pn = Panel(win, bg=BG)
        pn.pack(fill="both", expand=True, padx=18, pady=18)

        tk.Label(pn.inner, text="Minecraft завершился с ошибкой", bg=PANEL, fg=RED,
                 font=(FONT, 15, "bold")).pack(anchor="w")
        tk.Label(pn.inner, text=f"Версия {version} · код завершения {code}",
                 bg=PANEL, fg=GREY, font=(FONT, 9)).pack(anchor="w", pady=(2, 10))

        box = tk.Frame(pn.inner, bg=FIELD)
        box.pack(fill="both", expand=True)
        sb = tk.Scrollbar(box, bg=PANEL, troughcolor=FIELD, activebackground=RED, relief="flat", bd=0)
        sb.pack(side="right", fill="y")
        text = tk.Text(box, height=16, bg=FIELD, fg=TEXT, relief="flat", bd=0, highlightthickness=0,
                       font=("Consolas", 9), wrap="none", yscrollcommand=sb.set)
        text.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        sb.config(command=text.yview)
        text.insert("1.0", log_text or "Логи не найдены. Возможно, игра закрылась до запуска.")
        text.config(state="disabled")

        row = tk.Frame(pn.inner, bg=PANEL)
        row.pack(fill="x", pady=(12, 0))

        def copy_logs():
            win.clipboard_clear()
            win.clipboard_append(log_text)

        Btn(row, "Копировать логи", copy_logs, style="ghost", bg=PANEL, h=34).pack(side="left")
        Btn(row, "Папка логов", lambda: open_folder(os.path.join(root, "logs")),
            style="ghost", bg=PANEL, h=34).pack(side="left", padx=8)
        Btn(row, "ОК", win.destroy, style="primary", bg=PANEL, h=34, size=11).pack(side="right")

        win.grab_set()
        win.focus_set()

    # ---------- Java ----------
    def java_section(self, p):
        pn = Panel(p)
        pn.pack(fill="x", pady=4)
        head = tk.Frame(pn.inner, bg=PANEL)
        head.pack(fill="x")
        tk.Label(head, text="Java для игры", bg=PANEL, fg=TEXT, font=(FONT, 11, "bold")).pack(side="left")
        Btn(head, "Указать вручную", self.pick_java, style="ghost", bg=PANEL, h=28, size=9).pack(side="right")
        Btn(head, "Авто для версии", self.auto_java, style="ghost", bg=PANEL, h=28, size=9).pack(side="right", padx=6)
        required, component = java_requirement(self.settings.get("version", DEFAULT_VERSION), self.settings.get("root"))
        tk.Label(pn.inner,
                 text=f"Minecraft {self.settings.get('version')} → подобрана Java {required}",
                 bg=PANEL, fg=RED, font=(FONT, 10, "bold")).pack(anchor="w", pady=(8, 2))
        tk.Label(pn.inner,
                 text="Лаунчер сначала ищет подходящую Java на компьютере, а если её нет — пробует установить официальный runtime Mojang.",
                 bg=PANEL, fg=GREY, font=(FONT, 8), wraplength=680, justify="left").pack(anchor="w")
        self.java_box = tk.Frame(pn.inner, bg=PANEL)
        self.java_box.pack(fill="x", pady=(8, 0))
        if self.java_cache is None:
            tk.Label(self.java_box, text="Поиск установленных Java...", bg=PANEL, fg=GREY,
                     font=(FONT, 9)).pack(anchor="w")
            threading.Thread(target=self._scan_java, daemon=True).start()
        else:
            self.fill_java_list()

    def _scan_java(self):
        found = [(path, java_major(path)) for path in find_javas(self.settings.get("root"))]
        self.java_cache = found
        self.ui(self.fill_java_list)

    def fill_java_list(self):
        for w in self.java_box.winfo_children():
            w.destroy()
        req, _component = java_requirement(self.settings.get("version", DEFAULT_VERSION), self.settings.get("root"))
        cur = self.settings.get("java_by_major", {}).get(str(req), "")
        legacy = self.settings.get("java", "")
        if not cur and legacy and java_major(legacy) == req:
            cur = legacy
        if not self.java_cache:
            tk.Label(self.java_box, text="Java не найдена автоматически. При запуске лаунчер попробует скачать runtime.",
                     bg=PANEL, fg=GREY, font=(FONT, 9)).pack(anchor="w")
        for path, major in self.java_cache:
            exact = major == req
            compatible = major is not None and major >= req
            r = tk.Frame(self.java_box, bg=PANEL)
            r.pack(fill="x", pady=2)
            title = f"Java {major}" if major else "версия неизвестна"
            suffix = " · подходит" if exact else (" · новее" if compatible else " · не подходит")
            tk.Label(r, text=title + suffix, bg=PANEL,
                     fg=("#78d69b" if exact else (TEXT if compatible else "#ff6b74")),
                     font=(FONT, 9, "bold"), width=25, anchor="w").pack(side="left")
            tk.Label(r, text=path, bg=PANEL, fg=GREY, font=(FONT, 8), anchor="w").pack(
                side="left", fill="x", expand=True)
            selected = path == cur
            Btn(r, "Выбрана" if selected else "Выбрать", lambda p=path: self.set_java(p),
                style="soft" if selected else "ghost", bg=PANEL, h=25, size=8).pack(side="right")
        if cur and cur not in [path for path, _ in self.java_cache]:
            tk.Label(self.java_box, text=f"Сохранённый путь: {cur}", bg=PANEL, fg=GREY,
                     font=(FONT, 8)).pack(anchor="w", pady=(4, 0))

    def set_java(self, path):
        major = java_major(path)
        if major is not None:
            mapping = self.settings.setdefault("java_by_major", {})
            mapping[str(major)] = path
            # Retain the legacy field for compatibility with older launcher configs.
            self.settings["java"] = path
        self.save_settings()
        self.show_page("settings", animate=False)

    def auto_java(self):
        self.settings["java"] = ""
        self.settings["java_by_major"] = {}
        self.save_settings()
        self.show_page("settings", animate=False)

    def pick_java(self):
        path = filedialog.askopenfilename(filetypes=[("Java", "javaw.exe;java.exe"), ("Все файлы", "*.*")])
        if not path:
            return
        major = java_major(path)
        if major is None:
            return messagebox.showerror("Ошибка", "Не удалось определить версию Java по этому файлу")
        required, _component = java_requirement(self.settings.get("version", DEFAULT_VERSION), self.settings.get("root"))
        if major < required:
            return messagebox.showerror("Неподходящая Java",
                f"Для Minecraft {self.settings.get('version')} рекомендуется Java {required} или новее. Выбрана Java {major}.")
        self.set_java(path)

    def resolve_java(self, root, mc_version, cb):
        """Select the exact Java runtime for the selected Minecraft version; install Mojang runtime if missing."""
        required, component = java_requirement(mc_version, root)
        by_major = self.settings.get("java_by_major", {}) or {}
        configured = by_major.get(str(required), "")
        legacy_manual = self.settings.get("java") or ""

        # Version-specific configured Java, then exact locally installed Java.
        if configured and os.path.isfile(configured) and java_major(configured) == required:
            return configured, required, component
        for path in find_javas(root):
            if java_major(path) == required:
                return path, required, component
        # A manually selected Java can be used as a fallback only if it is new enough.
        if legacy_manual and os.path.isfile(legacy_manual):
            manual_major = java_major(legacy_manual)
            if manual_major == required:
                return legacy_manual, manual_major, component

        # Try the matching Mojang runtime, stored inside the launcher's game directory.
        if component and mll_runtime is not None:
            try:
                installed = mll_runtime.get_executable_path(component, root)
                if installed and os.path.isfile(installed) and java_major(installed) == required:
                    return installed, required, component
            except Exception:
                pass
            try:
                available = mll_runtime.get_jvm_runtimes()
                if component in available:
                    self.set_status(f"Загрузка Java {required} для Minecraft {mc_version}...")
                    mll_runtime.install_jvm_runtime(component, root, callback=cb)
                    installed = mll_runtime.get_executable_path(component, root)
                    if installed and os.path.isfile(installed):
                        installed_major = java_major(installed)
                        if installed_major == required:
                            return installed, installed_major, component
            except Exception as e:
                runtime_error = str(e)
            else:
                runtime_error = "Подходящий runtime отсутствует в каталоге Mojang."
        else:
            runtime_error = "Модуль установки Java runtime недоступен в minecraft-launcher-lib."

        # Last resort: use a newer installed Java only when it is likely to be compatible.
        newer = [(java_major(path), path) for path in find_javas(root)]
        newer = [(major, path) for major, path in newer if major is not None and major > required]
        newer.sort(key=lambda item: item[0])
        if newer:
            return newer[0][1], newer[0][0], component
        if legacy_manual and os.path.isfile(legacy_manual):
            manual_major = java_major(legacy_manual)
            if manual_major is not None and manual_major > required:
                return legacy_manual, manual_major, component
        raise RuntimeError(
            f"Для Minecraft {mc_version} подходит Java {required}. Подходящая Java не найдена, "
            f"а автоматическая установка не удалась. {runtime_error} "
            f"Открой Настройки → Java или установи Java {required}."
        )

    # ---------- Запуск ----------
    def start_game(self, server=None):
        if self.launching or self.game_running:
            messagebox.showinfo("STIVOX", "Minecraft уже запускается или работает.")
            return
        acc = self.current_account()
        if not acc:
            messagebox.showwarning("Нет аккаунта", "Сначала выбери аккаунт")
            return self.show_page("accounts")
        self.save_settings()
        self.launching = True
        threading.Thread(target=self._launch,
                         args=(acc, self.settings["root"], self.settings["version"], self.ram_var.get(),
                               self.settings.get("loader", "vanilla")),
                         daemon=True).start()

    def find_installed(self, root, pred):
        ids = [v["id"] for v in mll.utils.get_installed_versions(root)]
        matches = [i for i in ids if pred(i)]
        return matches[-1] if matches else None

    def ensure_fabric(self, root, mc, cb, java):
        def is_fabric(i):
            return i.startswith("fabric-loader") and i.endswith("-" + mc)
        found = self.find_installed(root, is_fabric)
        if not found:
            self.set_status("Установка Fabric...")
            mll.fabric.install_fabric(mc, root, callback=cb, java=java)
            found = self.find_installed(root, is_fabric)
        if not found:
            raise RuntimeError("Fabric не установился. Попробуй ещё раз или выбери другую версию.")
        dedupe_version_libraries(root, found)
        return found

    def ensure_forge(self, root, mc, cb, java):
        forge_ver = mll.forge.find_forge_version(mc)
        if not forge_ver:
            raise RuntimeError(f"Для Minecraft {mc} не найдено Forge.")
        installed_id = mll.forge.forge_to_installed_version(forge_ver)
        if self.find_installed(root, lambda i: i == installed_id):
            return installed_id
        self.set_status("Установка Forge...")
        mll.forge.install_forge_version(forge_ver, root, callback=cb, java=java)
        return installed_id

    def _launch(self, acc, root, version, ram, loader, server=None):
        try:
            os.makedirs(root, exist_ok=True)
            state = {"max": 1}

            def set_max(v):
                state["max"] = max(1, v)

            def set_prog(v):
                self.ui(lambda: self.progress.set(v / state["max"]))

            cb = {"setStatus": self.set_status, "setProgress": set_prog, "setMax": set_max}

            # Install/read the selected base version first: its JSON contains javaVersion.
            if not self.find_installed(root, lambda i: i == version):
                self.set_status(f"Загрузка Minecraft {version}...")
                mll.install.install_minecraft_version(version, root, callback=cb)

            java, major, component = self.resolve_java(root, version, cb)
            self.set_status(f"Используется Java {major} для Minecraft {version}")

            target = version
            if loader == "fabric":
                target = self.ensure_fabric(root, version, cb, java)
            elif loader == "forge":
                target = self.ensure_forge(root, version, cb, java)
            self.ui(lambda: self.progress.set(0))

            options = {
                "username": acc["name"],
                "uuid": acc["uuid"],
                "token": "",
                "jvmArguments": [f"-Xmx{ram}M", f"-Xms{min(ram, 1024)}M"],
                "gameDirectory": root,
                "executablePath": java,
            }
            if server:
                host, port = self.parse_server_address(server)
                options["server"] = host
                options["port"] = port
            self.set_status("Запуск игры" + (" · подключение к серверу" if server else "") + "...")
            command = mll.command.get_minecraft_command(target, root, options)
            command, removed_asm = sanitize_asm_classpath(command)
            started = time.time()
            logs_dir = os.path.join(root, "logs")
            os.makedirs(logs_dir, exist_ok=True)
            out_path = os.path.join(logs_dir, "launcher_output.log")
            with open(out_path, "w", encoding="utf-8", errors="replace") as out:
                out.write(f"Java: {java} (версия {major}; требуется {java_requirement(version, root)[0]})\n")
                out.write(f"Версия: {target}\n")
                if removed_asm:
                    out.write("Исправление classpath: удалены дубли ASM:\n")
                    for jar_path in removed_asm:
                        out.write("  - " + jar_path + "\n")
                out.write("Команда: " + " ".join(str(c) for c in command) + "\n\n")
                out.flush()
                proc = subprocess.Popen(command, cwd=root, stdout=out, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.launching = False
            self.set_status(f"{LOADER_NAMES.get(loader, 'Vanilla')} {version} запущен · Java {major}")
            self.ui(self.withdraw)
            self.game_running = True
            code = self.monitor_game(proc, root)
            self.game_running = False
            self.ui(lambda: self.on_game_exit(code, root, version, started))
        except Exception as e:
            self.launching = False
            self.set_status("Ошибка запуска")
            msg = str(e)
            self.ui(lambda: messagebox.showerror("Ошибка", msg))


if __name__ == "__main__":
    App().mainloop()
