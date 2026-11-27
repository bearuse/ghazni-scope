# FreeRTOS on QEMU mps2-an385 (Cortex-M3) with the Ghazni Scope recorder.
#   make            build/demo.elf (clang + ld.lld, no libc)
#   make run        python3 ../../host/ghazni_scope.py --exec "qemu-system-arm ... -serial stdio"
K       := ../../third_party/FreeRTOS-Kernel
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

run: build/demo.elf
	python3 ../../host/ghazni_scope.py --exec "$(QEMU)"

clean:
	rm -rf build
.PHONY: run clean
