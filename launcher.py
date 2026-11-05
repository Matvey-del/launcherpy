import os, re, json, hashlib, shutil, threading, subprocess, ctypes, uuid, math, time, gzip, struct, zipfile
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, filedialog
import minecraft_launcher_lib as mll
try:
    import minecraft_launcher_lib.runtime as mll_runtime
except Exception:
    mll_runtime = None

# Legacy storage path retained so existing profiles, settings and installed game files remain available.
APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "RedLauncher")
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
ACCOUNTS_FILE = os.path.join(APP_DIR, "profiles.json")
STATS_FILE = os.path.join(APP_DIR, "stats.json")
DEFAULT_ROOT = os.path.join(APP_DIR, "game")
DEFAULT_VERSION = "1.21.4"
NAV = [("play", "Играть"), ("versions", "Версии"), ("servers", "Серверы"),
       ("mods", "Моды"), ("worlds", "Миры"), ("more", "Ещё")]

LOADER_NAMES = {"vanilla": "Vanilla", "fabric": "Fabric", "forge": "Forge"}

BG = "#14252b"
SIDE = "#172c32"
PANEL = "#1d353b"
FIELD = "#12252b"
LINE = "#42616a"
SHADOW = "#0a171c"
RED = "#53c9bd"
RED_HI = "#82e6d8"
RED_DARK = "#174b4a"
TEXT = "#f2fbfa"
GREY = "#b1c8c8"
MUTED = "#789596"
FONT = "Segoe UI"

