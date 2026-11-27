/* Ghazni Scope recorder for FreeRTOS (docs/FREERTOS.md).
 *
 * The trace hooks (scope_freertos.h) put 16-byte events into a RAM ring
 * with interrupts masked; nothing else happens in the kernel's paths. A
 * low-priority task named "tracer" (the viewer hides it at first, as with
 * Ghazni) drains the ring every SCOPE_PERIOD_MS into compact 'D' frames,
 * sends the task and object names when they change (and once a second),
 * and per-task statistics every 100 ms, all through scope_port_write().
 * When the ring is full, events are dropped and counted; the next frame
 * says how many (the viewer shows "lost").
 *
 * MIT License - see LICENSE. */
#include <stdarg.h>
#include <string.h>
#include "FreeRTOS.h"
#include "task.h"
#include "queue.h"
#include "event_groups.h"
#include "scope_proto.h"
#include "scope_encode.h"
#include "scope_port.h"

#ifndef SCOPE_RING_EVENTS
#define SCOPE_RING_EVENTS   2048        /* power of two; 32 KiB */
#endif
#ifndef SCOPE_MAX_TASKS
#define SCOPE_MAX_TASKS     32
#endif
#ifndef SCOPE_MAX_OBJECTS
#define SCOPE_MAX_OBJECTS   32
#endif
#ifndef SCOPE_MAX_IRQS
#define SCOPE_MAX_IRQS      8
#endif
#ifndef SCOPE_PERIOD_MS
#define SCOPE_PERIOD_MS     10
#endif
#ifndef SCOPE_TASK_PRIO
#define SCOPE_TASK_PRIO     ( tskIDLE_PRIORITY + 1 )
#endif
#ifndef SCOPE_TASK_STACK
#define SCOPE_TASK_STACK    ( configMINIMAL_STACK_SIZE * 4 )
#endif
#define BATCH 64
#ifndef configIDLE_TASK_NAME
#define configIDLE_TASK_NAME "IDLE"     /* tasks.c's default */
#endif

#if configNUMBER_OF_CORES > 1
#define SCOPE_CPU() ( ( uint8_t ) portGET_CORE_ID() )
#else
#define SCOPE_CPU() 0
#endif

/* ---- the ring */
static struct scope_ev ring[SCOPE_RING_EVENTS];
static volatile uint32_t r_head, r_tail, r_lost;

static void put(uint8_t type, uint8_t a, uint8_t b, uint32_t arg)
{
    UBaseType_t m = portSET_INTERRUPT_MASK_FROM_ISR();
    if (r_head - r_tail >= SCOPE_RING_EVENTS) {
        r_lost++;
    } else {
        struct scope_ev *e = &ring[r_head & (SCOPE_RING_EVENTS - 1)];
        e->tick = scope_port_time();
        e->type = type;
        e->cpu = SCOPE_CPU();
        e->a = a;
        e->b = b;
        e->arg = arg;
        r_head++;
    }
    portCLEAR_INTERRUPT_MASK_FROM_ISR(m);
}

/* ---- tasks: our numbers live in the TCB (uxTaskGetTaskNumber) */
struct task_rec {
    void *tcb;
    char name[16];
    uint8_t prio, base, state, used;
    uint32_t stack_size;
    uint64_t run_ticks, run_from;
};
static struct task_rec tasks[SCOPE_MAX_TASKS];
static uint8_t ntasks;
static volatile uint8_t names_dirty = 1, objs_dirty = 1;

static uint8_t task_id(void *tcb)
{
    if (!tcb)
        return SCOPE_NONE;
    UBaseType_t n = uxTaskGetTaskNumber((TaskHandle_t)tcb);
    if (n == SCOPE_IDLE)
        return SCOPE_IDLE;
    return n >= 1 && n <= ntasks ? (uint8_t)(n - 1) : SCOPE_NONE;
}

void scope_rtos_task_create(void *tcb, const char *name, unsigned prio, void *stack_lo, void *stack_hi)
{
    if (strncmp(name, configIDLE_TASK_NAME, sizeof configIDLE_TASK_NAME - 1) == 0) {
        vTaskSetTaskNumber((TaskHandle_t)tcb, SCOPE_IDLE);     /* the viewer's idle */
        return;
    }
    if (ntasks >= SCOPE_MAX_TASKS)
        return;
    struct task_rec *t = &tasks[ntasks++];
    t->tcb = tcb;
    strncpy(t->name, name, sizeof t->name);
    t->prio = t->base = (uint8_t)prio;
    t->state = SCOPE_ST_READY;
    t->used = 1;
    if (stack_hi && stack_hi > stack_lo)
        t->stack_size = (uint32_t)((char *)stack_hi - (char *)stack_lo) + sizeof(StackType_t);
    vTaskSetTaskNumber((TaskHandle_t)tcb, ntasks);     /* id + 1: 0 = not ours */
    names_dirty = 1;                /* ready: FreeRTOS adds it to a ready list next (scope_rtos_ready) */
}

