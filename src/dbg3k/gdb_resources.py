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
    gdb.write('__dbg3k_stack_v1__' + json.dumps(dict(
        schema='dbg3k.stack.v1', stop=stop, thread=str(thread.global_num),
        registers=registers, frames=frames, truncated=frame is not None), separators=(',', ':')) + '\n')
