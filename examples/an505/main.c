#include <stdint.h>
static volatile uint32_t total;

static void print(const char *message)
{
    register uint32_t r0 __asm("r0") = 0x04;
    register const char *r1 __asm("r1") = message;
    __asm volatile("bkpt 0xab" : "+r"(r0) : "r"(r1) : "memory");
}

__attribute__((noinline)) static int bar(int n)
{
    int result = n * 3;
    total += (uint32_t)result;
    return result;
}

__attribute__((noinline)) static int foo(int n)
{
    int result = n + 2;
    result += bar(result);
    return result;
}

int main(void)
{
    print("dbg3k AN505 example ready\n");
    for (int n = 0; n < 20; n++) {
        int value = foo(n);
        total += (uint32_t)value;
    }
    print("example finished\n");
    return 0;
}
