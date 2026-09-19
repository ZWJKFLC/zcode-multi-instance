#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZCode multi-instance patcher — dynamic regex engine (version-resilient).

Locates every patch site via STABLE strings that survive re-minification
(ZCODE_DATA_BASE_DIR / ".zcode" / getDataBaseDir tags / icon_windows.png /
tray_icon.ico), instead of hardcoded minified names. Validates both known
versions (3.10.2, 3.11.2) byte-for-byte against the static patches.

Usage:
  python patch-zcode-dynamic.py            # generate app.asar.patched
  python patch-zcode-dynamic.py --apply    # + close ZCode / backup / replace
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time

RES = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")),
                   "Programs", "ZCode", "resources")
ASAR = os.path.join(RES, "app.asar")
EXE = os.path.join(os.path.dirname(RES), "ZCode.exe")
DST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.asar.patched")
PATCHED_SIG = b"ZCODE_INSTANCE_ICON||("

ID = r"[A-Za-z_$][A-Za-z0-9_$]{0,5}"
MAIN = "/out/main/index.js"
HOST = "/out/host/index.js"
SCHED = "/out/scheduler/index.js"
CHUNKS = (MAIN, HOST, SCHED)


class Abort(Exception):
    pass


# ---------------------------------------------------------------- asar io

def parse_asar(data):
    s1, s2, s3, js = struct.unpack("<4I", data[:16])
    header = json.loads(data[16:16 + js])
    entries = {}

    def walk(node, prefix=""):
        for name, ent in node.get("files", {}).items():
            p = prefix + "/" + name
            if "files" in ent:
                walk(ent, p)
            elif "offset" in ent:
                entries[p] = ent

    walk(header)
    return s1, s2, s3, js, header, entries


def read_chunk(data, data_off, entries, path):
    ent = entries[path]
    off, size = int(ent["offset"]), int(ent["size"])
    return data[data_off + off:data_off + off + size]


def sha_integrity(b):
    bs = 4194304
    return {"algorithm": "SHA256", "hash": hashlib.sha256(b).hexdigest(),
            "blockSize": bs,
            "blocks": [hashlib.sha256(b[i:i + bs]).hexdigest() for i in range(0, len(b), bs)]}


# ---------------------------------------------------------------- rules

