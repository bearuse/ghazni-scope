/* The shared FreeRTOS demo (demo.c). */
#ifndef DEMO_H
#define DEMO_H
#ifndef DEMO_STACK
#define DEMO_STACK 256                  /* words */
#endif
void demo_start(void);                  /* before vTaskStartScheduler */
void demo_isr(void);                    /* from an interrupt, every 20 ms */
#endif
