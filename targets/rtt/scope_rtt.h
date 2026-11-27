/* Ghazni Scope over a debug probe: a SEGGER RTT compatible up-buffer
 * (docs/RTT.md). The probe (J-Link, OpenOCD, pyOCD, or ghazni-scope
 * --rtt-gdb through any GDB server) reads it from RAM while the CPU runs:
 * no UART needed.
 *
 *   void scope_port_write(const uint8_t *buf, size_t n)
 *   {
 *       while (n) {                         // wait while the probe catches up
 *           unsigned w = scope_rtt_write(buf, n);
 *           buf += w; n -= w;
 *           if (n) vTaskDelay(1);
 *       }
 *   }
 *
 * If your project already has SEGGER's RTT (SEGGER_RTT.c), do not use this
 * file: write the frames with SEGGER_RTT_Write(channel, buf, n) instead,
 * on a channel of its own, and point the tool at that channel.
 *
 * MIT License - see LICENSE. */
#ifndef SCOPE_RTT_H
#define SCOPE_RTT_H

#include <stdint.h>

#ifndef SCOPE_RTT_SIZE
#define SCOPE_RTT_SIZE  4096        /* bytes; the probe reads it every few ms */
#endif

/* Copies as much of buf as fits now; returns the bytes taken (0..n). */
unsigned scope_rtt_write(const uint8_t *buf, unsigned n);

/* Bytes the probe has not read yet. */
unsigned scope_rtt_pending(void);

#endif
