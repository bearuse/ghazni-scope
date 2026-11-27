/* SEGGER RTT compatible control block with one up-buffer, "Scope"
 * (scope_rtt.h). Layout as SEGGER documents it, so every RTT reader finds
 * it: the 16-byte ID "SEGGER RTT", the number of up and down buffers, then
 * per buffer: name, start, size, write offset, read offset, flags. The
 * target writes WrOff, the probe writes RdOff; one free byte tells full
 * from empty. MIT License - see LICENSE. */
#include "scope_rtt.h"

struct rtt_buf {
    const char *name;
    char *start;
    unsigned size;
    volatile unsigned wr;           /* target */
    volatile unsigned rd;           /* probe */
    unsigned flags;
};

struct rtt_cb {
    char id[16];
    int n_up, n_down;
    struct rtt_buf up[1], down[1];
};

static char scope_rtt_data[SCOPE_RTT_SIZE];
static char scope_rtt_none[1];

/* the symbol RTT readers look for */
struct rtt_cb _SEGGER_RTT __attribute__((used, aligned(4))) = {
    .id = { 0 },                    /* set last, at the first write: a reader never
                                       sees a half-made block */
    .n_up = 1, .n_down = 1,
    .up = { { "Scope", scope_rtt_data, SCOPE_RTT_SIZE, 0, 0, 0 } },
    .down = { { "None", scope_rtt_none, sizeof scope_rtt_none, 0, 0, 0 } },
};

static void scope_rtt_init(void)
{
    static const char id[] = "SEGGER RTT";
    volatile char *p = _SEGGER_RTT.id;
    for (unsigned i = 0; i < sizeof id; i++)        /* reversed, the ID's first byte last */
        p[sizeof id - 1 - i] = id[sizeof id - 1 - i];
}

unsigned scope_rtt_pending(void)
{
    struct rtt_buf *b = &_SEGGER_RTT.up[0];
    unsigned wr = b->wr, rd = b->rd;
    return wr >= rd ? wr - rd : b->size - rd + wr;
}

unsigned scope_rtt_write(const uint8_t *buf, unsigned n)
{
    if (_SEGGER_RTT.id[0] != 'S')
        scope_rtt_init();
    struct rtt_buf *b = &_SEGGER_RTT.up[0];
    unsigned wr = b->wr, free = b->size - 1 - scope_rtt_pending(), done = 0;
    if (n > free)
        n = free;
    while (done < n) {
        unsigned chunk = b->size - wr;              /* up to the end, then wrap */
        if (chunk > n - done)
            chunk = n - done;
        for (unsigned i = 0; i < chunk; i++)
            b->start[wr + i] = (char)buf[done + i];
        done += chunk;
        wr = (wr + chunk) % b->size;
    }
#if defined(__ARM_ARCH) && __ARM_ARCH >= 7
    __asm__ volatile("dmb" ::: "memory");           /* the data before the offset */
#else
    __asm__ volatile("" ::: "memory");
#endif
    b->wr = wr;
    return done;
}
