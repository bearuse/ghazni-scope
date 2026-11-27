/* Cortex-M3 start-up for QEMU mps2-an385: vector table, .data / .bss, main. */
#include <stdint.h>

extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss, _estack;
extern int main(void);
extern void vPortSVCHandler(void), xPortPendSVHandler(void), xPortSysTickHandler(void);
void timer0_isr(void);

void Reset_Handler(void)
{
    uint32_t *s = &_sidata, *d = &_sdata;
    while (d < &_edata)
        *d++ = *s++;
    for (d = &_sbss; d < &_ebss; d++)
        *d = 0;
    main();
    for (;;) {}
}

static void fault(void)
{
    for (;;) {}
}

__attribute__((section(".vectors"), used))
static void (*const vectors[16 + 32])(void) = {
    (void (*)(void))&_estack, Reset_Handler, fault, fault, fault, fault, fault, 0, 0, 0, 0,
    vPortSVCHandler, fault, 0, xPortPendSVHandler, xPortSysTickHandler,
    [16 + 8] = timer0_isr,             /* TIMER0 */
};
