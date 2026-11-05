import os, re, json, hashlib, shutil, threading, subprocess, ctypes, uuid, math, time, gzip, struct, zipfile
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, filedialog
import minecraft_launcher_lib as mll

APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "RedLauncher")
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
ACCOUNTS_FILE = os.path.join(APP_DIR, "profiles.json")
STATS_FILE = os.path.join(APP_DIR, "stats.json")
DEFAULT_ROOT = os.path.join(APP_DIR, "game")
DEFAULT_VERSION = "1.21.4"
NAV = [("play", "Главная"), ("stats", "Статистика"), ("accounts", "Аккаунты"), ("versions", "Версии"),
       ("mods", "Моды"), ("doctor", "Диагностика"), ("settings", "Настройки")]

LOADER_NAMES = {"vanilla": "Vanilla", "fabric": "Fabric", "forge": "Forge"}

BG = "#0d0d0d"
SIDE = "#121212"
PANEL = "#171717"
FIELD = "#0c0c0c"
LINE = "#262626"
SHADOW = "#000000"
RED = "#e02330"
RED_HI = "#ff4a55"
RED_DARK = "#5e0d13"
TEXT = "#f4f4f4"
GREY = "#8c8c8c"
MUTED = "#555555"
FONT = "Segoe UI"


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
    r"C:\Program Files\Microsoft\jdk-*\bin\javaw.exe",
    r"C:\Program Files\Zulu\*\bin\javaw.exe",
    r"C:\Program Files\BellSoft\*\bin\javaw.exe",
]


def find_javas():
    import glob
    cands = []
    jh = os.environ.get("JAVA_HOME")
    if jh:
        cands.append(os.path.join(jh, "bin", "javaw.exe"))
    for pat in JAVA_PATTERNS:
        cands += glob.glob(pat)
    seen, result = set(), []
    for c in cands:
        if os.path.isfile(c):
            key = os.path.normcase(os.path.normpath(c))
            if key not in seen:
                seen.add(key)
                result.append(c)
    return result


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
    SH = 4

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
        rrect(self, 0, 0, w - 1, h - self.SH - 1, r, fill=self.fill, outline=LINE, tags="bg")
        self.tag_lower("bg")


