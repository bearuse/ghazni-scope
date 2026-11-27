# FreeRTOS on Linux with the Ghazni Scope recorder.
#   make            build/demo
#   make run        python3 ../../host/ghazni_scope.py --exec build/demo  (http://localhost:8800)
K       := ../../third_party/FreeRTOS-Kernel
R       := ../../targets/freertos
CC      ?= gcc
CFLAGS  ?= -O2 -g -Wall -Wextra -Wno-unused-parameter
override CFLAGS += -I. -I../common -DDEMO_STACK=1024 -I$(R) -I../../include -I$(K)/include -I$(K)/portable/ThirdParty/GCC/Posix \
           -I$(K)/portable/ThirdParty/GCC/Posix/utils -pthread
SRCS    := main.c port.c ../common/demo.c $(R)/scope_freertos.c \
           $(K)/tasks.c $(K)/queue.c $(K)/list.c $(K)/event_groups.c $(K)/timers.c \
           $(K)/portable/MemMang/heap_4.c $(K)/portable/ThirdParty/GCC/Posix/port.c \
           $(K)/portable/ThirdParty/GCC/Posix/utils/wait_for_event.c

build/demo: $(SRCS) ../common/demo.h FreeRTOSConfig.h $(R)/scope_freertos.h ../../include/scope_encode.h ../../include/scope_proto.h
	@mkdir -p build
	$(CC) $(CFLAGS) $(SRCS) -o $@ -pthread

run: build/demo
	python3 ../../host/ghazni_scope.py --exec build/demo

clean:
	rm -rf build
.PHONY: run clean
