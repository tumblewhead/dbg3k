"""Formatting of observed resources; all unavailable values remain explicit."""
from .resources import CodeCatalog, EnergyModel, InstructionProfile, StackProfile


def resource_text(stack: StackProfile, catalog: CodeCatalog | None,
                  counts: InstructionProfile, level: int, stop: int,
                  energy: EnergyModel | None, count_status: str) -> tuple[str, str, str]:
    sample = stack.sample
    frames = sample['frames'] if sample and sample['stop'] == stop else []
    selected = next((f for f in frames if f['level'] == level), None)
    function = catalog.lookup(selected['pc']) if catalog and selected else None
    title = f'{selected["function"]} · frame #{level} · stop {stop}' if selected else 'No current stack sample'
    stack_lines = [title]
    if sample and frames:
        registers = sample['registers']
        stack_lines.append(f'Visible frames: {len(frames)} · thread {sample["thread"]}'
                           + (' · capped at 128' if sample.get('truncated') else ''))
        if function:
            instances = sum(f['kind'] == 'normal' and catalog.lookup(f['pc']) == function for f in frames)
        else:
            instances = sum(f['function'] == selected['function'] for f in frames) if selected else 0
        stack_lines.append(f'Selected function: {instances} active frame(s) (normal only)')
        for name in ('sp', 'msp', 'psp'):
            value = registers.get(name)
            stack_lines.append(f'{name.upper()}: {"unavailable" if value is None else f"0x{value:08x}"}')
        if selected:
            index = frames.index(selected)
            stack_lines.append(f'Younger visible frames: {index}')
            sp = selected['sp']
            stack_lines.append(f'Selected frame SP: {"unavailable" if sp is None else f"0x{sp:08x}"}')
            own = StackProfile.own_bytes(frames, index)
            inclusive = StackProfile.inclusive_bytes(frames, index)
            key = (sample['thread'], function.key if function else selected['function'])
            peaks = stack.peaks.get(key, [None, None])
            fmt = lambda v: 'unavailable' if v is None else f'~{v} B'
            stack_lines += [f'Own frame estimate: {fmt(own)}',
                            f'Including active callees: {fmt(inclusive)}',
                            f'Sampled peaks own/incl: {fmt(peaks[0])} / {fmt(peaks[1])}']
        stack_lines.append('SP deltas are estimates; peaks are sampled, not bounds.')
        for index, frame in enumerate(frames):
            size = StackProfile.own_bytes(frames, index)
            stack_lines.append(f'#{frame["level"]} {frame["function"]} · {"?" if size is None else f"~{size} B"}')
    else:
        stack_lines.append('Waiting for a halted GDB register/frame snapshot.')

    code_lines = [title]
    if function:
        code_lines += [f'Containing ELF body: {function.names[0]}',
                       f'ELF code bytes: {function.size} B · {function.section}',
                       f'Body: 0x{function.start:x} · aliases: {len(function.names)}']
    else:
        code_lines.append('ELF code bytes: unavailable (no unique sized function symbol)')
    valid_counts = counts.run is not None and not count_status
    measured = counts.by_function.get(function.key, 0) if valid_counts and function else None
    code_lines += [f'Exclusive guest dispatches: {measured if measured is not None else "unavailable"}',
                   f'All-code dispatches: {counts.total if valid_counts else "unavailable"}',
                   f'Unknown/ambiguous PC dispatches: {counts.unknown if valid_counts else "unavailable"}']
    if valid_counts:
        share = f'{100 * measured / counts.total:.2f}%' if measured is not None and counts.total else 'unavailable'
        code_lines += [f'Share of all-code dispatches: {share}',
                       f'Window: QEMU run {counts.run[:8]} · since launch',
                       'Final snapshot' if counts.complete else 'Periodic snapshot (~100 ms; not stop-synchronized)']
    elif count_status:
        code_lines.append(count_status)
    code_lines.append('Dispatches are not retired instructions or silicon cycles. Inclusive counts unavailable.')

    energy_lines = [title, 'Active-core energy ESTIMATE · exclusive work only']
    if energy is None:
        energy_lines.append('Configure assumptions in palette → Energy model.')
    else:
        energy_lines += [f'Current slope: {energy.ua_per_mhz:g} µA/MHz',
                         f'Throughput: {energy.mips_per_mhz:g} MIPS/MHz',
                         f'Voltage: {energy.voltage:g} V',
                         f'Charge/instruction: {energy.charge_pc(1):g} pC']
        if measured is not None:
            energy_lines += [f'Estimated charge: {energy.charge_pc(measured):g} pC',
                             f'Estimated energy: {energy.energy_pj(measured):g} pJ']
        else:
            energy_lines.append('Energy unavailable until matching ELF/count data exists.')
    energy_lines += ['Average power: unavailable (target duration needed).',
                     'User assumptions; excludes idle, leakage, peripherals and memory effects.']
    return ('\n'.join(stack_lines), '\n'.join(code_lines), '\n'.join(energy_lines))