class Btn(tk.Canvas):
    """Скруглённая кнопка с плавной сменой цвета при наведении."""
    STYLES = {
        "primary": (RED, RED_HI, TEXT),
        "soft": (RED_DARK, "#7f1820", TEXT),
        "ghost": ("#222222", "#2e2e2e", TEXT),
        "danger": ("#241012", "#3a1419", "#ff6b74"),
        "nav": (SIDE, "#1d1d1d", GREY),
        "nav_on": (RED_DARK, "#7f1820", TEXT),
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
            rrect(self, 0, 0, w - 1, h - 1, h / 2, fill=self.glow, outline="")
            rrect(self, 2, 2, w - 3, h - 3, (h - 4) / 2, fill=self.cur, outline="")
        else:
            rrect(self, 0, 0, w - 1, h - 1, h / 2, fill=self.cur, outline="")
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
    def __init__(self, parent, letter, bg=PANEL, size=44):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, bd=0)
        self.create_oval(1, 1, size - 1, size - 1, fill=RED_DARK, outline=RED, width=2)
        self.create_text(size / 2, size / 2, text=(letter[:1] or "?").upper(),
                         fill=TEXT, font=(FONT, int(size * 0.38), "bold"))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RED LAUNCHER")
        self.geometry("900x640")
        self.minsize(850, 590)
        self.configure(bg=BG)

        self.settings = load_json(CONFIG_FILE, {})
        self.settings.setdefault("root", DEFAULT_ROOT)
        self.settings.setdefault("version", DEFAULT_VERSION)
        self.settings.setdefault("ram", min(2048, max(1024, total_ram_mb() - 1536)))
        self.settings.setdefault("snapshots", False)
        self.settings.setdefault("account", None)
        self.settings.setdefault("java", "")
        self.settings.setdefault("loader", "vanilla")
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
                         "settings": self.page_settings, "doctor": self.page_doctor}
        self.build_shell()
        self.show_page("play", animate=False)

    # ---------- оболочка ----------
    def build_shell(self):
        # Компактная боковая навигация и отдельная рабочая область.
        side = tk.Frame(self, bg=SIDE, width=188)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        logo = tk.Canvas(side, width=188, height=96, bg=SIDE, highlightthickness=0, bd=0)
        logo.pack(fill="x")
        logo.create_text(20, 35, text="RED", anchor="w", fill=RED,
                         font=(FONT, 25, "bold"))
        logo.create_text(22, 62, text="LAUNCHER  /  2.1", anchor="w", fill=GREY,
                         font=(FONT, 8, "bold"))
        tk.Frame(side, bg=LINE, height=1).pack(fill="x", padx=14, pady=(0, 12))
        tk.Label(side, text="РАЗДЕЛЫ", bg=SIDE, fg=MUTED,
                 font=(FONT, 8, "bold")).pack(anchor="w", padx=18, pady=(0, 6))

        nav_box = tk.Frame(side, bg=SIDE)
        nav_box.pack(fill="x", padx=10, pady=(0, 8))
        self.nav = {}
        nav_labels = {
            "play": "◈  Главная",
            "stats": "◷  Статистика",
            "accounts": "◎  Аккаунты",
            "versions": "▤  Версии",
            "mods": "▦  Моды",
            "doctor": "⌕  Диагностика",
            "settings": "⚙  Настройки",
        }
        for key, title in NAV:
            label = nav_labels.get(key, title)
            b = Btn(nav_box, label, lambda k=key: self.show_page(k), style="nav", bg=SIDE,
                    size=10, h=36, width=164, stretch=True, align="w")
            b.pack(fill="x", pady=2)
            self.nav[key] = b

        # Нижний блок даёт быстрый контекст: выбранный профиль и версия.
        bottom = tk.Frame(side, bg="#151515", highlightthickness=1,
                          highlightbackground=LINE)
        bottom.pack(side="bottom", fill="x", padx=10, pady=(8, 10))
        tk.Label(bottom, text="ТЕКУЩИЙ ПРОФИЛЬ", bg="#151515", fg=MUTED,
                 font=(FONT, 7, "bold")).pack(anchor="w", padx=10, pady=(8, 2))
        self.side_account = tk.Label(bottom, text="Без аккаунта", bg="#151515", fg=TEXT,
                                     font=(FONT, 9, "bold"), anchor="w")
        self.side_account.pack(fill="x", padx=10)
        self.side_version = tk.Label(bottom, text=self.version_label(), bg="#151515", fg=GREY,
                                     font=(FONT, 8), anchor="w")
        self.side_version.pack(fill="x", padx=10, pady=(1, 8))
        tk.Label(side, text="WINDOWS  ·  BUILD 2.1", bg=SIDE, fg=MUTED,
                 font=(FONT, 7, "bold")).pack(side="bottom", pady=(0, 2))

        main = tk.Frame(self, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        topbar = tk.Frame(main, bg=BG, height=46)
        topbar.pack(fill="x", padx=24, pady=(10, 0))
        topbar.pack_propagate(False)
        self.header_title = tk.Label(topbar, text="RED  /  CONTROL CENTER", bg=BG,
                                     fg=TEXT, font=(FONT, 10, "bold"))
        self.header_title.pack(side="left", anchor="center")
        Btn(topbar, "Папка игры", lambda: open_folder(self.settings["root"]),
            style="ghost", bg=BG, h=28, size=8).pack(side="right", padx=(8, 0), anchor="center")
        tk.Label(topbar, text="BUILD 2.1", bg=RED_DARK, fg=TEXT,
                 font=(FONT, 7, "bold"), padx=9, pady=4).pack(side="right", anchor="center")
        tk.Frame(main, bg=RED_DARK, height=1).pack(fill="x", padx=24, pady=(0, 5))
        self.stage = tk.Frame(main, bg=BG)
        self.stage.pack(fill="both", expand=True, padx=24, pady=(8, 16))

    def show_page(self, key, animate=True):
        for k, b in self.nav.items():
            b.set_style("nav_on" if k == key else "nav")
        order = [k for k, _ in NAV]
        direction = 1
        if self.current in order:
            direction = 1 if order.index(key) > order.index(self.current) else -1
        self.current = key
        titles = {"play": "Главная", "stats": "Статистика", "accounts": "Аккаунты",
                  "versions": "Версии игры", "mods": "Моды", "doctor": "Диагностика",
                  "settings": "Настройки"}
        if hasattr(self, "header_title"):
            self.header_title.config(text="RED  /  " + titles.get(key, "CONTROL CENTER").upper())
        if hasattr(self, "side_account"):
            account = self.current_account()
            self.side_account.config(text=account["name"] if account else "Без аккаунта")
            self.side_version.config(text=self.version_label())

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
            new.place(x=60 * direction, y=0, relwidth=1, relheight=1)
            new.lift()
            self._slide(new, old, 60 * direction, 0)
        else:
            if old is not None and alive(old):
                old.destroy()
            new.place(x=0, y=0, relwidth=1, relheight=1)

    def _slide(self, new, old, start, step, steps=9):
        if not (alive(new) and alive(old)):
            self.slide_job = None
            return
        t = (step + 1) / steps
        x = int(start * (1 - (1 - (1 - t) ** 3)))
        new.place_configure(x=x)
        old.place_configure(x=x - start)
        if step + 1 < steps:
            self.slide_job = self.after(16, self._slide, new, old, start, step + 1, steps)
        else:
            self.slide_job = None
            old.destroy()
            self.outgoing = None
            new.place_configure(x=0)

    def heading(self, p, title, sub):
        tk.Label(p, text=title, bg=BG, fg=TEXT, font=(FONT, 18, "bold")).pack(anchor="w")
        tk.Label(p, text=sub, bg=BG, fg=GREY, font=(FONT, 8)).pack(anchor="w", pady=(0, 8))

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
        self.ui(lambda: self.status.config(text=text))

    def current_account(self):
        return next((a for a in self.accounts if a["name"] == self.settings.get("account")), None)

    def save_settings(self):
        self.settings["ram"] = self.ram_var.get()
        save_json(CONFIG_FILE, self.settings)

    # ---------- Главная ----------
    def page_play(self, p):
        self.heading(p, "Главная", "Аккаунт, сборка и память — всё для запуска в одном месте")
        acc = self.current_account()

        hero = Panel(p, radius=14)
        hero.pack(fill="x", pady=3)
        row = hero.inner
        Avatar(row, acc["name"] if acc else "?", size=40).pack(side="left", padx=(0, 11))
        info = tk.Frame(row, bg=PANEL)
        info.pack(side="left", fill="x", expand=True)
        tk.Label(info, text="АККАУНТ", bg=PANEL, fg=GREY,
                 font=(FONT, 7, "bold")).pack(anchor="w")
        tk.Label(info, text=acc["name"] if acc else "Не выбран", bg=PANEL, fg=TEXT,
                 font=(FONT, 13, "bold")).pack(anchor="w")
        Btn(row, "Аккаунты", lambda: self.show_page("accounts"), style="ghost", bg=PANEL,
            h=29, size=8).pack(side="right", padx=(8, 0))
        Btn(row, self.version_label(), lambda: self.show_page("versions"), style="soft",
            bg=PANEL, h=29, size=8).pack(side="right")

        quick = tk.Frame(p, bg=BG)
        quick.pack(fill="x", pady=3)
        ram = Panel(quick, radius=14)
        ram.pack(side="left", fill="both", expand=True, padx=(0, 4))
        top = tk.Frame(ram.inner, bg=PANEL)
        top.pack(fill="x")
        tk.Label(top, text="ОПЕРАТИВНАЯ ПАМЯТЬ", bg=PANEL, fg=GREY,
                 font=(FONT, 7, "bold")).pack(side="left")
        self.ram_label = tk.Label(top, text="", bg=PANEL, fg=RED,
                                  font=(FONT, 10, "bold"))
        self.ram_label.pack(side="right")
        max_ram = max(1024, min(4096, total_ram_mb() - 1024))
        Slider(ram.inner, self.ram_var, 1024, max_ram, 512,
               cmd=self.update_ram_label, bg=PANEL).pack(fill="x", pady=(7, 0))
        tk.Label(ram.inner, text="Для системы оставляется запас памяти",
                 bg=PANEL, fg=MUTED, font=(FONT, 7)).pack(anchor="w", pady=(3, 0))
        self.update_ram_label()

        path = Panel(quick, radius=14)
        path.pack(side="left", fill="both", expand=True, padx=(4, 0))
        pr = tk.Frame(path.inner, bg=PANEL)
        pr.pack(fill="x")
        left = tk.Frame(pr, bg=PANEL)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="ПАПКА ИГРЫ", bg=PANEL, fg=GREY,
                 font=(FONT, 7, "bold")).pack(anchor="w")
        tk.Label(left, text=self.settings["root"], bg=PANEL, fg=TEXT, font=(FONT, 8),
                 anchor="w", justify="left", wraplength=225).pack(anchor="w", pady=(4, 0))
        Btn(pr, "Открыть", lambda: open_folder(self.settings["root"]), style="ghost",
            bg=PANEL, h=28, size=8).pack(side="right", padx=(6, 0))

        self.progress = Progress(p)
        self.progress.pack(fill="x", pady=(11, 5))
        self.status = tk.Label(p, text="Готов к запуску", bg=BG, fg=GREY,
                               font=(FONT, 8))
        self.status.pack(anchor="w")
        Btn(p, "ЗАПУСТИТЬ MINECRAFT", self.start_game, style="primary", big=True,
            pulse=True, stretch=True).pack(fill="x", pady=(8, 0))

    def update_ram_label(self):
        try:
            self.ram_label.config(text=f"{self.ram_var.get() / 1024:g} ГБ")
        except (tk.TclError, AttributeError):
            pass

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
        self.version_list = tk.Listbox(lp.inner, bg=FIELD, fg=TEXT, selectbackground=RED,
                                       selectforeground=TEXT, relief="flat", font=(FONT, 11),
                                       highlightthickness=0, bd=0, activestyle="none", height=9)
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
        self.doctor_output = tk.Text(p, height=12, bg=FIELD, fg=TEXT, insertbackground=RED,
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
        report = ["RED LAUNCHER · MOD DOCTOR", "Папка: " + mods_dir,
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
        self.java_section(p)

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
            self.set_status("Minecraft закрыт без ошибок")
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
        Btn(head, "Авто", self.auto_java, style="ghost", bg=PANEL, h=28, size=9).pack(side="right", padx=6)
        self.java_box = tk.Frame(pn.inner, bg=PANEL)
        self.java_box.pack(fill="x", pady=(8, 0))
        if self.java_cache is None:
            tk.Label(self.java_box, text="Поиск установленных Java...", bg=PANEL, fg=GREY,
                     font=(FONT, 9)).pack(anchor="w")
            threading.Thread(target=self._scan_java, daemon=True).start()
        else:
            self.fill_java_list()

    def _scan_java(self):
        found = [(path, java_major(path)) for path in find_javas()]
        self.java_cache = found
        self.ui(self.fill_java_list)

    def fill_java_list(self):
        for w in self.java_box.winfo_children():
            w.destroy()
        cur = self.settings.get("java") or ""
        if not self.java_cache:
            tk.Label(self.java_box, text="Java не найдена автоматически. Укажи javaw.exe вручную.",
                     bg=PANEL, fg=GREY, font=(FONT, 9)).pack(anchor="w")
        for path, major in self.java_cache:
            r = tk.Frame(self.java_box, bg=PANEL)
            r.pack(fill="x", pady=2)
            ok = major is not None and major >= 21
            tk.Label(r, text=f"Java {major}" if major else "версия неизвестна", bg=PANEL,
                     fg=TEXT if ok else "#ff6b74", font=(FONT, 10, "bold"), width=14,
                     anchor="w").pack(side="left")
            tk.Label(r, text=path, bg=PANEL, fg=GREY, font=(FONT, 8), anchor="w").pack(
                side="left", fill="x", expand=True)
            selected = path == cur
            Btn(r, "Выбрана" if selected else "Выбрать", lambda p=path: self.set_java(p),
                style="soft" if selected else "ghost", bg=PANEL, h=26, size=9).pack(side="right")
        if cur and cur not in [p for p, _ in self.java_cache]:
            tk.Label(self.java_box, text=f"Вручную выбрано: {cur}", bg=PANEL, fg=GREY,
                     font=(FONT, 8)).pack(anchor="w", pady=(4, 0))

    def set_java(self, path):
        self.settings["java"] = path
        self.save_settings()
        self.show_page("settings", animate=False)

    def auto_java(self):
        self.set_java("")

    def pick_java(self):
        path = filedialog.askopenfilename(filetypes=[("Java", "*.exe"), ("Все файлы", "*.*")])
        if not path:
            return
        major = java_major(path)
        if major is None:
            return messagebox.showerror("Ошибка", "Не удалось определить версию Java по этому файлу")
        if major < 21:
            return messagebox.showerror("Ошибка", f"Для Minecraft 1.21.4 нужна Java 21 или новее. Выбрана Java {major}.")
        self.set_java(path)

    def resolve_java(self):
        """Путь к Java для запуска: выбранная вручную, либо автоматически найденная 21+, либо java из PATH."""
        manual = self.settings.get("java") or ""
        if manual:
            return manual
        for path in find_javas():
            major = java_major(path)
            if major is not None and major >= 21:
                return path
        return "java"

    # ---------- Запуск ----------
    def start_game(self):
        if self.launching or self.game_running:
            messagebox.showinfo("RED LAUNCHER", "Minecraft уже запускается или работает.")
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

    def _launch(self, acc, root, version, ram, loader):
        try:
            os.makedirs(root, exist_ok=True)
            java = self.resolve_java()
            major = java_major(java)
            if major is None or major < 21:
                raise RuntimeError(f"Для Minecraft {version} нужна Java 21 или новее. "
                                   f"Сейчас используется: {java} (версия {major}). "
                                   f"Укажи подходящую Java в Настройки → Java.")
            state = {"max": 1}

            def set_max(v):
                state["max"] = max(1, v)

            def set_prog(v):
                self.ui(lambda: self.progress.set(v / state["max"]))

            cb = {"setStatus": self.set_status, "setProgress": set_prog, "setMax": set_max}

            if not self.find_installed(root, lambda i: i == version):
                self.set_status(f"Загрузка Minecraft {version}...")
                mll.install.install_minecraft_version(version, root, callback=cb)

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
            self.set_status("Запуск игры...")
            command = mll.command.get_minecraft_command(target, root, options)
            command, removed_asm = sanitize_asm_classpath(command)
            started = time.time()
            logs_dir = os.path.join(root, "logs")
            os.makedirs(logs_dir, exist_ok=True)
            out_path = os.path.join(logs_dir, "launcher_output.log")
            with open(out_path, "w", encoding="utf-8", errors="replace") as out:
                out.write(f"Java: {java} (версия {major})\n")
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
            self.set_status(f"{LOADER_NAMES.get(loader, 'Vanilla')} {version} запущен")
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
