/* FreeRTOS on QEMU mps2-an385 (Cortex-M3) running the Ghazni Scope demo
 * (../common/demo.c). TIMER0 interrupts every 20 ms: the demo's ISR.
 *   qemu-system-arm -M mps2-an385 -display none -monitor none -serial stdio -kernel build/demo.elf */
#include <stdint.h>
#include "FreeRTOS.h"
#include "task.h"
#include "demo.h"

#define REG(a)          (*(volatile uint32_t *)(a))
#define TIMER0          0x40000000u             /* CMSDK APB timer, 25 MHz */
#define NVIC_ISER0      REG(0xE000E100u)
#define NVIC_IPR(n)     (*(volatile uint8_t *)(0xE000E400u + (n)))
#define TIMER0_IRQ      8

void uart_init(void);
void uart_putc(char c);
void scope_mps2_tick(void);

static void say(const char *s)
{
    while (*s)
        uart_putc(*s++);
}

void vApplicationTickHook(void) { scope_mps2_tick(); }

void timer0_isr(void)
{
    REG(TIMER0 + 0xC) = 1;                      /* clear */
    demo_isr();
}

void vAssertCalled(const char *file, int line)
{
    (void)line;
    taskDISABLE_INTERRUPTS();
    say("assert ");
    say(file);
    say("\n");
    for (;;) {}
}

int main(void)
{
    uart_init();
    say("[demo] FreeRTOS demo for Ghazni Scope (Cortex-M3, QEMU mps2-an385)\n");
    demo_start();
    REG(TIMER0 + 0x8) = configCPU_CLOCK_HZ / 50;   /* reload: 20 ms */
    REG(TIMER0 + 0x4) = configCPU_CLOCK_HZ / 50;
    REG(TIMER0 + 0x0) = (1u << 0) | (1u << 3);      /* enable, interrupt */
    NVIC_IPR(TIMER0_IRQ) = 6 << (8 - configPRIO_BITS);  /* below the syscall ceiling: may use FromISR */
    NVIC_ISER0 = 1u << TIMER0_IRQ;
    vTaskStartScheduler();
    return 1;
}
