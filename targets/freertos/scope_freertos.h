/* Ghazni Scope recorder for FreeRTOS (docs/FREERTOS.md).
 *
 * Include this file at the END of FreeRTOSConfig.h. It turns FreeRTOS's
 * trace hook macros into Scope events: task switches with the reason a
 * task stopped (which queue, semaphore, mutex or event group it waits on,
 * a delay, ...), wake-ups, queue / semaphore / mutex / event group use,
 * priority inheritance, the heap, task and object names. Your interrupt
 * handlers add scope_isr_begin/end; your code can add user events.
 *
 * Needs in FreeRTOSConfig.h (checked below):
 *   configUSE_TRACE_FACILITY 1            object and task numbers
 *   configRECORD_STACK_HIGH_ADDRESS 1     stack size in the statistics (optional)
 *   INCLUDE_xTaskGetCurrentTaskHandle 1
 *   INCLUDE_uxTaskGetStackHighWaterMark 1 (optional)
 * and a port (scope_port.h): a timestamp and a way to write bytes.
 *
 * MIT License - see LICENSE. */
#ifndef SCOPE_FREERTOS_H
#define SCOPE_FREERTOS_H

#ifndef __ASSEMBLER__
#include <stdint.h>

/* ---- public API (your code) */
void scope_init(void);                          /* before vTaskStartScheduler: creates the
                                                   streaming task "tracer" */
void scope_isr_begin(uint8_t isr);              /* first thing in an interrupt handler */
void scope_isr_end(uint8_t isr);                /* last thing */
void scope_isr_name(uint8_t isr, const char *name);
void scope_name_object(void *handle, const char *name);    /* event groups, or queues
                                                   without vQueueAddToRegistry */
void scope_user(uint8_t channel, uint32_t value);
void scope_print(uint8_t channel, const char *text);
void scope_printf(uint8_t channel, const char *fmt, ...);
void scope_state(uint8_t machine, const char *state);     /* state machine (0..63) */
uint32_t scope_lost(void);                      /* events dropped: the ring was full */

/* ---- hooks (called by the macros below; not for your code) */
void scope_rtos_task_create(void *tcb, const char *name, unsigned prio, void *stack_lo, void *stack_hi);
void scope_rtos_task_delete(void *tcb);
void scope_rtos_switched_out(void *tcb);
void scope_rtos_switched_in(void *tcb);
void scope_rtos_ready(void *tcb);
void scope_rtos_block(unsigned state, void *object, int is_evgroup);
void scope_rtos_suspend(void *tcb);
void scope_rtos_prio(void *tcb, unsigned new_prio, unsigned old_prio, int base_too);
void scope_rtos_queue_create(void *queue);
void scope_rtos_queue_name(void *queue, const char *name);
void scope_rtos_queue_send(void *queue, unsigned waiting_after, int from_isr);
void scope_rtos_queue_receive(void *queue, unsigned waiting_after, int from_isr);
void scope_rtos_evgroup_create(void *group);
void scope_rtos_evgroup_set(void *group, uint32_t bits, int from_isr);
void scope_rtos_evgroup_got(void *group, uint32_t bits);
void scope_rtos_heap(int op, void *addr, unsigned size);
void scope_rtos_timeout(void);

/* ---- FreeRTOS trace macros */
#if configUSE_TRACE_FACILITY != 1
#error "Ghazni Scope needs configUSE_TRACE_FACILITY 1"
#endif

#if ( configRECORD_STACK_HIGH_ADDRESS == 1 ) || ( portSTACK_GROWTH > 0 )
#define SCOPE_STACK_HI_( t ) ( ( void * ) ( t )->pxEndOfStack )
#else
#define SCOPE_STACK_HI_( t ) ( ( void * ) 0 )
#endif

#define traceTASK_CREATE( pxNewTCB ) \
    scope_rtos_task_create( ( void * ) ( pxNewTCB ), ( pxNewTCB )->pcTaskName, \
                            ( unsigned ) ( pxNewTCB )->uxPriority, ( void * ) ( pxNewTCB )->pxStack, \
                            SCOPE_STACK_HI_( pxNewTCB ) )
#define traceTASK_DELETE( pxTaskToDelete )      scope_rtos_task_delete( ( void * ) ( pxTaskToDelete ) )
#define traceTASK_SWITCHED_OUT()                scope_rtos_switched_out( ( void * ) pxCurrentTCB )
#define traceTASK_SWITCHED_IN()                 scope_rtos_switched_in( ( void * ) pxCurrentTCB )
#define traceMOVED_TASK_TO_READY_STATE( pxTCB ) scope_rtos_ready( ( void * ) ( pxTCB ) )

