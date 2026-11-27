/* Ghazni Scope port for QEMU mps2-an385: timestamps from SysTick (25 MHz
 * CPU clock), frames to UART0 (CMSDK UART, QEMU -serial stdio). */
#include <stdint.h>
#include "FreeRTOS.h"
#include "scope_port.h"

#define REG(a)          (*(volatile uint32_t *)(a))
#define UART0           0x40004000u
#define UART_DATA       REG(UART0 + 0x0)
#define UART_STATE      REG(UART0 + 0x4)        /* bit 0: TX full */
#define UART_CTRL       REG(UART0 + 0x8)        /* bit 0: TX enable */
#define UART_BAUDDIV    REG(UART0 + 0x10)
#define SYST_RVR        REG(0xE000E014u)
#define SYST_CVR        REG(0xE000E018u)
#define SCB_ICSR        REG(0xE000ED04u)
#define PENDSTSET       (1u << 26)

static volatile uint32_t ticks;                 /* SysTick wraps, counted by the tick hook */

void scope_mps2_tick(void) { ticks++; }

void uart_init(void)
{
    UART_BAUDDIV = 16;
    UART_CTRL = 1;
}

void uart_putc(char c)
{
    while (UART_STATE & 1) {}
    UART_DATA = (uint8_t)c;
}

uint64_t scope_port_time(void)
{
    uint32_t reload = SYST_RVR, t = ticks, v = SYST_CVR;
    if ((SCB_ICSR & PENDSTSET) && v > reload / 2) {     /* wrapped, the hook has not run yet */
        t++;
    }
    return (uint64_t)t * (reload + 1) + (reload - v);
}

uint64_t scope_port_hz(void) { return configCPU_CLOCK_HZ; }

#ifdef SCOPE_RTT
/* through the debug probe (make rtt): the RTT buffer, waiting while it is full */
#include "task.h"
#include "scope_rtt.h"

void scope_port_write(const uint8_t *buf, size_t n)
{
    while (n) {
        unsigned w = scope_rtt_write(buf, (unsigned)n);
        buf += w;
        n -= w;
        if (n)
            vTaskDelay(1);
    }
}
#else
void scope_port_write(const uint8_t *buf, size_t n)
{
    while (n--)
        uart_putc((char)*buf++);
}
#endif
