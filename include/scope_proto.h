/* Ghazni Scope stream protocol, target -> host (docs/PROTOCOL.md).
 *
 * RTOS-neutral: Ghazni's kernel tracer and the FreeRTOS recorder
 * (targets/freertos) send the same frames, and tools read both. All
 * integers little endian. Each frame on the wire:
 *
 *     0x01  COBS(frame bytes)  0x00
 *
 * in between ordinary console text (which never contains 0x00 or 0x01).
 *
 * MIT License - see LICENSE. */
#ifndef SCOPE_PROTO_H
#define SCOPE_PROTO_H

#include <stdint.h>

#define SCOPE_SOF       0x01
#define SCOPE_EOF       0x00
#define SCOPE_VERSION   3

/* 'H' hello byte [5]: which system sends the stream */
#define SCOPE_OS_GHAZNI     0
#define SCOPE_OS_FREERTOS   1

/* task ids in events: 0..0xFC tasks, the CPU's idle thread, nobody */
#define SCOPE_IDLE  0xFF
#define SCOPE_NONE  0xFE

/* event types (struct scope_ev.type). a, b = task ids unless noted */
#define TEV_SWITCH   1      /* CPU switches from a to b; arg = state the outgoing task
                               leaves in (SCOPE_ST_*) | what it blocks on << 8
                               (SCOPE_BLK_*) | object or task number << 16 */
#define TEV_WAKE     2      /* a became ready */
#define TEV_IRQ      3      /* interrupt arg starts (a = interrupted task) */
#define TEV_TIMEOUT  4      /* a's blocking call timed out */
#define TEV_THROTTLE 5      /* a used up its CPU budget (b = who runs instead) */
#define TEV_TIMER    6      /* a kernel timer fired, arg = notification bits */
#define TEV_FAULT    7      /* a faulted */
#define TEV_CALL     8      /* a calls endpoint arg & 0xFF (synchronous IPC), b = server
                               that got it or SCOPE_NONE (queued); arg >> 8 = label */
#define TEV_SEND     9      /* the same, no reply wanted */
#define TEV_RECV     10     /* server a takes a queued message from b, arg = endpoint */
#define TEV_REPLY    11     /* server a answers client b */
#define TEV_SIGNAL   12     /* a signals / gives / sends to object b; arg = bits (event),
                               count or messages waiting after (semaphore, queue), 0 (mutex) */
#define TEV_USER     13     /* user event of task a: b = channel, arg = value */
#define TEV_USTR     14     /* 4 bytes of a text user event: b = channel | TSTR_*,
                               arg = the bytes, a string ends with a 0 byte */
#define TEV_HEAP     15     /* heap of a: b = op, arg = size; then b = op | HEAP_ADDR,
                               arg = address (low 32 bits) */
#define TEV_IRQ_END  16     /* interrupt arg handled (a = interrupted task) */
#define TEV_PRIO     17     /* a's effective priority becomes b (inheritance), arg = before */
#define TEV_TAKE     18     /* a took object b (mutex, semaphore, queue message, bits);
                               arg = count / messages left */

#define TSTR_FIRST      0x80
#define TSTR_STATE      0x40    /* a state of state machine (channel & 0x3F) */
#define HEAP_ALLOC      0
#define HEAP_FREE       1
#define HEAP_ADDR       0x80

/* task states (TEV_SWITCH arg, 'S' frames); 3..10 = the task stopped running
 * of its own accord (blocked, slept, died) */
#define SCOPE_ST_INACTIVE   0
#define SCOPE_ST_RUNNING    1
#define SCOPE_ST_READY      2       /* preempted */
#define SCOPE_ST_SEND       3       /* blocked sending (endpoint, full queue) */
#define SCOPE_ST_RECV       4       /* blocked receiving (endpoint, empty queue, semaphore, mutex) */
#define SCOPE_ST_REPLY      5       /* waiting for a server's reply */
#define SCOPE_ST_WAIT       6       /* waiting for bits / a notification */
#define SCOPE_ST_SLEEP      7       /* delayed */
#define SCOPE_ST_FAULTED    8
#define SCOPE_ST_EXITED     9       /* deleted */
#define SCOPE_ST_STOPPED    10      /* suspended */
#define SCOPE_ST_THROTTLED  11

/* what a task blocks on (TEV_SWITCH arg >> 8) */
#define SCOPE_BLK_NONE      0
#define SCOPE_BLK_ENDPOINT  1
#define SCOPE_BLK_OBJECT    2       /* an entry of the object table ('O': notifications) */
#define SCOPE_BLK_TASK      3       /* the server it waits on for a reply */

/* object kinds ('O' frame, one byte per object) */
#define SCOPE_OBJ_EVENT     0       /* bits (Ghazni notification) */
#define SCOPE_OBJ_MUTEX     1
#define SCOPE_OBJ_SEMAPHORE 2
#define SCOPE_OBJ_QUEUE     3       /* message queue: TEV_SIGNAL = send, TEV_TAKE = receive */
#define SCOPE_OBJ_EVGROUP   4       /* event group: TEV_SIGNAL arg = bits set */

/* frames (first byte):
 *   'H' hello   [1] version [2] ncpus [3] ntasks [4] 1 = a repeat [5] SCOPE_OS_*
 *               [8..15] timestamp Hz; then per task 20 bytes: id, base prio, 0, 0, name[16]
 *   'D' events  [1..8] sequence of the first [9..10] n [12..15] lost before it
 *               [16..23] base timestamp; then n compact events:
 *                 zigzag varint  timestamp - previous
 *                 u8             type | cpu << 4   (type > 15: low nibble 0, then u8 type)
 *                 u8             a
 *                 u8             b      if scope_has_b(type)
 *                 varint         arg    if scope_has_arg(type)
 *   'O' objects [1] n endpoints [2] n objects [3] n interrupts; then 16-byte names,
 *               endpoints first; then per interrupt u16 number + 14-byte name;
 *               then one byte per object: its kind (SCOPE_OBJ_*)
 *   'S' stats   [1..8] uptime us [9] n [10] sizeof(struct scope_task) [12..15] us spent
 *               sending the stream (wraps); then n x struct scope_task
 *   'X' stopped */
struct scope_ev {                   /* 16 bytes */
    uint64_t tick;
    uint8_t type, cpu, a, b;
    uint32_t arg;
};

struct scope_task {                 /* 32 bytes */
    uint8_t id, state, prio, base_prio;
    uint32_t throttles;
    uint64_t cpu_us;
    uint32_t stack_used, stack_size;
    uint64_t kern_us;
};

static inline int scope_has_b(unsigned t)
{
    return t == TEV_SWITCH || t == TEV_PRIO || t == TEV_TAKE ||
           (t >= TEV_THROTTLE && t <= TEV_HEAP && t != TEV_TIMER && t != TEV_FAULT);
}

static inline int scope_has_arg(unsigned t)
{
    return t == TEV_SWITCH || t == TEV_IRQ || t == TEV_TIMER || t >= TEV_CALL;
}

#endif
