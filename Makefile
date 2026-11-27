# Ghazni Scope
#   make test          host unit tests + FreeRTOS on Linux + Cortex-M3 in QEMU
#   make test-host     host unit tests only (no target)
#   make test-ui       the web page in a browser (node + playwright)
#   make demo          FreeRTOS demo on Linux, live view at http://localhost:8800
#   make demo-m3       the same on Cortex-M3 (QEMU mps2-an385; needs clang, ld.lld, qemu-system-arm)
#   make install       pipx install --force . (the ghazni-scope command)
test: test-host
	python3 tests/run_freertos.py

test-ui:
	$(MAKE) -s -C examples/freertos-posix
	node tests/test_ui.js

test-host:
	python3 tests/test_host.py

demo:
	$(MAKE) -C examples/freertos-posix run

demo-m3:
	$(MAKE) -C examples/freertos-mps2 run

clean:
	$(MAKE) -C examples/freertos-posix clean
	$(MAKE) -C examples/freertos-mps2 clean

install:
	pipx install --force .

.PHONY: test test-ui test-host demo demo-m3 clean install