# Profile artwork bundled with the launcher. GIF is supported by Tkinter on Windows 7.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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
        "primary": (RED, RED_HI, TEXT),
        "soft": ("#174b4a", "#226a65", TEXT),
        "ghost": ("#203940", "#2b4b52", TEXT),
        "danger": ("#3a2022", "#512a2d", "#ff9b9f"),
        "nav": ("#172c32", "#23434a", "#b1c8c8"),
        "nav_on": ("#185653", "#24766e", "#ffffff"),
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
        self.geometry("1040x700")
        self.minsize(900, 620)
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
            image = image.resize((int(image.width * ratio), int(image.height * ratio)), Image.Resampling.LANCZOS)
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
        """Compact glass-style shell: narrow left navigation and a clean content stage."""
        self._resize_wallpaper()
        main = tk.Frame(self, bg=BG, highlightthickness=1, highlightbackground=LINE)
        main.place(x=16, y=16, relwidth=1, relheight=1, width=-32, height=-32)

        topbar = tk.Frame(main, bg=SIDE, height=54)
        topbar.pack(side="top", fill="x")
        topbar.pack_propagate(False)

        brand = tk.Frame(topbar, bg=SIDE)
        brand.pack(side="left", fill="y", padx=(18, 0))
        tk.Label(brand, text="STIVOX", bg=SIDE, fg=RED,
                 font=(FONT, 19, "bold")).pack(side="left", pady=(7, 0))
        tk.Label(brand, text="  MINECRAFT", bg=SIDE, fg=GREY,
                 font=(FONT, 8, "bold")).pack(side="left", pady=(14, 0))
        tk.Frame(topbar, bg=LINE, width=1, height=26).pack(side="left", padx=18, pady=14)

        self.header_title = tk.Label(topbar, text="ИГРАТЬ", bg=SIDE, fg=TEXT,
                                     font=(FONT, 10, "bold"))
        self.header_title.pack(side="left", anchor="center")

        right = tk.Frame(topbar, bg=SIDE)
        right.pack(side="right", fill="y", padx=14)
        self.top_status = tk.Label(right, text="● ГОТОВ", bg=SIDE, fg="#8fe0b1",
                                   font=(FONT, 8, "bold"))
        self.top_status.pack(side="left", padx=(0, 12), pady=17)
        self.header_meta = tk.Label(right, text="Без аккаунта · Vanilla 1.21.4",
                                    bg=SIDE, fg=GREY, font=(FONT, 8))
        self.header_meta.pack(side="left", padx=(0, 12), pady=17)
        Btn(right, "ПАПКА", lambda: open_folder(self.settings["root"]),
            style="ghost", bg=SIDE, h=29, size=8).pack(side="left", pady=12)

        body = tk.Frame(main, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=12)

        nav_shell = tk.Frame(body, bg=SIDE, width=142,
                             highlightthickness=1, highlightbackground=LINE)
        nav_shell.pack(side="left", fill="y", padx=(0, 12))
        nav_shell.pack_propagate(False)
        tk.Label(nav_shell, text="МЕНЮ", bg=SIDE, fg=MUTED,
                 font=(FONT, 7, "bold")).pack(anchor="w", padx=13, pady=(13, 8))
        self.nav = {}
        nav_labels = {
            "play": "⌂   Играть", "versions": "▤   Версии", "servers": "◎   Серверы",
            "mods": "▦   Моды", "worlds": "▣   Миры", "more": "···   Ещё"
        }
        for key, _title in NAV:
            b = Btn(nav_shell, nav_labels[key], lambda k=key: self.show_page(k),
                    style="nav", bg=SIDE, size=8, h=39, width=122,
                    stretch=True, align="left")
            b.pack(side="top", fill="x", padx=8, pady=3)
            self.nav[key] = b
        tk.Frame(nav_shell, bg=LINE, height=1).pack(fill="x", padx=12, pady=10)
        tk.Label(nav_shell, text="STIVOX 3.1", bg=SIDE, fg=MUTED,
                 font=(FONT, 7, "bold")).pack(side="bottom", anchor="w", padx=13, pady=12)

        self.stage = tk.Frame(body, bg=BG)
        self.stage.pack(side="left", fill="both", expand=True)

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
        acc = self.current_account()
        self.heading(p, "Добро пожаловать в STIVOX", "Быстрый запуск Minecraft и управление сборкой")

        # Main launch area: two clearly separated columns.
        columns = tk.Frame(p, bg=BG)
        columns.pack(fill="x", pady=(4, 9))

        hero = Panel(columns, fill="#203d42", radius=15)
        hero.pack(side="left", fill="both", expand=True, padx=(0, 7))
        row = tk.Frame(hero.inner, bg="#203d42")
        row.pack(fill="both", expand=True)
        tk.Label(row, text="ТЕКУЩАЯ СБОРКА", bg="#203d42", fg=GREY,
                 font=(FONT, 7, "bold")).pack(anchor="w")
        tk.Label(row, text="Minecraft", bg="#203d42", fg=TEXT,
                 font=(FONT, 21, "bold")).pack(anchor="w", pady=(5, 0))
        tk.Label(row, text=self.settings["version"], bg="#203d42", fg=RED,
                 font=(FONT, 12, "bold")).pack(anchor="w")
        req, _component = java_requirement(self.settings.get("version"), self.settings.get("root"))
        tk.Label(row, text=f"{LOADER_NAMES.get(self.settings.get('loader', 'vanilla'), 'Vanilla')}  ·  Java {req}",
                 bg="#203d42", fg=GREY, font=(FONT, 8)).pack(anchor="w", pady=(4, 10))
        Btn(row, "ЗАПУСТИТЬ  ▶", self.start_game, style="primary",
            bg="#203d42", h=43, size=10, width=190).pack(anchor="w")

        config = Panel(columns, fill="#1b3239", radius=15)
        config.pack(side="left", fill="both", expand=True, padx=(7, 0))
        tk.Label(config.inner, text="ПРОФИЛЬ", bg="#1b3239", fg=GREY,
                 font=(FONT, 7, "bold")).pack(anchor="w")
        ar = tk.Frame(config.inner, bg="#1b3239")
        ar.pack(fill="x", pady=(7, 10))
        Avatar(ar, acc["name"] if acc else "?", bg="#1b3239", size=34).pack(side="left", padx=(0, 9))
        namebox = tk.Frame(ar, bg="#1b3239")
        namebox.pack(side="left", fill="x", expand=True)
        tk.Label(namebox, text=acc["name"] if acc else "Аккаунт не выбран",
                 bg="#1b3239", fg=TEXT, font=(FONT, 9, "bold")).pack(anchor="w")
        tk.Label(namebox, text="Локальный профиль", bg="#1b3239", fg=GREY,
                 font=(FONT, 7)).pack(anchor="w")
        Btn(config.inner, "СМЕНИТЬ АККАУНТ", lambda: self.show_page("accounts"),
            style="ghost", bg="#1b3239", h=29, size=7, stretch=True).pack(fill="x")

        # RAM and quick controls stay in their own compact card.
        ram_panel = Panel(p, fill="#1b3239", radius=13)
        ram_panel.pack(fill="x", pady=(0, 9))
        rt = tk.Frame(ram_panel.inner, bg="#1b3239")
        rt.pack(fill="x")
        tk.Label(rt, text="ВЫДЕЛЕННАЯ ПАМЯТЬ", bg="#1b3239", fg=GREY,
                 font=(FONT, 7, "bold")).pack(side="left")
        self.ram_label = tk.Label(rt, text="", bg="#1b3239", fg=RED, font=(FONT, 9, "bold"))
        self.ram_label.pack(side="right")
        max_ram = max(1024, min(4096, total_ram_mb() - 1024))
        Slider(ram_panel.inner, self.ram_var, 1024, max_ram, 256,
               cmd=self.update_ram_label, bg="#1b3239").pack(fill="x", pady=(5, 0))
        self.update_ram_label()

        lower = tk.Frame(p, bg=BG)
        lower.pack(fill="x", pady=(0, 8))
        tk.Label(lower, text="БЫСТРЫЙ ДОСТУП", bg=BG, fg=GREY,
                 font=(FONT, 7, "bold")).pack(anchor="w", pady=(0, 5))
        shortcuts = tk.Frame(lower, bg=BG)
        shortcuts.pack(fill="x")
        shortcuts_list = [
            ("Серверы", lambda: self.show_page("servers")),
            ("Миры", lambda: self.show_page("worlds")),
            ("Скриншоты", lambda: self.open_game_folder("screenshots")),
            ("Ресурспаки", lambda: self.open_game_folder("resourcepacks")),
            ("Логи", lambda: open_folder(os.path.join(self.settings["root"], "logs"))),
            ("Папка игры", lambda: open_folder(self.settings["root"])),
        ]
        for label, cmd in shortcuts_list:
            Btn(shortcuts, label, cmd, style="ghost", bg=BG, h=29, size=7,
                stretch=True, width=95).pack(side="left", fill="x", expand=True, padx=2)

        dashboard = tk.Frame(p, bg=BG)
        dashboard.pack(fill="x", pady=(0, 5))
        servers_card = Panel(dashboard, fill="#1b3239", radius=13)
        servers_card.pack(side="left", fill="both", expand=True, padx=(0, 6))
        sr_head = tk.Frame(servers_card.inner, bg="#1b3239")
        sr_head.pack(fill="x")
        tk.Label(sr_head, text="ИЗБРАННЫЕ СЕРВЕРЫ", bg="#1b3239", fg=GREY,
                 font=(FONT, 7, "bold")).pack(side="left")
        Btn(sr_head, "Все", lambda: self.show_page("servers"), style="ghost",
            bg="#1b3239", h=23, size=7).pack(side="right")
        favorites = self.server_entries()[:2]
        if not favorites:
            tk.Label(servers_card.inner, text="Добавь сервер, чтобы подключаться в один клик.",
                     bg="#1b3239", fg=GREY, font=(FONT, 8), wraplength=320).pack(anchor="w", pady=(8, 2))
        for item in favorites:
            rr = tk.Frame(servers_card.inner, bg="#1b3239")
            rr.pack(fill="x", pady=(5, 0))
            tk.Label(rr, text=item["name"], bg="#1b3239", fg=TEXT,
                     font=(FONT, 8, "bold")).pack(side="left", anchor="w")
            Btn(rr, "Играть", lambda a=item["address"]: self.start_game(a), style="soft",
                bg="#1b3239", h=23, size=7).pack(side="right")

        activity = Panel(dashboard, fill="#1b3239", radius=13)
        activity.pack(side="left", fill="both", expand=True, padx=(6, 0))
        total_time = sum(load_json(STATS_FILE, {}).values())
        tk.Label(activity.inner, text="ИГРОВАЯ АКТИВНОСТЬ", bg="#1b3239", fg=GREY,
                 font=(FONT, 7, "bold")).pack(anchor="w")
        tk.Label(activity.inner, text=fmt_hours(total_time), bg="#1b3239", fg=TEXT,
                 font=(FONT, 16, "bold")).pack(anchor="w", pady=(4, 0))
        tk.Label(activity.inner, text="общее время в игре", bg="#1b3239", fg=GREY,
                 font=(FONT, 7)).pack(anchor="w")
        Btn(activity.inner, "Статистика", lambda: self.show_page("stats"),
            style="ghost", bg="#1b3239", h=23, size=7).pack(anchor="w", pady=(5, 0))

        self.progress = Progress(p)
        self.progress.pack(fill="x", pady=(5, 3))
        self.status = tk.Label(p, text="Готов к запуску", bg=BG, fg=GREY, font=(FONT, 8))
        self.status.pack(anchor="w")

    def open_game_folder(self, name):
        open_folder(os.path.join(self.settings["root"], name))

    def set_placeholder(self, field, value):
        field.entry.insert(0, value)
        field.entry.config(fg=MUTED)
        def focus_in(_event=None):
            if field.entry.get() == value:
                field.entry.delete(0, "end")
                field.entry.config(fg=TEXT)
        def focus_out(_event=None):
            if not field.entry.get().strip():
                field.entry.insert(0, value)
                field.entry.config(fg=MUTED)
        field.entry.bind("<FocusIn>", focus_in)
        field.entry.bind("<FocusOut>", focus_out)

    def update_ram_label(self):
        try:
            self.ram_label.config(text=f"{self.ram_var.get() / 1024:g} ГБ")
        except (tk.TclError, AttributeError):
            pass

    # ---------- Серверы ----------
    def server_entries(self):
        items, seen = [], set()
        # First include servers already saved by Minecraft itself.
        for item in read_servers(self.settings["root"]):
            addr = (item.get("ip") or "").strip()
            if not addr:
                continue
            key = addr.lower()
            if key not in seen:
                seen.add(key)
                items.append({"name": item.get("name") or addr, "address": addr, "source": "Minecraft"})
        for item in self.settings.get("saved_servers", []) or []:
            addr = (item.get("address") or "").strip()
            key = addr.lower()
            if addr and key not in seen:
                seen.add(key)
                items.append({"name": item.get("name") or addr, "address": addr, "source": "Избранное"})
        return items

    def parse_server_address(self, address):
        value = (address or "").strip()
        if value.startswith("[") and "]" in value:
            host, tail = value[1:].split("]", 1)
            port = tail[1:] if tail.startswith(":") else "25565"
        elif value.count(":") == 1:
            host, port = value.rsplit(":", 1)
        else:
            host, port = value, "25565"
        if not host or not re.fullmatch(r"[A-Za-z0-9._:-]+", host):
            raise ValueError("Проверь адрес сервера")
        if not str(port).isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError("Порт должен быть числом от 1 до 65535")
        return host, str(int(port))

    def page_servers(self, p):
        self.heading(p, "Серверы", "Подключайся в один клик к серверам из Minecraft или добавляй свои")
        add = Panel(p, radius=12)
        add.pack(fill="x", pady=(0, 8))
        tk.Label(add.inner, text="ДОБАВИТЬ СЕРВЕР", bg=PANEL, fg=GREY,
                 font=(FONT, 7, "bold")).pack(anchor="w")
        fields = tk.Frame(add.inner, bg=PANEL)
        fields.pack(fill="x", pady=(6, 0))
        self.server_name_field = Field(fields, bg=PANEL, h=34)
        self.server_name_field.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.set_placeholder(self.server_name_field, "Название сервера")
        self.server_addr_field = Field(fields, bg=PANEL, h=34)
        self.server_addr_field.pack(side="left", fill="x", expand=True, padx=6)
        self.set_placeholder(self.server_addr_field, "play.example.com:25565")
        Btn(fields, "Добавить", self.add_server, style="primary", bg=PANEL,
            h=34, size=8).pack(side="right", padx=(6, 0))

        list_panel = Panel(p, radius=12)
        list_panel.pack(fill="both", expand=True)
        header = tk.Frame(list_panel.inner, bg=PANEL)
        header.pack(fill="x", pady=(0, 5))
        tk.Label(header, text="ТВОИ СЕРВЕРЫ", bg=PANEL, fg=TEXT,
                 font=(FONT, 9, "bold")).pack(side="left")
        items = self.server_entries()
        tk.Label(header, text=f"{len(items)}", bg=PANEL, fg=RED,
                 font=(FONT, 9, "bold")).pack(side="right")
        if not items:
            tk.Label(list_panel.inner, text="Список пока пуст. Добавь IP сервера выше или сохрани сервер в меню Minecraft.",
                     bg=PANEL, fg=GREY, font=(FONT, 9), wraplength=780,
                     justify="left").pack(anchor="w", pady=12)
        for item in items:
            row = tk.Frame(list_panel.inner, bg=PANEL)
            row.pack(fill="x", pady=3)
            Avatar(row, item["name"], size=34).pack(side="left", padx=(0, 9))
            info = tk.Frame(row, bg=PANEL)
            info.pack(side="left", fill="x", expand=True)
            tk.Label(info, text=item["name"], bg=PANEL, fg=TEXT,
                     font=(FONT, 10, "bold")).pack(anchor="w")
            tk.Label(info, text=item["address"] + "  ·  " + item["source"], bg=PANEL,
                     fg=GREY, font=(FONT, 8)).pack(anchor="w")
            Btn(row, "ПОДКЛЮЧИТЬ", lambda a=item["address"]: self.start_game(a),
                style="primary", bg=PANEL, h=30, size=8).pack(side="right")
            if item["source"] == "Избранное":
                Btn(row, "Убрать", lambda a=item["address"]: self.remove_server(a),
                    style="ghost", bg=PANEL, h=30, size=8).pack(side="right", padx=(0, 6))

    def add_server(self):
        name = self.server_name_field.get()
        address = self.server_addr_field.get()
        if address == "play.example.com:25565":
            address = ""
        if name == "Название сервера":
            name = ""
        try:
            self.parse_server_address(address)
        except ValueError as exc:
            return messagebox.showwarning("Адрес сервера", str(exc))
        if not name or name == "Название сервера":
            name = address
        saved = self.settings.setdefault("saved_servers", [])
        if any((x.get("address", "").lower() == address.lower()) for x in saved):
            return messagebox.showinfo("Сервер", "Этот адрес уже есть в избранном")
        saved.append({"name": name[:48], "address": address})
        self.save_settings()
        self.show_page("servers", animate=False)

    def remove_server(self, address):
        self.settings["saved_servers"] = [x for x in self.settings.get("saved_servers", [])
                                           if x.get("address", "").lower() != address.lower()]
        self.save_settings()
        self.show_page("servers", animate=False)

    # ---------- Миры и резервные копии ----------
    def world_dir(self):
        return os.path.join(self.settings["root"], "saves")

    def page_worlds(self, p):
        self.heading(p, "Миры", "Резервные копии миров — защити свои постройки перед обновлением модов")
        bar = tk.Frame(p, bg=BG)
        bar.pack(fill="x", pady=(0, 8))
        Btn(bar, "СОЗДАТЬ БЭКАП МИРА", self.choose_world_backup, style="primary",
            bg=BG, h=34, size=8).pack(side="left")
        Btn(bar, "ВОССТАНОВИТЬ ИЗ ZIP", self.restore_world_backup, style="ghost",
            bg=BG, h=34, size=8).pack(side="left", padx=7)
        Btn(bar, "ОТКРЫТЬ ПАПКУ", lambda: open_folder(self.world_dir()), style="ghost",
            bg=BG, h=34, size=8).pack(side="right")

        panel = Panel(p, radius=12)
        panel.pack(fill="both", expand=True)
        saves = self.world_dir()
        os.makedirs(saves, exist_ok=True)
        worlds = []
        for name in sorted(os.listdir(saves)):
            path = os.path.join(saves, name)
            if os.path.isdir(path) and os.path.isfile(os.path.join(path, "level.dat")):
                try:
                    modified = time.strftime("%d.%m.%Y %H:%M", time.localtime(os.path.getmtime(os.path.join(path, "level.dat"))))
                except OSError:
                    modified = "—"
                worlds.append((name, modified))
        top = tk.Frame(panel.inner, bg=PANEL)
        top.pack(fill="x", pady=(0, 6))
        tk.Label(top, text="ЛОКАЛЬНЫЕ МИРЫ", bg=PANEL, fg=TEXT,
                 font=(FONT, 9, "bold")).pack(side="left")
        tk.Label(top, text=str(len(worlds)), bg=PANEL, fg=RED,
                 font=(FONT, 9, "bold")).pack(side="right")
        if not worlds:
            tk.Label(panel.inner, text="Миров пока нет. Создай мир в Minecraft — он появится здесь.",
                     bg=PANEL, fg=GREY, font=(FONT, 9)).pack(anchor="w", pady=15)
        for name, modified in worlds:
            row = tk.Frame(panel.inner, bg=PANEL)
            row.pack(fill="x", pady=3)
            Avatar(row, name, size=34).pack(side="left", padx=(0, 9))
            info = tk.Frame(row, bg=PANEL)
            info.pack(side="left", fill="x", expand=True)
            tk.Label(info, text=name, bg=PANEL, fg=TEXT,
                     font=(FONT, 10, "bold")).pack(anchor="w")
            tk.Label(info, text="Изменён: " + modified, bg=PANEL, fg=GREY,
                     font=(FONT, 8)).pack(anchor="w")
            Btn(row, "БЭКАП", lambda n=name: self.backup_world(n), style="soft",
                bg=PANEL, h=29, size=8).pack(side="right")
            Btn(row, "ПАПКА", lambda n=name: open_folder(os.path.join(saves, n)),
                style="ghost", bg=PANEL, h=29, size=8).pack(side="right", padx=(0, 5))

    def choose_world_backup(self):
        saves = self.world_dir()
        worlds = [n for n in os.listdir(saves) if os.path.isfile(os.path.join(saves, n, "level.dat"))]
        if not worlds:
            return messagebox.showinfo("Резервная копия", "Сохранённых миров пока нет.")
        if len(worlds) == 1:
            return self.backup_world(worlds[0])
        win = tk.Toplevel(self, bg=BG)
        win.title("Выбрать мир")
        win.geometry("380x300")
        win.transient(self)
        pn = Panel(win, bg=BG)
        pn.pack(fill="both", expand=True, padx=14, pady=14)
        tk.Label(pn.inner, text="Какой мир сохранить?", bg=PANEL, fg=TEXT,
                 font=(FONT, 11, "bold")).pack(anchor="w")
        for name in worlds:
            Btn(pn.inner, name, lambda n=name: (win.destroy(), self.backup_world(n)),
                style="ghost", bg=PANEL, h=32, size=9, stretch=True).pack(fill="x", pady=3)
        win.grab_set()

    def backup_world(self, name):
        source = os.path.join(self.world_dir(), name)
        if not os.path.isfile(os.path.join(source, "level.dat")):
            return messagebox.showerror("Бэкап", "Не найден level.dat. Папка не похожа на мир Minecraft.")
        default = re.sub(r"[^A-Za-z0-9._-]+", "_", name) + "_" + time.strftime("%Y%m%d_%H%M") + ".zip"
        dest = filedialog.asksaveasfilename(title="Сохранить резервную копию", defaultextension=".zip",
                                             initialfile=default, filetypes=[("ZIP archive", "*.zip")])
        if not dest:
            return
        try:
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
                for base, dirs, files in os.walk(source):
                    dirs[:] = [d for d in dirs if d not in ("session.lock",)]
                    for filename in files:
                        if filename.lower() == "session.lock":
                            continue
                        full = os.path.join(base, filename)
                        rel = os.path.relpath(full, source)
                        zf.write(full, os.path.join(name, rel))
            messagebox.showinfo("Бэкап готов", "Резервная копия сохранена:\n" + dest)
        except Exception as exc:
            messagebox.showerror("Ошибка бэкапа", str(exc))

    def restore_world_backup(self):
        archive = filedialog.askopenfilename(title="Выбрать резервную копию",
                                             filetypes=[("ZIP archive", "*.zip")])
        if not archive:
            return
        try:
            with zipfile.ZipFile(archive, "r") as zf:
                infos = zf.infolist()
                files = [i for i in infos if not i.is_dir()]
                roots = set()
                for item in infos:
                    normalized = item.filename.replace("\\", "/")
                    parts = normalized.split("/")
                    if not normalized or normalized.startswith("/") or ".." in parts:
                        raise ValueError("В архиве обнаружен небезопасный путь")
                    if parts[0]:
                        roots.add(parts[0])
                    mode = (item.external_attr >> 16) & 0o170000
                    if mode == 0o120000:
                        raise ValueError("Архив содержит символическую ссылку")
                level_files = [i for i in files if i.filename.replace("\\", "/").endswith("/level.dat")]
                if not level_files or len(roots) != 1:
                    raise ValueError("Не удалось распознать резервную копию мира STIVOX")
                if zf.testzip() is not None:
                    raise ValueError("ZIP-архив повреждён")
                source_root = next(iter(roots))
                dest_name = source_root
                saves = self.world_dir()
                target = os.path.join(saves, dest_name)
                if os.path.exists(target):
                    dest_name = source_root + "_restored_" + time.strftime("%Y%m%d_%H%M%S")
                    target = os.path.join(saves, dest_name)
                os.makedirs(target, exist_ok=True)
                root_prefix = source_root + "/"
                for item in infos:
                    normalized = item.filename.replace("\\", "/")
                    if not normalized.startswith(root_prefix):
                        continue
                    rel = normalized[len(root_prefix):]
                    if not rel:
                        continue
                    output = os.path.abspath(os.path.join(target, *rel.split("/")))
                    if os.path.commonpath([os.path.abspath(target), output]) != os.path.abspath(target):
                        raise ValueError("Небезопасный путь в архиве")
                    if item.is_dir():
                        os.makedirs(output, exist_ok=True)
                    else:
                        os.makedirs(os.path.dirname(output), exist_ok=True)
                        with zf.open(item, "r") as src_file, open(output, "wb") as dst_file:
                            shutil.copyfileobj(src_file, dst_file)
                if not os.path.isfile(os.path.join(target, "level.dat")):
                    shutil.rmtree(target, ignore_errors=True)
                    raise ValueError("В архиве не найден level.dat")
            messagebox.showinfo("Восстановление", "Мир восстановлен как: " + dest_name)
            self.show_page("worlds", animate=False)
        except Exception as exc:
            messagebox.showerror("Не удалось восстановить", str(exc))

    # ---------- Раздел Ещё ----------
    def page_more(self, p):
        self.heading(p, "Ещё", "Управление профилем, статистикой и инструментами лаунчера")
        grid = tk.Frame(p, bg=BG)
        grid.pack(fill="x")
        items = [
            ("АККАУНТЫ", "Профили и переключение игрока", "Открыть", lambda: self.show_page("accounts")),
            ("СТАТИСТИКА", "Время игры и любимые серверы", "Посмотреть", lambda: self.show_page("stats")),
            ("ДИАГНОСТИКА", "Проверка модов и исправление ASM", "Проверить", lambda: self.show_page("doctor")),
            ("НАСТРОЙКИ", "Java, папка игры и обслуживание", "Настроить", lambda: self.show_page("settings")),
        ]
        for idx, (title, desc, action, command) in enumerate(items):
            card = Panel(grid, radius=12)
            card.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=4, pady=4)
            tk.Label(card.inner, text=title, bg=PANEL, fg=TEXT,
                     font=(FONT, 10, "bold")).pack(anchor="w")
            tk.Label(card.inner, text=desc, bg=PANEL, fg=GREY,
                     font=(FONT, 8), wraplength=330).pack(anchor="w", pady=(4, 8))
            Btn(card.inner, action, command, style="ghost", bg=PANEL,
                h=29, size=8).pack(anchor="w")
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        folders = Panel(p, radius=12)
        folders.pack(fill="x", pady=(9, 0))
        tk.Label(folders.inner, text="ПАПКИ ИГРЫ", bg=PANEL, fg=GREY,
                 font=(FONT, 7, "bold")).pack(anchor="w", pady=(0, 6))
        row = tk.Frame(folders.inner, bg=PANEL)
        row.pack(fill="x")
        for label, folder in (("Скриншоты", "screenshots"), ("Ресурспаки", "resourcepacks"),
                              ("Шейдеры", "shaderpacks"), ("Логи", "logs"), ("Папка игры", "")):
            path = self.settings["root"] if not folder else os.path.join(self.settings["root"], folder)
            Btn(row, label, lambda x=path: open_folder(x), style="ghost", bg=PANEL,
                h=29, size=8, stretch=True, width=100).pack(side="left", fill="x", expand=True, padx=3)

    # ---------- Аккаунты ----------
    def page_accounts(self, p):
        self.heading(p, "Аккаунты", "Профили для запуска игры")
        if not self.accounts:
            tk.Label(p, text="Аккаунтов пока нет. Создай первый ниже.",
                     bg=BG, fg=GREY, font=(FONT, 10)).pack(anchor="w", pady=(0, 6))
        for acc in self.accounts:
            is_cur = acc["name"] == self.settings.get("account")
            pn = Panel(p)
            pn.pack(fill="x", pady=3)
            Avatar(pn.inner, acc["name"]).pack(side="left", padx=(0, 12))
            info = tk.Frame(pn.inner, bg=PANEL)
            info.pack(side="left", fill="x", expand=True)
            tk.Label(info, text=acc["name"], bg=PANEL, fg=RED if is_cur else TEXT,
                     font=(FONT, 13, "bold")).pack(anchor="w")
            caption = ("выбран" if is_cur else "офлайн-аккаунт") + (" · с паролем" if acc.get("password_hash") else "")
            tk.Label(info, text=caption, bg=PANEL, fg=GREY, font=(FONT, 9)).pack(anchor="w")
            Btn(pn.inner, "Удалить", lambda n=acc["name"]: self.delete_account(n), style="danger",
                bg=PANEL, h=30, size=9).pack(side="right", padx=(6, 0))
            if not is_cur:
                Btn(pn.inner, "Выбрать", lambda n=acc["name"]: self.select_account(n), style="soft",
                    bg=PANEL, h=30, size=9).pack(side="right")

        form = Panel(p)
        form.pack(fill="x", pady=(12, 0))
        tk.Label(form.inner, text="Новый аккаунт", bg=PANEL, fg=TEXT,
                 font=(FONT, 12, "bold")).pack(anchor="w")
        tk.Label(form.inner, text="Имя: 1–16 символов, латиница, цифры и _", bg=PANEL,
                 fg=GREY, font=(FONT, 9)).pack(anchor="w", pady=(8, 3))
        self.name_field = Field(form.inner, bg=PANEL)
        self.name_field.pack(fill="x")
        tk.Label(form.inner, text="Пароль для входа в лаунчер (необязательно)", bg=PANEL,
                 fg=GREY, font=(FONT, 9)).pack(anchor="w", pady=(8, 3))
        self.pass_field = Field(form.inner, show="*", bg=PANEL)
        self.pass_field.pack(fill="x")
        Btn(form.inner, "Добавить аккаунт", self.add_account, style="primary", size=10,
            h=34).pack(anchor="e", pady=(12, 0))

    def add_account(self):
        name = self.name_field.get()
        if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", name):
            return messagebox.showwarning("Ошибка", "Имя: 1–16 символов, только латиница, цифры и _")
        if any(a["name"].lower() == name.lower() for a in self.accounts):
            return messagebox.showwarning("Ошибка", "Аккаунт с таким именем уже есть")
        acc = {"name": name, "uuid": offline_uuid(name)}
        pwd = self.pass_field.raw()
        if pwd:
            acc["salt"], acc["password_hash"] = hash_password(pwd)
        self.accounts.append(acc)
        save_json(ACCOUNTS_FILE, self.accounts)
        if not self.current_account():
            self.settings["account"] = name
            self.save_settings()
        self.show_page("accounts", animate=False)

    def ask_password(self, name):
        win = tk.Toplevel(self, bg=BG)
        win.title("Вход")
        win.resizable(False, False)
        win.transient(self)
        win.geometry("360x240")
        res = {"v": None}
        pn = Panel(win, bg=BG)
        pn.pack(fill="both", expand=True, padx=18, pady=18)
        tk.Label(pn.inner, text=f"Пароль для {name}", bg=PANEL, fg=TEXT,
                 font=(FONT, 12, "bold")).pack(anchor="w")
        field = Field(pn.inner, show="*", bg=PANEL)
        field.pack(fill="x", pady=12)

        def ok(_=None):
            res["v"] = field.raw()
            win.destroy()
        field.entry.bind("<Return>", ok)
        Btn(pn.inner, "Войти", ok, style="primary", h=34).pack(anchor="e")
        win.grab_set()
        field.entry.focus_set()
        self.wait_window(win)
        return res["v"]

    def select_account(self, name):
        acc = next(a for a in self.accounts if a["name"] == name)
        if acc.get("password_hash"):
            pwd = self.ask_password(name)
            if pwd is None:
                return
            _, digest = hash_password(pwd, acc["salt"])
            if digest != acc["password_hash"]:
                return messagebox.showerror("Ошибка", "Неверный пароль")
        self.settings["account"] = name
        self.save_settings()
        self.show_page("accounts", animate=False)

    def delete_account(self, name):
        if not messagebox.askyesno("Удаление", f"Удалить аккаунт {name}?"):
            return
        self.accounts = [a for a in self.accounts if a["name"] != name]
        save_json(ACCOUNTS_FILE, self.accounts)
        if self.settings.get("account") == name:
            self.settings["account"] = None
            self.save_settings()
        self.show_page("accounts", animate=False)

    # ---------- Версии ----------
    def version_label(self):
        return f"{LOADER_NAMES.get(self.settings.get('loader', 'vanilla'), 'Vanilla')} {self.settings['version']}"

    def page_versions(self, p):
        self.heading(p, "Версии", "Vanilla, Fabric и Forge для Minecraft")
        tabs = Panel(p)
        tabs.pack(fill="x")
        row = tk.Frame(tabs.inner, bg=PANEL)
        row.pack(fill="x")
        for key, name in LOADER_NAMES.items():
            Btn(row, name, lambda k=key: self.set_loader_tab(k),
                style="soft" if key == self.loader_tab else "ghost",
                bg=PANEL, h=30, size=9).pack(side="left", padx=(0, 6))
        if self.loader_tab == "vanilla":
            self.snap_var = tk.BooleanVar(value=self.settings["snapshots"])
            tk.Label(row, text="Снапшоты", bg=PANEL, fg=GREY, font=(FONT, 9)).pack(side="right", padx=6)
            Toggle(row, self.snap_var, cmd=self.on_snapshots_toggle, bg=PANEL).pack(side="right")

        lp = Panel(p)
        lp.pack(fill="x", pady=(10, 0))
        self.version_status = tk.Label(lp.inner, text="", bg=PANEL, fg=GREY, font=(FONT, 9))
        self.version_status.pack(anchor="w")
        self.version_filter = Field(lp.inner, bg=PANEL, h=32)
        self.version_filter.pack(fill="x", pady=(6, 3))
        self.version_filter.entry.insert(0, "Поиск версии, например 1.21.4")
        self.version_filter.entry.bind("<KeyRelease>", lambda e: self.fill_versions())
        self.version_list = tk.Listbox(lp.inner, bg=FIELD, fg=TEXT, selectbackground=RED,
                                       selectforeground=TEXT, relief="flat", font=(FONT, 10),
                                       highlightthickness=0, bd=0, activestyle="none", height=8)
        self.version_list.pack(fill="x", pady=6)
        Btn(lp.inner, "Выбрать версию", self.choose_version, style="primary", h=34).pack(anchor="e")

        if self.loader_tab in self.loader_cache:
            self.fill_versions()
        else:
            self.load_loader_list(self.loader_tab)

    def set_loader_tab(self, loader):
        self.loader_tab = loader
        self.show_page("versions", animate=False)

    def load_loader_list(self, loader):
        self.set_version_status("Загрузка списка...")

        def work():
            try:
                if loader == "vanilla":
                    items = [(v["id"], v["type"]) for v in mll.utils.get_version_list()]
                elif loader == "fabric":
                    items = [(v, "release") for v in mll.fabric.get_stable_minecraft_versions()]
                else:
                    seen = []
                    for v in mll.forge.list_forge_versions():
                        mc = v.split("-")[0]
                        if mc not in seen:
                            seen.append(mc)
                    items = [(v, "release") for v in reversed(seen)]
                self.loader_cache[loader] = items
                self.ui(lambda: self.on_loader_list(loader))
            except Exception as e:
                self.ui(lambda: self.set_version_status(f"Не удалось загрузить список: {e}"))
        threading.Thread(target=work, daemon=True).start()

    def set_version_status(self, text):
        self.ui(lambda: self.version_status.config(text=text))

    def on_loader_list(self, loader):
        if loader == self.loader_tab:
            self.fill_versions()

    def fill_versions(self):
        items = self.loader_cache.get(self.loader_tab, [])
        snap = self.loader_tab == "vanilla" and self.settings["snapshots"]
        self.visible_versions = [i for i, t in items if t == "release" or (snap and t == "snapshot")]
        query = ""
        if hasattr(self, "version_filter") and alive(self.version_filter):
            query = self.version_filter.get().strip().lower()
            if query.startswith("поиск версии"):
                query = ""
        if query:
            self.visible_versions = [v for v in self.visible_versions if query in v.lower()]
        self.version_list.delete(0, "end")
        for vid in self.visible_versions:
            self.version_list.insert("end", vid)
        if self.settings.get("loader") == self.loader_tab and self.settings["version"] in self.visible_versions:
            idx = self.visible_versions.index(self.settings["version"])
            self.version_list.selection_set(idx)
            self.version_list.see(idx)
        self.version_status.config(text=f"Доступно версий: {len(self.visible_versions)}")

    def on_snapshots_toggle(self):
        self.settings["snapshots"] = self.snap_var.get()
        save_json(CONFIG_FILE, self.settings)
        if self.loader_tab in self.loader_cache:
            self.fill_versions()

    def choose_version(self):
        sel = self.version_list.curselection()
        if not sel:
            return messagebox.showwarning("Ошибка", "Выбери версию в списке")
        self.settings["loader"] = self.loader_tab
        self.settings["version"] = self.visible_versions[sel[0]]
        self.save_settings()
        self.show_page("play", animate=False)

    # ---------- Моды ----------
    def mod_dirs(self):
        root = self.settings["root"]
        return os.path.join(root, "mods"), os.path.join(root, "mods_disabled")

    def page_mods(self, p):
        self.heading(p, "Моды", "Включай и выключай моды переключателем")
        tk.Label(p, text="Для модов нужен загрузчик Fabric или Forge под выбранную версию игры.",
                 bg=BG, fg=MUTED, font=(FONT, 9)).pack(anchor="w", pady=(0, 8))
        mods_dir, dis_dir = self.mod_dirs()
        os.makedirs(mods_dir, exist_ok=True)
        os.makedirs(dis_dir, exist_ok=True)

        jars = []
        for folder, enabled in [(mods_dir, True), (dis_dir, False)]:
            for f in sorted(os.listdir(folder)):
                if f.lower().endswith(".jar"):
                    jars.append((f, enabled))

        box = Panel(p)
        box.pack(fill="x")
        if not jars:
            tk.Label(box.inner, text="Модов нет. Добавь .jar файл кнопкой ниже.",
                     bg=PANEL, fg=GREY, font=(FONT, 10)).pack(anchor="w", pady=4)
        for name, enabled in jars:
            var = tk.BooleanVar(value=enabled)
            r = tk.Frame(box.inner, bg=PANEL)
            r.pack(fill="x", pady=3)
            tk.Label(r, text=name, bg=PANEL, fg=TEXT, font=(FONT, 10)).pack(side="left")
            Toggle(r, var, cmd=lambda n=name, v=var: self.toggle_mod(n, v.get()), bg=PANEL).pack(side="right")

        row = tk.Frame(p, bg=BG)
        row.pack(anchor="w", pady=12)
        Btn(row, "Добавить мод (.jar)", self.add_mod, style="primary", h=34).pack(side="left", padx=(0, 8))
        Btn(row, "Открыть папку модов", lambda: open_folder(mods_dir), style="ghost", h=34).pack(side="left")

    def toggle_mod(self, name, enabled):
        mods_dir, dis_dir = self.mod_dirs()
        src, dst = (dis_dir, mods_dir) if enabled else (mods_dir, dis_dir)
        try:
            os.makedirs(dst, exist_ok=True)
            shutil.move(os.path.join(src, name), os.path.join(dst, name))
        except OSError as e:
            messagebox.showerror("Ошибка", str(e))
            self.show_page("mods", animate=False)

    def add_mod(self):
        path = filedialog.askopenfilename(filetypes=[("Mod", "*.jar")])
        if not path:
            return
        mods_dir, _ = self.mod_dirs()
        os.makedirs(mods_dir, exist_ok=True)
        shutil.copy(path, os.path.join(mods_dir, os.path.basename(path)))
        self.show_page("mods", animate=False)

    # ---------- Диагностика модов ----------
    def page_doctor(self, p):
        self.heading(p, "Диагностика", "Проверка сборки Minecraft и автоматический поиск конфликтов")
        root = self.settings["root"]
        mods_dir, _ = self.mod_dirs()
        top = Panel(p)
        top.pack(fill="x", pady=(0, 8))
        tk.Label(top.inner, text="MOD DOCTOR", bg=PANEL, fg=RED,
                 font=(FONT, 12, "bold")).pack(anchor="w")
        tk.Label(top.inner, text="Проверяет JAR-файлы, повторяющиеся mod ID и несовпадение версии Minecraft.",
                 bg=PANEL, fg=GREY, font=(FONT, 9), wraplength=560, justify="left").pack(anchor="w", pady=(4, 10))
        Btn(top.inner, "ПРОВЕРИТЬ МОДЫ", self.run_mod_doctor, style="primary", h=36).pack(anchor="w")
        repair = Panel(p)
        repair.pack(fill="x", pady=4)
        tk.Label(repair.inner, text="Ремонт Fabric / ASM", bg=PANEL, fg=TEXT,
                 font=(FONT, 11, "bold")).pack(anchor="w")
        tk.Label(repair.inner, text="Удаляет дубли одной и той же библиотеки ASM из JSON профиля Fabric. Перед изменением создаётся резервная копия.",
                 bg=PANEL, fg=GREY, font=(FONT, 9), wraplength=560, justify="left").pack(anchor="w", pady=(4, 8))
        Btn(repair.inner, "ИСПРАВИТЬ ASM", self.repair_asm, style="soft", h=34).pack(anchor="w")
        self.doctor_output = tk.Text(p, height=10, bg=FIELD, fg=TEXT, insertbackground=RED,
                                     relief="flat", bd=0, highlightthickness=1,
                                     highlightbackground=LINE, font=("Consolas", 9), wrap="word")
        self.doctor_output.pack(fill="both", expand=True, pady=(8, 0))
        self.doctor_output.insert("1.0", "Готов к диагностике. Нажми «Проверить моды».\n")
        self.doctor_output.config(state="disabled")

    def _doctor_report(self, content):
        if not hasattr(self, "doctor_output") or not alive(self.doctor_output):
            return
        self.doctor_output.config(state="normal")
        self.doctor_output.delete("1.0", "end")
        self.doctor_output.insert("1.0", content)
        self.doctor_output.config(state="disabled")

    def run_mod_doctor(self):
        mods_dir, dis_dir = self.mod_dirs()
        os.makedirs(mods_dir, exist_ok=True)
        os.makedirs(dis_dir, exist_ok=True)
        rows, ids, bad = [], {}, []
        for folder, enabled in ((mods_dir, True), (dis_dir, False)):
            for filename in sorted(os.listdir(folder)):
                if not filename.lower().endswith(".jar"):
                    continue
                path = os.path.join(folder, filename)
                try:
                    with zipfile.ZipFile(path, "r") as jar:
                        names = set(jar.namelist())
                        metadata = None
                        modid = None
                        if "fabric.mod.json" in names:
                            metadata = json.loads(jar.read("fabric.mod.json").decode("utf-8"))
                            modid = metadata.get("id")
                            env = metadata.get("environment", "*")
                            if env == "server":
                                bad.append("Только серверный мод: " + filename)
                        elif "META-INF/mods.toml" in names:
                            raw = jar.read("META-INF/mods.toml").decode("utf-8", "replace")
                            match = re.search(r"(?m)^modId\s*=\s*[\'\"]([^\'\"]+)", raw)
                            modid = match.group(1) if match else None
                        elif "mcmod.info" in names:
                            raw = jar.read("mcmod.info").decode("utf-8", "replace")
                            try:
                                data = json.loads(raw)
                                if isinstance(data, list) and data:
                                    modid = data[0].get("modid")
                            except Exception:
                                pass
                        if modid and enabled:
                            ids.setdefault(modid.lower(), []).append(filename)
                        rows.append(("%s  %s" % ("ON " if enabled else "OFF", filename), modid))
                except Exception as exc:
                    bad.append("Повреждённый JAR: %s (%s)" % (filename, exc))
        report = ["STIVOX 3.1 · MOD DOCTOR", "Папка: " + mods_dir,
                  "Найдено JAR: %d (включено %d, отключено %d)" %
                  (len(rows), sum(1 for x in rows if x[0].startswith("ON ")),
                   sum(1 for x in rows if x[0].startswith("OFF "))), ""]
        report.extend("%s%s" % (name, ("  [id: " + modid + "]") if modid else "") for name, modid in rows)
        duplicates = [(mid, files) for mid, files in ids.items() if len(files) > 1]
        if duplicates:
            report.extend(["", "КОНФЛИКТЫ:"])
            report.extend("Повторный mod ID '%s': %s" % (mid, ", ".join(files)) for mid, files in duplicates)
        if bad:
            report.extend(["", "ПРЕДУПРЕЖДЕНИЯ:"] + bad)
        if not duplicates and not bad:
            report.extend(["", "Критичных проблем по метаданным не найдено."])
        report.extend(["", "Важно: совместимость по версии игры и зависимостям зависит от метаданных мода;",
                       "сканер не гарантирует отсутствие всех конфликтов."])
        self._doctor_report("\n".join(report))

    def repair_asm(self):
        root = self.settings["root"]
        version_id = self.find_installed(root, lambda i: i.startswith("fabric-loader") and i.endswith("-" + self.settings["version"]))
        if not version_id:
            return messagebox.showinfo("Fabric", "Профиль Fabric для выбранной версии ещё не установлен.")
        path = os.path.join(root, "versions", version_id, version_id + ".json")
        data = load_json(path, None)
        if not data or not isinstance(data.get("libraries"), list):
            return messagebox.showerror("Ошибка", "Не удалось прочитать JSON профиля Fabric.")
        before = len(data["libraries"])
        dedupe_version_libraries(root, version_id)
        data = load_json(path, data)
        removed = before - len(data.get("libraries", []))
        if removed:
            messagebox.showinfo("Готово", "Удалено дублирующихся записей библиотек: %d" % removed)
        else:
            messagebox.showinfo("Проверка завершена", "Дубли в JSON профиля не найдены. При запуске также будет очищаться classpath.")
        self._doctor_report("Профиль: %s\nБиблиотек до: %d\nБиблиотек после: %d\nУдалено: %d" %
                            (version_id, before, len(data.get("libraries", [])), removed))

    # ---------- Настройки ----------
    def page_settings(self, p):
        self.heading(p, "Настройки", "Папки и данные лаунчера")
        rows = [
            ("Корневая папка игры", self.settings["root"], "Изменить", self.change_root, "soft"),
            ("Вернуть папку по умолчанию", DEFAULT_ROOT, "Сбросить", self.reset_root, "ghost"),
            ("Папка лаунчера", "аккаунты и конфиг", "Открыть", lambda: open_folder(APP_DIR), "ghost"),
        ]
        for title, value, btn, cmd, style in rows:
            pn = Panel(p)
            pn.pack(fill="x", pady=4)
            r = tk.Frame(pn.inner, bg=PANEL)
            r.pack(fill="x")
            left = tk.Frame(r, bg=PANEL)
            left.pack(side="left", fill="x", expand=True)
            tk.Label(left, text=title, bg=PANEL, fg=GREY, font=(FONT, 8, "bold")).pack(anchor="w")
            tk.Label(left, text=value, bg=PANEL, fg=TEXT, font=(FONT, 10)).pack(anchor="w")
            Btn(r, btn, cmd, style=style, bg=PANEL, h=30, size=9).pack(side="right")
        maintenance = Panel(p, radius=12)
        maintenance.pack(fill="x", pady=(8, 4))
        tk.Label(maintenance.inner, text="ОБСЛУЖИВАНИЕ", bg=PANEL, fg=GREY,
                 font=(FONT, 7, "bold")).pack(anchor="w")
        tk.Label(maintenance.inner, text="Очистка временного кэша лаунчера. Миры, моды, ресурсы, библиотеки и логи не затрагиваются.",
                 bg=PANEL, fg=GREY, font=(FONT, 8), wraplength=700,
                 justify="left").pack(anchor="w", pady=(4, 8))
        Btn(maintenance.inner, "ОЧИСТИТЬ БЕЗОПАСНЫЙ КЭШ", self.clear_safe_cache,
            style="soft", bg=PANEL, h=31, size=8).pack(anchor="w")
        self.java_section(p)

    def clear_safe_cache(self):
        root = self.settings["root"]
        candidates = [os.path.join(APP_DIR, "cache"), os.path.join(APP_DIR, "http_cache"),
                      os.path.join(APP_DIR, "tmp"), os.path.join(root, "webcache2")]
        targets = [x for x in candidates if os.path.isdir(x)]
        if not targets:
            return messagebox.showinfo("Очистка кэша", "Временный кэш не найден — очищать нечего.")
        total = 0
        for folder in targets:
            for base, _dirs, files in os.walk(folder):
                for filename in files:
                    try:
                        total += os.path.getsize(os.path.join(base, filename))
                    except OSError:
                        pass
        mb = total / (1024 * 1024)
        names = "\n".join(os.path.basename(x) for x in targets)
        if not messagebox.askyesno("Очистка кэша", f"Удалить временные данные ({mb:.1f} МБ)?\n\n{names}\n\nМиры, моды, библиотеки и логи не трогаются."):
            return
        removed = 0
        for folder in targets:
            try:
                shutil.rmtree(folder)
                removed += 1
            except OSError as exc:
                messagebox.showwarning("Частичная очистка", str(exc))
        messagebox.showinfo("Очистка", f"Удалено временных папок: {removed}")

    def change_root(self):
        path = filedialog.askdirectory()
        if path:
            self.settings["root"] = os.path.normpath(path)
            self.save_settings()
            self.show_page("settings", animate=False)

    def reset_root(self):
        self.settings["root"] = DEFAULT_ROOT
        self.save_settings()
        self.show_page("settings", animate=False)

    # ---------- Статистика ----------
    def monitor_game(self, proc, root):
        """Следит за логом игры: по строке 'Connecting to ...' считает время на сервере."""
        log = os.path.join(root, "logs", "latest.log")
        connect_re = re.compile(r"Connecting to ([^,\s]+), (\d+)")
        pos = 0
        cur_key, cur_start = None, None
        while proc.poll() is None:
            time.sleep(2)
            chunk, pos = read_new(log, pos)
            for line in chunk.splitlines():
                m = connect_re.search(line)
                if m:
                    now = time.time()
                    if cur_key:
                        add_playtime(cur_key, now - cur_start)
                    cur_key, cur_start = server_key(m.group(1), m.group(2)), now
                elif "Stopping!" in line and cur_key:
                    add_playtime(cur_key, time.time() - cur_start)
                    cur_key = None
        if cur_key:
            add_playtime(cur_key, time.time() - cur_start)
        return proc.wait()

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
