"""Incremental profile/energy replay with explicit build and session identity."""
import json
import os
from pathlib import Path

from .resources import EnergyModel, InstructionProfile


class JsonlTail:
    """Read only appended bytes, retaining incomplete lines until newline."""

    def __init__(self, path, *, offset=0):
        self.path = Path(path)
        self.offset = offset
        self.pending = b''
        self.identity = None
        self.anchor = None
        self.generation = 0
        self.skipped = 0
        self.backlog = 0

    def poll(self, budget=262144):
        with self.path.open('rb') as stream:
            info = os.fstat(stream.fileno())
            identity = (info.st_dev, info.st_ino)
            if ((self.identity is not None and identity != self.identity) or
                    info.st_size < self.offset):
                self.offset, self.pending = 0, b''
                self.anchor = None
                self.generation += 1
            elif self.anchor is not None:
                stream.seek(max(0, self.offset - len(self.anchor)))
                if stream.read(len(self.anchor)) != self.anchor:
                    self.offset, self.pending, self.anchor = 0, b'', None
                    self.generation += 1
            self.identity = identity
            stream.seek(self.offset)
            chunk = stream.read(budget)
            self.offset += len(chunk)
            self.backlog = max(0, info.st_size - self.offset)
            stream.seek(max(0, self.offset - 64))
            self.anchor = stream.read(min(64, self.offset))
        lines = (self.pending + chunk).split(b'\n')
        self.pending = lines.pop()
        records = []
        for line in lines:
            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
            except (ValueError, UnicodeError):
                self.skipped += 1
        return records


def recorded_model(record):
    values = tuple(record.get(key) for key in ('ua_per_mhz', 'mips_per_mhz', 'voltage'))
    if any(type(value) not in (int, float) for value in values):
        raise ValueError('Invalid recorded energy assumptions')
    return EnergyModel(*values)


class ProfileHistory:
    """Select one session, or follow the newest matching session with a profile.

    Old sessions writing late cannot supersede a newer session. Energy from one
    session never silently attaches to another session's profile during replay.
    """

    def __init__(self, catalog, *, session=None, profile=None):
        self.catalog = catalog
        self.requested_session = session
        self.profile = profile if profile is not None else InstructionProfile()
        self.selected_session = None
        self.energy_model = None
        self.energy_source = ''
        self._order = {}
        self._hashes = {}
        self._models = {}
        self._model_sources = {}
        self._sequences = {}

    def apply(self, record):
        if record.get('schema') != 'dbg3k.trace.v1' or record.get('kind') not in (
                'session_start', 'instruction_profile', 'energy_model'):
            return False
        session, sequence = record.get('session'), record.get('seq')
        if not isinstance(session, str) or not session or type(sequence) is not int:
            return False
        if self.requested_session is not None and session != self.requested_session:
            return False
        if sequence <= self._sequences.get(session, -1):
            return False
        self._order.setdefault(session, len(self._order))
        kind = record['kind']
        if kind == 'session_start':
            self._hashes[session] = record.get('elf_sha256')
        elif kind == 'energy_model':
            model = recorded_model(record)
            if record.get('elf_sha256') not in (None, self.catalog.sha256):
                if self.requested_session:
                    raise ValueError('Recorded energy model ELF hash mismatch')
                self._sequences[session] = sequence
                return False
            self._models[session] = model
            self._model_sources[session] = str(record.get('source', 'recorded assumptions'))[:256]
        else:
            if record.get('elf_sha256') != self.catalog.sha256:
                if self.requested_session:
                    raise ValueError('Requested JSONL session ELF hash mismatch')
                self._sequences[session] = sequence
                return False
            if self._hashes.get(session) not in (None, self.catalog.sha256):
                raise ValueError('JSONL session build hash conflicts with profile')
            if (self.selected_session is not None and
                    self._order[session] < self._order[self.selected_session]):
                self._sequences[session] = sequence
                return False
            if session != self.selected_session:
                # Validate before replacing the existing profile.
                replacement = InstructionProfile()
                replacement.update_record(record, self.catalog)
                self.profile.__dict__.update(replacement.__dict__)
            else:
                self.profile.update_record(record, self.catalog)
            self.selected_session = session
            self._hashes[session] = self.catalog.sha256
        self._sequences[session] = sequence
        if self.selected_session is not None:
            self.energy_model = self._models.get(self.selected_session)
            self.energy_source = (f'JSONL session {self.selected_session[:8]} · '
                                  + self._model_sources.get(self.selected_session, 'no recorded assumptions'))
        elif self.requested_session and self._hashes.get(session) == self.catalog.sha256:
            # A new live session may record its configured model before the
            # first instruction snapshot; its session-start build hash binds it.
            self.energy_model = self._models.get(session)
            self.energy_source = f'JSONL session {session[:8]} · ' + self._model_sources.get(session, '')
        return kind in ('instruction_profile', 'energy_model')


def recover_energy_model(directory, prefix, elf_sha256):
    """Recover the newest explicit model whose session proves this ELF hash."""
    paths = sorted(Path(directory).glob(prefix + '_*.jsonl'), reverse=True)
    for path in paths:
        hashes, models, conflicting = {}, {}, set()
        try:
            with path.open('rb') as stream:
                for index, line in enumerate(stream):
                    # Skip variable/frame records without decoding their values.
                    if not any(key in line for key in (b'"energy_model"', b'"instruction_profile"', b'"session_start"')):
                        continue
                    try:
                        record = json.loads(line)
                        if record.get('schema') != 'dbg3k.trace.v1':
                            continue
                        session = record['session']
                        if record.get('kind') in ('session_start', 'instruction_profile') and record.get('elf_sha256'):
                            if hashes.get(session) not in (None, record['elf_sha256']):
                                conflicting.add(session)
                            hashes[session] = record['elf_sha256']
                        if record.get('kind') == 'energy_model':
                            model = recorded_model(record)
                            if record.get('elf_sha256') in (None, elf_sha256):
                                models[session] = (index, model)
                    except (ValueError, KeyError, TypeError, AttributeError):
                        continue
        except OSError:
            continue
        candidates = [(index, model, session) for session, (index, model) in models.items()
                      if hashes.get(session) == elf_sha256 and session not in conflicting]
        if candidates:
            _, model, session = max(candidates, key=lambda item: item[0])
            return model, session
    return None