void scope_rtos_task_delete(void *tcb)
{
    uint8_t id = task_id(tcb);
    if (id < ntasks)
        tasks[id].state = SCOPE_ST_EXITED;
}

/* why the task that runs now is about to stop: set by the blocking hooks,
 * used when it is switched out (per CPU) */
static struct { uint8_t task, state, kind, obj; } pending[configNUMBER_OF_CORES];
static uint8_t out_task[configNUMBER_OF_CORES];

static uint8_t obj_id(void *obj, int is_evgroup);

void scope_rtos_block(unsigned state, void *object, int is_evgroup)
{
    uint8_t c = SCOPE_CPU(), o = object ? obj_id(object, is_evgroup) : SCOPE_NONE;
    pending[c].task = task_id(xTaskGetCurrentTaskHandle());
    pending[c].state = (uint8_t)state;
    pending[c].kind = o == SCOPE_NONE ? SCOPE_BLK_NONE : SCOPE_BLK_OBJECT;
    pending[c].obj = o == SCOPE_NONE ? 0 : o;
}

void scope_rtos_suspend(void *tcb)
{
    uint8_t c = SCOPE_CPU(), id = task_id(tcb);
    if (tcb == (void *)xTaskGetCurrentTaskHandle()) {
        pending[c].task = id;
        pending[c].state = SCOPE_ST_STOPPED;
        pending[c].kind = SCOPE_BLK_NONE;
    } else if (id < ntasks) {
        tasks[id].state = SCOPE_ST_STOPPED;
    }
}

void scope_rtos_switched_out(void *tcb)
{
    out_task[SCOPE_CPU()] = task_id(tcb);
}

void scope_rtos_switched_in(void *tcb)
{
    uint8_t c = SCOPE_CPU(), from = out_task[c], to = task_id(tcb);
    uint32_t arg = SCOPE_ST_READY;      /* preempted, unless it said why it stops */
    if (from < ntasks && tasks[from].state == SCOPE_ST_EXITED)
        arg = SCOPE_ST_EXITED;
    else if (from != SCOPE_NONE && pending[c].task == from)
        arg = pending[c].state | (uint32_t)pending[c].kind << 8 | (uint32_t)pending[c].obj << 16;
    pending[c].task = SCOPE_NONE;
    if (from == to)
        return;                         /* the scheduler kept it */
    uint64_t now = scope_port_time();
    if (from < ntasks) {
        tasks[from].run_ticks += now - tasks[from].run_from;
        if (tasks[from].state != SCOPE_ST_EXITED)
            tasks[from].state = (uint8_t)(arg & 0xFF);
    }
    if (to < ntasks) {
        tasks[to].run_from = now;
        tasks[to].state = SCOPE_ST_RUNNING;
    }
    put(TEV_SWITCH, from, to, arg);
    out_task[c] = to;
}

void scope_rtos_ready(void *tcb)
{
    uint8_t id = task_id(tcb);
    if (id < ntasks && tasks[id].state != SCOPE_ST_RUNNING)
        tasks[id].state = SCOPE_ST_READY;
    put(TEV_WAKE, id, 0, 0);
}

void scope_rtos_prio(void *tcb, unsigned new_prio, unsigned old_prio, int base_too)
{
    uint8_t id = task_id(tcb);
    if (id < ntasks) {
        old_prio = tasks[id].prio;      /* FreeRTOS 11 calls the inherit hook after the change */
        tasks[id].prio = (uint8_t)new_prio;
        if (base_too)
            tasks[id].base = (uint8_t)new_prio;
    }
    if (new_prio != old_prio)
        put(TEV_PRIO, id, (uint8_t)new_prio, old_prio);
}

void scope_rtos_timeout(void)
{
    put(TEV_TIMEOUT, task_id(xTaskGetCurrentTaskHandle()), 0, 0);
}

/* ---- objects: queues (and the semaphores and mutexes made of them), event groups */
struct obj_rec {
    void *handle;
    char name[16];
    uint8_t kind;
};
static struct obj_rec objs[SCOPE_MAX_OBJECTS];
static uint8_t nobjs;