def build_chunk_rules(content, label, is_main):
    """content: bytes of one chunk. Returns list of (old, new, count, desc)."""
    rules = []

    # fix 1 — env forward condition -> unconditional.
    # Forms seen: `i!==tj()?{ZCODE_DATA_BASE_DIR:i}:{}` (3.10/3.11, comparison prefix —
    # MUST be consumed or the leftover `i!=={...}` silently disables the spread),
    # `xm()?{ZCODE_DATA_BASE_DIR:s}:{}` (3.12+).
    ms = list(re.finditer((r"(?:(?:" + ID + r")!==)?(?:" + ID + r"\(\))?\?\{ZCODE_DATA_BASE_DIR:(" +
                           ID + r")\}:\{\}").encode(), content))
    if len(ms) > 1 or (len(ms) == 0 and is_main):
        raise Abort("%s: env-forward condition matched %d times (main requires exactly 1)" % (label, len(ms)))
    if ms:
        m = ms[0]
        new = b"{ZCODE_DATA_BASE_DIR:" + m.group(1) + b"}"
        new += b" " * (len(m.group(0)) - len(new))
        rules.append((m.group(0), new, 1, "fix1 env-forward"))

    # fix 2 — re-anchor HOME-based ".zcode" paths to the chunk's env-aware getter.
    # Getter forms seen: `s(xt,"getDataBaseDir")` / `c(on,...)` / `a(Ui,...)` (3.12),
    # and object literal `getDataBaseDir:qr}` (3.12 main).
    gm = (re.search(("(" + ID + r')\(\)\{return ' + ID + r"\|\|" + ID + r"\|\|" + ID +
                    r"\}[a-z]\(\1,\"getDataBaseDir\"\)").encode(), content)
          or re.search((r"getDataBaseDir:(" + ID + r")[,}]").encode(), content))
    if not gm:
        # 3.14+ form: the chunk has NO getDataBaseDir getter at all (the
        # ZCODE_DATA_BASE_DIR support was dropped host-side). Instead of
        # re-pointing sites at a getter, inject the env check into each
        # site: `(X(),".zcode"` -> `((DATA?.trim()||X()),".zcode"`.
        # Only bare resolver calls preceded by `(` are patched; member-call
        # sites like `e.HOME.trim(),".zcode"` (resolveZcodeHome, remote
        # contexts with explicit homes) are deliberately left alone.
        G = None
        inj_counts = {}
        for sm in re.finditer((r'\((' + ID + r')\(\),"\.zcode"').encode(), content):
            inj_counts[sm.group(1)] = inj_counts.get(sm.group(1), 0) + 1
        if not inj_counts:
            raise Abort("%s: getDataBaseDir getter not found and no injectable '.zcode' sites" % label)
        for name, cnt in inj_counts.items():
            old = b'(' + name + b'(),".zcode"'
            new = (b'((process.env.ZCODE_DATA_BASE_DIR?.trim()||' + name + b'()),".zcode"')
            rules.append((old, new, cnt,
                          "fix2 inject DATA_BASE into %s x%d" % (name.decode(), cnt)))
        return rules

    G = gm.group(1)
    site_counts = {}
    skip_env = skip_home = 0
    for sm in re.finditer(("(" + ID + r')\(\),"\.zcode"').encode(), content):
        name = sm.group(1)
        look = content[max(0, sm.start() - 80):sm.start()]
        if name == G or b"ZCODE_HOME" in look:
            skip_home += 1
            continue
        site_counts[name] = site_counts.get(name, 0) + 1

    for name, cnt in site_counts.items():
        defs = re.findall(b"function " + re.escape(name) + rb"\(\)\{.{0,220}",
                          content, re.S)
        ok = False
        for d in defs:
            if b"getDataBaseDir" in d:
                ok = True  # env-aware copy elsewhere; replacing is harmless-safe? no — abort below
                raise Abort("%s: site %r points at a getDataBaseDir copy; manual check needed" % (label, name))
            if b"ZCODE_HOME" in d:
                raise Abort("%s: site %r looks like ZCODE_HOME resolver; manual check needed" % (label, name))
            if b"process.env.HOME" in d and b"ZCODE_DATA_BASE_DIR" not in d:
                ok = True
        if not ok and (b"homedir as " + name) in content:
            ok = True
        if not ok:
            raise Abort("%s: resolver for %r not recognized (not HOME-based/homedir); manual check needed" % (label, name))
        rules.append((name + b'(),".zcode"', G + b'(),".zcode"', cnt,
                      "fix2 %s->%s x%d" % (name.decode(), G.decode(), cnt)))

    # fix 3 — window/taskbar icon + AUMID (main only)
    if is_main:
        ANY = r"[A-Za-z_$][A-Za-z0-9_$]*"  # non-minified names like `process` may be long
        icon_pat = ('(' + ID + r')=process\.platform==="win32"\?(' + ID +
                    r')\.isPackaged\?(' + ID + r')\(' + '(' + ANY + r')' +
                    r'\.resourcesPath,"icon_windows\.png"\)').encode()
        pm = re.search(icon_pat, content)
        if not pm:
            raise Abort("main: icon_windows.png anchor not found")
        v, app, j, res = pm.group(1), pm.group(2), pm.group(3), pm.group(4)
        new = (v + b"=(process.env.ZCODE_INSTANCE_AUMID&&" + app +
               b".setAppUserModelId(process.env.ZCODE_INSTANCE_AUMID),"
               b"process.env.ZCODE_INSTANCE_ICON?" + j + b"(process.env.ZCODE_INSTANCE_ICON):"
               b'process.platform==="win32"?' + app + b".isPackaged?" + j + b"(" + res +
               b'.resourcesPath,"icon_windows.png")')
        rules.append((pm.group(0), new, 1, "fix3 window icon + AUMID"))

        cm = list(re.finditer(("(" + ID + r'\(import\.meta\.dirname,"\.\./\.\./build/icon\.png"\))([,;])').encode(),
                              content))
        if len(cm) != 1:
            raise Abort("main: icon chain tail matched %d times (expected 1)" % len(cm))
        # keep the original separator (`,` var-chain / `;`): swallowing it once
        # produced `...png"))H$=` — SyntaxError: Unexpected identifier
        rules.append((cm[0].group(0), cm[0].group(1) + b")" + cm[0].group(2), 1, "fix3 close icon chain"))

        tm = re.search((r"function (" + ID + r")\(\)\{return (" + ID + r")\.isPackaged\?(" + ID +
                        r")\(([A-Za-z_$][A-Za-z0-9_$]*)\.resourcesPath,\"tray_icon\.ico\"\):(" + ID +
                        r')\(import\.meta\.dirname,"\.\./\.\./build/icon\.ico"\)\}').encode(), content)
        if not tm:
            raise Abort("main: tray_icon.ico anchor not found")
        f, tapp, tj, tres, tj2 = tm.groups()
        tnew = (b"function " + f + b"(){return process.env.ZCODE_INSTANCE_ICON||(" + tapp +
                b".isPackaged?" + tj + b"(" + tres + b'.resourcesPath,"tray_icon.ico"):' + tj2 +
                b'(import.meta.dirname,"../../build/icon.ico"))}')
        rules.append((tm.group(0), tnew, 1, "fix3 tray icon"))

    return rules


