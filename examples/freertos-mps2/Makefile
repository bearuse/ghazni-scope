# FreeRTOS on QEMU mps2-an385 (Cortex-M3) with the Ghazni Scope recorder.
#   make            build/demo.elf (clang + ld.lld, no libc)
#   make run        $(SCOPE) --exec "qemu-system-arm ... -serial stdio"
#   make rtt        build-rtt/demo.elf: the stream through the debug probe (RTT), not the UART
#   make run-rtt    QEMU's GDB server plays the probe: $(SCOPE) --rtt-gdb ... --elf build-rtt/demo.elf
K       := ../../third_party/FreeRTOS-Kernel
# the viewer: this checkout's copy; SCOPE=ghazni-scope to use the installed one
SCOPE   ?= PYTHONPATH=../.. python3 -m ghazni_scope
R       := ../../targets/freertos
CC      := clang
CFLAGS  ?= -O2 -g
override CFLAGS += --target=thumbv7m-none-eabi -mcpu=cortex-m3 -mthumb -ffreestanding -fno-builtin \
           -nostdlib -Wall -Wno-unused-parameter -I. -Ilibc -I../common -I$(R) -I../../include \
           -I$(K)/include -I$(K)/portable/GCC/ARM_CM3
SRCS    := startup.c main.c port.c libc.c ../common/demo.c $(R)/scope_freertos.c \
           $(K)/tasks.c $(K)/queue.c $(K)/list.c $(K)/event_groups.c $(K)/timers.c \
           $(K)/portable/MemMang/heap_4.c $(K)/portable/GCC/ARM_CM3/port.c
QEMU    := qemu-system-arm -M mps2-an385 -display none -monitor none -serial stdio -kernel build/demo.elf

build/demo.elf: $(SRCS) mps2.ld FreeRTOSConfig.h ../common/demo.h $(R)/scope_freertos.h ../../include/scope_encode.h
	@mkdir -p build
	$(CC) $(CFLAGS) $(SRCS) -fuse-ld=lld -Wl,-T,mps2.ld -Wl,--gc-sections -o $@

# the same demo, the stream in an RTT buffer (targets/rtt, docs/RTT.md)
build-rtt/demo.elf: $(SRCS) ../../targets/rtt/scope_rtt.c ../../targets/rtt/scope_rtt.h mps2.ld FreeRTOSConfig.h
	@mkdir -p build-rtt
	$(CC) $(CFLAGS) -DSCOPE_RTT -I../../targets/rtt $(SRCS) ../../targets/rtt/scope_rtt.c \
	    -fuse-ld=lld -Wl,-T,mps2.ld -Wl,--gc-sections -o $@
rtt: build-rtt/demo.elf

GDB_PORT ?= 3333
run-rtt: build-rtt/demo.elf
	qemu-system-arm -M mps2-an385 -display none -monitor none -serial null \
	    -gdb tcp:127.0.0.1:$(GDB_PORT) -kernel build-rtt/demo.elf & \
	$(SCOPE) --rtt-gdb 127.0.0.1:$(GDB_PORT) --elf build-rtt/demo.elf; kill %1

run: build/demo.elf
	$(SCOPE) --exec "$(QEMU)"

clean:
	rm -rf build build-rtt
.PHONY: run rtt run-rtt clean
