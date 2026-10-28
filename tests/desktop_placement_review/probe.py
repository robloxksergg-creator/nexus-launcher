"""Review-stage diagnostic harness. Never an installer or an updater.

Preflight and state-changing cases deliberately fail closed.
Windows reading primitives are candidates pending filesystem integration review.
Importing this module and parsing arguments perform no filesystem operations.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile
import re
import struct
import time
from contextlib import contextmanager, ExitStack

MAX_ENTRIES = 2048
MAX_ENTRY = 512 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024
MAX_ZIP = 512 * 1024 * 1024
MAX_CENTRAL = 2 * 1024 * 1024
MAX_READ = 3 * 1024 * 1024 * 1024
MAX_DEPTH = 32
MAX_TREE_NODES = 4096  # includes directories and files, not only payload files
MAX_RELATIVE_UTF16 = 1024
MAX_DIR_BUFFER = 64 * 1024
MAX_DIR_RECORDS = 256
MAX_DIR_NAME_BYTES = 8192  # long and active short names together, per buffer
# Conservative attribute subset; not an exhaustive Windows attribute model.
DIR_ALLOWED_ATTRIBUTES = 0x1 | 0x2 | 0x4 | 0x10 | 0x20 | 0x80 | 0x100 | 0x800


def id_both_layout():
    """Derive default Windows x64 SDK layout, not host-native Python layout.

    Field order: FILE_ID_BOTH_DIR_INFO; widths: Windows Data Types;
    natural member alignment and final struct rounding: Microsoft x64 ABI.
    Documentation and the complete derived table are recorded in REVIEW.md.
    """
    fields = (('NextEntryOffset', 4, 4), ('FileIndex', 4, 4),
              ('CreationTime', 8, 8), ('LastAccessTime', 8, 8),
              ('LastWriteTime', 8, 8), ('ChangeTime', 8, 8),
              ('EndOfFile', 8, 8), ('AllocationSize', 8, 8),
              ('FileAttributes', 4, 4), ('FileNameLength', 4, 4),
              ('EaSize', 4, 4), ('ShortNameLength', 1, 1),
              ('ShortName', 24, 2), ('FileId', 8, 8), ('FileName', 2, 2))
    offsets, position = {}, 0
    for name, size, alignment in fields:
        position = (position + alignment - 1) // alignment * alignment
        offsets[name] = position
        position += size
    return offsets, (position + 7) // 8 * 8


ID_BOTH_OFFSETS, ID_BOTH_C_SIZE = id_both_layout()
ID_BOTH_PREFIX = ID_BOTH_OFFSETS['FileName']

SOURCE = Path('D:/nexus2/startup-updater-20261016/private-package/NEXUS-Bootstrap-beta2')
ARCHIVE = Path('D:/nexus2/startup-updater-20261016/NEXUS-Bootstrap-beta2-PRIVATE.zip')
WORKSPACE = Path('D:/nexus2/desktop-placement-prototype-20261017')
ZIP_SHA256 = '9c3054dfc2ddf5d12c984ae6015a3799822783e3be2e8346eef3bbf3d29ba4f8'
PREFIX = 'NEXUS-Bootstrap-beta2/'
REQUIRED = frozenset(('NEXUS.exe', '_internal/assets/bootstrap-release.json',
                      '_internal/assets/initial-envelope.json', '_internal/assets/initial-package.zip'))
CASES = ('valid', 'corrupt', 'missing-exe', 'missing-resource', 'unexpected-file',
         'unsafe-path', 'reparse-source', 'reparse-target',
         'interrupted-exception', 'interrupted-process')


class Refusal(ValueError):
    """An explicit preflight refusal, not an expected scenario success."""


def native_query_result_policy(*, return_status, io_status=None,
                               pending_completed=False, information=None,
                               capacity=MAX_DIR_BUFFER):
    """Symbolic NtQueryDirectoryFile result policy only, NOT a Native binding.

    Only a future binding may translate actual NTSTATUS bit patterns. A pending
    operation requires independently confirmed completion before IOSB is read.
    A non-pending call is classified by its direct return, not a stale IOSB.
    Metadata validation does not prove buffer provenance, handles or containment.
    """
    if type(return_status) is not str or type(pending_completed) is not bool:
        return {'status': 'REFUSED', 'code': 'NATIVE_STATUS_ARGUMENTS'}
    status = return_status
    if return_status == 'STATUS_PENDING':
        if not pending_completed:
            return {'status': 'INCOMPLETE', 'code': 'COMPLETION_PENDING'}
        if type(io_status) is not str or io_status == 'STATUS_PENDING':
            return {'status': 'BLOCKED', 'code': 'FINAL_COMPLETION_UNCONFIRMED'}
        status = io_status
    if status in ('STATUS_BUFFER_OVERFLOW', 'STATUS_BUFFER_TOO_SMALL', 'STATUS_INFO_LENGTH_MISMATCH'):
        return {'status': 'INCOMPLETE', 'code': 'PAGE_TRUNCATED_NO_RETRY'}
    if status == 'STATUS_CANCELLED':
        return {'status': 'INCOMPLETE', 'code': 'CANCELLED_NO_RECORDS'}
    if status in ('STATUS_NOT_SUPPORTED', 'STATUS_NOT_IMPLEMENTED', 'STATUS_INVALID_INFO_CLASS'):
        return {'status': 'BLOCKED', 'code': 'UNSUPPORTED_NATIVE_QUERY'}
    if status not in ('STATUS_SUCCESS', 'STATUS_NO_MORE_FILES'):
        return {'status': 'REFUSED', 'code': 'NATIVE_QUERY_STATUS'}
    return page_length_policy(api='native',
                              completion='success' if status == 'STATUS_SUCCESS' else 'end',
                              capacity=capacity, information=information)


def page_length_policy(*, api, completion, capacity, information=None):
    """Pure contract decisions, not API calls or verification of OS evidence.

    A future adapter must supply a trusted final completion mapping. VALIDATED
    here means only self-consistent metadata; bytes still require full parsing.
    Neither capacity nor a zero-filled tail establishes a byte count.
    """
    if api not in ('win32', 'native') or type(capacity) is not int or not 0 < capacity <= MAX_DIR_BUFFER:
        return {'status': 'REFUSED', 'code': 'PAGE_ARGUMENTS'}
    if completion == 'pending':
        return {'status': 'INCOMPLETE', 'code': 'COMPLETION_PENDING'}
    if completion == 'overflow':
        return {'status': 'INCOMPLETE', 'code': 'PAGE_TRUNCATED_NO_RETRY'}
    if completion not in ('success', 'end'):
        return {'status': 'REFUSED', 'code': 'PAGE_COMPLETION'}
    if api == 'win32':
        return {'status': 'BLOCKED', 'code': 'WIN32_NO_DOCUMENTED_BYTE_COUNT'}
    if type(information) is not int or not 0 <= information <= capacity:
        return {'status': 'REFUSED', 'code': 'PAGE_BYTE_COUNT'}
    if completion == 'end':
        if information != 0:
            return {'status': 'REFUSED', 'code': 'END_WITH_DATA'}
        return {'status': 'VALIDATED', 'disposition': 'END_NO_RECORDS'}
    if information == 0:
        return {'status': 'INCOMPLETE', 'code': 'EMPTY_SUCCESS_NOT_END'}
    if information < ID_BOTH_PREFIX + 2:
        return {'status': 'REFUSED', 'code': 'PAGE_SPAN_TOO_SHORT'}
    return {'status': 'VALIDATED', 'span': (0, information),
            'disposition': 'STRUCTURAL_VALIDATION_REQUIRED'}


def child_name_policy(*, name, kind, attributes):
    """Classify artificial metadata; does not validate a real child object.

    Dot records require explicit, counted audit handling outside the strict
    binary parser. This does not weaken that parser's INVALID_NAME rejection.
    """
    if (type(name) is not str or type(kind) is not str or kind not in ('file', 'directory')
            or type(attributes) is not int or attributes < 0):
        return {'status': 'REFUSED', 'code': 'CHILD_METADATA'}
    if attributes & ~DIR_ALLOWED_ATTRIBUTES or (attributes & 0x80 and attributes != 0x80):
        return {'status': 'REFUSED', 'code': 'CHILD_ATTRIBUTES'}
    if bool(attributes & 0x10) != (kind == 'directory'):
        return {'status': 'REFUSED', 'code': 'CHILD_TYPE'}
    if name in ('.', '..'):
        if kind != 'directory':
            return {'status': 'REFUSED', 'code': 'SPECIAL_NOT_DIRECTORY'}
        return {'status': 'VALIDATED', 'disposition': 'AUDIT_SKIP_NO_OPEN',
                'code': 'DOT_SELF' if name == '.' else 'DOT_PARENT'}
    try:
        if len(relative_name(name)) != 1:
            raise Refusal('UNSAFE_PATH')
    except Refusal:
        return {'status': 'REFUSED', 'code': 'CHILD_NAME'}
    return {'status': 'VALIDATED', 'disposition': 'OPEN_CANDIDATE_NOT_TRUSTED'}


class DescriptionRefusal(Refusal):
    """Structured input error; never contains a partially accepted inventory."""
    def __init__(self, code, index=None):
        super().__init__(code)
        self.code, self.index = code, index


class BinaryDirectoryRefusal(Refusal):
    def __init__(self, code, offset=0):
        super().__init__(code)
        self.code, self.offset = code, offset


def parse_id_both_buffer(buffer):
    """Parse immutable, bounded synthetic x64 FILE_ID_BOTH_DIR_INFO bytes.

    Input is the logical record-chain span, with at most seven terminal padding
    bytes, NOT an arbitrary capacity-sized Windows allocation. No OS calls.
    A future adapter must establish span length; this parser does not do so.
    """
    try:
        return _parse_id_both_buffer(buffer)
    except BinaryDirectoryRefusal as error:
        return {'status': 'REFUSED', 'error': {'code': error.code, 'offset': error.offset}}


def _parse_id_both_buffer(buffer):
    if type(buffer) is not bytes:
        raise BinaryDirectoryRefusal('BUFFER_TYPE')
    if len(buffer) > MAX_DIR_BUFFER:
        raise BinaryDirectoryRefusal('BUFFER_LIMIT')
    if len(buffer) < ID_BOTH_PREFIX + 2:
        raise BinaryDirectoryRefusal('BUFFER_TOO_SHORT')
    position, name_bytes = 0, 0
    records, names = [], set()
    while True:
        if len(records) >= MAX_DIR_RECORDS:
            raise BinaryDirectoryRefusal('RECORD_LIMIT', position)
        remaining = len(buffer) - position
        if position % 8:
            raise BinaryDirectoryRefusal('RECORD_ALIGNMENT', position)
        if remaining < ID_BOTH_PREFIX + 2:
            raise BinaryDirectoryRefusal('RECORD_TOO_SHORT', position)
        def field(name, fmt):
            return struct.unpack_from('<' + fmt, buffer, position + ID_BOTH_OFFSETS[name])[0]
        step = field('NextEntryOffset', 'I')
        if step:
            if step < ID_BOTH_PREFIX:
                raise BinaryDirectoryRefusal('OFFSET_IN_HEADER', position)
            if step % 8:
                raise BinaryDirectoryRefusal('OFFSET_ALIGNMENT', position)
            if step > remaining:
                raise BinaryDirectoryRefusal('OFFSET_BOUNDS', position)
            if step == remaining:
                raise BinaryDirectoryRefusal('MISSING_TERMINATOR', position)
            if remaining - step < ID_BOTH_PREFIX + 2:
                raise BinaryDirectoryRefusal('NEXT_RECORD_TOO_SHORT', position)
        boundary = step or remaining
        length = field('FileNameLength', 'I')
        if not length or length % 2:
            raise BinaryDirectoryRefusal('NAME_LENGTH', position)
        if length > 510:
            raise BinaryDirectoryRefusal('NAME_LIMIT', position)
        if ID_BOTH_PREFIX + length > boundary:
            raise BinaryDirectoryRefusal('NAME_BOUNDS', position)
        short_length = field('ShortNameLength', 'b')
        if short_length < 0 or short_length > 24 or short_length % 2:
            raise BinaryDirectoryRefusal('SHORT_NAME_LENGTH', position)
        name_bytes += length + short_length
        if name_bytes > MAX_DIR_NAME_BYTES:
            raise BinaryDirectoryRefusal('NAMES_TOTAL_LIMIT', position)
        attributes = field('FileAttributes', 'I')
        if attributes & ~DIR_ALLOWED_ATTRIBUTES or (attributes & 0x80 and attributes != 0x80):
            raise BinaryDirectoryRefusal('ATTRIBUTES_POLICY', position)
        eof, allocated = field('EndOfFile', 'q'), field('AllocationSize', 'q')
        if eof < 0 or allocated < 0:
            raise BinaryDirectoryRefusal('NEGATIVE_SIZE', position)
        directory = bool(attributes & 0x10)
        if not directory and eof > MAX_ENTRY:
            raise BinaryDirectoryRefusal('ENTRY_SIZE', position)
        start = position + ID_BOTH_PREFIX
        short_start = position + ID_BOTH_OFFSETS['ShortName']
        try:
            name = buffer[start:start + length].decode('utf-16-le', errors='strict')
            short = buffer[short_start:short_start + short_length].decode('utf-16-le', errors='strict')
        except UnicodeDecodeError as error:
            raise BinaryDirectoryRefusal('INVALID_UTF16', position) from error
        try:
            if len(relative_name(name)) != 1 or (short and len(relative_name(short)) != 1):
                raise Refusal('UNSAFE_PATH')
        except Refusal as error:
            raise BinaryDirectoryRefusal('INVALID_NAME', position) from error
        if name.casefold() in names:
            raise BinaryDirectoryRefusal('DUPLICATE_NAME', position)
        names.add(name.casefold())
        records.append({'name': name, 'type': 'directory' if directory else 'file',
                        'size': None if directory else eof, 'attributes': attributes,
                        # FileId is opaque bits, not a signed numeric identity guarantee.
                        'file_id': buffer[position + ID_BOTH_OFFSETS['FileId']:
                                          position + ID_BOTH_OFFSETS['FileId'] + 8].hex(),
                        'short_name': short})
        if not step:
            # Strict input-span policy, NOT a requirement that OS unused tail is zero.
            if remaining - ID_BOTH_PREFIX - length > 7:
                raise BinaryDirectoryRefusal('TERMINAL_SPAN_POLICY', position)
            return {'status': 'VALIDATED_BINARY_DESCRIPTIONS',
                    'records': tuple(records), 'name_bytes': name_bytes}
        # Strictly positive aligned forward step: no cycle/reused offset is possible.
        position += step


def parse_descriptions(records):
    """Validate plain in-memory descriptions, not Windows directory buffers.

    Input: list/tuple of exact dicts with path, type and size. File size is an
    exact int; directory size must be None. Only already-canonical forward-slash
    paths are accepted. Implicit parent directories are permitted. No disk I/O.
    VALIDATED_DESCRIPTIONS is not PASS, readiness or filesystem authentication.
    """
    try:
        return _parse_descriptions(records)
    except DescriptionRefusal as error:
        return {'status': 'REFUSED', 'error': {'code': error.code, 'index': error.index}}


def _parse_descriptions(records):
    if type(records) not in (list, tuple):
        raise DescriptionRefusal('INPUT_TYPE')
    if not 0 < len(records) <= MAX_TREE_NODES:
        raise DescriptionRefusal('RECORD_COUNT')
    entries, spelling = {}, {}
    total, files = 0, 0
    for index, record in enumerate(records):
        if type(record) is not dict or len(record) != 3 or set(record) != {'path', 'type', 'size'}:
            raise DescriptionRefusal('RECORD_SCHEMA', index)
        name, kind, size = record['path'], record['type'], record['size']
        if type(name) is not str:
            raise DescriptionRefusal('PATH_TYPE', index)
        try:
            parts = relative_name(name)
        except Refusal as error:
            raise DescriptionRefusal(str(error), index) from error
        if len(parts) > MAX_DEPTH or len(name.encode('utf-16-le')) > MAX_RELATIVE_UTF16 * 2:
            raise DescriptionRefusal('PATH_LIMIT', index)
        if type(kind) is not str or kind not in ('file', 'directory'):
            raise DescriptionRefusal('ENTRY_TYPE', index)
        if kind == 'directory':
            if size is not None:
                raise DescriptionRefusal('DIRECTORY_SIZE', index)
        else:
            if type(size) is not int or size < 0:
                raise DescriptionRefusal('FILE_SIZE', index)
            if size > MAX_ENTRY:
                raise DescriptionRefusal('ENTRY_SIZE', index)
            files += 1
            total += size
            if files > MAX_ENTRIES:
                raise DescriptionRefusal('FILE_COUNT', index)
            if total > MAX_TOTAL:
                raise DescriptionRefusal('TOTAL_SIZE', index)
        key = name.casefold()
        if key in entries:
            raise DescriptionRefusal('DUPLICATE_PATH', index)
        for length in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:length])
            previous = spelling.setdefault(prefix.casefold(), prefix)
            if previous != prefix:
                raise DescriptionRefusal('CASE_ALIAS', index)
        entries[key] = (name, kind, size)
    for name, kind, size in entries.values():
        parts = name.split('/')
        for length in range(1, len(parts)):
            parent = entries.get('/'.join(parts[:length]).casefold())
            if parent is not None and parent[1] != 'directory':
                raise DescriptionRefusal('FILE_PARENT_CONFLICT')
    return {'status': 'VALIDATED_DESCRIPTIONS',
            'inventory': tuple(sorted(entries.values(), key=lambda item: (item[0].casefold(), item[0]))),
            'file_count': files, 'total_bytes': total}


class TreeLedger:
    """Pure admission policy for FUTURE handle-derived metadata.

    This does not enumerate/open files and does not authenticate its inputs.
    Parent-before-child admission is mandatory. An adapter must additionally
    validate the opened object's type/identity and retain its parent handle.
    Any rejection poisons the session: no continuation or success afterward.
    """
    def __init__(self):
        self.nodes = {}
        self.files = 0
        self.total = 0
        self.failed = False

    def admit(self, name, *, directory, size, attributes, disk=True, links=1):
        if self.failed:
            raise Refusal('TREE_SESSION_FAILED')
        self.failed = True
        parts = relative_name(name)
        if len(parts) > MAX_DEPTH or len(name.encode('utf-16-le')) > MAX_RELATIVE_UTF16 * 2:
            raise Refusal('TREE_PATH_LIMIT')
        if len(self.nodes) >= MAX_TREE_NODES:
            raise Refusal('TREE_NODE_LIMIT')
        if (type(directory) is not bool or type(size) is not int or type(attributes) is not int
                or type(disk) is not bool or type(links) is not int or attributes < 0):
            raise Refusal('TREE_METADATA')
        if not disk or attributes & 0x400:
            raise Refusal('TREE_REPARSE_OR_NON_DISK')
        if bool(attributes & 0x10) != directory or size < 0:
            raise Refusal('TREE_OBJECT_TYPE')
        if not directory and links != 1:
            raise Refusal('TREE_HARDLINK')
        key = name.casefold()
        if key in self.nodes:
            raise Refusal('TREE_DUPLICATE')
        if len(parts) > 1:
            parent = '/'.join(parts[:-1])
            recorded = self.nodes.get(parent.casefold())
            if recorded is None or not recorded[1] or recorded[0] != parent:
                raise Refusal('TREE_PARENT')
        if not directory:
            if self.files >= MAX_ENTRIES or size > MAX_ENTRY or self.total + size > MAX_TOTAL:
                raise Refusal('TREE_SIZE_LIMIT')
            self.files += 1
            self.total += size
        self.nodes[key] = (name, directory)
        self.failed = False


def worker_action(*, owned_handle, exited, deadline_reached, termination_requested):
    """Pure supervisor decision only; never launches, waits or kills anything.

    Ownership must come from the future parent's creation result, never a PID
    supplied by a worker. This boolean does not itself establish ownership.
    """
    if not owned_handle:
        return 'BLOCKED_NO_OWNED_HANDLE'
    if exited:
        return 'ASSESS_RESULT'
    if termination_requested:
        return 'WAIT_BOUNDED_FOR_TERMINATION'
    if deadline_reached:
        return 'REQUEST_TERMINATION_OF_OWNED_CHILD'
    return 'WAIT_BOUNDED'


def assess_worker_result(*, exited, exit_code, timed_out, report_complete,
                         expected_reason=None, reported_reason=None):
    """Pure classification, NOT acceptance of filesystem evidence or readiness."""
    if timed_out:
        return 'FAIL_TIMEOUT'
    if not exited:
        return 'BLOCKED_WORKER_NOT_EXITED'
    if exit_code != 0 or not report_complete:
        return 'FAIL_INCOMPLETE_OR_ERROR'
    if expected_reason is not None:
        if reported_reason != expected_reason:
            return 'FAIL_UNEXPECTED_REFUSAL'
        return 'NOT TESTED_FILESYSTEM_EVIDENCE_REQUIRED'
    if reported_reason is not None:
        return 'FAIL_UNEXPECTED_REFUSAL'
    return 'NOT TESTED_FILESYSTEM_EVIDENCE_REQUIRED'


def relative_name(value):
    """Conservative Windows policy; do not normalize an unsafe name into safety."""
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise Refusal('UNSAFE_PATH')
    parts = value.split('/')
    for part in parts:
        if (not part or part in ('.', '..') or part[-1:] in ('.', ' ')
                or any(ord(c) < 32 or 0xd800 <= ord(c) <= 0xdfff or c in '\\<>:"|?*' for c in part)
                or len(part.encode('utf-16-le')) > 510
                or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?', part, re.I)):
            raise Refusal('UNSAFE_PATH')
    return tuple(parts)


def check_names(names):
    seen = set()
    spellings = {}
    for name in names:
        parts = relative_name(name)
        key = name.casefold()
        if key in seen:
            raise Refusal('DUPLICATE_PATH')
        seen.add(key)
        for i in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:i])
            old = spellings.setdefault(prefix.casefold(), prefix)
            if old != prefix:
                raise Refusal('CASE_ALIAS')
    for name in seen:
        if any('/'.join(name.split('/')[:i]) in seen for i in range(1, len(name.split('/')))):
            raise Refusal('PARENT_CONFLICT')


class Budget:
    """Cooperative deadlines, not cancellation of a blocked synchronous OS read."""
    def __init__(self, maximum=MAX_READ, seconds=120, clock=time.monotonic):
        self.maximum = maximum
        self.used = 0
        self.clock = clock
        self.deadline = clock() + seconds

    def check(self):
        if self.clock() >= self.deadline:
            raise Refusal('TIME_LIMIT')

    def charge(self, count):
        self.check()
        if count < 0 or self.used + count > self.maximum:
            raise Refusal('READ_LIMIT')
        self.used += count


class BoundedReader:
    """Seekable ZIP view with per-request allocation and aggregate read bounds."""
    def __init__(self, stream, budget):
        self.stream, self.budget = stream, budget

    def read(self, size=-1):
        self.budget.check()
        if size < 0:
            size = MAX_CENTRAL
        if size > MAX_CENTRAL or size > self.budget.maximum - self.budget.used:
            raise Refusal('READ_REQUEST_LIMIT')
        data = self.stream.read(size)
        self.budget.charge(len(data))
        return data

    def seek(self, *args):
        self.budget.check()
        return self.stream.seek(*args)

    def tell(self):
        return self.stream.tell()

    def seekable(self):
        return True


def check_eocd(stream, length):
    """Bound central-directory allocation BEFORE constructing ZipFile.

    This narrow reference contract rejects ZIP64, multi-disk, comments and SFX.
    It is intentionally stricter than a general purpose ZIP reader.
    """
    if length < 22 or length > MAX_ZIP:
        raise Refusal('ZIP_LENGTH')
    stream.seek(length - 22)
    raw = stream.read(22)
    if len(raw) != 22:
        raise Refusal('ZIP_EOCD')
    signature, disk, cd_disk, disk_count, count, size, offset, comment = struct.unpack('<4s4H2LH', raw)
    if (signature != b'PK\x05\x06' or disk or cd_disk or comment
            or count != disk_count or count == 65535 or size == 0xffffffff
            or offset == 0xffffffff):
        raise Refusal('ZIP_UNSUPPORTED_LAYOUT')
    if not 0 < count <= MAX_ENTRIES or size > MAX_CENTRAL or offset + size != length - 22:
        raise Refusal('ZIP_CENTRAL_LIMIT')
    stream.seek(0)
    if stream.read(4) != b'PK\x03\x04':
        raise Refusal('ZIP_UNSUPPORTED_LAYOUT')
    stream.seek(0)
    return count


@contextmanager
def windows_read(path):
    """Open verified local-drive components, keeping ancestors and leaf pinned.

    OPEN_REPARSE_POINT protects only the final component of each open. Therefore
    ancestors are opened/checked in order and held without write/delete sharing.
    No claims against kernel/admin actors or pre-existing writable mappings.
    """
    import ctypes
    from ctypes import wintypes
    if os.name != 'nt':
        raise Refusal('WINDOWS_REQUIRED')
    import msvcrt
    path = Path(path)
    if not path.is_absolute() or not re.fullmatch('[A-Za-z]:', path.drive):
        raise Refusal('LOCAL_ABSOLUTE_PATH_REQUIRED')
    relative_name('/'.join(path.parts[1:]))
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    kernel.GetDriveTypeW.restype = wintypes.UINT
    class Info(ctypes.Structure):
        _fields_ = [('attributes', wintypes.DWORD), ('created', wintypes.FILETIME),
                    ('accessed', wintypes.FILETIME), ('written', wintypes.FILETIME),
                    ('volume', wintypes.DWORD), ('high', wintypes.DWORD),
                    ('low', wintypes.DWORD), ('links', wintypes.DWORD),
                    ('index_high', wintypes.DWORD), ('index_low', wintypes.DWORD)]
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(Info)]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    if kernel.GetDriveTypeW(path.anchor) != 3:
        raise Refusal('FIXED_LOCAL_DISK_REQUIRED')
    chain = list(reversed(path.parents)) + [path]
    with ExitStack() as stack:
        for position, component in enumerate(chain):
            leaf = position == len(chain) - 1
            handle = kernel.CreateFileW('\\\\?\\' + str(component),
                                        0x80000000 if leaf else 0x80, 1, None, 3,
                                        0x00200000 | (0 if leaf else 0x02000000), None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            # Separate scope transfers leaf ownership only after successful CRT adoption.
            with ExitStack() as owner:
                owner.callback(kernel.CloseHandle, handle)
                info = Info()
                if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
                    raise ctypes.WinError(ctypes.get_last_error())
                if kernel.GetFileType(handle) != 1 or info.attributes & 0x400:
                    raise Refusal('REPARSE_OR_NON_DISK_OBJECT')
                if bool(info.attributes & 0x10) == leaf:
                    raise Refusal('OBJECT_TYPE')
                if not leaf:
                    owner.pop_all()  # transfer lifetime to the outer stack
                    stack.callback(kernel.CloseHandle, handle)
                    continue
                if info.links != 1:
                    raise Refusal('HARDLINK_NOT_ALLOWED')
                descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
                owner.pop_all()
                try:
                    stream = os.fdopen(descriptor, 'rb')
                except BaseException:
                    os.close(descriptor)
                    raise
                with stream:
                    yield stream, (info.high << 32) | info.low


def hash_stream(stream, maximum, budget=None):
    budget = budget or Budget()
    digest = hashlib.sha256()
    total = 0
    while True:
        budget.check()
        request = min(256 * 1024, maximum - total + 1,
                      budget.maximum - budget.used)
        if request <= 0:
            raise Refusal('READ_LIMIT')
        block = stream.read(request)
        budget.charge(len(block))
        total += len(block)
        if total > maximum:
            raise Refusal('BYTE_LIMIT')
        if not block:
            return total, digest.hexdigest()
        digest.update(block)


def validate_entries(entries):
    if not 0 < len(entries) <= MAX_ENTRIES:
        raise Refusal('ENTRY_COUNT')
    total = 0
    names = []
    for entry in entries:
        # Reject names truncated by ZipInfo at NUL rather than accepting aliases.
        if entry.orig_filename != entry.filename or not entry.filename.startswith(PREFIX):
            raise Refusal('ZIP_NAME')
        relative = entry.filename[len(PREFIX):]
        relative_name(relative)
        mode = entry.external_attr >> 16
        if (entry.is_dir() or entry.flag_bits & 1 or entry.external_attr & 0x410
                or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
            raise Refusal('ZIP_ENTRY_TYPE')
        if not 0 <= entry.file_size <= MAX_ENTRY or not 0 <= entry.compress_size <= MAX_ZIP:
            raise Refusal('ENTRY_SIZE')
        total += entry.file_size
        if total > MAX_TOTAL:
            raise Refusal('TOTAL_SIZE')
        names.append(relative)
    check_names(names)
    if not REQUIRED.issubset(names):
        raise Refusal('REQUIRED_FILE_MISSING')
    return names


def inventory_from_zip(archive, budget=None):
    budget = budget or Budget()
    entries = archive.infolist()
    names = validate_entries(entries)  # all structural checks before decompressing
    result = {}
    for entry, name in zip(entries, names):
        with archive.open(entry) as stream:
            item = hash_stream(stream, entry.file_size, budget)
        if item[0] != entry.file_size:
            raise Refusal('ZIP_SIZE')
        result[name] = item
    return result


def read_reference():
    # Same handle, no write/delete sharing, from hash through central directory.
    # Kept uncalled until Windows integration and source traversal are reviewed.
    budget = Budget()
    with windows_read(ARCHIVE) as (stream, length):
        if length > MAX_ZIP:
            raise Refusal('ZIP_LENGTH')
        if hash_stream(stream, MAX_ZIP, budget)[1] != ZIP_SHA256:
            raise Refusal('ZIP_HASH_MISMATCH')
        view = BoundedReader(stream, budget)
        count = check_eocd(view, length)
        with zipfile.ZipFile(view) as archive:
            if len(archive.infolist()) != count:
                raise Refusal('ZIP_COUNT_MISMATCH')
            return inventory_from_zip(archive, budget)


def preflight():
    # Fail before any helper import, source read or filesystem operation.
    # Bounded, handle-based source directory enumeration is not implemented yet.
    raise Refusal('PREFLIGHT_BLOCKED_PENDING_FILESYSTEM_REVIEW')


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest='command', required=True)
    sub.add_parser('preflight')
    case = sub.add_parser('run-case', help='Reserved; refuses without filesystem operations')
    case.add_argument('case', choices=CASES)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == 'run-case':
        print(json.dumps({'status': 'NOT TESTED', 'case': args.case,
                          'reason': 'MUTATING_RUNNER_NOT_IMPLEMENTED_OR_AUTHORIZED'}))
        return 4
    try:
        result = preflight()
    except Refusal as error:
        print(json.dumps({'status': 'REFUSED', 'reason': str(error)}))
        return 2
    # Unexpected errors deliberately propagate with their traceback.
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
