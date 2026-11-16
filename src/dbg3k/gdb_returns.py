"""Loaded inside GDB's Python interpreter, never imported by the frontend.

Observe returns only from debug-visible frames encountered at actual stops.
Internal finish breakpoints report structured evidence and automatically resume;
they do not execute target functions or guess values from registers.
"""
import json
import gdb

PREFIX = '__dbg3k_return_v1__'


class ReturnProbe(gdb.FinishBreakpoint):
    def __init__(self, observer, key, frame, caller, callee, display, thread):
        super().__init__(frame, internal=True)
        self.silent = True
        self.observer, self.key = observer, key
        self.caller, self.callee, self.display, self.thread_id = caller, callee, display, thread

    def stop(self):
        self.observer.probes.pop(self.key, None)
        try:
            value = self.return_value
            value = str(value) if value is not None else None
        except (gdb.error, RuntimeError):
            value = None
        record = dict(schema='dbg3k.gdb-return.v1', caller=self.caller,
                      callee=self.callee, callee_display=self.display,
                      thread=self.thread_id,
                      value=value)
        gdb.write(PREFIX + json.dumps(record, separators=(',', ':')) + '\n')
        return False

    def out_of_scope(self):
        # Unwinding/cancellation is not evidence of a normal return value.
        self.observer.probes.pop(self.key, None)


class ReturnObserver:
    def __init__(self):
        self.probes = {}
        gdb.events.stop.connect(self.on_stop)
        gdb.events.exited.connect(self.on_exit)

    def on_exit(self, event):
        self.clear()

    def clear(self):
        for probe in list(self.probes.values()):
            if probe.is_valid():
                probe.delete()
        self.probes.clear()

    def close(self):
        gdb.events.stop.disconnect(self.on_stop)
        gdb.events.exited.disconnect(self.on_exit)
        self.clear()

    def on_stop(self, event=None):
        try:
            frame = gdb.newest_frame()
            thread = gdb.selected_thread()
            if not frame or not thread or frame.type() != gdb.NORMAL_FRAME:
                return
            caller = frame.older()
            if not caller or not frame.name() or not caller.name():
                return
            # A caller's stack address and return PC distinguish recursive
            # activations without treating the callee's changing SP as identity.
            key = (thread.global_num, int(caller.read_register('sp')),
                   caller.pc(), frame.name())
            if key in self.probes or len(self.probes) >= 128:
                return
            symbol = frame.function()
            if symbol is None or symbol.symtab is None:
                return
            args = []
            block = frame.block()
            while block and block.function is None:
                block = block.superblock
            if block:
                for arg in block:
                    if arg.is_argument:
                        try:
                            value = str(frame.read_var(arg)).replace('\n', ' ')
                        except gdb.error:
                            value = '?'
                        args.append(value if len(value) <= 28 else value[:25] + '…')
                        if len(args) == 5:
                            break
            display = frame.name() + '(' + ', '.join(args) + ')'
            self.probes[key] = ReturnProbe(self, key, frame, caller.name(),
                                          frame.name(), display, str(thread.global_num))
        except (gdb.error, RuntimeError, ValueError):
            # Startup, inline/optimized frames and unwinding may be unsupported.
            # The ordinary MI finish path remains available.
            return


if '_dbg3k_return_observer' in globals():
    _dbg3k_return_observer.close()
_dbg3k_return_observer = ReturnObserver()
_dbg3k_return_observer.on_stop()
