/* FreeRTOS on Linux (POSIX port) with the Ghazni Scope recorder. */
#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

#define configUSE_PREEMPTION                    1
#define configUSE_TIME_SLICING                  1
#define configTICK_RATE_HZ                      1000
#define configMAX_PRIORITIES                    8
#define configMINIMAL_STACK_SIZE                ( ( unsigned short ) 1024 )
#define configTOTAL_HEAP_SIZE                   ( ( size_t ) ( 1024 * 1024 ) )
#define configMAX_TASK_NAME_LEN                 16
#define configTICK_TYPE_WIDTH_IN_BITS           TICK_TYPE_WIDTH_64_BITS
#define configIDLE_SHOULD_YIELD                 1
#define configUSE_MUTEXES                       1
#define configUSE_RECURSIVE_MUTEXES             1
#define configUSE_COUNTING_SEMAPHORES           1
#define configQUEUE_REGISTRY_SIZE               16
#define configUSE_TICK_HOOK                     1
#define configUSE_IDLE_HOOK                     0
#define configUSE_TIMERS                        0
#define configSUPPORT_DYNAMIC_ALLOCATION        1
#define configSUPPORT_STATIC_ALLOCATION         0
#define configCHECK_FOR_STACK_OVERFLOW          0
#define configUSE_MALLOC_FAILED_HOOK            0

/* Ghazni Scope */
#define configUSE_TRACE_FACILITY                1
#define configRECORD_STACK_HIGH_ADDRESS         1

#define INCLUDE_vTaskDelay                      1
#define INCLUDE_xTaskDelayUntil                 1
#define INCLUDE_vTaskSuspend                    1
#define INCLUDE_vTaskDelete                     1
#define INCLUDE_vTaskPrioritySet                1
#define INCLUDE_uxTaskPriorityGet               1
#define INCLUDE_xTaskGetCurrentTaskHandle       1
#define INCLUDE_uxTaskGetStackHighWaterMark     1
#define INCLUDE_xTaskGetSchedulerState          1

extern void vAssertCalled( const char * file, int line );
#define configASSERT( x )    if( !( x ) ) vAssertCalled( __FILE__, __LINE__ )

#include "scope_freertos.h"     /* last: the trace hooks */
#endif
