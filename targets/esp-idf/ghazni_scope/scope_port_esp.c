/* Ghazni Scope port for ESP-IDF: one clock for both CPUs (esp_timer, 1 us)
 * and the frames on a UART (CONFIG_SCOPE... below; UART0 = the console by
 * default: frames and log lines share it, docs/ESP-IDF.md).
 * MIT License - see LICENSE. */
#include <stdint.h>
#include <stddef.h>
#include "sdkconfig.h"
#include "esp_timer.h"
#include "driver/uart.h"
#include "scope_port.h"

#ifndef SCOPE_UART
#define SCOPE_UART      UART_NUM_0
#endif

uint64_t scope_port_time(void) { return (uint64_t)esp_timer_get_time(); }
uint64_t scope_port_hz(void) { return 1000000; }

/* the heap: ESP-IDF's allocator calls these with CONFIG_HEAP_USE_HOOKS=y
   (FreeRTOS's traceMALLOC is not used there); a free comes without its size */
#if CONFIG_HEAP_USE_HOOKS
#include "esp_heap_caps.h"
#include "scope_freertos.h"
void esp_heap_trace_alloc_hook(void *ptr, size_t size, uint32_t caps) { scope_rtos_heap(0, ptr, (unsigned)size); }
void esp_heap_trace_free_hook(void *ptr) { scope_rtos_heap(1, ptr, 0); }
#endif

void scope_port_write(const uint8_t *buf, size_t n)
{
    static int ready;
    if (!ready) {               /* the driver: raw bytes (no CR added before LF), buffered */
        if (!uart_is_driver_installed(SCOPE_UART))
            uart_driver_install(SCOPE_UART, 256, 8192, 0, NULL, 0);
        ready = 1;
    }
    uart_write_bytes(SCOPE_UART, buf, n);
}
