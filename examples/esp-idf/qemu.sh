#!/bin/bash
# The demo in Espressif's QEMU (ESP32, two CPUs), the UART on stdout:
# the stream for ghazni-scope --exec. Runs where ESP-IDF's tools are (after
# export.sh, or in the espressif/idf Docker image; see Makefile).
cd "$(dirname "$0")"
Q=$(command -v qemu-system-xtensa || ls -d /opt/esp/tools/qemu-xtensa/*/qemu/bin/qemu-system-xtensa 2>/dev/null | head -1)
[ -x "$Q" ] || { echo "qemu-system-xtensa not found: python \$IDF_PATH/tools/idf_tools.py install qemu-xtensa" >&2; exit 1; }
exec "$Q" -M esp32 -m 4M -display none -monitor none -serial file:/dev/stdout \
    -drive file=build/flash.bin,if=mtd,format=raw -nic none
