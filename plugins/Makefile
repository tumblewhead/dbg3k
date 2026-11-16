CC ?= cc
QEMU_INCLUDE ?= /usr/include
CFLAGS ?= -O2 -g
all: libdbg3k-counts.so
libdbg3k-counts.so: counts.c
	$(CC) $(CFLAGS) -std=c11 -Wall -Wextra -Werror -fPIC -fvisibility=hidden -shared -I$(QEMU_INCLUDE) $(shell pkg-config --cflags glib-2.0) $< -o $@ $(shell pkg-config --libs glib-2.0)
.PHONY: all
