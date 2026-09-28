#!/usr/bin/env bash
set -euo pipefail
image=$(realpath "$1")
sha=$2
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
# These are fresh, task-owned inspection outputs. Existing outputs fail safely.
scripts/helpers/unpack_firmware.sh "$image" tmp/candidate-inspection
unsquashfs -d tmp/candidate-inspection/rootfs tmp/candidate-inspection/rk-unpacked/rootfs.img
python3 scripts/check_line_endings.py --rootfs tmp/candidate-inspection/rootfs
python3 scripts/verify_candidate.py --rootfs tmp/candidate-inspection/rootfs --image "$image" --sha "$sha" --report candidate-evidence/package-report.json

scripts/helpers/unpack_firmware.sh firmware/U1_2.0.0.205_20260914173503_upgrade.bin tmp/candidate-stock
unsquashfs -d tmp/candidate-stock/rootfs tmp/candidate-stock/rk-unpacked/rootfs.img home/lava/firmware_MCU
diff -rq tmp/candidate-stock/rootfs/home/lava/firmware_MCU tmp/candidate-inspection/rootfs/home/lava/firmware_MCU
for component in MiniLoaderAll.bin uboot.img oem.img userdata.img; do
    cmp "tmp/candidate-stock/rk-unpacked/$component" "tmp/candidate-inspection/rk-unpacked/$component"
done
scripts/helpers/boot_fit.sh extract tmp/candidate-stock/rk-unpacked/boot.img tmp/candidate-stock/fit
scripts/helpers/boot_fit.sh extract tmp/candidate-inspection/rk-unpacked/boot.img tmp/candidate-inspection/fit
# Kernel and FDT must match stock; resource logos are changed by upstream.
cmp tmp/candidate-stock/fit/kernel.img tmp/candidate-inspection/fit/kernel.img
cmp tmp/candidate-stock/fit/fdt.dtb tmp/candidate-inspection/fit/fdt.dtb
echo 'Unchanged MCU firmware, bootloader, kernel, FDT, OEM and userdata components verified'
