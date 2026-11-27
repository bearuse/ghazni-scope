/* Ghazni Scope: compact event encoding and COBS framing (docs/PROTOCOL.md).
 * Header only, freestanding (no libc). MIT License - see LICENSE. */
#ifndef SCOPE_ENCODE_H
#define SCOPE_ENCODE_H

#include <stdint.h>
#include "scope_proto.h"

/* worst case bytes for one compact event: varint delta 10, type 2, a, b, varint arg 5 */
#define SCOPE_EV_MAX 19

static inline unsigned scope_varint(uint8_t *p, uint64_t v)
{
    unsigned n = 0;
    do {
        p[n++] = (uint8_t)((v & 0x7F) | (v > 0x7F ? 0x80 : 0));
        v >>= 7;
    } while (v);
    return n;
}

static inline void scope_put16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static inline void scope_put32(uint8_t *p, uint32_t v)
{
    for (int i = 0; i < 4; i++)
        p[i] = (uint8_t)(v >> (8 * i));
}
static inline void scope_put64(uint8_t *p, uint64_t v)
{
    for (int i = 0; i < 8; i++)
        p[i] = (uint8_t)(v >> (8 * i));
}

/* n events -> compact form after a 'D' header; returns the bytes written */
static inline unsigned scope_encode_events(uint8_t *p, const struct scope_ev *e, unsigned n, uint64_t base)
{
    unsigned w = 0;
    uint64_t prev = base;
    for (unsigned i = 0; i < n; i++) {
        int64_t d = (int64_t)(e[i].tick - prev);
        prev = e[i].tick;
        w += scope_varint(p + w, ((uint64_t)d << 1) ^ (uint64_t)(d >> 63));   /* zigzag */
        if (e[i].type > 15) {           /* v3: escaped type */
            p[w++] = (uint8_t)(e[i].cpu << 4);
            p[w++] = e[i].type;
        } else {
            p[w++] = (uint8_t)((e[i].type & 0x0F) | e[i].cpu << 4);
        }
        p[w++] = e[i].a;
        if (scope_has_b(e[i].type))
            p[w++] = e[i].b;
        if (scope_has_arg(e[i].type))
            w += scope_varint(p + w, e[i].arg);
    }
    return w;
}

/* 'D' frame: header + events; returns the frame length (buf: 24 + n * SCOPE_EV_MAX) */
static inline unsigned scope_frame_events(uint8_t *buf, uint64_t first, const struct scope_ev *e,
                                          unsigned n, uint32_t lost)
{
    for (int i = 0; i < 24; i++)
        buf[i] = 0;
    buf[0] = 'D';
    scope_put64(buf + 1, first);
    scope_put16(buf + 9, (uint16_t)n);
    scope_put32(buf + 12, lost);
    scope_put64(buf + 16, n ? e[0].tick : 0);
    return 24 + scope_encode_events(buf + 24, e, n, n ? e[0].tick : 0);
}

/* COBS: no 0x00 in the output (so 0x00 can end the frame). out: n + n/254 + 1 bytes */
static inline unsigned scope_cobs(const uint8_t *in, unsigned n, uint8_t *o)
{
    unsigned code_at = 0, w = 1;
    uint8_t code = 1;
    for (unsigned i = 0; i < n; i++) {
        if (in[i] == 0) {
            o[code_at] = code;
            code_at = w++;
            code = 1;
        } else {
            o[w++] = in[i];
            if (++code == 0xFF) {
                o[code_at] = code;
                code_at = w++;
                code = 1;
            }
        }
    }
    o[code_at] = code;
    return w;
}

/* a whole wire frame: SOF, COBS(frame), EOF. out: n + n/254 + 3 bytes */
static inline unsigned scope_wire(const uint8_t *frame, unsigned n, uint8_t *out)
{
    out[0] = SCOPE_SOF;
    unsigned m = scope_cobs(frame, n, out + 1);
    out[m + 1] = SCOPE_EOF;
    return m + 2;
}

#endif
