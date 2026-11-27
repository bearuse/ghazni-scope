/* Writes wire frames made by include/scope_encode.h to stdout, for
 * tests/test_host.py: every event type, large deltas and arguments, a
 * frame long enough for COBS's 254-byte blocks. */
#include <stdio.h>
#include "scope_encode.h"

int main(void)
{
    static struct scope_ev ev[300];
    static uint8_t frame[24 + 300 * SCOPE_EV_MAX], wire[sizeof frame + sizeof frame / 254 + 3];
    unsigned n = 0;
    uint64_t t = 1000;
    for (unsigned type = 1; type <= 18; type++)
        ev[n++] = (struct scope_ev){t += type * 1000003ull, (uint8_t)type, (uint8_t)(type & 1),
                                    (uint8_t)type, (uint8_t)(0xF0 + type), 0xFFFFFFF0u - type};
    while (n < 300) {
        ev[n] = (struct scope_ev){t += n, TEV_SIGNAL, 0, (uint8_t)n, 3, n * 77};
        n++;
    }
    ev[5].tick = ev[4].tick - 5;            /* timestamps may go backwards across CPUs */
    unsigned len = scope_frame_events(frame, 42, ev, n, 7);
    fwrite(wire, 1, scope_wire(frame, len, wire), stdout);
    printf("text between frames\n");
    for (unsigned i = 0; i < n; i++)        /* the expected events, as text */
        printf("%llu %u %u %u %u %u\n", (unsigned long long)ev[i].tick, ev[i].type, ev[i].cpu, ev[i].a,
               scope_has_b(ev[i].type) ? ev[i].b : 0, scope_has_arg(ev[i].type) ? ev[i].arg : 0);
    return 0;
}