static uint8_t new_obj(void *handle, uint8_t kind, int is_evgroup)
{
    if (nobjs >= SCOPE_MAX_OBJECTS)
        return SCOPE_NONE;
    struct obj_rec *o = &objs[nobjs++];
    o->handle = handle;
    o->kind = kind;
    static const char *const pre[] = { "ev", "mtx", "sem", "q", "grp" };
    /* a default name until it is registered: kind and number */
    unsigned n = nobjs - 1, i = 0;
    for (const char *p = pre[kind]; *p && i < 12; p++)
        o->name[i++] = *p;
    if (n >= 10)
        o->name[i++] = (char)('0' + n / 10);
    o->name[i++] = (char)('0' + n % 10);
#if configUSE_TRACE_FACILITY == 1
    if (is_evgroup)
        vEventGroupSetNumber(handle, nobjs);
    else
        vQueueSetQueueNumber((QueueHandle_t)handle, nobjs);
#endif
    objs_dirty = 1;
    return (uint8_t)(nobjs - 1);
}

static uint8_t obj_id(void *obj, int is_evgroup)
{
    UBaseType_t n = is_evgroup ? uxEventGroupGetNumber(obj) : uxQueueGetQueueNumber((QueueHandle_t)obj);
    return n >= 1 && n <= nobjs ? (uint8_t)(n - 1) : SCOPE_NONE;
}

void scope_rtos_queue_create(void *queue)
{
    uint8_t kind;
    switch (ucQueueGetQueueType((QueueHandle_t)queue)) {
    case queueQUEUE_TYPE_MUTEX:
    case queueQUEUE_TYPE_RECURSIVE_MUTEX:   kind = SCOPE_OBJ_MUTEX; break;
    case queueQUEUE_TYPE_COUNTING_SEMAPHORE:
    case queueQUEUE_TYPE_BINARY_SEMAPHORE:  kind = SCOPE_OBJ_SEMAPHORE; break;
    default:                                kind = SCOPE_OBJ_QUEUE; break;
    }
    new_obj(queue, kind, 0);
}

static void name_obj(uint8_t id, const char *name)
{
    if (id == SCOPE_NONE || !name)
        return;
    memset(objs[id].name, 0, sizeof objs[id].name);
    strncpy(objs[id].name, name, sizeof objs[id].name);
    objs_dirty = 1;
}

void scope_rtos_queue_name(void *queue, const char *name) { name_obj(obj_id(queue, 0), name); }

void scope_name_object(void *handle, const char *name)
{
    uint8_t id = obj_id(handle, 0);
    for (uint8_t i = 0; i < nobjs && id == SCOPE_NONE; i++)
        if (objs[i].handle == handle)
            id = i;
    name_obj(id, name);
}

void scope_rtos_queue_send(void *queue, unsigned waiting_after, int from_isr)
{
    uint8_t o = obj_id(queue, 0);
    if (o == SCOPE_NONE)
        return;
    uint8_t who = from_isr ? SCOPE_NONE : task_id(xTaskGetCurrentTaskHandle());
    put(TEV_SIGNAL, who, o, objs[o].kind == SCOPE_OBJ_MUTEX ? 0 : waiting_after);
}

void scope_rtos_queue_receive(void *queue, unsigned waiting_after, int from_isr)
{
    uint8_t o = obj_id(queue, 0);
    if (o == SCOPE_NONE)
        return;
    uint8_t who = from_isr ? SCOPE_NONE : task_id(xTaskGetCurrentTaskHandle());
    put(TEV_TAKE, who, o, objs[o].kind == SCOPE_OBJ_MUTEX ? 0 : waiting_after);
}

void scope_rtos_evgroup_create(void *group) { new_obj(group, SCOPE_OBJ_EVGROUP, 1); }

void scope_rtos_evgroup_set(void *group, uint32_t bits, int from_isr)
{
    uint8_t o = obj_id(group, 1);
    if (o != SCOPE_NONE)
        put(TEV_SIGNAL, from_isr ? SCOPE_NONE : task_id(xTaskGetCurrentTaskHandle()), o, bits);
}

void scope_rtos_evgroup_got(void *group, uint32_t bits)
{
    uint8_t o = obj_id(group, 1);
    if (o != SCOPE_NONE)
        put(TEV_TAKE, task_id(xTaskGetCurrentTaskHandle()), o, bits);
}

