/* FreeRTOS on Linux (POSIX port) running the Ghazni Scope demo
 * (../common/demo.c). The recorder's frames and the text go to stdout.
 * SCOPE_RUN_S=n in the environment: exit after n seconds (tests). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "FreeRTOS.h"
#include "task.h"
#include "demo.h"

static void say(const char *s) { (void)!write(1, s, strlen(s)); }

void vApplicationTickHook(void)             /* the tick "interrupt" (a signal handler) */
{
    static unsigned n;
    if (++n % 20 == 0)
        demo_isr();
}

static void stopper(void *arg)
{
    vTaskDelay(pdMS_TO_TICKS((TickType_t)(uintptr_t)arg * 1000));
    say("[demo] done\n");
    vTaskDelay(pdMS_TO_TICKS(50));          /* the last frames */
    exit(0);
}

void vAssertCalled(const char *file, int line)
{
    fprintf(stderr, "assert %s:%d\n", file, line);
    abort();
}

int main(void)
{
    demo_start();
    const char *run = getenv("SCOPE_RUN_S");
    if (run)
        xTaskCreate(stopper, "stopper", 1024, (void *)(uintptr_t)atoi(run), 7, NULL);
    say("[demo] FreeRTOS demo for Ghazni Scope (Linux)\n");
    vTaskStartScheduler();
    return 1;
}
