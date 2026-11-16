"""Loaded in GDB. Structured stop snapshots; reads registers, never runs target code."""
import gdb
import json


def dbg3k_stack_snapshot(stop):
    thread = gdb.selected_thread()
    if thread is None:
        return
    frame = gdb.newest_frame()
    registers = {}
    for name in ('sp', 'msp', 'psp', 'control', 'ipsr', 'xpsr'):
        try:
            registers[name] = int(frame.read_register(name))
        except (gdb.error, ValueError, TypeError):
            registers[name] = None
    if registers['ipsr'] is None and registers['xpsr'] is not None:
        registers['ipsr'] = registers['xpsr'] & 0x1ff
    frames = []
    while frame is not None and len(frames) < 128:
        try:
            sp = int(frame.read_register('sp'))
        except (gdb.error, ValueError, TypeError):
            sp = None
        kind = frame.type()
        frames.append(dict(level=frame.level(), function=frame.name() or '??', pc=frame.pc(), sp=sp,
                           kind='normal' if kind in (gdb.NORMAL_FRAME, gdb.SENTINEL_FRAME)
                           and registers['ipsr'] in (None, 0)
                           else 'inline' if kind == gdb.INLINE_FRAME else 'other'))
        try:
            frame = frame.older()
        except gdb.error:
            break
    memory, memory_error = None, None
    base = registers.get('sp')
    if (base is not None and frames and all(f['kind'] == 'normal' and f['sp'] is not None for f in frames)):
        # Only the sampled contiguous normal stack slice; never invent a stack
        # origin or read beyond its highest unwound SP. Bound target reads.
        top = max(f['sp'] for f in frames)
        length = min(256, max(0, top - base))
        if length:
            try:
                raw = gdb.selected_inferior().read_memory(base, length)
                memory = dict(start=base, hex=bytes(raw).hex())
            except gdb.error as exc:
                memory_error = str(exc)
    gdb.write('__dbg3k_stack_v1__' + json.dumps(dict(
        schema='dbg3k.stack.v1', stop=stop, thread=str(thread.global_num),
        registers=registers, frames=frames, truncated=frame is not None,
        memory=memory, memory_error=memory_error), separators=(',', ':')) + '\n')
