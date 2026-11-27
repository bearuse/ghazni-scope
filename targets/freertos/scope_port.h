/* Ghazni Scope recorder for FreeRTOS: what your board provides.
 * Examples: examples/freertos-posix/port.c (Linux), examples/freertos-mps2/
 * port.c (Cortex-M3 under QEMU). MIT License - see LICENSE. */
#ifndef SCOPE_PORT_H
#define SCOPE_PORT_H

#include <stddef.h>
#include <stdint.h>

/* A free-running timestamp, as fine as you have (a cycle counter, a
 * hardware timer); called with interrupts masked, from tasks and ISRs. */
uint64_t scope_port_time(void);
uint64_t scope_port_hz(void);               /* its frequency */

/* Write bytes to the host (UART, USB CDC, TCP, RTT, ...). Called only
 * from the "tracer" task; may block. Frames are 0x01 COBS(...) 0x00, so
 * they can share a UART with console text that has no 0x00 / 0x01. */
void scope_port_write(const uint8_t *buf, size_t n);

#endif
