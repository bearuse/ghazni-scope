# Ghazni Scope
#   make test          host unit tests + FreeRTOS on Linux + Cortex-M3 in QEMU
#   make test-host     host unit tests only (no target)
#   make demo          FreeRTOS demo on Linux, live view at http://localhost:8800
#   make demo-m3       the same on Cortex-M3 (QEMU mps2-an385; needs clang, ld.lld, qemu-system-arm)
test: test-host
	python3 tests/run_freertos.py

test-host:
	python3 tests/test_host.py

demo:
	$(MAKE) -C examples/freertos-posix run

demo-m3:
	$(MAKE) -C examples/freertos-mps2 run

clean:
	$(MAKE) -C examples/freertos-posix clean
	$(MAKE) -C examples/freertos-mps2 clean

.PHONY: test test-host demo demo-m3 clean