def build_patched_from(src_path):
    data = open(src_path, "rb").read()
    s1, s2, s3, js, header, entries = parse_asar(data)
    data_off = 8 + s2

    main_content = read_chunk(data, data_off, entries, MAIN)
    rules_by_path = {}
    report = []
    for path in CHUNKS:
        content = main_content if path == MAIN else read_chunk(data, data_off, entries, path)
        rules = build_chunk_rules(content, path.rsplit("/", 2)[-2], path == MAIN)
        rules_by_path[path] = rules
        for _, _, _, desc in rules:
            report.append("  %-8s %s" % (path.rsplit("/", 2)[-2] + "/", desc))

    payload = data[data_off:]
    new_payload = bytearray()
    cur = 0
    for path in sorted(entries, key=lambda p: int(entries[p]["offset"])):
        ent = entries[path]
        off, size = int(ent["offset"]), int(ent["size"])
        content = payload[off:off + size]
        if path in rules_by_path:
            for old, new, expect, _ in rules_by_path[path]:
                n = content.count(old)
                assert n == expect, "%s: %r found %d, expected %d" % (path, old[:60], n, expect)
                content = content.replace(old, new)
            ent["size"] = len(content)
            ent["integrity"] = sha_integrity(content)
        ent["offset"] = str(cur)
        new_payload += content
        cur += len(content)

    jb = json.dumps(header, separators=(",", ":")).encode("utf-8")
    s3n = (4 + len(jb) + 3) & ~3
    s2n = (8 + len(jb) + 3) & ~3
    out = struct.pack("<4I", 4, s2n, s3n, len(jb)) + jb + b"\x00" * (s2n - 8 - len(jb)) + bytes(new_payload)

    # self verify
    a, b2, c2, j2 = struct.unpack("<4I", out[:16])
    assert (a, b2, c2, j2) == (4, s2n, s3n, len(jb))
    h2 = json.loads(out[16:16 + j2])
    e2 = {}

    def walk2(node, prefix=""):
        for name, ent2 in node.get("files", {}).items():
            p = prefix + "/" + name
            if "files" in ent2:
                walk2(ent2, p)
            elif "offset" in ent2:
                e2[p] = ent2

    walk2(h2)
    nd = 8 + s2n
    for path, rules in rules_by_path.items():
        ent2 = e2[path]
        content = out[nd + int(ent2["offset"]):nd + int(ent2["offset"]) + int(ent2["size"])]
        for old, new, expect, _ in rules:
            assert content.count(old) == 0, "verify: OLD still present"
            assert content.count(new) >= expect, "verify: NEW missing"
        assert hashlib.sha256(content).hexdigest() == ent2["integrity"]["hash"], "verify: hash %s" % path

    # syntax gate: node --check every patched chunk. This is what would have
    # caught the 3.12.1 chain-tail bug (SyntaxError killed the main process).
    node = shutil.which("node")
    if not node:
        report.append("  WARNING: node not found - skipped JS syntax check")
    else:
        import tempfile
        for path, rules in rules_by_path.items():
            ent2 = e2[path]
            content = out[nd + int(ent2["offset"]):nd + int(ent2["offset"]) + int(ent2["size"])]
            fd, tmp = tempfile.mkstemp(suffix=".mjs")
            try:
                os.write(fd, content)
                os.close(fd)
                r = subprocess.run([node, "--check", tmp], capture_output=True, timeout=60)
            finally:
                os.unlink(tmp)
            if r.returncode != 0:
                raise Abort("%s: patched chunk fails node --check:\n%s" %
                            (path, r.stderr.decode("utf-8", "replace")[:500]))
        report.append("  verify/  node --check OK on %d patched chunks" % len(rules_by_path))
    return out, report