/* why the running task is about to stop (SCOPE_ST_* values: 3 send, 4 recv, 6 wait, 7 sleep) */
#define traceBLOCKING_ON_QUEUE_RECEIVE( pxQueue )   scope_rtos_block( 4, ( void * ) ( pxQueue ), 0 )
#define traceBLOCKING_ON_QUEUE_PEEK( pxQueue )      scope_rtos_block( 4, ( void * ) ( pxQueue ), 0 )
#define traceBLOCKING_ON_QUEUE_SEND( pxQueue )      scope_rtos_block( 3, ( void * ) ( pxQueue ), 0 )
#define traceTASK_DELAY()                           scope_rtos_block( 7, ( void * ) 0, 0 )
#define traceTASK_DELAY_UNTIL( x )                  scope_rtos_block( 7, ( void * ) 0, 0 )
#define traceEVENT_GROUP_WAIT_BITS_BLOCK( xEventGroup, uxBitsToWaitFor ) \
    scope_rtos_block( 6, ( void * ) ( xEventGroup ), 1 )
#define traceEVENT_GROUP_SYNC_BLOCK( xEventGroup, uxBitsToSet, uxBitsToWaitFor ) \
    scope_rtos_block( 6, ( void * ) ( xEventGroup ), 1 )
#define traceTASK_NOTIFY_TAKE_BLOCK( uxIndexToWait )    scope_rtos_block( 6, ( void * ) 0, 0 )
#define traceTASK_NOTIFY_WAIT_BLOCK( uxIndexToWait )    scope_rtos_block( 6, ( void * ) 0, 0 )
#define traceTASK_SUSPEND( pxTaskToSuspend )        scope_rtos_suspend( ( void * ) ( pxTaskToSuspend ) )

#define traceTASK_PRIORITY_INHERIT( pxTCBOfMutexHolder, uxInheritedPriority ) \
    scope_rtos_prio( ( void * ) ( pxTCBOfMutexHolder ), ( unsigned ) ( uxInheritedPriority ), \
                     ( unsigned ) ( pxTCBOfMutexHolder )->uxPriority, 0 )
#define traceTASK_PRIORITY_DISINHERIT( pxTCBOfMutexHolder, uxOriginalPriority ) \
    scope_rtos_prio( ( void * ) ( pxTCBOfMutexHolder ), ( unsigned ) ( uxOriginalPriority ), \
                     ( unsigned ) ( pxTCBOfMutexHolder )->uxPriority, 0 )
#define traceTASK_PRIORITY_SET( pxTask, uxNewPriority ) \
    scope_rtos_prio( ( void * ) ( pxTask ), ( unsigned ) ( uxNewPriority ), \
                     ( unsigned ) ( pxTask )->uxPriority, 1 )

/* queues, semaphores, mutexes: they are all queues in FreeRTOS */
#define traceQUEUE_CREATE( pxNewQueue )             scope_rtos_queue_create( ( void * ) ( pxNewQueue ) )
#define traceQUEUE_REGISTRY_ADD( xQueue, pcQueueName ) \
    scope_rtos_queue_name( ( void * ) ( xQueue ), ( pcQueueName ) )
#define traceQUEUE_SEND( pxQueue ) \
    scope_rtos_queue_send( ( void * ) ( pxQueue ), ( unsigned ) ( pxQueue )->uxMessagesWaiting + 1, 0 )
#define traceQUEUE_SEND_FROM_ISR( pxQueue ) \
    scope_rtos_queue_send( ( void * ) ( pxQueue ), ( unsigned ) ( pxQueue )->uxMessagesWaiting + 1, 1 )
#define traceQUEUE_RECEIVE( pxQueue ) \
    scope_rtos_queue_receive( ( void * ) ( pxQueue ), ( unsigned ) ( pxQueue )->uxMessagesWaiting - 1, 0 )
#define traceQUEUE_RECEIVE_FROM_ISR( pxQueue ) \
    scope_rtos_queue_receive( ( void * ) ( pxQueue ), ( unsigned ) ( pxQueue )->uxMessagesWaiting - 1, 1 )
#define traceQUEUE_RECEIVE_FAILED( pxQueue )        scope_rtos_timeout()

/* event groups */
#define traceEVENT_GROUP_CREATE( xEventGroup )      scope_rtos_evgroup_create( ( void * ) ( xEventGroup ) )
#define traceEVENT_GROUP_SET_BITS( xEventGroup, uxBitsToSet ) \
    scope_rtos_evgroup_set( ( void * ) ( xEventGroup ), ( uint32_t ) ( uxBitsToSet ), 0 )
#define traceEVENT_GROUP_SET_BITS_FROM_ISR( xEventGroup, uxBitsToSet ) \
    scope_rtos_evgroup_set( ( void * ) ( xEventGroup ), ( uint32_t ) ( uxBitsToSet ), 1 )
#define traceEVENT_GROUP_WAIT_BITS_END( xEventGroup, uxBitsToWaitFor, xTimeoutOccurred ) \
    do { if( !( xTimeoutOccurred ) ) scope_rtos_evgroup_got( ( void * ) ( xEventGroup ), \
                                                              ( uint32_t ) ( uxBitsToWaitFor ) ); \
         else scope_rtos_timeout(); } while( 0 )

/* heap (heap_1..5) */
#define traceMALLOC( pvAddress, uiSize )            scope_rtos_heap( 0, ( pvAddress ), ( unsigned ) ( uiSize ) )
#define traceFREE( pvAddress, uiSize )              scope_rtos_heap( 1, ( pvAddress ), ( unsigned ) ( uiSize ) )

#endif /* __ASSEMBLER__ */
#endif
