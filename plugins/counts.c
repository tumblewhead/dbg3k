/* SPDX-License-Identifier: GPL-2.0-or-later
 * Single-vCPU guest instruction dispatch histogram. Translation never counts
 * as execution. Snapshots are atomic, cumulative, and identified by ELF SHA256.
 */
#include <glib.h>
#include <qemu-plugin.h>
#include <glib/gstdio.h>
#include <stdio.h>
#include <string.h>

QEMU_PLUGIN_EXPORT int qemu_plugin_version = QEMU_PLUGIN_VERSION;
typedef struct { uint64_t pc, count; } Counter;
static GHashTable *counters;
static GMutex lock;
static GThread *writer;
static gint done;
static char *output, *elf_hash, *run;
static uint64_t total, overflow, sequence;
#define MAX_PCS 262144

static void snapshot(bool complete)
{
    GString *json = g_string_new(NULL);
    g_mutex_lock(&lock);
    g_string_append_printf(json,
        "{\"schema\":\"dbg3k.qemu-counts.v1\",\"metric\":\"instruction-dispatch\","
        "\"elf_sha256\":\"%s\",\"run\":\"%s\",\"seq\":%" PRIu64 ","
        "\"complete\":%s,\"total\":%" PRIu64 ",\"overflow\":%" PRIu64 ",\"pcs\":[",
        elf_hash, run, ++sequence, complete ? "true" : "false", total, overflow);
    GHashTableIter iter;
    gpointer value;
    bool first = true;
    g_hash_table_iter_init(&iter, counters);
    while (g_hash_table_iter_next(&iter, NULL, &value)) {
        Counter *counter = value;
        if (!counter->count) { continue; }
        g_string_append_printf(json, "%s[\"0x%" PRIx64 "\",%" PRIu64 "]",
                               first ? "" : ",", counter->pc, counter->count);
        first = false;
    }
    g_mutex_unlock(&lock);
    g_string_append(json, "]}\n");
    char *temporary = g_strconcat(output, ".tmp", NULL);
    GError *error = NULL;
    if (!g_file_set_contents(temporary, json->str, json->len, &error) ||
        g_rename(temporary, output) != 0) {
        fprintf(stderr, "dbg3k counts snapshot failed: %s\n", error ? error->message : "rename");
        g_atomic_int_set(&done, 1); /* Avoid flooding stderr on an unwritable path. */
    }
    g_clear_error(&error);
    g_free(temporary);
    g_string_free(json, TRUE);
}

static gpointer write_periodically(gpointer unused)
{
    (void)unused;
    while (!g_atomic_int_get(&done)) {
        snapshot(false);
        g_usleep(100000);
    }
    return NULL;
}

static void execute(unsigned int cpu, void *userdata)
{
    (void)cpu;
    Counter *counter = userdata;
    g_mutex_lock(&lock);
    ++total;
    if (counter) { ++counter->count; } else { ++overflow; }
    g_mutex_unlock(&lock);
}

#if QEMU_PLUGIN_VERSION >= 7
static void translate(struct qemu_plugin_tb *tb, void *userdata)
#else
static void translate(qemu_plugin_id_t id, struct qemu_plugin_tb *tb)
#endif
{
#if QEMU_PLUGIN_VERSION >= 7
    (void)userdata;
#else
    (void)id;
#endif
    for (size_t i = 0; i < qemu_plugin_tb_n_insns(tb); ++i) {
        struct qemu_plugin_insn *insn = qemu_plugin_tb_get_insn(tb, i);
        uint64_t pc = qemu_plugin_insn_vaddr(insn);
        g_mutex_lock(&lock);
        Counter *counter = g_hash_table_lookup(counters, &pc);
        if (!counter && g_hash_table_size(counters) < MAX_PCS) {
            counter = g_new0(Counter, 1);
            counter->pc = pc;
            g_hash_table_insert(counters, &counter->pc, counter);
        }
        g_mutex_unlock(&lock);
        qemu_plugin_register_vcpu_insn_exec_cb(insn, execute, QEMU_PLUGIN_CB_NO_REGS, counter);
    }
}

#if QEMU_PLUGIN_VERSION >= 7
static void finish(void *userdata)
#else
static void finish(qemu_plugin_id_t id, void *userdata)
#endif
{
#if QEMU_PLUGIN_VERSION < 7
    (void)id;
#endif
    (void)userdata;
    g_atomic_int_set(&done, 1);
    g_thread_join(writer);
    snapshot(true);
    g_hash_table_destroy(counters);
    g_free(output); g_free(elf_hash); g_free(run);
}

QEMU_PLUGIN_EXPORT int qemu_plugin_install(qemu_plugin_id_t id, const qemu_info_t *info,
                                          int argc, char **argv)
{
    const char *elf = NULL;
    if (!info->system_emulation || info->system.max_vcpus != 1) {
        fprintf(stderr, "dbg3k counts requires single-vCPU system emulation\n");
        return -1;
    }
    for (int i = 0; i < argc; ++i) {
        if (g_str_has_prefix(argv[i], "out=")) { output = g_strdup(argv[i] + 4); }
        else if (g_str_has_prefix(argv[i], "elf=")) { elf = argv[i] + 4; }
        else { fprintf(stderr, "dbg3k counts: unknown option %s\n", argv[i]); return -1; }
    }
    char *bytes = NULL;
    gsize size;
    if (!output || !*output || !elf || !g_file_get_contents(elf, &bytes, &size, NULL)) {
        fprintf(stderr, "dbg3k counts requires out=PATH,elf=ELF\n");
        return -1;
    }
    elf_hash = g_compute_checksum_for_data(G_CHECKSUM_SHA256, (guchar *)bytes, size);
    g_free(bytes);
    run = g_uuid_string_random();
    counters = g_hash_table_new_full(g_int64_hash, g_int64_equal, NULL, g_free);
    writer = g_thread_new("dbg3k-counts", write_periodically, NULL);
#if QEMU_PLUGIN_VERSION >= 7
    qemu_plugin_register_vcpu_tb_trans_cb(id, translate, NULL);
#else
    qemu_plugin_register_vcpu_tb_trans_cb(id, translate);
#endif
    qemu_plugin_register_atexit_cb(id, finish, NULL);
    return 0;
}
