/* The little of libc FreeRTOS and the recorder use (freestanding build). */
#include <stddef.h>
#include <stdint.h>

void *memset(void *d, int c, size_t n)
{
    unsigned char *p = d;
    while (n--)
        *p++ = (unsigned char)c;
    return d;
}

void *memcpy(void *d, const void *s, size_t n)
{
    unsigned char *p = d;
    const unsigned char *q = s;
    while (n--)
        *p++ = *q++;
    return d;
}

void *memmove(void *d, const void *s, size_t n)
{
    unsigned char *p = d;
    const unsigned char *q = s;
    if (p < q)
        while (n--)
            *p++ = *q++;
    else
        while (n--)
            p[n] = q[n];
    return d;
}

int memcmp(const void *a, const void *b, size_t n)
{
    const unsigned char *p = a, *q = b;
    for (; n; n--, p++, q++)
        if (*p != *q)
            return *p - *q;
    return 0;
}

size_t strlen(const char *s)
{
    size_t n = 0;
    while (s[n])
        n++;
    return n;
}

int strncmp(const char *a, const char *b, size_t n)
{
    for (; n; n--, a++, b++)
        if (*a != *b || !*a)
            return (unsigned char)*a - (unsigned char)*b;
    return 0;
}

char *strncpy(char *d, const char *s, size_t n)
{
    size_t i = 0;
    for (; i < n && s[i]; i++)
        d[i] = s[i];
    for (; i < n; i++)
        d[i] = 0;
    return d;
}

/* EABI helpers clang calls for these */
void __aeabi_memcpy(void *d, const void *s, size_t n) { memcpy(d, s, n); }
void __aeabi_memcpy4(void *d, const void *s, size_t n) __attribute__((alias("__aeabi_memcpy")));
void __aeabi_memcpy8(void *d, const void *s, size_t n) __attribute__((alias("__aeabi_memcpy")));
void __aeabi_memset(void *d, size_t n, int c) { memset(d, c, n); }
void __aeabi_memclr(void *d, size_t n) { memset(d, 0, n); }
void __aeabi_memclr4(void *d, size_t n) __attribute__((alias("__aeabi_memclr")));
void __aeabi_memclr8(void *d, size_t n) __attribute__((alias("__aeabi_memclr")));

/* 64-bit unsigned division (the recorder's statistics) */
uint64_t __udivmoddi4(uint64_t n, uint64_t d, uint64_t *rem)
{
    uint64_t q = 0, r = 0;
    for (int i = 63; i >= 0; i--) {
        r = r << 1 | ((n >> i) & 1);
        if (r >= d) {
            r -= d;
            q |= 1ULL << i;
        }
    }
    if (rem)
        *rem = r;
    return q;
}

/* r0:r1 / r2:r3 -> quotient r0:r1, remainder r2:r3 */
__attribute__((naked)) void __aeabi_uldivmod(void)
{
    __asm volatile("push {r4, lr}\n"
                   "sub sp, sp, #16\n"
                   "add r4, sp, #8\n"
                   "str r4, [sp]\n"
                   "bl __udivmoddi4\n"
                   "ldr r2, [sp, #8]\n"
                   "ldr r3, [sp, #12]\n"
                   "add sp, sp, #16\n"
                   "pop {r4, pc}\n");
}
