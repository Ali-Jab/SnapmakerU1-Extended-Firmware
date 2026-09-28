#!/usr/bin/env python3
"""Inspect a separately unpacked candidate; never contacts a printer."""
import argparse
import ast
import hashlib
import json
import stat
from pathlib import Path
import subprocess
from types import SimpleNamespace


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def verify(root, source, sha):
    elf_count = 0
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            header = stream.read(20)
        if header[:4] == b"\x7fELF":
            require(len(header) == 20 and header[5] in (1, 2), "Invalid ELF header: " + str(path))
            machine = int.from_bytes(header[18:20], "little" if header[5] == 1 else "big")
            require(machine in (40, 183), "Non-ARM packaged ELF: " + str(path))
            elf_count += 1
    require(elf_count > 0, "No packaged ELF binaries found")
    for name in ("etc/init.d/rcS", "etc/init.d/S49extended-config"):
        require((root / name).stat().st_mode & stat.S_IXUSR, "Packaged startup script not executable: " + name)
    mappings = {
        "home/lava/moonraker/moonraker/components/spoollink.py": "38-feature-spoollink/root/home/lava/moonraker/moonraker/components/spoollink.py",
        "home/lava/klipper/klippy/extras/spoollink.py": "38-feature-spoollink/root/home/lava/klipper/klippy/extras/spoollink.py",
        "usr/local/share/firmware-config/extended/klipper/tpu_conditional_auto_feed.cfg": "39-feature-tpu-print-guard/root/usr/local/share/firmware-config/extended/klipper/tpu_conditional_auto_feed.cfg",
        "etc/nginx/fluidd.d/filament.conf": "68-app-filament-ui/root/etc/nginx/fluidd.d/filament.conf",
    }
    for name in ("index.html", "script.js", "style.css", "spoolman-utils.js"):
        target = "usr/local/filament-ui/html/" + name
        mappings[target] = "68-app-filament-ui/root/" + target
    matched = {}
    for target, origin in mappings.items():
        expected = source / "overlays/firmware-extended" / origin
        actual = root / target
        require(actual.is_file(), "Missing packaged file: " + target)
        require(digest(actual) == digest(expected), "Packaged/source mismatch: " + target)
        matched[target] = digest(actual)
        if actual.suffix == ".py":
            compile(actual.read_bytes(), str(actual), "exec")

    versions = {name: (root / "etc" / name).read_text().strip()
                for name in ("BUILD_VERSION", "BASE_VERSION", "BUILD_PROFILE", "FULLVERSION")}
    require(versions["BUILD_PROFILE"] == "extended", "Unexpected profile")
    require(versions["BASE_VERSION"] == "2.0.0.205_20260914173503", "Unexpected stock base")
    require(sha[:12] in versions["BUILD_VERSION"], "Source identity missing from build label")
    require("ali-candidate" in versions["FULLVERSION"], "Candidate identity missing")

    extras = root / "home/lava/klipper/klippy/extras"
    detect = (extras / "filament_detect.py").read_text()
    tree = ast.parse(detect)
    methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
               and node.name == "_filament_info_update"]
    require(len(methods) == 1, "RFID event producer missing or ambiguous")
    module = ast.Module(body=[methods[0]], type_ignores=[])
    namespace = {}
    exec(compile(ast.fix_missing_locations(module), "packaged-filament-detect", "exec"), namespace)
    timestamps = iter((100.01, 100.02, 100.03))
    obj = SimpleNamespace(reactor=SimpleNamespace(monotonic=lambda: next(timestamps)),
                          _filament_info=[None] * 4, _notify_data_update_cb=[])
    update = namespace["_filament_info_update"]
    first = {"CARD_UID": [1, 2, 3, 4]}
    second = dict(first)
    update(obj, 2, first)
    update(obj, 2, second)
    require(second["CARD_EVENT_TIME"] > first["CARD_EVENT_TIME"], "Same-tag event did not advance")
    update(obj, 2, {}, True)
    require(obj._filament_info[2]["CARD_EVENT_TIME"] == 100.03, "Clear event not stamped")
    require(obj._filament_info[0] is None, "Event changed another channel")
    require("'CARD_EVENT_TIME': 0" in (extras / "filament_protocol.py").read_text(),
            "Protocol event field missing")

    ui = (root / "usr/local/filament-ui/html/script.js").read_text()
    require("+ Create Spool" in ui and "+ Add RFID" in ui, "Local UI actions missing")
    require("access_token" in ui or "token" in ui, "Upstream authentication handling missing")
    config = (root / "home/lava/origin_printer_data/config/fluidd.cfg").read_text()
    require("[gcode_macro SM_PRINT_AUTO_FEED]" in config, "TPU guard target missing")
    require("[gcode_macro AUTO_FEEDING_BATCH]" in config, "Manual batch interface missing")
    return {"versions": versions, "packaged_files": matched, "arm_elf_files": elf_count,
            "rfid_producer_cases": ["same_uid", "clear", "channel_isolation"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--sha", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.rootfs, args.source, args.sha)
    fs = args.rootfs.parent / "rk-unpacked/rootfs.img"
    superblock = subprocess.check_output(["unsquashfs", "-s", str(fs)], text=True)
    require("Compression zstd" in superblock, "Root filesystem is not zstd")
    require(fs.stat().st_size <= 300 * 1024 * 1024, "Root filesystem exceeds 300 MiB slot")
    result.update({"source_sha": args.sha, "image": args.image.name,
        "image_bytes": args.image.stat().st_size, "image_sha256": digest(args.image),
        "rootfs_bytes": fs.stat().st_size, "squashfs": superblock,
        "submodules": subprocess.check_output(["git", "-C", str(args.source),
                            "submodule", "status", "--recursive"], text=True).strip(),
        "hardware_validated": False})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print("Candidate package verification passed")


if __name__ == "__main__":
    main()
