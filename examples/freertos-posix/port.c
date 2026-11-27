/* Ghazni Scope port for FreeRTOS on Linux: microsecond timestamps, frames
 * to stdout (tools read them with --exec). */
#include <time.h>
#include <unistd.h>
#include "scope_port.h"

uint64_t scope_port_time(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000u + (uint64_t)ts.tv_nsec / 1000u;
}

uint64_t scope_port_hz(void) { return 1000000u; }

void scope_port_write(const uint8_t *buf, size_t n)
{
    while (n) {                         /* one write per frame keeps it whole in a pipe */
        ssize_t w = write(1, buf, n);
        if (w <= 0)
            return;
        buf += w;
        n -= (size_t)w;
    }
}