void scope_rtos_heap(int op, void *addr, unsigned size)
{
    if (!addr)
        return;
    uint8_t who = xTaskGetSchedulerState() == taskSCHEDULER_NOT_STARTED ? SCOPE_NONE
                  : task_id(xTaskGetCurrentTaskHandle());
    put(TEV_HEAP, who, (uint8_t)op, size);
    put(TEV_HEAP, who, (uint8_t)op | HEAP_ADDR, (uint32_t)(uintptr_t)addr);
}

/* ---- interrupts and user events */
static struct { uint16_t id; char name[14]; } irqs[SCOPE_MAX_IRQS];
static uint8_t nirqs;

static uint8_t running_task(void)
{
    return out_task[SCOPE_CPU()];
}

void scope_isr_begin(uint8_t isr) { put(TEV_IRQ, running_task(), 0, isr); }
void scope_isr_end(uint8_t isr) { put(TEV_IRQ_END, running_task(), 0, isr); }

void scope_isr_name(uint8_t isr, const char *name)
{
    if (nirqs >= SCOPE_MAX_IRQS)
        return;
    irqs[nirqs].id = isr;
    strncpy(irqs[nirqs].name, name, sizeof irqs[nirqs].name);
    nirqs++;
    objs_dirty = 1;
}

void scope_user(uint8_t channel, uint32_t value)
{
    put(TEV_USER, task_id(xTaskGetCurrentTaskHandle()), channel, value);
}

static void text(uint8_t flags, const char *s)
{
    uint8_t who = task_id(xTaskGetCurrentTaskHandle());
    size_t n = strlen(s);
    for (size_t off = 0; off <= n; off += 4) {      /* the 0 byte too: the end */
        uint32_t w = 0;
        for (size_t k = 0; k < 4 && off + k <= n; k++)
            w |= (uint32_t)(uint8_t)s[off + k] << (8 * k);
        put(TEV_USTR, who, (uint8_t)(flags | (off ? 0 : TSTR_FIRST)), w);
    }
}

void scope_print(uint8_t channel, const char *s) { text(channel & 0x3F, s); }
void scope_state(uint8_t machine, const char *state) { text((machine & 0x3F) | TSTR_STATE, state); }

void scope_printf(uint8_t channel, const char *fmt, ...)
{
    char buf[128];
    unsigned w = 0;
    va_list ap;
    va_start(ap, fmt);
    for (const char *p = fmt; *p && w < sizeof buf - 12; p++) {     /* %d %u %x %s %c %% */
        if (*p != '%' || !p[1]) {
            buf[w++] = *p;
            continue;
        }
        char c = *++p, tmp[12];
        if (c == 's') {
            for (const char *q = va_arg(ap, const char *); q && *q && w < sizeof buf - 1; q++)
                buf[w++] = *q;
        } else if (c == 'c') {
            buf[w++] = (char)va_arg(ap, int);
        } else if (c == 'd' || c == 'u' || c == 'x') {
            long v = c == 'd' ? va_arg(ap, int) : (long)va_arg(ap, unsigned);
            unsigned long u = v < 0 ? (unsigned long)-v : (unsigned long)v;
            int k = 0;
            do {
                unsigned d = (unsigned)(u % (c == 'x' ? 16 : 10));
                tmp[k++] = (char)(d < 10 ? '0' + d : 'a' + d - 10);
                u /= c == 'x' ? 16 : 10;
            } while (u && k < 11);
            if (v < 0)
                buf[w++] = '-';
            while (k)
                buf[w++] = tmp[--k];
        } else {
            buf[w++] = c;
        }
    }
    va_end(ap);
    buf[w] = 0;
    text(channel & 0x3F, buf);
}

uint32_t scope_lost(void) { return r_lost; }

/* ---- the streaming task */
static uint8_t frame[24 + BATCH * SCOPE_EV_MAX + 256];
static uint8_t wire[sizeof frame + sizeof frame / 254 + 4];
static struct scope_ev batch[BATCH];
static uint32_t send_us;                /* time spent writing (the 'S' frames report it) */
static uint64_t t_start;                /* scope_init: uptime is counted from here */

static void send(const uint8_t *f, unsigned n)
{
    uint64_t t0 = scope_port_time();
    scope_port_write(wire, scope_wire(f, n, wire));
    send_us += (uint32_t)((scope_port_time() - t0) * 1000000u / scope_port_hz());
}

