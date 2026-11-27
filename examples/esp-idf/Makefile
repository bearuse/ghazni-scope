# The FreeRTOS demo on ESP32 (ESP-IDF) with Ghazni Scope.
#   make            build/flash.bin (ESP-IDF if installed, else the espressif/idf Docker image)
#   make run        in Espressif's QEMU, live view at http://localhost:8800
#   make flash      to a real board: idf.py flash, then: ghazni-scope --serial /dev/ttyUSB0 --baud 921600
IDF_IMAGE ?= espressif/idf:v5.3.2
SCOPE     ?= PYTHONPATH=../.. python3 -m ghazni_scope
ROOT      := $(abspath ../..)
ifeq ($(shell command -v idf.py),)
IDF = docker run --rm -i -v $(ROOT):/project -w /project/examples/esp-idf -e HOME=/tmp $(IDF_IMAGE)
else
IDF =
endif

build/flash.bin: main/main.c ../common/demo.c ../../targets/freertos/scope_freertos.c ../../targets/freertos/scope_freertos.h \
                 ../../targets/esp-idf/ghazni_scope/scope_port_esp.c ../../targets/esp-idf/ghazni_scope/CMakeLists.txt sdkconfig.defaults
	@if [ sdkconfig -ot sdkconfig.defaults ]; then rm -f sdkconfig; fi   # new defaults: a new sdkconfig
	$(IDF) bash -c 'idf.py -B build set-target esp32 >/dev/null && idf.py -B build build && \
	    cd build && esptool.py --chip esp32 merge_bin --fill-flash-size 4MB -o flash.bin @flash_args'

run: build/flash.bin
	$(SCOPE) --exec "$(if $(IDF),$(subst -i ,-i --entrypoint bash ,$(IDF)) qemu.sh,./qemu.sh)"

flash: build/flash.bin
	$(IDF) idf.py -B build flash

clean:
	rm -rf build sdkconfig
.PHONY: run flash clean
