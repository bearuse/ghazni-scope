/* The FreeRTOS demo (../../common/demo.c) on ESP32 (two CPUs) with Ghazni
 * Scope: a hardware timer interrupts every 20 ms (the demo's ISR), the
 * stream goes out on UART0. MIT License - see LICENSE. */
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gptimer.h"
#include "demo.h"

static bool IRAM_ATTR on_timer(gptimer_handle_t t, const gptimer_alarm_event_data_t *e, void *arg)
{
    demo_isr();                 /* gives the semaphore, yields if a task woke */
    return false;
}

void app_main(void)
{
    printf("[demo] FreeRTOS demo for Ghazni Scope (ESP32)\n");
    demo_start();
    gptimer_handle_t t;
    gptimer_config_t c = { .clk_src = GPTIMER_CLK_SRC_DEFAULT, .direction = GPTIMER_COUNT_UP,
                           .resolution_hz = 1000000 };
    ESP_ERROR_CHECK(gptimer_new_timer(&c, &t));
    gptimer_alarm_config_t a = { .alarm_count = 20000, .reload_count = 0,
                                 .flags.auto_reload_on_alarm = true };
    ESP_ERROR_CHECK(gptimer_set_alarm_action(t, &a));
    gptimer_event_callbacks_t cb = { .on_alarm = on_timer };
    ESP_ERROR_CHECK(gptimer_register_event_callbacks(t, &cb, NULL));
    ESP_ERROR_CHECK(gptimer_enable(t));
    ESP_ERROR_CHECK(gptimer_start(t));
}
