# Ghazni Scope
#   make test          host unit tests + FreeRTOS on Linux + Cortex-M3 in QEMU
#   make test-host     host unit tests only (no target)
#   make test-ui       the web page in a browser (node + playwright)
#   make demo          FreeRTOS demo on Linux, live view at http://localhost:8800
#   make demo-m3       the same on Cortex-M3 (QEMU mps2-an385; needs clang, ld.lld, qemu-system-arm)
#   make install       pipx install --force . (the ghazni-scope command)
#   make manual-pdf    docs/pdf/Ghazni-Scope-Manual.pdf from docs/MANUAL.md (pip install markdown; node + playwright)
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

manual-pdf:
	@mkdir -p build
	python3 tools/pdf/manual_html.py build/manual.html
	node tools/pdf/print_pdf.js build/manual.html docs/pdf/Ghazni-Scope-Manual.pdf

install:
	pipx install --force .

.PHONY: manual-pdf test test-ui test-host demo demo-m3 clean install