# ---------------------------------------------------------------- helpers

def exe_version():
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-Item '%s').VersionInfo.ProductVersion" % EXE],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def pick_source():
    """Prefer a versioned backup; live asar must be unpatched to be usable directly."""
    baks = sorted(glob.glob(os.path.join(RES, "app.asar.bak-*")), reverse=True)
    live = open(ASAR, "rb").read()
    _, _, _, _, _, entries = parse_asar(live)
    live_main = read_chunk(live, 8 + struct.unpack("<4I", live[:16])[1], entries, MAIN)
    if PATCHED_SIG not in live_main:
        ver = exe_version()
        bak = os.path.join(RES, "app.asar.bak-%s" % ver)
        if not os.path.exists(bak):
            shutil.copy2(ASAR, bak)
            print("backed up pristine app.asar -> %s" % os.path.basename(bak))
        return bak
    ver = exe_version()
    for b in baks:
        # only a backup matching the INSTALLED version is a valid source;
        # picking the newest backup regardless once cross-installed a 3.12.1
        # asar into a 3.11.2 install
        if os.path.basename(b) != "app.asar.bak-%s" % ver:
            continue
        d = open(b, "rb").read()
        try:
            _, _, _, _, _, ent = parse_asar(d)
            if PATCHED_SIG not in read_chunk(d, 8 + struct.unpack("<4I", d[:16])[1], ent, MAIN):
                print("live asar is patched; using backup %s as source" % os.path.basename(b))
                return b
        except Exception:
            continue
    raise Abort("live app.asar is patched and no pristine backup for installed version %s; "
                "run rollback first or reinstall ZCode" % ver)


def zcode_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ZCode.exe"],
                         capture_output=True, text=True).stdout
    return "ZCode.exe" in out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    try:
        src = pick_source()
        print("source:", src)
        out, report = build_patched_from(src)
    except Abort as e:
        print("PATCH ABORTED:", e)
        print("This ZCode version changed beyond the engine's anchors.")
        print("=> Ask your AI assistant to re-locate patterns (see guide, section 'upgrade').")
        return 2
    open(DST, "wb").write(out)
    print("PATCH OK ->", DST)
    for line in report:
        print(line)

    if args.apply:
        if zcode_running():
            print("closing ZCode...")
            subprocess.run(["taskkill", "/IM", "ZCode.exe", "/F"], capture_output=True)
            for _ in range(20):
                time.sleep(1)
                if not zcode_running():
                    break
            else:
                print("ZCode did not exit; aborting.")
                return 3
        for _ in range(10):
            try:
                shutil.copy2(DST, ASAR)
                print("app.asar replaced")
                break
            except PermissionError:
                print("app.asar busy, retry in 3s...")
                time.sleep(3)
        else:
            print("replace failed: app.asar still busy")
            return 4
        print("done. relaunch ZCode via your launchers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