static void send_hello(int repeat)
{
    memset(frame, 0, 16 + SCOPE_MAX_TASKS * 20);
    frame[0] = 'H';
    frame[1] = SCOPE_VERSION;
    frame[2] = configNUMBER_OF_CORES;
    frame[3] = ntasks;
    frame[4] = (uint8_t)repeat;
    frame[5] = SCOPE_OS_FREERTOS;
    scope_put64(frame + 8, scope_port_hz());
    for (uint8_t i = 0; i < ntasks; i++) {
        uint8_t *t = frame + 16 + i * 20;
        t[0] = i;
        t[1] = tasks[i].base;
        memcpy(t + 4, tasks[i].name, 16);
    }
    send(frame, 16 + ntasks * 20u);
}

static void send_objects(void)
{
    unsigned n = 4 + (nobjs + nirqs) * 16u + nobjs;
    memset(frame, 0, n);
    frame[0] = 'O';
    frame[1] = 0;                       /* no endpoints in FreeRTOS */
    frame[2] = nobjs;
    frame[3] = nirqs;
    for (uint8_t i = 0; i < nobjs; i++)
        memcpy(frame + 4 + i * 16, objs[i].name, 16);
    for (uint8_t i = 0; i < nirqs; i++) {
        uint8_t *p = frame + 4 + (nobjs + i) * 16;
        scope_put16(p, irqs[i].id);
        memcpy(p + 2, irqs[i].name, 14);
    }
    for (uint8_t i = 0; i < nobjs; i++)
        frame[4 + (nobjs + nirqs) * 16 + i] = objs[i].kind;
    send(frame, n);
}

static void send_stats(void)
{
    uint64_t now = scope_port_time(), hz = scope_port_hz();
    memset(frame, 0, 16);
    frame[0] = 'S';
    scope_put64(frame + 1, (now - t_start) * 1000000u / hz);
    frame[9] = ntasks;
    frame[10] = sizeof(struct scope_task);
    scope_put32(frame + 12, send_us);
    for (uint8_t i = 0; i < ntasks; i++) {
        struct task_rec *t = &tasks[i];
        uint64_t run = t->run_ticks + (t->state == SCOPE_ST_RUNNING ? now - t->run_from : 0);
        struct scope_task st = { i, t->state, t->prio, t->base, 0, run * 1000000u / hz, 0, t->stack_size, 0 };
#if INCLUDE_uxTaskGetStackHighWaterMark == 1
        if (t->stack_size && t->state != SCOPE_ST_EXITED) {
            uint32_t free_b = (uint32_t)uxTaskGetStackHighWaterMark((TaskHandle_t)t->tcb) * sizeof(StackType_t);
            st.stack_used = free_b < t->stack_size ? t->stack_size - free_b : 0;
        }
#endif
        memcpy(frame + 16 + i * sizeof st, &st, sizeof st);
    }
    send(frame, 16 + ntasks * (unsigned)sizeof(struct scope_task));
}

static void scope_task(void *arg)
{
    (void)arg;
    uint64_t seq = 0;
    uint32_t lost_sent = 0;
    unsigned tick = 0;
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        if (names_dirty || tick % (1000 / SCOPE_PERIOD_MS) == 0) {
            int repeat = !names_dirty || seq;
            names_dirty = 0;
            send_hello(repeat);
        }
        if (objs_dirty || tick % (1000 / SCOPE_PERIOD_MS) == 0) {
            objs_dirty = 0;
            send_objects();
        }
        for (;;) {
            uint32_t h = r_head, t = r_tail, n = h - t;
            if (!n)
                break;
            if (n > BATCH)
                n = BATCH;
            for (uint32_t i = 0; i < n; i++)
                batch[i] = ring[(t + i) & (SCOPE_RING_EVENTS - 1)];
            r_tail = t + n;             /* the consumer's only write */
            uint32_t lost = r_lost;
            send(frame, scope_frame_events(frame, seq + (lost - lost_sent), batch, n, lost - lost_sent));
            seq += n + (lost - lost_sent);
            lost_sent = lost;
        }
        if (++tick % (100 / SCOPE_PERIOD_MS) == 0)
            send_stats();
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(SCOPE_PERIOD_MS));
    }
}

void scope_init(void)
{
    t_start = scope_port_time();
    for (int c = 0; c < configNUMBER_OF_CORES; c++) {
        pending[c].task = SCOPE_NONE;
        out_task[c] = SCOPE_NONE;
    }
    xTaskCreate(scope_task, "tracer", SCOPE_TASK_STACK, NULL, SCOPE_TASK_PRIO, NULL);
}
