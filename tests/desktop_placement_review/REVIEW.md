# Placement harness review — 2026-10-18

Overall: **FAIL — not execution-ready. Preflight remains unconditionally blocked.**
Only these three review files were edited. No production module was read or
modified for this revision. No payload was read/hashed; no experiment was run.

## Status matrix

| Area | Status | Evidence / remaining requirement |
|---|---|---|
| Python syntax / AST | PASS | Both Python sources parsed and compiled in memory, not executed as scripts |
| Pure unit tests | PASS | Latest Native-contract run: 112 tests, OK, exit 0; previous stage: 104 tests |
| Names, aliases, metadata/resource policies | PASS | In-memory tests; not a Windows filesystem claim |
| Preflight gate | PASS (static) | Unconditional structured refusal before filesystem access |
| Import/argument handling | PASS (static) | No top-level filesystem I/O; pure parser exercised |
| Windows leaf/ancestor handle operations | NOT TESTED | Candidate implementation, no API invocation |
| ZIP same-object lifetime | NOT TESTED | Static design uses one open handle; Windows sharing not integration-tested |
| Safe source directory enumeration | BLOCKED | Pure bounded admission implemented/tested; Windows adapter not implemented or validated |
| Hard cancellation of blocked reads | BLOCKED | Pure supervisor policy tested; actual worker/termination NOT TESTED; no absolute OS completion guarantee |
| Existing beta2 ZIP compatibility | NOT TESTED | Strict contract rejects comments, ZIP64, SFX, explicit directories |
| Filesystem fixtures / placement / sentinels | NOT TESTED | No workspace or fixtures created; no write runner |
| Reparse / concurrent mutation / interruption | NOT TESTED | Requires separately approved integration tests |

No experiment or installation has PASS status. No partial tree can be marked
ready: there is no placement, activation or readiness implementation.

## Windows candidate and precise limitations

`windows_read` uses OPEN_EXISTING (3), FILE_FLAG_OPEN_REPARSE_POINT (0x00200000)
and FILE_SHARE_READ (1) without write/delete sharing. Directory components add
FILE_FLAG_BACKUP_SEMANTICS (0x02000000), request FILE_READ_ATTRIBUTES (0x80), and
are held in an ExitStack until the leaf stream closes. The leaf requests
GENERIC_READ (0x80000000). Each opened handle is checked with GetFileType and
GetFileInformationByHandle: disk object, expected file/directory type, no reparse
attribute. Leaf hardlinks are rejected (link count must equal 1).

The reparse flag protects the component being opened; it is not a whole-path
protection by itself. Hence the candidate opens/checks ancestors in order and
keeps them pinned. Absolute drive-letter paths on fixed local disks only;
UNC, device inputs and mapped/removable drives are refused. Internal extended
path prefix is added only after validating the caller path.

The handle is adopted by msvcrt.open_osfhandle, then fdopen; CRT stream close owns
that handle. Exception paths close only opened resources. There is no file
cleanup or retry. The re-raising BaseException handler exists solely to close an
adopted descriptor if fdopen fails, never to convert errors into success.

This is NOT a proof against privileged/kernel actors, volume namespace changes,
filesystem/filter peculiarities, writable mappings, or all concurrent mutations.
Metadata/identity alone is not claimed to solve races. No Windows integration
claim is made until separate tests confirm component pinning, sharing conflicts,
reparse rejection, handle ownership, Unicode and long-path behavior.

References consulted:
- [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
- [GetFileInformationByHandle](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle)
- [open_osfhandle](https://docs.python.org/3.12/library/msvcrt.html#msvcrt.open_osfhandle)
- [zipfile file-like input](https://docs.python.org/3.12/library/zipfile.html)

## ZIP reference and resource limits

The original source folder and external ZIP are separate constants in probe.py.
Expected inventory is derived ONLY from the separately pinned outer ZIP, never
from the copied/source tree. Target, sentinels and reports remain future separate
locations under D:/nexus2/desktop-placement-prototype-20261017; none is accessed.

`read_reference` is dormant. It keeps one windows_read context and one stream
through hash verification, bounded EOCD inspection, ZipFile parsing and member
hashes. It never reopens the archive by name. Sharing semantics intend to deny
ordinary concurrent writes/delete; actual Windows behavior is NOT TESTED.

Limits, enforced before entry decompression:
- external ZIP <= 512 MiB;
- <= 2048 entries; central directory <= 2 MiB, bounded BEFORE ZipFile constructor;
- one expanded entry <= 512 MiB; declared expanded total <= 1 GiB;
- aggregate actual bytes read <= 3 GiB, including hashing, compressed ZIP reads
  and decompressed member bytes (deliberately conservative accounting);
- maximum ZIP read allocation 2 MiB; hash chunks <= 256 KiB;
- shared cooperative deadline 120 seconds checked before/after reads.

EOCD checks reject ZIP64, multi-disk, comments and SFX; central offset/size must
end exactly before EOCD. Metadata validation completes before any entry open.
The reference is SHA-256-checked before central-directory parsing. No fixture
compatibility assumption is substituted for a real test.

A cooperative deadline cannot interrupt one stalled synchronous OS/decompression
operation. Hard timeout cancellation remains unresolved, without worker tests or
new system settings. Actual source enumeration limits remain unimplemented;
preflight cannot reach any source inspection.

## Traversal policy

Reject slash-rooted paths, empty/dot/parent components, backslashes, colons/ADS,
control characters/NUL, trailing dots/spaces, reserved Windows device names,
components longer than 255 UTF-16 units and relative names longer than 1024 code
points. Reject casefold duplicates, inconsistent directory-component spelling
and file/parent conflicts. This conservative string policy is not a complete
model of Windows Unicode, 8.3 aliases or case-sensitive directories; actual
handle-based containment/enumeration must still be designed and tested.

ZIP permits regular entries only, no symlink/reparse/directory, no encryption,
only stored/deflate compression. ZipInfo NUL truncation is explicitly rejected.
No extraction, hardlinks, cleanup or target writes are implemented.

## Actual verification commands

Interpreter: C:/Users/Икрам/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe

```powershell
& 'C:/Users/Икрам/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -I -B -m unittest discover -s D:/nexus2/launcher-next/desktop_placement_review -p test_probe_logic.py -v
```

Tests use BytesIO, fake metadata, fake clocks and a fake failing stream only.
They import the review module, but never call main/preflight/read_reference/
windows_read, never open payload, never create disk fixtures or child workers.
No pytest or full regression was run. AST/compile checks use in-memory source
compilation and create no bytecode. No constant PYTHONPATH/environment change.

## Next permission boundary

Do not run preflight: it refuses PREFLIGHT_BLOCKED_PENDING_FILESYSTEM_REVIEW.
Do not run placement cases: all reserved run-case commands return NOT TESTED/4.
There are no executable placement commands to approve at this stage.

Next code-only scope: bounded handle-based directory enumeration and explicit
hard-timeout strategy, followed by review. Windows filesystem tests, real ZIP
inspection, workspace creation, copied fixtures, reports/sentinels, reparse point
creation and interruption experiments require separate explicit permission.
Production module changes or dependencies would require separate permission;
none is needed or proposed for this code-only candidate.

Hash equality proves byte preservation relative to the chosen reference only.
It is not Authenticode, provenance, publisher identity or Windows acceptance.


## Current revision: tree and timeout blockers

Only probe.py, test_probe_logic.py and this REVIEW.md were changed.
There were no production reads/changes, package reads, package enumeration,
source/ZIP hashes, workers, fixtures, experiment directories or preflight runs.
No attempt was made to close an OS-level blocker with a mock assertion.

### Implemented and tested pure tree policy — PASS

TreeLedger accepts metadata supplied by a future trusted adapter, not raw
filesystem access. Limits: 4096 total nodes, 2048 files, depth 32, relative path
1024 UTF-16 units, per-file 512 MiB, declared file total 1 GiB. Existing shared
Budget enforces actual read charges separately (3 GiB across reference reads,
ZIP parsing/decompression; a future source reader must use the same budget).
Parent must already be admitted as a directory with exactly matching spelling.
Reject reparse/non-disk objects, inconsistent types, file hardlinks, duplicates,
case aliases and unsafe names. Any rejected admission poisons the session,
preventing continuation after failure. These checks authenticate no handles and
are not proof that supplied metadata corresponds to an opened object.

### Proposed directory adapter — BLOCKED / NOT TESTED

The documented GetFileInformationByHandleEx FileIdBothDirectoryInfo interface
can enumerate an existing directory handle. Subsequent calls resume its cursor.
It requires bounded buffer parsing, not os.walk:

1. A reviewed root-opening procedure holds and validates the root/ancestors.
   Existing windows_read opens a file leaf, not a reusable directory root API.
2. Enumerate from the held directory handle into a fixed 64 KiB buffer. Cap calls
   as well as entries, including dot entries and repeated responses; check the
   cooperative deadline before/after every call. No unbounded accumulation.
3. Validate record offsets/alignment, length and UTF-16 decoding before reading
   each name. Special dot entries may only be skipped explicitly. Reject embedded
   separators, invalid names, reparses and unexpected object types. Reserve node
   budget before trying to open the child.
4. Open a SINGLE child name relative to that held directory, not a reconstructed
   absolute path. NtCreateFile documents ObjectAttributes.RootDirectory for this.
   Use open-existing semantics, no writes or delete sharing; validate the returned
   object's attributes/type, volume and identity against enumeration data. Reject
   mismatch rather than retry. Keep parents open while descending, depth <= 32.
5. Only after handle validation and size admission read bounded bytes. Type/ID
   checks alone are insufficient: no-follow behavior and parent retention must
   be demonstrated on Windows. Reparse rejection must occur before traversal.
6. Concurrent mutation does not produce a guaranteed atomic tree snapshot.
   Retain bounded evidence and fail on detected change, but do not claim that an
   enumeration/second scan freezes the entire tree. No ready state is created.

STOP before implementing a native adapter relying on unconfirmed flags/semantics.
The exact NtCreateFile option combination, directory access rights, information
structure ABI and no-follow guarantees require a focused design/compatibility
review. No ctypes enumeration/native-open adapter was added or invoked here.
In particular, do not assume CreateFileW has a RootDirectory argument or that
FILE_FLAG_OPEN_REPARSE_POINT protects every ancestor in a single open.

Official references:
- [GetFileInformationByHandleEx](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex)
- [FILE_ID_BOTH_DIR_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_both_dir_info)
- [NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile)

### Proposed timeout boundary — BLOCKED / NOT TESTED

Potential stalls include directory/metadata calls, CreateFile, reads/seeks, ZIP
parsing/decompression, close/flush of a future writer, process creation and waits.
Cooperative Budget checks cannot interrupt those calls.

The smallest future isolation boundary is one read-only worker, no grandchildren,
for the entire source/reference inspection. The parent must not open/enumerate
payload or decompress it. Parent owns the process handle from creation; no lookup
or killing by a reported PID, taskkill, process-name matching or foreign process.
No unbounded stdout/stderr communicate buffers: cap result protocol bytes, reject
unknown/incomplete records and use bounded waits. Process startup itself is not
covered automatically by subprocess communicate timeout; document that boundary.

The parent starts its monotonic deadline before dispatch, never trusts heartbeat
messages to extend it, and requests termination on its own child handle if time
expires. It then waits a second bounded grace period. If child exit is not
confirmed, report BLOCKED with no retry/replacement child, no file cleanup and no
PASS. Keep enough ownership information for later explicit operator action.
A failed termination request is an error, not a successful timeout test.

TerminateProcess is asynchronous for another process, and pending I/O can delay
exit. Thus this design bounds the supervisor's waiting policy; it does NOT prove
that Windows can terminate a stuck driver operation within a fixed wall time.
No code in this revision launches or terminates a process. worker_action and
assess_worker_result are pure policy functions and establish no real ownership.
A report, exit 0 or matching expected refusal alone yields NOT TESTED until
independent filesystem evidence has been checked. Timeout overrides a success
report. Incomplete report, nonzero exit or unexpected refusal cannot pass.

Future placement workers would be a separate permission scope: termination does
not roll back files. Parent must separately inspect partial tree/temp files and
sentinels; missing completion evidence never means ready/installed. No automatic
cleanup is permitted.

References:
- [TerminateProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess)
- [subprocess timeouts](https://docs.python.org/3.12/library/subprocess.html)

### Executed checks in this revision

PASS: 41 pure unit tests, 0 failures/errors, 0 skipped, exit 0, 0.050 s.
The exact unittest command remains above. All previous 24 tests were retained;
17 tree-policy/supervisor/result-classification tests were added. Test data is
in memory; module import reads review source only. No OS handle, directory API,
source/package path, worker or preflight function is called by these tests.
AST and in-memory compilation are checked separately, with no pyc creation.
Static review is not an executed Windows integration test.

### Future Windows integration matrix — all NOT TESTED

- ABI parsing against synthetic directory buffers first; malformed offsets,
  oversized/odd UTF-16 names, duplicate pages and entry/call bounds.
- Approved disposable directory root: regular, Unicode, long paths, file versus
  directory changes, symlink/junction at each ancestor and leaf, outside sentinel.
- Parent rename/delete attempts while held; child replacement between enumerate
  and open; reparse mutation, file ID mismatch, case/8.3 aliases and hardlinks.
- Entry/depth/bytes limits enforced before any inadmissible child read.
- Worker startup failure, blocked read, slow decompression, output flood, timeout,
  failed termination and missing exit confirmation; never target unrelated PIDs.
- Interrupted partial placement and preserved sentinels only under a later scope.

### Next safe step

Code-only review of exact native API adapter signatures/options and pure binary
record parsers. Keep preflight blocked. If documentation cannot establish required
semantics, request a separate Windows test plan using disposable fixtures, not the
real beta2 tree. Such tests and workers remain unauthorized here. No production
change, dependency installation or system setting is required by this proposal.

SHA-256 remains a byte-reference comparison, not a signature or publisher proof.
An attacker able to replace both bytes and an unauthenticated expected hash can
supply a matching pair; these checks do not confer Authenticode or update trust.


## Latest stage: Windows API review and pure description parser

This section is the current result; earlier executed-check sections are historical.
Overall remains BLOCKED, not ready. Only the three approved review files changed.

### Parser contract and results — PASS for in-memory policy only

`parse_descriptions(records)` accepts an exact list/tuple, 1..4096 entries, each an
exact dict with precisely path/type/size fields. Types are file or directory;
file sizes are exact nonnegative integers (bool rejected), directory size is None.
Schema, count and string-length bounds are checked before sorting or encoding
large data. Directory sizes are absent in output (represented by None).

Accepted paths are already canonical relative forward-slash strings. Normalized
output preserves spelling and Unicode; no slash conversion, case rewriting,
traversal collapse or NFC normalization is performed. Backslashes are rejected,
not interpreted as a second separator. Implicit directories are allowed; an
explicit parent record must have type directory. This batch parser is independent
of TreeLedger, whose streaming policy requires parent-before-child records.

Success returns VALIDATED_DESCRIPTIONS plus an immutable tuple of
(path, type, size) tuples sorted by (casefold path, original path), file_count and
total_bytes. A structured refusal returns only REFUSED/error(code,index), with
no partial inventory. Global conflicts can have index=None. Only the component's
own DescriptionRefusal is converted to a result; unexpected exceptions propagate.

Checks: unsafe/absolute/drive/ADS/traversal paths; empty/dot components; reserved
names; control/NUL and lone surrogate characters; trailing dots/spaces; 255 UTF-16
unit components; path <=1024 code points AND <=1024 UTF-16 units; depth <=32;
casefold duplicates; directory-component case aliases; file-as-parent conflicts;
unknown types/schema fields; contradictory duplicate metadata; negative/non-int
sizes; <=2048 files, <=512 MiB/file and <=1 GiB total declared file bytes.
The batch inventory contains descriptions only: no hashes or authenticated file
objects. It neither opens paths nor establishes an install/ready state.

Python casefold is conservative and differs from Windows filesystem comparison.
No claim is made to reproduce NTFS uppercase tables, normalization, 8.3 names,
per-directory case sensitivity or all namespace aliases. Those remain adapter
concerns. Rejecting an ambiguous description is preferable to fixing its name.

### API-by-API review

Documentation below was actually retrieved. D = documented API behavior;
I = design inference requiring future validation. Every Windows execution test
listed here is NOT TESTED. No Native adapter was implemented.

| Mechanism | D: guarantee / required flags or rights | Not guaranteed / I: residual risk | Future confirmation |
|---|---|---|---|
| CreateFileW | OPEN_EXISTING=3 opens without creation. Candidate requests GENERIC_READ for leaf, FILE_READ_ATTRIBUTES for ancestors; local path checked first. | Absolute-path lookup is not handle-relative openat; returned handle says nothing about a later lookup by name. | Missing path must remain absent; swap component before/after each open; reject outside-root object. |
| OPEN_REPARSE_POINT=0x00200000 | Opens reparse point itself rather than normal final reparse processing; inspect returned attributes. | One flag is not a whole-path TOCTOU proof or validation of ancestors. | Junction/symlink at every ancestor and leaf; prove no outside read. |
| BACKUP_SEMANTICS=0x02000000 | Needed for directory handles. Backup privileges, if already present, affect security checks. | Does not pin a namespace, grant isolation, or prove regular-file type. | Ordinary unelevated account, directories versus files, ACL failure; no privilege changes. |
| dwShareMode | READ=1, WRITE=2, DELETE=4; incompatibility fails. Delete sharing covers rename/delete access; sharing lasts until close. Attribute/EA access is not controlled identically. | Denying write/delete sharing is not a recursive tree freeze; children may still change. | Competing write/rename/delete handles before and after open, child mutation with parent held. |
| GetFileInformationByHandle | Returns BY_HANDLE_FILE_INFORMATION on success; volume serial + file index can compare object identities. Check BOOL/error and directory/reparse attributes. | File ID is not provenance or an atomic snapshot. Network/filesystem support differs. | Compare open handles during replacement, hardlinks and metadata changes; reject API failure. |
| GetFileInformationByHandleEx | Supports FileAttributeTagInfo(9), FileStandardInfo(1), FileIdInfo(18), directory classes. Rights depend on class; FILE_ID_BOTH_DIR_INFO states no specific query rights. Candidate may request FILE_LIST_DIRECTORY, but that is a design choice, not a documented universal requirement. | Classes/drivers/OS support differ; modern IDs still do not stop substitution. | Supported local filesystem matrix; unsupported class fails closed; validate structure ABI and buffer lengths. |
| GetFileType | Classifies disk/pipe/character; accept FILE_TYPE_DISK=1 only. UNKNOWN=0 can mean failure; distinguish GetLastError when diagnosing. | Does not distinguish file versus directory, reparse or trustworthy payload. | Disk directory and file, pipe, invalid handle; no fallback to accept UNKNOWN. |
| open_osfhandle | Converts an existing OS handle to CRT descriptor, usable by fdopen. Candidate uses read-only binary mode. | No new path validation or sharing protection; ownership mistakes cause leaks/double close. | Verify success/failure ownership, exact one close, invalid descriptors, binary byte preservation. |
| Directory handle enumeration | GetFileInformationByHandleEx FileIdBothDirectoryInfo enumerates that handle and subsequent calls resume. Use bounded buffer and FILE_LIST_DIRECTORY access. | No atomic tree snapshot; enumerated name is not an already opened child; Windows structs require careful ABI parsing. | Malformed synthetic records first, then bounded pages, mutations, exhaustion and repeated pages in disposable tree. |
| Handle-relative child open | NtCreateFile documents ObjectAttributes.RootDirectory plus relative ObjectName, FILE_OPEN; directory/file access differs. | Native status/ABI/option combinations add maintenance cost; not equivalent to a proven Win32 openat wrapper. | Single-component names only; concurrent rename, reparse, type/ID mismatch and sharing tests before enabling adapter. |

The candidate currently uses legacy identity fields, not FileIdInfo. A future
ReFS-compatible design should review 128-bit FILE_ID_INFO rather than presume
legacy indices are sufficient. FileAttributeTagInfo provides attribute/tag data;
no attribute query by itself authenticates content or prevents later changes.

The handle-ownership requirement follows the CRT documentation: after successful
_open_osfhandle adoption the descriptor owns the handle, so close through the
stream/descriptor, not a second CloseHandle. No adoption path was executed here.

D: delete-sharing restrictions apply to rename/delete requests on the opened
object. I: retaining validated parent handles can constrain certain substitution
attempts, but does not block all child changes, metadata changes, volume remaps,
privileged actors, filters or case/alias behavior. A held handle identifies an
object even if its namespace changes; reconstructing its pathname and reopening
is a new lookup. Do not derive full containment from identity equality.

Sources (official, retrieved for this stage):
- [CreateFileW flags, sharing, access](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
- [Legacy handle metadata](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle)
- [GetFileInformationByHandleEx](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex)
- [FILE_ID_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info)
- [FILE_ATTRIBUTE_TAG_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_attribute_tag_info)
- [GetFileType](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfiletype)
- [Python open_osfhandle](https://docs.python.org/3.12/library/msvcrt.html#msvcrt.open_osfhandle)
- [NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile)

### Timeouts: separate meanings

1. Cooperative deadline: Budget checks between operations. It cannot interrupt
   an already blocked synchronous call or decompression.
2. Hard wall-time budget: desired supervisor bound, not currently implemented or
   proven for startup, driver I/O, process termination or result collection.
3. Forced termination: future parent would act only on its owned child handle;
   no PID/name lookup, unrelated process or unbounded output collection.
4. Actual exit: TerminateProcess is asynchronous; I/O cancellation may delay exit.
   An expired bounded wait means BLOCKED, not successful termination.
5. Partial operations: killing a future placement worker cannot roll back copied
   bytes, temporary files or partial trees. No cleanup or retry follows implicitly.
6. Independent filesystem verification: later parent inspection must check
   incomplete tree, temp file status, sentinels and missing readiness evidence.
   Exit 0, report text or matching refusal is insufficient.

[TerminateProcess reference](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess).
No worker, process control or filesystem adapter was implemented in this stage.

### Latest status matrix

| Item | Status | Actual evidence |
|---|---|---|
| Pure descriptions parser | PASS | 17 new tests plus prior 41: 58 total, no failure, exit 0 |
| AST / in-memory compilation | PASS | Both Python files; no pyc |
| Preflight | BLOCKED | Unconditional refusal retained; not invoked |
| Safe tree enumeration | BLOCKED | API design only, no implementation/Windows evidence |
| Hard timeout | BLOCKED | Design/pure policy only, no worker evidence |
| Claimed readiness of harness | FAIL | Critical blockers are open |
| Real ZIP/package compatibility | NOT TESTED | Neither read nor enumerated |
| Windows integration / placement | NOT TESTED | No API calls, fixtures or worker |

Future tests must cover each row's confirmation column, including malformed binary
buffer offsets/alignment/UTF-16, concurrency at each open, unsupported metadata
classes, bounded resources before payload read, pending-I/O termination, failed
termination, incomplete reports and independent partial-state inspection.
The description parser is NOT a binary FILE_ID_BOTH_DIR_INFO parser.

Next safe step: review the proposed adapter signatures and build a pure binary
record parser if that API contract is chosen, still without OS calls. Any later
Windows tests require separately approved disposable fixtures and exact scope;
keep real package, preflight and placement disabled.


Final documentation clarification: FILE_ID_BOTH_DIR_INFO explicitly documents no
specific access rights for querying that information. Earlier proposals to
request FILE_LIST_DIRECTORY describe conservative adapter access, not a proven
API requirement. Validate actual supported access masks before implementation.
File IDs may be reused over time; do not confuse FileIndex (directory position,
undefined on NTFS) with FileId (object reference).

- [Directory structure, rights, identity limits](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_both_dir_info)
- [CRT ownership transfer](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/open-osfhandle?view=msvc-170)

Final verification after the schema length guard: 58 tests, 0 failures/errors,
0 skipped, exit 0, 0.117 s. AST/compile passed for both Python files. The earlier
verbose run also passed all 58 (0.500 s). No filesystem integration took place.


## Current stage: pure FILE_ID_BOTH_DIR_INFO binary parser

This section supersedes earlier next-step proposals to build a binary parser.
Only probe.py, test_probe_logic.py and REVIEW.md were changed. All OS/placement
entry points remain disabled. Synthetic bytes are the only input tested.

### ABI justification (documented declaration + derived x64 layout)

The layout target is the default Windows x64 SDK C declaration, little-endian.
No ctypes, SDK compilation, host-native struct packing or Windows API was used.
Offsets are calculated by id_both_layout from field order, Windows widths and
natural alignment. They are not guessed or taken from host platform C types.

| Field | Windows type / bytes | Alignment | Derived offset |
|---|---|---|---|
| NextEntryOffset | DWORD / 4 | 4 | 0 |
| FileIndex | DWORD / 4 | 4 | 4 |
| CreationTime | LARGE_INTEGER / 8 | 8 | 8 |
| LastAccessTime | LARGE_INTEGER / 8 | 8 | 16 |
| LastWriteTime | LARGE_INTEGER / 8 | 8 | 24 |
| ChangeTime | LARGE_INTEGER / 8 | 8 | 32 |
| EndOfFile | LARGE_INTEGER / 8 | 8 | 40 |
| AllocationSize | LARGE_INTEGER / 8 | 8 | 48 |
| FileAttributes | DWORD / 4 | 4 | 56 |
| FileNameLength | DWORD / 4 | 4 | 60 |
| EaSize | DWORD / 4 | 4 | 64 |
| ShortNameLength | CCHAR / 1 | 1 | 68 |
| implicit padding | 1 | - | 69 |
| ShortName | WCHAR[12] / 24 | 2 | 70 |
| implicit padding | 2 | - | 94 |
| FileId | LARGE_INTEGER / 8 | 8 | 96 |
| FileName[1] | WCHAR / 2, followed by variable name | 2 | 104 |

DWORD is 32-bit, CCHAR 8-bit, WCHAR 16-bit; LARGE_INTEGER contributes an aligned
8-byte member. The x64 ABI rounds each member to its alignment and aggregate
size to 8. Thus the fixed prefix before FileName is 104 bytes; the declaration
with FileName[1] has derived sizeof 112 including tail padding. The parser uses
104 + FileNameLength, NOT sizeof as the variable-name offset. This derivation
supports default x64 layout only, not arbitrary packing or other ABI claims.

Microsoft explicitly requires 8-byte record alignment and aligned nonterminal
NextEntryOffset. MS-FSCC independently details the corresponding binary field
widths, byte-counted names and padding. It is corroborating format documentation,
not a claim that a native API allocation is an SMB wire packet. Final variable
record does not need a rounded-up tail. The minimum accepted nonempty-name span
is 106 bytes; subsequent starts must be 8-aligned relative to buffer offset 0.
The actual allocation base address is not observable from this bytes parser.

Official references retrieved:
- [Native declaration and 8-byte alignment](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_both_dir_info)
- [Windows scalar widths](https://learn.microsoft.com/en-us/windows/win32/winprog/windows-data-types)
- [x64 member/aggregate layout](https://learn.microsoft.com/en-us/cpp/build/x64-software-conventions?view=msvc-170)
- [Binary field descriptions and padding](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/1e144bff-c056-45aa-bd29-c13d214ee2ba)

### Pure parser contract

parse_id_both_buffer accepts exact immutable bytes only. Bytearray/memoryview and
subclasses are rejected, avoiding mutable input during parsing. Input must be the
logical chain span, optionally with <=7 terminal padding bytes. It must NOT be an
arbitrary capacity-sized OS buffer. Establishing valid span length is a future
adapter BLOCKER: this function cannot infer bytes returned from buffer capacity.

Bounds before decoding: <=64 KiB input, >=106 bytes; <=256 records; name lengths
positive/even and <=510 bytes; active short-name length signed, even, 0..24;
long + active short-name bytes <=8192 per buffer. NextEntryOffset is unsigned,
forward, aligned, outside the fixed prefix, and leaves a complete next record
inside the buffer. Offsets equal to the end mean missing terminator. A name must
fit entirely in its own record, never spill into the next header. Strict forward
movement plus the record cap prevents cycles and reused offsets without an
unbounded visited set. Zero step terminates exactly once, with no following read.

UTF-16LE decoding is strict, including active short-name bytes. Long and short
names must be a single conservative Windows component; dot/dotdot, separators,
ADS, device names, NUL and ambiguous spellings are refused. Original Unicode and
case are preserved. Casefold duplicate long names within a buffer are refused.
No long/short alias resolution or inter-buffer duplicate detection is claimed.

Attribute policy is deliberately narrower than Windows: allow READONLY(1),
HIDDEN(2), SYSTEM(4), DIRECTORY(0x10), ARCHIVE(0x20), NORMAL(0x80),
TEMPORARY(0x100), COMPRESSED(0x800), or zero. NORMAL cannot combine with other
attributes. Reject REPARSE_POINT, DEVICE and every unknown/unlisted bit. This is
harness policy, not an exhaustive statement of valid Windows attributes. Type is
inferred only from DIRECTORY; this is not an actual object-type check.
EndOfFile/AllocationSize are decoded as signed 64-bit and negative values refused;
file EOF <=512 MiB. Directory output size=None; raw directory size is not used.
No assumption that allocation >= EOF (sparse/compressed cases exist).

FileId is preserved as exactly eight opaque bytes encoded as hex, with no signed
numeric meaning. FileIndex, timestamps and EaSize are not used as identity or
validated semantically; this is not a complete MS-FSCC protocol validator.
No timestamp validation, EA validation or allocation/cluster-size validation is
claimed. Other stored metadata fields cannot authenticate the real object.

Unused short-name storage and padding are ignored, not required zero. Terminal
span restriction (<=7 bytes) is an explicit conservative harness input policy;
Windows documentation does NOT promise at most seven unused bytes in a returned
capacity buffer. Excess tail yields TERMINAL_SPAN_POLICY, not an assertion of OS
corruption. The parser cannot discover unlinked records hidden in unused padding.

Success: VALIDATED_BINARY_DESCRIPTIONS, records in chain order, name_bytes.
Each record has original name, type, size, attributes, raw file_id and short_name.
Refusal: REFUSED/error(code,offset), no records or partial inventory. Only the
component's own BinaryDirectoryRefusal is converted; strict decode errors map
to INVALID_UTF16. Unexpected exceptions propagate. No file/path/ZIP/API access
occurs anywhere in the binary parse call graph.

### Unit tests and actual results

Command (same fixed Python 3.12 runtime, isolated import mode, bytecode disabled):

```powershell
& 'C:/Users/Икрам/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -I -B -m unittest discover -s D:/nexus2/launcher-next/desktop_placement_review -p test_probe_logic.py -q
```

- Initial binary additions: 84 tests, OK, exit 0 (0.175 s).
- Expanded run: 90 tests, one failure, exit 1. The aggregate-name boundary fixture
  contained 8176 bytes, not the asserted 8192; parser returned the correct count.
  Only fixture name length was corrected: 16*510 + 32 = 8192; limit unchanged.
- Final run: **90 tests, 0 failures/errors, 0 skipped, exit 0 (0.139 s)**.

All prior 58 tests retained; 32 binary-parser tests added. The binary fixture
builder uses an independent literal layout and struct.pack_into, not parser
constants for offsets. Tests include every requested error class, active short
names, terminal padding, partial-result refusal, 256-record boundary, exact
8192-byte names budget, opaque field boundaries, 250 seeded random buffers and
unexpected-error propagation. No external files/fixtures/processes were used.
AST parsing and compilation in memory are performed separately; no pyc creation.

### Current status and remaining blockers

| Component | Status | Scope of evidence |
|---|---|---|
| Binary parser | PASS | Tested synthetic inputs and stated conservative policies only |
| Existing description / resource / worker-policy tests | PASS | Pure in-memory checks retained |
| AST / compile | PASS | Both Python sources, in-memory compilation |
| Runtime Windows ABI compatibility | NOT TESTED | No SDK compilation, API invocation or OS buffers |
| Valid native-buffer span extraction | BLOCKED | Capacity is not valid length; adapter contract unresolved |
| Windows filesystem adapter / tree enumeration | BLOCKED | No handle-relative enumeration/open adapter or race evidence |
| Hard timeout | BLOCKED | No worker, cancellation or pending-I/O integration tests |
| Preflight / placement / installer readiness | BLOCKED | Preflight remains unconditional refusal; no experiment |

Successful binary parsing proves neither containment nor TOCTOU safety, stable
identity, safe later open, Authenticode, publisher trust or install readiness.
Native Windows dot entries and some valid attribute combinations are intentionally
refused; a future adapter must explicitly handle that policy, never silently
weaken it. No assurance that existing beta2 can be enumerated by this candidate.

Next safe step: code-only agreement on valid-length extraction, handling of dot
entries and the exact handle-relative adapter boundary. Native ABI and race
behavior then need a separately authorized disposable Windows integration plan.
Hard timeout remains open: cooperative deadline cannot interrupt a stalled call,
forced process termination may await I/O, and partial files require independent
inspection. No worker or process-control implementation was added.

The real package and ZIP were neither read, hashed nor enumerated. No Windows
API/ctypes adapter/Native API, worker, preflight or placement was invoked. No
experiment directory, fixture or sentinel was created; production is unchanged.


## Current stage: proposed Windows directory adapter contract (NOT implemented)

Current result supersedes previous next-step suggestions. Three review files only:
probe.py adds page-length and child-name policy functions; test_probe_logic.py
adds 14 pure tests; this report records the contract. No adapter/worker was added.

### A. Capacity, completed bytes and logical record span

DOCUMENTED: GetFileInformationByHandleEx takes an input dwBufferSize and returns
BOOL. Its signature provides no separate used-byte output. FILE_ID_BOTH_DIR_INFO
links records by NextEntryOffset and marks the last with zero. Neither capacity
nor trailing zero bytes are an actual returned-byte count.

INFERENCE, not implemented: on a confirmed successful Win32 call, a bounded
chain walk could compute a candidate logical end from the terminal record's
start + 104 + FileNameLength. It would validate each offset/name within capacity,
stop at the first terminal entry and ignore the tail. That yields a record-chain
span derived from content, NOT an independent count of bytes written. No scan
for zero padding, sizeof rounding or parsing until capacity is acceptable.
This option remains BLOCKED pending an explicit adapter contract and OS tests;
it must not be silently wired into the existing strict parser.

DOCUMENTED ALTERNATIVE: NtQueryDirectoryFile reports actual bytes written in
IO_STATUS_BLOCK.Information for completed successful data returns. This is a
routine-specific meaning; NtCreateFile.Information instead reports an open/create
outcome, NOT a byte count. Only final completion status plus this documented count
can bound the native data span. Native FILE_INFORMATION_CLASS values are distinct
from Win32 FILE_INFO_BY_HANDLE_CLASS: do not reuse Win32 class 0xa as a Native
class value. Select FileIdBothDirectoryInformation by the correct SDK definition.

Proposed native span pipeline (design only):
1. Fresh bounded buffer, sole outstanding query on a held directory, no concurrent
   enumeration on that handle. Bind final status and byte count to this query.
2. Await actual completion; STATUS_PENDING is INCOMPLETE. Never inspect a pending
   buffer or release its storage while I/O may still reference it.
3. Only confirmed successful data completion with integer 0 < Information <=
   capacity <=64 KiB can expose bytes [0:Information]. Wrong type/range is REFUSED.
4. Independently walk within that range to establish the terminal logical end.
   Bound all fields/offsets; compute the end, never scan for zeros. Ignore
   post-terminal bytes as unspecified unused output; keep both lengths in evidence.
   The parser then receives the exact logical record-chain span, not capacity.
5. Parse and validate structure/names before accepting records; completion and
   length alone mean STRUCTURAL_VALIDATION_REQUIRED, not safe objects or PASS.
6. STATUS_SUCCESS with Information=0 is INCOMPLETE, NOT end-of-directory. A known
   final no-more-files status with no data may terminate enumeration. Buffer
   overflow/truncated records are INCOMPLETE; stop without retry/resize/restart.

The documentation discusses increasing a buffer after empty-success cases. This
harness deliberately stops instead: a fail-closed policy, not a claim that such
responses are invalid Windows behavior. Unknown/error status is REFUSED. A last
record with NextEntryOffset=0 ends a PAGE only, not the entire directory scan.

page_length_policy implements only these decisions on artificial metadata.
VALIDATED means self-consistent proposed protocol input, never verified OS
provenance. No slicing/extraction or status/ABI adapter is implemented. The
length-source question is documented for Native queries, but end-to-end span
extraction/runtime compatibility remains BLOCKED.

Official references retrieved for this stage:
- [Win32 signature and capacity](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex)
- [Record chain](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_both_dir_info)
- [Native query byte count, statuses, concurrency](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntquerydirectoryfile)
- [IO_STATUS_BLOCK](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdm/ns-wdm-_io_status_block)

### B. Dot entries: explicit audit-only policy, no parser weakening

Exact names '.' and '..' describe self/parent, not ordinary descendants. Never
open, recurse, join them into a path or use '..' to find the root's parent.
A future structural decoder must first validate full boundaries, UTF-16, lengths
and attributes of ALL records, then classify special entries explicitly. It may
not catch INVALID_NAME from the strict parser and skip a supposedly bad record.
The existing binary parser still rejects dots; this stage does not change it.
Integration of a structural/special-policy stage is therefore a remaining gap.

child_name_policy accepts artificial name/type/attributes only. For special
names it requires directory type plus DIRECTORY attribute, no reparse/device or
unlisted attributes; inconsistent type/attribute causes REFUSED. Valid-looking
dots return AUDIT_SKIP_NO_OPEN with DOT_SELF or DOT_PARENT. They must be counted
against raw record/page/session budgets and recorded as special audit events,
not omitted silently or inserted into inventory. Repeated dots across a scan
must stop the session as duplicate/progress failure rather than enable retries.
Neither special entry is required to be present.

FileId is not required nonzero and '..' ID is not trusted as a parent authority.
No comparison/open of its referent is needed. EOF/EA/timestamps cannot prove its
identity; structural lengths/attributes must still be checked by the decoder.
Any unexpected type/attribute is REFUSED for the session, not silently ignored.
Names like '../x', './x', '. ', '...' and separators receive CHILD_NAME refusal.
These are policy tests, not evidence that actual dot records were inspected.

[Binary name and dot-entry semantics](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/1e144bff-c056-45aa-bd29-c13d214ee2ba).

### C. Handle-relative child opening: proposal, not openat equivalence

CreateFileW has no RootDirectory parameter. An absolute reconstructed path is
another namespace lookup; even retained parents and matching IDs do not turn it
into handle-relative access.

NtCreateFile documents ObjectAttributes.RootDirectory and a relative ObjectName.
Proposed child operation borrows the held directory and passes exactly ONE
validated component (no separators, dot names, drive, ADS, aliases supplied as an
alternate lookup or absolute path). Use FILE_OPEN, FILE_SHARE_READ only, null EA,
no create/overwrite/delete dispositions. Read/list access, FILE_READ_ATTRIBUTES
and SYNCHRONIZE are requested only as required for the operation. Candidate uses
FILE_SYNCHRONOUS_IO_NONALERT with SYNCHRONIZE and FILE_OPEN_REPARSE_POINT so final
reparse processing is bypassed; inspect returned attributes and refuse reparse.

Do not assume FILE_DIRECTORY_FILE can simply be combined with every no-follow
option: the NtCreateFile page restricts combinations. A type-neutral metadata/
read/list open followed by handle-based type validation is a candidate requiring
review, not a confirmed parameter recipe. Exact access masks, x64 structures,
user-mode bindings and filesystem/Windows compatibility remain BLOCKED. No
OBJ_DONT_REPARSE guarantee is assumed from third-party discussions.

Post-open (before enumeration/data read): require a disk object; correct directory
or file type; no reparse attribute/tag; expected volume serial equals parent/root;
compatible supported file ID equals enumeration evidence when comparison is
available; match name/type/size evidence, reject observed change without retry.
Legacy 64-bit IDs versus 128-bit FileIdInfo must be explicitly compatible. Zero,
unsupported or incomparable identity is BLOCKED, not accepted on pathname alone.
IDs are evidence, not provenance; no claims against reuse over time or mappings.

The parent and ancestor handles remain held until descendant handles close.
Do not reopen by absolute pathname after validation or CRT adoption. Volume/ID
checks do not freeze directory contents. A name may change between enumeration
and open; retained parent alone does not stop child writes, new children, alias
lookup, metadata changes or privileged/kernel/filter actors. Enumeration is not
an atomic snapshot. This design narrows lookup, but is not a proven POSIX openat
equivalent or full containment/TOCTOU proof.

- [NtCreateFile parameters](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile)
- [CreateFileW parameters](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)

### D. Proposed interface, written as contract only

No Protocol, ctypes wrapper, adapter class or runnable method is implemented.
Opaque handle tokens below represent adapter-owned OS objects, not caller PIDs
or trusted integer values supplied by a server/record.

| Proposed operation | Inputs / outputs | Ownership and refusal boundary |
|---|---|---|
| open_root(root_spec, limits) | Restricted configured local root -> VALIDATED(root token, volume, ID) or REFUSED/BLOCKED | Opens existing only; validates ancestors/root without traversal; root establishment unresolved. Adapter owns token; no token returned on uncertain open. |
| next_page(directory token) | Borrowed root/child dir -> VALIDATED(page + count/provenance + cursor evidence), explicit END, INCOMPLETE, REFUSED or BLOCKED | One outstanding call; returned bytes immutable; directory token held; final status/count belongs to this query. Terminal record does not imply directory END. |
| classify_special(record) | Structurally validated record -> audited skip or refusal | No opening, path joining, recursion, child token or inventory insertion. Count event against limits. |
| open_child(parent token, single component, expected evidence) | Borrowed parent -> VALIDATED(child token + observed type/volume/ID), REFUSED/INCOMPLETE/BLOCKED | Native handle-relative only; no fallback absolute path. Newly acquired handles closed if validation fails; uncertain I/O ownership retained, not fabricated as closed. |
| close_owned(token) | One owned token -> confirmed closed or BLOCKED | Exactly once, children before parents. Caller cannot close borrowed handle. CRT adoption transfers leaf ownership; no double CloseHandle. |
| finish(session) | Explicit directory END for every admitted directory + complete evidence | This scope never emits installed/ready/PASS. Any incomplete/refused/blocked event poisons session; independent verification still required. |

VALIDATED refers to one operation's stated evidence only; REFUSED is a known
policy/input violation, INCOMPLETE is unfinished/truncated operation, BLOCKED is
an unproven guarantee or unsupported mechanism. Unexpected exceptions propagate
and abort, never success. No partial inventory is accepted after uncertain state.
Closing owned OS resources is not file cleanup. No file deletion, retry, restart,
new replacement worker or automatic cleanup is authorized on any error.

Proposed session limits: 64 KiB/page; <=256 records/page; <=8192 active-name bytes/
page; <=4096 nodes total including special records; <=2048 ordinary files; depth
<=32; relative UTF-16 <=1024 units; <=512 MiB/file, <=1 GiB declared file total;
<=3 GiB actual reads shared with ZIP/reference; <=1024 page calls globally,
including empty/error calls. Each directory needs one explicit END; cap also
prevents endless empty/duplicate pages. No arbitrary OS enumeration sort order
assumption. Pure worker policy/deadline remains separate and NOT a hard timeout.

These are fail-closed harness limits; some otherwise valid trees will be refused.
Current helpers do not yet enforce global page/dot/cursor accounting. A complete
adapter would need that implementation and a reviewed bounded-resource protocol.

### Verification and current status

Actual command: the fixed Python -I -B unittest discover command recorded above.
Result: **104 tests, 0 failures/errors, 0 skipped, exit 0, 0.184 seconds**.
All prior 90 tests retained; 14 policy tests added. They check capacity versus
count, pending/overflow/zero-success, explicit END, invalid counts, dot auditing,
wrong attributes/types, dotlike traversal and unchanged strict parser refusal.
No mock or fabricated API response is represented as Windows security evidence.

| Item | Status | Basis |
|---|---|---|
| Contract-policy logic | PASS | In-memory unit tests |
| AST/compile | PASS | In-memory syntax checks of both Python files |
| Win32 used-byte count source | BLOCKED | No separate documented output; content-derived span not independent count |
| Native byte-count mechanism | Documented, NOT TESTED | NtQueryDirectoryFile Information; no binding/extraction implemented |
| Dot policy | PASS for pure policy; integration BLOCKED | Strict parser intentionally unchanged; structural routing not implemented |
| Root / handle-relative containment | BLOCKED | Exact parameter recipe and OS evidence pending |
| Enumeration / hard timeout / harness readiness | BLOCKED | No adapter, worker or runtime tests |

Required future checks: exact query class/ABI and byte count versus oversized
capacity; nonzero tail; partial overflow/zero-success; multiple pages ending only
on explicit status; audited dots and reparse/type anomalies; parent/child rename
and replacement races; volume and 64/128-bit identity mismatches; cursor/entry/
byte limits; pending buffer lifetime; close failures; process timeout and partial
state under a later separately authorized plan using disposable fixtures.

Next safe step: agree the Native-based contract and API parameter review, resolve
type-neutral directory no-follow and root establishment, then prepare a separate
Windows integration plan. Do not enable preflight from these policy tests.
One attempted optional Microsoft IFS documentation URL returned an error; no
assumption or guarantee is based on that unavailable page.

No Windows API, Native/ctypes adapter, worker or preflight was invoked. The real
package/ZIP was not read, hashed or enumerated. No experiment directory, fixtures,
sentinels or external reports were created. Production/configuration unchanged.


## Current review: Native API, root establishment, ownership and resource contract

This is the latest stage. Earlier proposal/verification sections remain historical.
No adapter or worker was implemented. Only the three permitted review files were
changed. native_query_result_policy is symbolic pure policy; it makes no Native
calls and cannot translate raw statuses, establish handles or validate OS evidence.

### Classification of evidence

D = directly documented; I = conservative design inference/policy;
T = needs future Windows integration evidence. PASS in the tables means executed
pure tests or static verification only, never observed operating-system behavior.

### Native signatures and ABI review (D, derived x64 offsets, T for live binding)

NtQueryDirectoryFile, in declaration order:

| Parameter | ABI type / role | Proposed binding contract, not implementation |
|---|---|---|
| FileHandle | HANDLE input | Held directory from NtCreateFile/NtOpenFile, never substituted by name |
| Event | optional HANDLE | NULL in proposed synchronous mode |
| ApcRoutine | optional function pointer | NULL; no APC callback implementation |
| ApcContext | optional PVOID | NULL; no completion-port/APC association assumed |
| IoStatusBlock | pointer to IO_STATUS_BLOCK | Stable owned storage until actual completion |
| FileInformation | output PVOID | Owned aligned buffer, not immutable bytes until completed |
| Length | ULONG, 32-bit capacity | <=64 KiB; distinct from used bytes |
| FileInformationClass | FILE_INFORMATION_CLASS, 32-bit enum | Native FileIdBothDirectoryInformation=37 |
| ReturnSingleEntry | BOOLEAN, 8-bit | FALSE for bounded packed pages |
| FileName | optional UNICODE_STRING pointer | NULL; no wildcard/filter state |
| RestartScan | BOOLEAN, 8-bit | First scan only; no restart/retry after uncertainty |

D: non-NULL Event or APC routine requires an asynchronously opened file object.
I: synchronous mode with null callback/event simplifies ownership but can block;
it is not a timeout mechanism. ReturnSingleEntry is BOOLEAN, not Win32 BOOL.
No raw syscall numbers or user-mode ctypes imports were added.

IO_STATUS_BLOCK: union(NTSTATUS Status, PVOID Pointer), then ULONG_PTR Information.
Derived default x64 union is 8 bytes aligned 8; Status is signed 32-bit at offset
0, reserved Pointer overlays offset 0; Information is pointer-sized unsigned
64-bit at offset 8; sizeof=16. Do not model Information as DWORD or read Pointer.
Its meaning is request-dependent, not universally a byte count.

NtCreateFile parameter order: PHANDLE FileHandle; ACCESS_MASK DesiredAccess;
POBJECT_ATTRIBUTES ObjectAttributes; PIO_STATUS_BLOCK IoStatusBlock;
optional PLARGE_INTEGER AllocationSize; ULONG FileAttributes; ULONG ShareAccess;
ULONG CreateDisposition; ULONG CreateOptions; optional PVOID EaBuffer;
ULONG EaLength. NTSTATUS is the return value, not a BOOL. Returned Information
identifies FILE_OPENED/other create disposition outcome, not query buffer size.

Default x64 OBJECT_ATTRIBUTES derivation:
Length ULONG at 0; four-byte pad; RootDirectory HANDLE at 8; ObjectName pointer
at 16; Attributes ULONG at 24; four-byte pad; SecurityDescriptor pointer at 32;
SecurityQualityOfService pointer at 40; sizeof=48, alignment=8.
UNICODE_STRING: USHORT Length at 0, USHORT MaximumLength at 2, four-byte pad,
PWSTR Buffer at 8; sizeof=16. Lengths are byte counts, not Python character counts.
No assumptions about alternative packing, x86 or ARM64 ABI are made.

The existing variable record layout remains default x64, prefix 104 / FileId 96.
The Native FILE_ID_BOTH_DIR_INFORMATION declaration uses signed LARGE_INTEGER
fields and WCHAR names; its matching physical layout must be verified in any
future binding. Native class 37 is NOT Win32 FileIdBothDirectoryInfo 10 (0xa).
These are separate enums even when their returned structure layouts correspond.

Sources retrieved:
- [NtQueryDirectoryFile signature](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntquerydirectoryfile)
- [IO_STATUS_BLOCK and return-status precedence](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdm/ns-wdm-_io_status_block)
- [NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile)
- [OBJECT_ATTRIBUTES](https://learn.microsoft.com/en-us/windows/win32/api/ntdef/ns-ntdef-_object_attributes)
- [UNICODE_STRING](https://learn.microsoft.com/en-us/windows/win32/api/ntdef/ns-ntdef-_unicode_string)
- [Native enum, value 37](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdm/ne-wdm-_file_information_class)
- [Native record declaration](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_id_both_dir_information)
- [x64 ABI alignment](https://learn.microsoft.com/en-us/cpp/build/x64-software-conventions?view=msvc-170)

### Completion and Information interpretation

D: after direct STATUS_PENDING, wait for independently established completion and
then consult IOSB.Status. For non-pending return, use the direct return status,
not an IOSB status that may differ. The native_query_result_policy function uses
symbolic labels only; pending_completed is a caller-supplied test input, NOT proof
of a real signal, completion or ownership. An adapter must establish that proof.
No broad NT_SUCCESS acceptance is used: pending/informational values are not data.

| Effective status / condition | Contract result | Information / bytes allowed |
|---|---|---|
| Direct STATUS_PENDING, completion not confirmed | INCOMPLETE | No IOSB/buffer consumption or reuse, regardless of stale success |
| Pending completion claimed but final status missing or still pending | BLOCKED | Completion unconfirmed; no span |
| STATUS_SUCCESS, 106 <= Information <= capacity <=64 KiB | VALIDATED metadata only | Candidate [0,Information); full structural validation still mandatory |
| STATUS_SUCCESS, Information=0 | INCOMPLETE | Not EOF; stop without retry/resize |
| Success with invalid count/type, count>capacity or short span | REFUSED | No data accepted |
| STATUS_NO_MORE_FILES, Information=0 | VALIDATED END only | No records; this is not install/readiness success |
| STATUS_NO_MORE_FILES with nonzero/unknown Information | REFUSED | Conservative end consistency requirement; no capacity or zero-tail inference |
| STATUS_BUFFER_OVERFLOW / STATUS_BUFFER_TOO_SMALL / STATUS_INFO_LENGTH_MISMATCH | INCOMPLETE | Never parse returned partial bytes; no automatic retry |
| STATUS_CANCELLED | INCOMPLETE | No records, no inference of closed handles or absence of partial work |
| STATUS_NOT_SUPPORTED / STATUS_NOT_IMPLEMENTED / STATUS_INVALID_INFO_CLASS | BLOCKED | No fallback to different enum/unsafe absolute lookup |
| Other error, warning or informational label | REFUSED | Fail closed; no generic success classification |

STATUS_NO_MORE_FILES is an explicitly accepted terminal warning, not a generic
NT_SUCCESS case. D: routine-specific successful query data has a byte count.
I: the strict zero-Information EOF consistency requirement and stopping on empty
success are harness policies, not universal assertions about all driver behavior.
No data from failed/open/cancelled operations is promoted to a byte span.
Post-terminal unused tail and independent logical-span extraction remain unresolved
in code. This new policy does not remove the existing parser's tail restrictions.

### Root establishment and component guarantees

Root remains BLOCKED. A syntactically local drive path and fixed-disk check are
not proof of stable volume mapping, root ownership or namespace containment.
Opening the whole absolute root with a final-component no-follow flag does not
prove ancestors were not traversed. Reconstructing paths after holding handles
remains new name lookup; it is not handle-relative validation.

| Component | D / I boundary | Residual issue |
|---|---|---|
| Initial volume/root anchor | D: absolute names and relative root handles are supported | Mapping the configured drive/volume to the intended trusted filesystem and rejecting object-manager aliases is not designed/proven |
| Each filesystem ancestor | D: no-follow flag applies to opened file object; handle can query attributes | Exact relative open, required rights and returned type/volume checks need confirmed recipe and tests |
| Reparse components | D: FILE_OPEN_REPARSE_POINT bypasses normal final reparse processing | Never assume it protects unvalidated earlier components or arbitrary object-manager indirection |
| Held parent | I: no delete-sharing may constrain competing rename/delete opens | Does not freeze child entries, all attribute changes, volume mappings or privileged/filter actions |
| Concurrent rename/replacement | D: enumeration may observe changes or miss them | Compare actual handle evidence and refuse observed mismatch; no atomic snapshot/identity persistence claim |

Existing windows_read is a dormant previous candidate, NOT an approved root or
Native adapter. Do not call it to satisfy this review. No new fallback was added.

### File and directory child recipes: reviewed, still BLOCKED

D: RootDirectory can designate a filesystem directory or an object-manager
directory; the proposed token must specifically be a validated filesystem
DIRECTORY on the intended disk/volume, not just any valid HANDLE. ObjectName must
be exactly one preserved validated child component; no drive/separator/dot/ADS.
Borrow parent until child validation/close finishes. FILE_OPEN only, no write,
append, overwrite, delete-on-close or creation flags. FILE_SHARE_READ only is a
design choice subject to compatible existing opens; it can fail legitimately.

File candidate: READ_DATA + READ_ATTRIBUTES, SYNCHRONIZE for synchronous mode,
FILE_NON_DIRECTORY_FILE and FILE_OPEN_REPARSE_POINT, with
FILE_SYNCHRONOUS_IO_NONALERT. D: NON_DIRECTORY excludes directories but may still
represent devices/volumes; it is NOT regular-file authentication. T: validate
disk type, no reparse/tag, supported file ID, volume, expected name/type/size and
single-link policy before payload reads; exact combination and binding untested.

Directory candidate: LIST_DIRECTORY + READ_ATTRIBUTES, optional justified
TRAVERSE, SYNCHRONIZE for synchronous mode. FILE_DIRECTORY_FILE constrains type,
but Microsoft's documented list of compatible options does not explicitly
include FILE_OPEN_REPARSE_POINT. Do NOT declare that combination safe because it
seems to work elsewhere. A type-neutral open then validate directory proposal
is NOT a confirmed alternative: exact valid access/options/no-follow behavior
still requires authoritative clarification and Windows evidence.

No guessed bitmask or OBJ_DONT_REPARSE promise was selected. SecurityDescriptor,
EA, AllocationSize and inheritance choices must not create/change objects;
OBJECT_ATTRIBUTES.Length must match the confirmed ABI. Access rights affect
what can be queried, not which security guarantees automatically follow.
Post-open type/attributes/volume/64-or-128-bit ID comparisons can detect changes,
but do not prove stable containment or safe subsequent lookup. Keep actual
validated handle for reading; no absolute reopening after the comparison.

### Ownership states and uncertainty (contract only)

- VALIDATED: one operation's documented evidence and checks succeeded. Not a
  globally safe tree, publisher proof, install readiness or final PASS.
- REFUSED: known input/policy/error outcome; abort. It does not authorize cleanup.
- INCOMPLETE: operation pending, truncated, cancelled or lacking complete data.
  Keep operation storage and tokens accounted for; never accept partial inventory.
- BLOCKED: required guarantee unsupported/unproven or ownership/closure uncertain.
  Stop without retry, fallback, new worker or pretending the token was released.

A future owner registry must track: no token, owned-and-open, borrowed, in-flight,
closing, confirmed-closed and closure-unknown. Only the owning scope can close;
children before parents; borrowing lasts until dependent operation finishes.
On ordinary validation refusal, close only known-owned, non-pending resources
and verify the close result. This is resource release, not filesystem cleanup.
If close fails or final I/O completion is unknown, retain uncertainty in the
ledger and return BLOCKED; do not retry the same possibly-invalid numeric handle
(it could be reused), discard storage, double close, or label it confirmed closed.
No actual owner registry or close logic was implemented in this stage.

Creation/open returning pending must not expose an unvalidated handle for use.
Keep request/OBJECT_ATTRIBUTES/UNICODE_STRING/buffer lifetimes until completion;
what can safely be released in each real call is T. CRT adoption transfers leaf
ownership; before adoption failure the original owner remains responsible. No
mixing CloseHandle and descriptor close, no parent close while borrowed.
Cancellation request or worker kill request alone does not prove operation exit.

### Limits review: before work versus missing integration

| Limit | Current enforcement | Before unbounded work? / gap |
|---|---|---|
| 64 KiB page capacity | Pure page policy and binary parser | PASS for supplied in-memory inputs; no API dispatch gate exists |
| 256 records, 8192 active name bytes/page | Binary parser before decode/append | PASS for synthetic buffers only |
| Nodes/files/depth/path/declared sizes | TreeLedger / descriptions parser | PASS pure tests; not integrated with actual enumeration |
| 1024 page calls globally, including empty/error | Proposed contract only | BLOCKED: must reserve before issuing each query, never after |
| Global dot/cursor duplication/progress | Proposed contract only | BLOCKED: count dots before skipping, no restart on uncertain progress |
| 3 GiB actual reads | Budget/hash/ZIP pure primitives | Needs future common ledger; no claim of actual I/O accounting |
| Time deadline | Cooperative checks only | BLOCKED for hard timeout; stuck call/process exit may exceed budget |

Even process termination may wait for pending I/O. No fixed bound on OS/driver
termination is proved. Parent must not accept a success message after timeout;
partial files/sentinels require independent later inspection in a separately
authorized placement experiment. No worker or interruption experiment occurred.

### Question / documented guarantee / risk / evidence / status

| Question | Documented guarantee | Remaining risk | Required evidence | Status |
|---|---|---|---|---|
| Native class value | FILE_INFORMATION_CLASS lists FileIdBothDirectoryInformation=37 | Confusion with Win32 10 or wrong returned structure | SDK ABI/class binding verification | D confirmed; runtime NOT TESTED |
| Status authority | Pending -> completed IOSB; otherwise direct return | Stale IOSB or premature buffer reuse | Pure policy PASS; actual completion/lifetime test still needed | PASS policy / NOT TESTED runtime |
| Query byte count | Successful query Information is bytes written | Wrong routine/count, capacity confusion, unused tail | Exact count + structural span extraction on approved fixtures | BLOCKED integration |
| Root anchor/ancestors | Absolute or RootDirectory-relative names supported | Reparse/object namespace/mapping and concurrent change | Confirmed opening recipe + disposable Windows race matrix | BLOCKED |
| File child open | FILE_OPEN, non-directory and reparse options individually documented | Devices/aliasing, combination and ABI not exercised | Post-open type/volume/ID and no-follow integration tests | BLOCKED |
| Directory child open | Directory type constraint and option restrictions documented | No validated directory/no-follow combination | Authoritative parameter review + Windows tests | BLOCKED |
| Handle ownership/close | Handles/request storage have API-defined lifetimes | Pending operation and uncertain close/double-close | Owner-state implementation review then isolated tests | BLOCKED |
| Global resource gates | Pure parsers have tested local bounds | Missing page/cursor/read-session integration | Reserve-before-query/parse accounting tests | BLOCKED |
| Hard timeout | Termination/completion can be asynchronous | Hung driver and partial work | Separately scoped worker/I/O and state inspection tests | BLOCKED |
| Harness/installer ready | None claimed | All critical runtime questions above | No acceptance based on pure tests alone | BLOCKED |

### Actual commands and results

```powershell
& 'C:/Users/Икрам/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -I -B -m unittest discover -s D:/nexus2/launcher-next/desktop_placement_review -p test_probe_logic.py -q
```

Result: **112 tests, 0 failures/errors, 0 skipped, exit 0 (0.137 s)**.
All previous 104 tests retained; eight necessary result-authority/status tests
added. AST and compile checks use ast.parse and compile(source, path, 'exec')
on the two review sources only, without execution, imports of ctypes, or pyc.
No raw NTSTATUS translation is tested or implemented. A test saying 'pending
completed' models policy input, never a real Windows completion observation.

Next safe step: resolve the documented directory/no-follow combination and root
anchor policy, then agree a focused disposable Windows integration plan before
any implementation/testing permission. Keep preflight and placement blocked.
Nothing authorizes Native binding, worker, real package access or cleanup.


## DRAFT ONLY — separate Windows integration test plan

Status: PLAN FOR REVIEW. No implementation, fixture preparation or execution is
authorized by this document. All cases below remain NOT TESTED or BLOCKED.
Historical pure-test PASS results above do not transfer to these cases.
Only REVIEW.md changed in this stage; probe.py and test_probe_logic.py unchanged.

### Scope, gates and future synthetic area

Future candidate suite directory: <owner-approved local temporary directory>/
NEXUS-Integration-<unique-run-id>. This is a placeholder, NOT a directory to create
now. Resolve/approve its actual absolute path and local volume before execution;
do not trust an environment variable as ownership proof. Reject any existing
run-id directory instead of reusing it. Never use the 20261017 placement area,
beta2 directory/ZIP, installed NEXUS, production data, credentials or trust stores.

Per-case future layout, all NEW and exclusively owned by that run:
- cases/<ID>/root: only this is the selected source root under test.
- cases/<ID>/outside: synthetic canaries outside the selected root but INSIDE the
  same approved case area; never an actual user directory or pre-existing file.
- cases/<ID>/destination: only for separately approved partial-write cases.
- evidence/<ID>: bounded manifests, operation traces and result records.

Manifest each intended create/mutation before preparing fixtures, with path,
small deterministic byte content, exact allowed effects and ownership. Refuse
unknown existing paths/reparse points. Each case is fresh; no cleanup/retry after
failure, no reused partial result. A later cleanup requires a separate explicit
scope and ownership review; this plan adds no cleanup machinery.

Proposed footprint for a default run: <=32 MiB synthetic file data, <=2 MiB per
file, <=32 MiB evidence, <=2 owned test processes at once. Directory-count cases
may need <=5000 empty directories but only after explicit count approval. Enforce
caps before preparation. Test-specific resource budgets can be SMALLER than
production limits to prove dispatch/read gates without huge files or artificial
system disk exhaustion. Such injection must be explicit in the future test
adapter, cannot alter production configuration and cannot raise existing caps.

Gates (all currently closed):
G0: owner approves this plan, volume, fixture manifest, code/ABI review and exact
per-case side effects. Root and directory/no-follow recipe still need resolution.
G1: separately reviewed diagnostic adapter/observer may be implemented only under
new permission. Code under test and independent observer must be distinguishable.
G2: authorize read-only/small-fixture ABI and result-lifetime tests first.
G3: authorize reparse/race actors only after G2 evidence is reviewed.
G4: authorize worker/timeout and tiny partial-write cases separately after G3.
Do not advance on elapsed time, pure tests, partial success or an exit code.
No commands to run an adapter are provided because no adapter exists.

### Evidence and status rules for every case

Save OS build/architecture, filesystem/volume capabilities, non-secret process
identity, test code version/digests, approved case manifest and monotonic timeline.
Record exact requested access/share/disposition/options, direct NTSTATUS, final
completion evidence, IOSB status/count only when valid, class number, bounded
record bytes and offsets, type/attributes/volume/file ID observations, owned token
lifetimes, and separately observed filesystem state. Never log credentials or
real project data. Trace both the adapter and independent observer; do not use the
same parser/output alone to verify itself. SDK layout probes need independent
offsetof/sizeof evidence (no installing compilers: absence leaves the case BLOCKED).

Content/size hashes establish preservation of chosen synthetic bytes, not
publisher identity. Compare names, expected attributes, types and content;
do not treat access timestamps as stable byte-integrity evidence.

PASS requires the exact expected outcome AND independent evidence for the stated
property. Expected negative refusals may PASS that one guard only, never overall
readiness. NOT TESTED means not executed; BLOCKED means a prerequisite or adequate
observation is missing; FAIL means observed violation. Keep status separate from
an adapter result VALIDATED/REFUSED/INCOMPLETE/BLOCKED. No generic nonzero exit
acceptance. Unexpected outcome/exception, boundary escape, unowned token/process,
unknown ownership/closure, buffer reuse while pending, missing evidence, security
prompt or exceeded bound -> stop case AND suite; preserve evidence, no retry.

Read-containment evidence must include actual operations/validated handle binding,
not only an unchanged canary: reading does not alter its bytes. If an independent
observer cannot establish what was opened/read, that property stays BLOCKED.
A test-controlled barrier establishes an interleaving; a mock/sleep does not prove
behavior of a hung driver or cover every race. Race repetitions, if ever approved,
are a fixed schedule in advance, never automatic retries after a failure.

### Side-effect classes (apply per row through the preparation column)

Every listed class is FUTURE ONLY and requires explicit permission. Evidence
writes are allowed only under evidence/<ID>, capped as above. The independent
observer may read only that case's synthetic root/outside/destination and owned
handles. Normal resource closure is allowed when ownership/completion is known;
never delete fixtures or retry an uncertain close.

R: create declared small regular-file/directory fixtures; inspection then read-only.
No content mutation, links, worker or external access during the check.
M: R plus the one declared synthetic rename/replace/write actor operation at an
approved barrier; no mutation outside that case or privilege/ACL changes.
J: M plus only listed symlink/junction points within the case, targeting its own
outside canary. No targets beyond the approved case, volume mount points or
permission escalation. If link creation needs unavailable privileges/developer
mode, BLOCKED; do not change policy or fall back silently to another link type.
W: R plus at most one explicitly owned Python diagnostic worker and one listed
actor, no grandchildren, no package EXE. Parent retains actual process handle;
no taskkill, PID/name-based kill, unrelated process or shell command execution.
P: W plus only specified tiny synthetic destination/temp writes at acknowledged
checkpoints; no activation/pointers/receipts/installed marker. No real payload.
These classes do not permit registry, ACL, privileges, mounts, Defender/SAC or
policy changes. If Windows protection blocks a test binary/interpreter, STOP.

### Matrix (all cases unexecuted)

| ID | свойство | подготовка | проверка | ожидаемый результат | свидетельства | stop condition | статус |
|---|---|---|---|---|---|---|---|
| A01 | Root anchor binds the approved synthetic volume/root | R; fresh local case; known expected root/ancestor identities | Observe initial anchor and each component open/validation before enumeration | Correct directory/volume evidence; otherwise BLOCKED, no read of unvalidated child | Independent root/ancestor type, IDs, volume and open trace, exact recipe | Namespace mapping/anchor unclear, any component unobserved | BLOCKED — root recipe unresolved |
| A02 | Retained ancestors constrain rename/delete as actually observed | M; root two levels deep; owned actor | At held-handle barrier attempt one declared ancestor rename/delete-access open | Sharing restriction observed OR session safely refuses detected change; no containment claim from sharing alone | Exact access/share/status, handle timeline and actual resulting path/ID | Wrong tree consumed, actor unowned, unexplained success | NOT TESTED |
| A03 | Invalid root forms refused before traversal | R; candidate strings only: relative, UNC, device, drive-relative, traversal | Request root validation without opening candidate namespaces | Specific root-policy refusal, no disallowed open | Candidate-class/refusal and independent open-call trace | Any attempt outside approved synthetic area | NOT TESTED |
| N01 | ABI widths, offsets and separate Native enum | R; no payload; already available trusted SDK toolchain if any | Compare sizeof/offsetof for IOSB, OBJECT_ATTRIBUTES, UNICODE_STRING and directory record against documented x64 layout; class 37 vs Win32 10 | Exact match on target OS/ABI; unsupported toolchain/ABI -> BLOCKED | Compiler/header identity and literal layout output, independent comparison | Requires installing/building application, mismatched layout | BLOCKED — independent layout probe/tool availability not approved |
| N02 | Information is completed bytes, not capacity | R; a few known names, deliberately oversized 64 KiB buffer | One completed Native page; distinguish capacity, count and terminal logical end; inspect only valid bounded region | Count in range, exact records, tail ignored as unspecified; strict parser receives logical chain only | Direct/final statuses, Information, capacity, annotated bytes and terminal offsets | Capacity inferred as count, zero-tail scan, pending read or out-of-range access | NOT TESTED |
| N03 | Truncation never produces accepted records | R; small buffer capacity requested only in test invocation, not production configuration | Trigger documented fixed-header/name truncation and collect exact status | INCOMPLETE for overflow/too-small, no parse/resize/retry | Status, request bound, record-consumption count zero | Partial inventory accepted or automatic retry | NOT TESTED |
| N04 | Zero-byte success is not directory END | R; required OS condition may not be reproducible deterministically | Observe actual success/count-zero if naturally produced; otherwise retain policy-only evidence | INCOMPLETE, no false END; unavailable OS response -> NOT TESTED | Actual OS call/status/count, no mock presented as OS evidence | Invented response reported as Windows behavior | NOT TESTED |
| N05 | Last record ends page only; explicit final status ends scan | R; enough short names for multiple bounded pages | Advance one directory cursor without restart until documented terminal status | Every expected ordinary name exactly once; final terminal status, not NextEntryOffset zero alone | Page indices/status/count/cursor evidence and independent expected name set | Duplicate/missing names, endless page, restart or unknown terminal status | NOT TESTED |
| N06 | Pending status and direct-return precedence | R; asynchronously issued real query only after separate parameter review | If query returns pending, wait for actual completion; otherwise use direct return | No pending buffer access; final IOSB used only after completion; stale values never data | Completion event/handle observation, buffer/IOSB lifetime trace | Pending cannot be induced -> record NOT TESTED; reuse/free or false status -> STOP | BLOCKED — async recipe/lifetime instrumentation pending |
| C01 | Single ordinary file is opened relative to borrowed parent | R; distinct small child bytes, held parent | Observe RootDirectory token and one-component UNICODE_STRING; validate returned object before reading | Same approved file/volume/identity; no absolute reopen | Request parameters, observed handle evidence and bounded content read trace | String reconstructed into absolute lookup, unsupported identity | BLOCKED — file recipe/runtime binding unreviewed |
| C02 | Directory child no-follow and type constraint | R; one directory; final access/options recipe must be approved | Open relative directory and query its type without traversing it first | Confirmed compatible no-follow recipe and type; otherwise BLOCKED | Actual flags/access/status and handle type/tag/volume | Guessed incompatible options, fallback removing protection | BLOCKED — directory/no-follow combination unresolved |
| C03 | Invalid single-child names never dispatch | R; synthetic candidates dot, dotdot, separators, ADS, drive, reserved names | Request child policy for held synthetic parent | Specific refusal; no corresponding Native open | Request/refusal, dispatch count and observer trace | Any forbidden lookup is issued | NOT TESTED |
| C04 | Dot entries audited without recursion | R; actual dot records only if filesystem returns them | Structurally validate, count and record dot event, skip without opening | DOT_SELF/DOT_PARENT audit; no inventory insertion or child handle; unexpected type/attributes refuse | Raw validated record, audit counter and no-open trace | Catching generic parser error as skip, traversal or silent omission | BLOCKED — strict-parser/special-stage routing not implemented |
| J01 | Reparse rejected at every component | J; separate fresh cases for ancestor, root, child directory and file; each link points only to case outside | Open/check at barrier appropriate to each component; never recurse through reparse | Exact reparse refusal before referent enumeration/read | Link tag/placement, open/read trace, independently inspected canary; unchanged bytes alone insufficient | Referent read, external target, missing privilege or unknown link behavior | NOT TESTED |
| J02 | Enumerate/open substitution is detected or safely constrained | J; held parent, ordinary child and synthetic alternate target | Actor substitutes child with junction/symlink between enumeration and open | No referent read; identity/type/reparse mismatch refusal, no retry | Both actors' barrier timeline, before/after IDs/tags, actual read token trace | Replacement accepted by name only or outside read unobservable | NOT TESTED |
| M01 | File-to-file and file-to-directory replacement | M; distinct known bytes/types | Replace the child after enumeration at an acknowledged barrier | Type/ID/size mismatch refuses; no automatic fresh inventory | Name-to-ID change, opened-object attributes and read-dispatch evidence | New object accepted with stale metadata | NOT TESTED |
| M02 | Mutation during enumeration is not an atomic-snapshot claim | M; one scheduled add/remove/rename within case | Observe cursor pages and finish/refusal behavior | Detected instability refuses; missed changes cannot support atomic snapshot claim | Mutation timeline and observer's final tree versus reported evidence | Test labelled atomic/safe despite incomplete observation | NOT TESTED |
| I01 | Volume and file identity comparisons | R; regular child plus approved test-only comparison mismatch inputs; actual second volume only if already available and owned | Compare enumeration/open evidence and root volume; separate pure mismatch injection from real OS evidence | Supported matching identity accepted locally; mismatch refuses | Raw 64/128-bit identity classes, volume evidence and comparison decision | Mixing incomparable ID widths or treating injected mismatch as volume test | NOT TESTED |
| I02 | Unsupported/zero/incomparable identity fails closed | R; approved volume capability if present, otherwise synthetic policy-only case | Request identity class without fallback to pathname-only trust | BLOCKED for unsupported/incomparable identity; no payload read | Actual unsupported status/capability, read count zero | Fallback to weaker trust or changing filesystem/system | NOT TESTED |
| O01 | Exceptions preserve ownership and close once | R; owned root/child tokens, approved local exception checkpoints | Raise diagnostic exception after each acquisition/adoption boundary | Abort; close only known-owned completed resources exactly once; parent after children | Acquisition/borrow/adopt/close-result ledger, independent token/accounting evidence | Double close, closing borrowed token, unrecorded handle loss | NOT TESTED |
| O02 | Pending I/O retains buffer, IOSB and borrowed directory | R; actual pending query requires approved async mode | Observe lifetime until completion; no early release/parse | INCOMPLETE while pending, storage and parent retained; uncertain close -> BLOCKED | Completion and lifetime trace; no use-after-free indication | Free/reuse/parent close before completion, unsafe close retry | BLOCKED — pending-query design unresolved |
| O03 | Unknown close result is not fabricated as closed | R; policy injection only unless a safe real failure is reproducible | Supply close-failure/uncertainty at an adapter boundary; no invalid OS handle probes | BLOCKED; no double-close retry or later use | Explicit injected-versus-real label and ownership ledger | Intentional unsafe close, retrying reused numeric handle | NOT TESTED — policy injection cannot prove actual close semantics |
| L01 | Page/record/name limits gate work | R; small dataset, test-specific smaller limits | Reach and exceed dispatch/page/record/name limits one at a time; count empty/error calls | Specific refusal before next disallowed query/decode; no restart | Reserved budget before call, actual dispatch count and bound | Limit checked only after excess work | NOT TESTED |
| L02 | Depth, node and file-count limits | R; shallow fixtures and smaller test-only limits; large-count run only separately approved | At exact boundary then one beyond, including dots in raw count | Boundary handled; excess child not opened/descended; specific refusal | Expected graph/count, operation and depth trace | Creating unapproved count/footprint or unbounded recursion | NOT TESTED |
| L03 | File size and shared actual-byte budget | R; tiny known files, much smaller read budget; no huge allocation/disk exhaustion | Check metadata cap before read, then byte budget before each request across all test readers | Oversize metadata refuses before reading; no request exceeding remaining allowance | Requested/returned-byte counters and independent byte evidence | Hidden reader bypasses ledger or over-budget read request issued | NOT TESTED |
| W01 | Owned worker startup and startup failure | W; future reviewed Python diagnostic worker only, no package binary | Start once; observe ownership; deterministic child startup error case separate | Owned handle retained or clear failure, no replacement worker; startup latency recorded without hard-bound promise | Parent-owned process token, startup/exit evidence and bounded protocol | Security block, unowned process/PID-based control or spawned grandchildren | BLOCKED — worker not implemented/approved |
| W02 | Operation not returning versus cooperative deadline | W; approved synthetic barrier stalls child; real driver hang not induced | Parent deadline expires while worker has not returned; heartbeat cannot extend it | No late success acceptance; bounded parent wait policy; actual driver-interruption property remains NOT TESTED | Monotonic timestamps, barrier acknowledgement, observed parent decision | Stall simulated but reported as proof of interrupting kernel I/O | BLOCKED — worker/runtime observer unavailable |
| W03 | Termination request differs from confirmed exit | W; same exclusively owned child; no unrelated targets | Request termination through owned handle, then bounded exit observation | Confirmed exit OR BLOCKED on uncertain exit; request alone never success | Request return, independent process-exit signal and bounded wait timeline | PID/name kill, unbounded wait or claiming guaranteed OS termination | BLOCKED — no worker/termination implementation |
| W04 | Uncertain exit and incomplete protocol poison session | W; controlled policy/error injection, never deliberately hang kernel driver | Missing/truncated/oversized result, late report, unconfirmed exit after grace | REFUSED/INCOMPLETE/BLOCKED, no retry/ready marker, ownership uncertainty retained | Input provenance, bounded protocol capture and final owner ledger | Unbounded output buffer, false PASS, automatic replacement process | BLOCKED — future protocol needed |
| V01 | Independent regular-state verification | R; exact expected manifest from fixture recipe, not discovered output | Observer compares source and outside canary names/types/content/size against recipe | Exact agreement for declared effects; no proof of publisher trust | Baseline + after manifests from independent reader, operation trace | Same parser/output used as sole oracle or unexplained differences | NOT TESTED |
| V02 | Partial synthetic destination never treated as ready | P; few tiny files and one temp; explicit exception checkpoint only | Interrupt after acknowledged bounded write checkpoint; independently inspect retained tree | Incomplete tree/temp retained, no ready/installed state; exact expected partial evidence or BLOCKED | Observer manifest, bytes/size and absence of completion authority, sentinel evidence | Real payload used, activation, auto deletion or unknown changed files | BLOCKED — partial-write scenario needs separate implementation/permission |
| V03 | Worker exit is not rollback or integrity evidence | P; same small write recipe; termination case separately approved | Observe exit and then independently inspect destination/outside, without automatic cleanup | No PASS from exit alone; safe-state property decided by explicit filesystem evidence | Process signal plus separate observed partial tree and allowed-effect comparison | Exit code substituted for tree verification, cleanup hides evidence | BLOCKED — worker/partial-state implementation not authorized |
| X01 | Unicode preservation and alias policy | R; Cyrillic, supplementary Unicode, supported case/short-name behavior in ordinary synthetic directory | Enumerate/open actual names preserving bytes/spelling; compare supported identity | Accepted names preserved; ambiguous aliases refuse; unsupported behavior BLOCKED | Original UTF-16 recipe, returned names, ID/alias observations | Silent normalization or unsupported names reported supported | NOT TESTED |
| X02 | Long path handling end-to-end | R; bounded deep fixture >260 characters but within approved policy and OS limits | Exercise root, relative child open, observer and parser with same declared path | Correct access and evidence OR explicit limitation; no global long-path setting change | Exact lengths/UTF-16, API statuses and observer compatibility | Enabling registry policy, removing test length or unsupported observer | NOT TESTED |
| X03 | Sharing/access failure classification | M; ordinary synthetic file; owned actor holds incompatible share mode | Attempt operation while actor's conflicting handle is held, one attempt | Exact sharing failure refuses; this does NOT establish ACL-denial handling | Requested access/share plus actual status and no data read | Calling sharing violation proof of real ACCESS_DENIED, retry loop | NOT TESTED |
| X04 | Genuine access-denied behavior without ACL changes | R only if an already provisioned owner-approved disposable restricted fixture exists | One permitted request expected to return actual access denial | REFUSED exact status; otherwise NOT TESTED; no attempt to grant access | Fixture ownership/provisioning provenance and actual denial | ACL/privilege change or touching a real user's protected path | BLOCKED — cannot provision denial fixture under current rules |
| X05 | Unsupported filesystem / information class | R only on already available owner-approved disposable local volume | Query capabilities/class once; no mount, format, VHD, network or fallback | BLOCKED for missing capability, preserve status; supported case assessed separately | Volume capability and actual unsupported status | Creating/mounting volume, unsupported class changed silently | BLOCKED — qualifying volume/capability not established |

### What documentation settles versus Windows evidence

Documented facts already referenced in Native review:
- Native FileIdBothDirectoryInformation is class 37, distinct from Win32 class 10.
- Successful completed Native query exposes bytes written in Information; capacity
  is an input. Pending completion changes which status is authoritative.
- Directory records link through NextEntryOffset; terminal zero ends that page.
- RootDirectory permits relative ObjectName. Final reparse behavior and type
  options are documented individually, not a complete containment proof.
- Sharing restrictions, handle/CRT ownership rules and asynchronous termination
  behavior have documented semantics.
These are not evidence that our future binding is correct on a particular OS.

Only Windows observations can confirm selected ABI bindings, exact compatible
flags/access rights, completion/lifetime paths, actual reparse/type behavior,
sharing and namespace races, usable file-ID classes, Unicode/long-path behavior,
filesystem errors and process-exit observations. Access-denial and unsupported
volume cases remain BLOCKED if they cannot be obtained within the approved rules.
Do not relax protections to manufacture a test result.

Even successful integration tests cannot promise:
- absence of every TOCTOU interleaving or an atomic snapshot of a mutable tree;
- protection against kernel/admin/filter actors, volume namespace changes or all
  filesystem/Windows versions and Unicode/8.3 alias behaviors;
- fixed-time return from a stuck syscall, process creation or termination;
- rollback or absence of partial writes because a worker exited;
- publisher authorship, Authenticode, Windows reputation or SAC acceptance from
  SHA-256 equality;
- readiness of placement harness, updater or installer from this matrix alone.

### Next permission request must be concrete

Owner review of this plan comes first. A later proposal must name exact cases,
resolved API recipe, disposable absolute location, file/count/byte/process caps,
code to be reviewed, independent observer and allowed side-effect classes.
Start with ABI/ordinary read-only cases; any unresolved no-follow/root guarantee
remains BLOCKED. Reparse/race, worker and partial-write scopes require distinct
approval. No approval is inferred from preparing this plan.

### Actions actually performed in this planning stage

Read the existing REVIEW.md, append this draft plan, then validate UTF-8, unique
matrix IDs and Markdown column counts using a standard-library script reading
only REVIEW.md. No executable test or source changed, so pure unit tests and
AST/compilation were NOT RUN in this stage. Earlier 112-test result is historical.
No Windows API, Native call, preflight, run-case, placement, worker, process actor,
fixture, experiment directory, reparse point, payload/ZIP access or cleanup took
place. Production, system settings and all Python sources remain unchanged.

Document validation: 37 unique IDs, eight columns per matrix row, all case
statuses NOT TESTED/BLOCKED; UTF-8 decoded successfully, final exit 0. The first
validator expected 38 rows and exited 1 on actual count 37. The assertion was
corrected; no case was removed. A subsequent attempt to append this verification
note failed in shell quoting before any file write; the note was applied with
the file patch tool instead. Neither failure executed any test or experiment.

Actual validation process: fixed Python executable above with `-I -B -`, script
provided through standard input; working directory D:/nexus2/launcher-next. Its
logic reads only REVIEW.md, selects matrix rows using the pattern
`^\| [A-Z][0-9]{2} \|`, splits each into eight columns, checks unique IDs and
asserts every status begins NOT TESTED or BLOCKED. No environment changes.

## Independent audit of Windows integration matrix

Scope: independent document-only challenge of the existing 37-case draft, not a
second execution or independent agent. All 37 rows were read against their stated
preconditions, observation method, expected result, stop rule and R/M/J/W/P side
effects. No case or original matrix row is rewritten here. Findings are design
gaps; they do not claim that Windows or the implementation failed a test.

Audit outcome: **BLOCKED for execution approval**. The plan contains useful scope
limits and correctly distinguishes synthetic policy from OS behavior, but is not
yet a sufficiently precise executable test specification. No finding below is
an authorization to implement a fix or run its proposed test.

### Findings

IA identifiers are audit findings, not new integration-test case IDs. P1 means
resolve before affected Windows execution; P2 means clarify evidence/coverage
before claiming that property. All findings remain open/BLOCKED. A proposed new
test is only a design request; no fixtures, test code or commands are added.

| ID/ссылка на случай | замечание | риск | требуемое уточнение | нужен ли новый тест | статус |
|---|---|---|---|---|---|
| IA-001 / G0–G2, A01, N01 | G0 requires resolved root/no-follow before G1/G2, while the early ABI checks are supposed to establish prerequisites without filesystem access. R does not explicitly authorize SDK compiler/probe processes. | P1: circular gate; ABI/tool use could acquire unintended process/build permission. | Split a no-filesystem ABI-design/synthetic-buffer gate from fixture/API gates. List exact trusted compiler/probe artifacts and processes only in a later explicit scope; unavailable tooling means BLOCKED. | No; split prerequisites and permission for N01. | BLOCKED |
| IA-002 / fixture preparation, A01, A03 | Fresh directory names and approval do not prove that preparation itself cannot follow a replaced ancestor or pre-existing link. Expected root identities have no independent provenance specified. | P1: fixture creation could escape before the adapter is tested. | Specify trusted synthetic-area establishment, exclusive creation, allowed ancestor metadata access, root identity provenance and handling of pre-existing/concurrently replaced paths. Do not bootstrap trust from the adapter output. | Yes: preparation/root-boundary negative cases, separately authorized. | BLOCKED |
| IA-003 / A02, J01, X02 | “Ancestor” and “each level” do not explicitly stop at the owned case boundary. A long-path ancestor could include suite/evidence directories or real temporary-directory ancestors. | P1: an actor may rename/reparse an unowned directory or invalidate unrelated case paths. | Enumerate exact component objects allowed to mutate. Only owned ancestors below an approved immutable case boundary; no mutations of volume root, user/temp ancestors, suite anchor or evidence path. Add pre-dispatch ownership checks. | No; expand component-specific variants and manifests. | BLOCKED |
| IA-004 / all evidence, J01–J02, V01–V03 | Observer independence is asserted, but no safe observer traversal, operation visibility or trusted log destination is specified. A manifest/hash can follow the same substituted link as the adapter. | P1: common-mode failure, observer boundary escape or fabricated no-read evidence. | Define a separately reviewed bounded observer, actual opened-object/read visibility, safe evidence storage outside actor-mutated paths and cross-checks independent of worker/adapter logs. If visibility is unavailable, no-read stays BLOCKED. | Yes: observer boundary/evidence-integrity negative checks. | BLOCKED |
| IA-005 / A03, C03, N02 | “No open” and “no out-of-range access” are not demonstrated by a software refusal log. The observer's trusted collection mechanism is unspecified. | P1: self-reported dispatch counts may conceal the prohibited operation; OS memory-read bounds are not proved. | Declare an approved independent observation mechanism and exact observable event. Distinguish policy refusal, absence of adapter dispatch and absence of OS/referent reads; do not promote one to the next. | No; tighten oracle and scope of each claim. | BLOCKED |
| IA-006 / N02 | Trimming to a terminal logical end may ignore bytes inside Information without a rule for permitted terminal tail, data provenance and malformed chains. Existing parser accepts only a narrow logical span. | P1: extraction could hide corruption or stale/unlinked records; count alone cannot validate a chain. | Specify count provenance, full bounded structural walk, terminal-tail policy and handling of inconsistent offsets/counts. Preserve original count/raw evidence; never zero-scan or infer written bytes from capacity. | Yes: count/chain inconsistency and terminal-tail extraction cases; synthetic vs OS evidence separate. | BLOCKED |
| IA-007 / N05, N02, L01 | 64 KiB packed pages with short names can contain more than the parser's 256-record cap. The positive pagination fixture could be refused before any valid multipage result. | P1: positive test cannot distinguish a pagination bug from a legitimate configured limit. | Calculate fixture names/page capacity and dot allowance before preparation; choose smaller approved page capacity ensuring each positive page stays within record/name caps. Keep separate over-limit negative cases. | No; make N05's positive setup concrete. | BLOCKED |
| IA-008 / N06, O02, W01–W03, G2–G4 | Pending/lifetime tests can block in G2, but worker isolation is deferred until after reparse/race G3. Even ordinary filesystem calls can fail to return. | P1: unsafe ordering, with no approved way to stop an early blocked call. | Resolve dispatch/observation isolation and stop limitations before any potentially blocking API case. Reorder approval gates or explicitly keep these cases BLOCKED; do not promise a hard cancellation bound. | No; fix gate dependency and execution prerequisites. | BLOCKED |
| IA-009 / N03–N06, I02, X05 | Explicit negative Windows cases are missing for direct error with stale-success IOSB, pending completed with error, unknown/informational status, out-of-range Information and unsupported status mapping. Pure tests cover parts only. | P1: a Native binding could map the wrong source/status/count while all happy-path OS cases pass. | Add an explicit status-authority case family. Separate reproducible actual Windows outcomes from controlled contract injection; unavailable actual responses remain NOT TESTED. No raw status/value is manufactured as Windows evidence. | Yes: dedicated completion/status-binding cases. | BLOCKED |
| IA-010 / N05, C04, L01–L02 | Per-scan duplicate page/cursor and repeated-dot handling lacks an independent case. A fixed page cap alone does not test progress correctness. | P2: restart/duplicate records may be hidden by budgets or silently skipped. | State cross-page identity/name/dot accounting and expected cursor progression; verify that a page terminal is not directory END. Repeated-response injection is policy evidence only. | Yes: progress/restart/duplicate special-record cases. | BLOCKED |
| IA-011 / J01–J02 | A static reparse and enumerate-before-open swap do not cover mutation after handle validation but before descent/read, or reparse/attribute mutation on held objects. | P1: a narrow passing interleaving may be generalized to all lookup/read stages. | Name barriers and observations at enumerate, open, validate, descend/read, and any forbidden reopen. Approve each link type/component separately; unavailable permissions or semantics remain BLOCKED. | Yes: post-validation component mutation variants. | BLOCKED |
| IA-012 / M01, I01 | M01 uses distinct bytes/types; a refusal may come only from size/type/content differences, without proving file-ID comparison. | P2: identity guard never exercised although the case appears to validate it. | Use fresh synthetic objects with matching relevant metadata/bytes but different supported file IDs, then record comparison/refusal before payload read. Do not assume IDs cannot be reused over time. | Yes: identity-only replacement case. | BLOCKED |
| IA-013 / M02, L03, X03 | Same-object in-place mutation or pre-existing writable mapping is not a distinct case; ID and size can remain unchanged. X03 tests only one sharing conflict. | P2: stable identity could be mistaken for stable content or comprehensive sharing exclusion. | Add ordinary in-place/same-size mutation and, if safely authorized, pre-existing writable-map variants. Record actual sharing success/failure and bounded bytes; do not assume mutation must be possible or impossible. | Yes: content-stability/sharing-direction cases. | BLOCKED |
| IA-014 / I01, I02, J01 | A real second-volume fixture cannot fit the currently defined single local case area; J forbids volume mount points. Zero/unsupported/incomparable identities are grouped without separate oracles. | P1: crossing the approved area or labelling injected metadata as a real volume test. | Keep physical cross-volume cases BLOCKED unless separately approved paired owned areas already exist. Split zero ID, unsupported class, width mismatch and real volume mismatch; preserve pure/OS evidence labels. | Yes: distinct identity variants; real volume variant needs new scope. | BLOCKED |
| IA-015 / I01–I02, M01 | No explicit hardlink case tests the single-link rule or multiple names for one object. | P1: path containment can be confused with exclusive ownership of the underlying object. | If later authorized, create links only between two NEW synthetic files/names in one owned case; approve this side-effect class separately. Verify link count and refusal without touching real data. | Yes: synthetic hardlink/link-count case. | BLOCKED |
| IA-016 / O01–O03 | Token traces alone do not prove exact-once OS close, correct CRT ownership transfer, noninheritance or absence of leaks. A fake close failure cannot establish actual close behavior. | P1: handle reuse/double-close or leaked/inherited resources may remain undetected. | Specify independent owned-token accounting, acquisition/adoption failure checkpoints and explicit inheritance policy. Never probe invalid/borrowed handles to provoke failure; keep nonreproducible real failure NOT TESTED. | Yes: CRT transfer, acquisition failure, inheritance and bounded-leak observations. | BLOCKED |
| IA-017 / global stop rule, O03, W04, N03 | Expected negative INCOMPLETE/BLOCKED outcomes and global stop-on-uncertainty rules do not specify whether a subsequent fresh case is allowed. Completion/status evidence can be intentionally missing in a negative case. | P1: continuing after real ownership uncertainty or stopping policy negatives inconsistently. | Define expected-refusal completion with confirmed safe ownership separately from live pending/closure/exit uncertainty. Real uncertainty always halts the suite; future continuation after a clean negative needs an explicit schedule/approval, never automatic retry. | No; clarify case/session/suite outcome rules. | BLOCKED |
| IA-018 / L01–L03, evidence caps | Limits cover records/bytes but not reserved handle count, concurrent borrow count, query calls returning no data, observer enumeration or loss of evidence at the log cap. | P1: bounded parser with unbounded dispatcher/observer/resources; exceeding caps can erase decisive evidence. | Specify reserve-before-work gates for calls, owned/in-flight handles, observer and evidence bytes; define bounded retained failure record, no automatic truncation-as-success. Separate smaller-limit tests from evidence for production-sized boundaries. | Yes: handle/evidence/observer budget exhaustion and exact-boundary cases. | BLOCKED |
| IA-019 / W01–W04 | No dedicated negative case for termination-request failure or parent interruption/exit while a child is owned. Output flooding is grouped with incomplete protocol without a concrete drain bound. | P1: orphaned worker, unbounded collection or unsafe later PID-based recovery. | Separate startup failure, request failure, missing exit confirmation, late/oversized output and supervisor interruption. Define ownership evidence and safe escalation when a process survives; no kill-by-PID, automatic replacement or unbounded wait. | Yes: worker lifecycle/control-failure cases under separate permission. | BLOCKED |
| IA-020 / V02–V03 | Partial-state tests specify post-checkpoint interruption but not partial bytes inside a file, fixture write failure, pre-existing destination or target reparse substitution. Absence of a ready marker is vacuous without defined readiness authority. | P1: claimed recovery/installation safety without observing the relevant consumer or write boundary. | Restrict claims to synthetic byte/state preservation. Specify exact checkpoints and observer evidence; keep real readiness/rollback outside scope. Add safe injected write-failure and target-boundary variants only after separate write/reparse approval; never exhaust a real disk. | Yes: mid-file/temp/destination refusal variants; not installer acceptance. | BLOCKED |
| IA-021 / X01–X02 | Unicode/alias and long-path outcomes are broad OR conditions. No fixed fixture manifest distinguishes supported names from expected refusal; observer long-path support is unproven. | P2: any outcome could be labelled acceptable, hiding lossy normalization or an untested path layer. | Predeclare each UTF-16/path-length fixture and expected success/refusal before execution; split root/child/observer path layers. Case-sensitive or 8.3 prerequisites must already exist; do not enable settings. | Yes: individual Unicode/alias/path-layer cases. | BLOCKED |
| IA-022 / X03–X05 | A sharing error, a real access denial and unsupported filesystem/class are correctly distinguished in text but still rely on unavailable lab preconditions. | P2: policy injection may fill coverage gaps improperly; seeking a real denial may reach user/protected data. | Preserve BLOCKED for missing owned fixtures/volumes. Define exact expected status per approved environment; no ACL, privilege, mount or policy changes; no substitution of STATUS_SHARING_VIOLATION for ACCESS_DENIED. | No; split conditional evidence and retain unexecuted status. | BLOCKED |
| IA-023 / A02, W03, M02, V01 | Several expected results are alternatives such as success OR safe refusal OR limitation, with no branch-specific acceptance decided in advance. | P2: post-hoc selection of a convenient result weakens falsifiability. | Record which environment-dependent branches are legitimately allowed and what each proves; unexpected branches are FAIL/BLOCKED, not a new acceptance rule after execution. | No; add precise per-variant acceptance. | BLOCKED |
| IA-024 / all future cases, G2–G4 | Current “proposed” caps do not assign an actor, independent observer and evidence limit to each variant. The two-process limit does not say whether it includes supervisor/toolchain/observer. | P1: unauthorized process creation, evidence outside the area or irreproducible race control. | Make each approved run card list every process/role, open/read/mutation target, cap, timeout/uncertain-exit action and stop owner. No dependency is installed to satisfy the plan. | No; concrete run cards before any approval. | BLOCKED |

### Coverage checked, including what the draft gets right

All 37 original cases remain present and unchanged. Coverage reviewed:
A01–A03 root/ancestors; N01–N06 ABI, lengths, page/end/statuses; C01–C04
relative children and special records; J01–J02 reparse; M01–M02 mutation;
I01–I02 identity; O01–O03 ownership; L01–L03 limits; W01–W04 lifecycle/timeouts;
V01–V03 independent/partial state; X01–X05 environment and compatibility.

The draft already forbids real payload, protection changes, automatic cleanup,
unsafe fallback and retry; correctly retains conditional access/volume tests as
unexecuted; and does not claim a guaranteed kernel-I/O timeout. Unchanged
sentinels and exit status are explicitly insufficient. These positive design
observations are not test PASS results.

Scenario classes exist, but bundling alternatives into one row is not the same
as separate, falsifiable variants. Missing cases in the findings must be designed
and approved individually before the affected properties can be claimed.
Invalid status/count/close/timeout negatives need both an exact expected decision
and credible evidence; synthetic injection can establish only its contract branch.

### Separation of evidence and unresolved guarantees

Keep distinct records/results for: (1) documentation, (2) pure synthetic policy/
buffer behavior, (3) SDK ABI/layout, (4) actual filesystem/API observations,
(5) ownership/completion, (6) supervisor timing/exit, (7) independently observed
partial state. One category cannot upgrade another to PASS. An “independent”
observer sharing all adapter path resolution/parser assumptions is not an oracle.

Even every successful approved variant would leave unproved: all possible races;
an atomic mutable-tree snapshot; containment against privileged/kernel/filter or
volume-namespace changes; support for untested Windows/filesystem/alias modes;
absolute syscall/process startup/termination deadlines; absence of all resource
leaks from finite observations; rollback from worker exit; publisher/Authenticode
trust; and readiness of NEXUS installer or placement system. Controlled race
interleavings give evidence for those interleavings only.

### Safe staged approval sequence (proposal only)

1. Document-only reconciliation of IA-001 through IA-024, precise acceptance
   branches and scope of independently observable properties. No code or files.
2. Separate permission for pure buffer/policy refinements, if needed; no OS calls.
3. Separate ABI-only diagnostic approval: existing trusted toolchain/probe details,
   outputs, processes, bounded owned artifacts and protection-stop behavior. No
   filesystem adapter access to fixtures or payload is implied.
4. Separately review any proposed adapter/observer code and root/no-follow recipe,
   synthetic-area preparation, safe blocking/ownership strategy and exact run
   cards BEFORE approving fixture creation/API tests. If this cannot be justified,
   remain BLOCKED. Do not run uncontained pending tests as an early shortcut.
5. Individual permission for ordinary owned synthetic filesystem cases, then an
   evidence review. No automatic promotion from ABI success to filesystem scope.
6. Separate permissions for reparse/hardlink/race actors, any paired-volume lab,
   asynchronous pending operations, and worker control. Resolve their dependency
   order explicitly; no implicit right to start a worker to rescue an earlier test.
7. Separate partial-write permission only after observer/ownership/worker evidence
   is reviewed. Deletion/cleanup is still a later distinct scope; failed or unknown
   ownership is never resolved by automatic recursive deletion.

No stage is approved by this audit. In particular, stopped-but-live workers or
unknown closure states require a separately agreed operational response, not
automatic continuation of the matrix.

### Actions actually performed in this audit

Read only the integration-plan portion of REVIEW.md, add this audit section,
then validate strict UTF-8, the six-column audit table, finding IDs and references
to the existing matrix. No Python source changed, so Python unit tests and
AST/compilation were NOT RUN. Historical 112-test results are not new evidence.

Only REVIEW.md changed. No Windows/Native API, preflight, run-case, placement,
worker/test actor or experiment was executed. No fixture, sentinel, experiment
directory or new artifact file was created. No real package/ZIP was accessed;
production, configuration and system settings are unchanged. Ordinary document
editing/validation tools are not worker or integration-process experiments.

Actual document-check result: exit 0. PowerShell/.NET strict UTF-8 decoding;
37 original unique case IDs with eight columns each; 24 unique audit findings
IA-001–IA-024 with six columns and BLOCKED status; all explicit case references
in the audit's first column matched the original matrix. No Python tests/AST,
integration tests or API/worker experiments ran. These checks validate document
structure only and assign no test PASS to any integration case.

## Contract decisions for the 24 independent audit findings

Document-only candidate contract; no execution or implementation approval.
The original 37-case matrix and original IA-001–IA-024 findings above are retained
verbatim as the historical baseline. This section supplies normative decisions
and cross-references, not replacement test results. It is not owner sign-off.

RESOLVED_BY_CONTRACT below means an unambiguous rule, explicit scope and closure
criterion now exist for that requirements question. It does not assert an
implementation, Windows observation, safe root or test PASS. OPEN identifies a
missing owner/design choice; BLOCKED_ON_WINDOWS_EVIDENCE means the operational
guarantee is still unproved. OUT_OF_SCOPE may be used only for a specifically
excluded claim, not to conceal a required protection. No Windows case is closed
by a prose decision or by the earlier pure tests.

The following six rule groups govern every related future run card. When an old
matrix row permits alternative outcomes, these stricter acceptance rules govern
the proposed future specification; the old row is not itself execution authority.

### Group 1 — ownership and pending I/O requirements

One operation has a monotonically unique session/operation identity. Its owner
is the creating diagnostic scope, not a PID, a numeric handle supplied by a
record, or a worker's ownership assertion. A parent token can be borrowed; a
borrow does not transfer the right to close it. Input-name storage, request
structure, IOSB and output buffer belong to that operation until release is
proved safe. A numeric handle value alone does not identify a lifetime.

| Operation state | Permitted use | Release / ownership requirement |
|---|---|---|
| RESERVED | Budgets acquired, no syscall dispatched | May release reservation and unsubmitted storage; no OS token assumed |
| SUBMITTED | Request may reference its storage | Do not parse, reuse, free or lose storage; retain parent borrow |
| PENDING | Direct STATUS_PENDING | Same restrictions; stale IOSB success/count is unusable |
| COMPLETION_CONFIRMED | Independent completion observation for that operation, authoritative status determined | Only successful bounded data may proceed to structural validation; error/EOF is classified without accepting partial bytes |
| CLASSIFIED | Local VALIDATED/REFUSED/INCOMPLETE/BLOCKED recorded | Does not establish handle closure or global readiness |
| RELEASING | Known-owned resource, no pending dependent request | Exactly one release attempt by its owner, children before parents |
| RELEASE_CONFIRMED | Release success observed for that lifetime | Retire token; never reuse a stale numeric value as recovery authority |
| OWNERSHIP_UNKNOWN | Open, completion, adoption or close cannot be confirmed | Stop entire run; retain ledger/storage while a live operation could reference them; no guessed free/close/retry |

Direct non-pending return is the status authority. After pending, final IOSB
becomes usable only after completion has been observed; direct pending, a
cancellation request and a termination request are never completion evidence.
Open outcome Information is not a directory-query byte count. Unsupported,
incomparable or inconsistent evidence is not normalized into success.

Handle lifecycle is separately recorded: unacquired, owned, borrowed, in-flight,
adopted by CRT, releasing, released, unknown. Successful CRT adoption transfers
leaf ownership once. Failed adoption keeps the original owner accountable unless
its actual semantics/evidence are uncertain, in which case the run is BLOCKED.
No descriptor close plus CloseHandle double release; no closing borrowed parents.
An independent observer may account for lifetimes but cannot prove safe release
from an adapter log alone. Pending storage is not discarded just because a time
budget expired. If the owning process exits, actual process-exit evidence and
independent state inspection are still required; no successful filesystem result
is inferred from OS resource reclamation.

### Group 2 — worker, observer and evidence authority

Future roles are distinct even if some are hosted in the same process:
supervisor authorizes operations and retains owned process handles; worker
performs only the approved synthetic operations; actor performs only the named
mutation; observer independently verifies named properties; decision authority
compares observations with the frozen run card. Role co-location does not confer
independence: an observer using the adapter's unverified resolver/parser as its
only oracle is insufficient. The concrete observer mechanism remains OPEN.

Observer read authority is limited to the approved synthetic case objects and
specifically listed owned metadata/handles. No recursive unbounded walk, package
access, arbitrary process memory, system-wide capture or unrelated paths. Any
necessary metadata observation above the synthetic boundary must be separately
listed and approved; it is not permission to mutate or read ancestor content.
Evidence storage is exclusively owned and outside actor-mutable paths. Exact
safe establishment and observation of that boundary are not presumed solved.

Four evidence channels must remain separate:
1. Worker report: an untrusted bounded claim, not an oracle.
2. Process status: an independently observed owned process-object exit, not a
   PID/name lookup or an exit-code-only filesystem conclusion.
3. Filesystem observation: independent names/types/content/size/identity and
   operation observations tied to the approved fixture recipe and object lifetime.
4. Decision: exact expected branch plus complete evidence. No missing channel
   can be substituted by a good hash, a mock, a report or an expected exit code.

Claims are explicitly tiered: policy refused; no adapter dispatch observed;
no disallowed object open/read observed. Evidence for one tier does not prove
the next. Sentinel byte equality cannot prove no reading. If the selected
observer cannot establish the claimed tier, that claim is BLOCKED, not passed
because a lower-tier check succeeded. Logs must show their collection source,
query/lifetime identity and bounds; missing evidence stops the run.

No general hard limit on Windows I/O completion, process startup or termination
is promised. Supervisor timing, termination request success, confirmed exit and
partial filesystem state are independent facts. Unknown exit/close retains the
ownership uncertainty; no replacement worker, retry or cleanup may hide it.

### Group 3 — pagination and reserve-before-work limits

Before each dispatch, reserve one call from a run-global query budget. Submitted
calls are charged permanently regardless of success, empty page, error, pending
or cancellation. No refunds that permit repeated dispatch; no restart, resize,
fallback class or reissued call after an uncertain outcome. Each directory owns
one cursor with one outstanding request; duplicate/replayed operation evidence
is rejected. Page terminal zero is not directory END.

Before decoding, reserve bounded byte/name/record work. Count every structurally
encountered record, including dots, duplicates and refused records. A raw dot
is audited but never opened/recursed or inserted into ordinary inventory. Across
pages, track ordinary names and dot appearances per held directory lifetime.
Repeated ordinary name, repeated dot or repeated page/progress evidence aborts
with a specific duplicate/progress refusal; undocumented cursor/progress becomes
BLOCKED. No deduplication-as-success. Directory order is not assumed sorted.

| Resource | Proposed cap | Gate before work; action on failure |
|---|---|---|
| Native query calls, including failed/empty calls | 1024 per run | Reserve before syscall; exhaustion REFUSED, no next call |
| Page bytes / page raw records / active-name bytes | 64 KiB / 256 / 8192 | Capacity before allocation; counts before decode/append; no unbounded accumulation |
| Raw records/nodes and ordinary files | 4096 and 2048 per run | Count dots and refused candidates; reserve before opening a new candidate |
| Depth / relative path UTF-16 units | 32 / 1024 | Validate before child dispatch or descent |
| File bytes / declared file total / actual read total | 512 MiB / 1 GiB / 3 GiB | Metadata before read; reserve each actual request across all readers, ZIP and observer separately attributable |
| Diagnostic-acquired owned OS resources | 64 per role; 128 across all roles | Reserve before acquisition; runtime baseline handles listed separately, never hidden diagnostic acquisitions |
| Outstanding operation / live borrows | One per directory, at most two across roles / 128 across roles | Reserve before submission/borrowing; retain reservations while pending/unknown |
| Synthetic file data / file / evidence | 32 MiB / 2 MiB / 32 MiB per approved run | Preparation and observer included; no real disk exhaustion |
| Failure-evidence reserve | 64 KiB inside the evidence cap | Reserved before starting; cap exhaustion stops work; no successful result from truncated evidence |
| Test-created processes | At most two concurrently, including diagnostic supervisor, worker, actor, observer or compiler/probe roles | Enumerate actual process tree in run card first; no implicit extra compiler/helper child or third process |

Reservations are conservative ceilings, not proofs that blocked calls return.
Borrow counts do not duplicate OS handles; borrowed references still need bounded
lifetimes. Every observer read/query has its own attribution and also charges the
applicable run-wide budget. Existing helpers do not implement these global gates.
Any required code, role or bound not covered by a run card leaves execution OPEN.
No implementation or larger resource allowance is authorized here.

N05 positive fixture is now specified at requirements level: 40 ordinary files
named f000 through f039, each <=256 synthetic bytes; request capacity 1024 bytes;
allow at most two explicitly audited dot names. A nonempty record needs at least
106 bytes, so at most nine such records fit a page, below both parser caps.
Require at least two data pages, exact expected ordinary-name set once each,
known final END, and <=64 query calls (a stricter test cap). Do not require a
particular sort order or a full page. If the environment cannot prepare/query
that fixture under the declared contract, record BLOCKED/NOT TESTED, not positive
pagination PASS. A 64 KiB over-record page is a separate negative limit variant.

N02 count/span rule: retain actual capacity, final status, Information and raw
bounded data separately. Structural walk is confined to [0,Information), not
capacity; every linked record must be complete and offsets monotone/aligned.
Compute logical end from the validated terminal record. No zero scan. For the
current strict-parser contract, at most seven ignored terminal padding bytes
inside that span are supported; more tail is BLOCKED pending a new explicit
contract, not silently trimmed. Preserve the original span/evidence. This is
a conservative acceptance subset, not a guarantee of all Windows buffer layouts.

### Group 4 — identity, mutations and limits of the claims

Every candidate is checked on its actual retained handle before data reading:
disk object, expected file/directory type, permitted attributes, no reparse/tag,
volume matches the validated parent/root, supported comparable file ID, applicable
size/link policy. Never reopen by absolute name after that comparison. Comparing
64-bit and 128-bit formats requires an explicit documented bridge; none is
assumed. Zero, unsupported or incomparable IDs cause BLOCKED without data read.
Observed mismatch causes REFUSED; no re-enumeration/fallback to accept a new name.

Distinct future variants are required; each is tied to an existing case rather
than being a new approved matrix row:
- M01/I01 identity-only: two NEW synthetic objects with equal bytes/size and
  relevant comparable metadata, but independently observed different file IDs.
  Require the identity mismatch guard before payload read, not a type/size guard.
- M02/L03/X03 content-only: same retained ID and same length, declared in-place
  writer barrier; separately consider a pre-existing writable map only if approved.
  Observe actual sharing/mutation behavior; stable ID is not byte stability.
- I01/I02 hardlink: two NEW names within one owned synthetic case, never a link
  to pre-existing data. Link count >1 refuses; unsupported link-count evidence is
  BLOCKED. Link creation needs its own future permission, outside current R/M/J.
- A02/M01/J02 rename/type/reparse: separate barriers before open, after open,
  after validation and before descent/read. Record attempted and actual mutation;
  an actor failure is not automatically evidence for a different successful race.
- I01/I02 comparison variants: volume mismatch, ID mismatch, zero ID, unavailable
  class and incomparable widths get separate outcomes/oracles. Physical paired
  volumes are excluded from the current single-area permission proposal. Any
  later real cross-volume case requires separate approved owned areas, not a
  forbidden mount/link or synthetic metadata masquerading as OS evidence.
- X01/X02: exact UTF-16 names and path lengths, expected success/refusal and layer
  (root, relative child, observer) must be fixed before fixture preparation. No
  shortening, case/8.3 configuration change or normalization after a failure.

These requirements can detect specific mismatches and bound the tested lookup,
but do not prove an atomic mutable-tree snapshot, future ID uniqueness, absence
of every TOCTOU interleaving, exclusive ownership forever, stable volume mapping,
or protection against privileged/kernel/filter actors. No finite variant set
settles all those guarantees; the claims remain deliberately narrower.

### Group 5 — refusal, uncertainty and the meaning of a final decision

| Local result / condition | Current session / run | Resource treatment | Retry, fallback, cleanup, new worker | Required final evidence |
|---|---|---|---|---|
| VALIDATED local step | May proceed only within the same explicitly approved run card and reserved limits | Known owner/borrows retained; consume only completed validated data | None implied; no transition to another permission stage | Source of status, object lifetime and applicable independent observation |
| REFUSED, even if expected | Stop this session and halt the run; no automatic next case | Release only confirmed-owned non-pending resources once; preserve fixtures/evidence | All forbidden; later fresh case needs explicit owner direction | Exact refusal plus independent guard/effect evidence and confirmed resource disposition |
| INCOMPLETE | Stop session and whole run; never a final PASS | Pending/uncertain request storage and dependencies stay accounted for; release only separately confirmed-safe resources | All forbidden | Independently observed completion/exit/ownership; if absent remain unresolved, not silently complete |
| BLOCKED | Stop session and whole run; never a final PASS | Retain unknown ownership/lifetime state, no fabricated close | All forbidden | Missing guarantee/ownership evidence or explicit new design decision must be supplied before another authorization |
| Unexpected exception, evidence failure or boundary violation | Stop session and whole run; FAIL for observed violation, BLOCKED if observation is insufficient | No broad exception-to-success conversion; preserve evidence and ownership uncertainty | All forbidden | Independent observed state and exact failure classification; absence of evidence cannot become PASS |

A deterministic expected REFUSED can support PASS of that named guard only if
independent evidence confirms the guard, allowed effects and completed resource
disposition. It does not make the entire run/harness PASS and does not permit
automatic continuation. INCOMPLETE or BLOCKED never becomes PASS because the
test expected it; the contract branch may be documented as observed, but the
Windows case remains incomplete/blocked. No positive result from a missing worker
report, a termination request, a known hash or an exit code alone.

For later synthetic partial writes, freeze the independent byte recipe and
checkpoint expectations beforehand. Require separate variants for a mid-file
prefix, temp file, write-failure injection, pre-existing destination refusal and
target reparse/substitution. Observe actual retained names/types/bytes; do not
pretend the absence of a marker establishes real launcher readiness. Real
installer activation, recovery, slot correctness and rollback remain outside
this diagnostic contract. No real disk exhaustion or production consumer.

### Group 6 — ordered, separate admission decisions

The following order is a proposed permission sequence, not a permission grant.
The previous draft's G0–G4 ordering is superseded for future run-card design only;
it is preserved above as the audited original.

| Stage | Scope | Entry and exit criteria | Separate permission / no automatic transition |
|---|---|---|---|
| 1 | Static contract and documented API/ABI requirements | Exact intended claims, open no-follow/root questions, role authority and acceptance branches recorded | Review this document; no source or runtime authorization |
| 2 | Synthetic ABI/parser checks | Pure in-memory inputs only; live SDK/compiler/probe execution is NOT implied | Any pure-code change/test needs its own scope; actual SDK probe process/artifacts need explicit approval distinct from pure ABI derivation |
| 3 | Windows ordinary synthetic-area checks | Approved root/prepare/observer recipe, exact code/run cards/area/caps and risk decision for potentially blocking calls; no unresolved necessary guarantee | Separate fixture/API approval. Pending/unknown-lifetime tests are not early ordinary checks and stay deferred. No worker launch permitted as an implicit rescue |
| 4 | Filesystem race/reparse/identity checks | Stage-3 evidence reviewed, exact actor mutations and barriers approved, safe observation and link rights available without system changes | Separate permission for each variant, hardlinks and any paired-area exception; no expansion from an ordinary file test |
| 5 | Worker, pending-I/O, lifecycle and timeout checks | Worker/supervisor/observer code, owned process authority, bounded protocol and uncertain-exit response separately reviewed | Separate worker/timeout permission; no fixed-time I/O promise, no cleanup/replacement child. Tiny partial-write scenarios need additional explicit write scope |
| 6 | Further admission decision | Independent review of collected evidence, unresolved risks and accepted claims | Owner decides whether to authorize any next scope; nothing advances automatically |

All synchronous Windows calls in stages 3/4 can still fail to return promptly.
This sequence cannot promise safe forced interruption without an approved
isolation/operational response. If a stage-3/4 run depends on a worker guarantee
not yet approved in stage 5, the earlier stage stays BLOCKED. Moving any worker
execution earlier would require an explicit separately reviewed change to this
sequence, not an automatic exception. Whether any narrow ordinary run can be
authorized without that dependency remains an OPEN owner/design decision.
Asynchronous pending operations and their ownership tests remain in stage 5.
No real access-denied or unsupported-volume fixture is sought outside the owned
area to bypass a missing prerequisite.

### Decision table and traceability

The status applies to the remark's requirements question, not a case execution.
References remain to the existing 37 cases; variants above must later acquire
individual frozen run cards, not be hidden inside a generic PASS.

| ID замечания | группа | решение контракта | связанные случаи из матрицы | остаточный риск | критерий закрытия | статус |
|---|---|---|---|---|---|---|
| IA-001 | 6 | Split documentation/pure ABI from live SDK processes and root-dependent Windows work; staged permissions above replace the circular prerequisite for pure work. | A01, N01 | Live tooling and root remain separately blocked. | Requirements distinguish stages 1/2 from live probes; no pure result grants a process/root operation. | RESOLVED_BY_CONTRACT |
| IA-002 | 1, 2, 6 | Fixture/root establishment requires an independently anchored owner/volume/ancestor recipe before any creation; fresh path strings alone are insufficient. | A01, A03 | No proven race-safe preparation/root anchor or provenance source. | Confirm recipe and actual root/ancestor containment on an approved Windows setup; no adapter self-attestation. | BLOCKED_ON_WINDOWS_EVIDENCE |
| IA-003 | 2, 4 | Actor mutation restricted to individually listed NEW objects below the owned case boundary; suite anchor, evidence area and real ancestors immutable. Above-boundary metadata access needs explicit listing. | A02, J01, X02 | Enforcement/observer not implemented. | Exact ownership boundary and per-actor target allowlist required by each run card; missing target authorization prevents dispatch. | RESOLVED_BY_CONTRACT |
| IA-004 | 2 | Independent bounded observer with separate evidence provenance and safe storage is mandatory; worker/parser output cannot be its sole oracle. | J01, J02, V01, V02, V03 | Specific independent observation/storage mechanism not selected. | Owner/design selection of observable tiers, observer mechanism and trust boundary before code/execution approval. | OPEN |
| IA-005 | 2 | Separate refusal, no dispatch and no object-read claims; require independent observation at the claimed tier, otherwise BLOCKED. | A03, C03, N02 | No verified OS/read-containment or memory-access observer. | Windows evidence shows the actual claimed event boundary without relying only on an adapter trace/canary. | BLOCKED_ON_WINDOWS_EVIDENCE |
| IA-006 | 3 | Count provenance and bounded chain walk required; no capacity/zero scan; preserve original bytes/count; strict <=7 terminal padding acceptance subset, extra tail BLOCKED rather than trimmed. | N02 | Real API span compatibility remains untested. | Acceptance/rejection and retained evidence are deterministic for each declared span/tail; unsupported tail cannot produce accepted inventory. | RESOLVED_BY_CONTRACT |
| IA-007 | 3 | Positive pagination uses f000–f039, 1024-byte pages, bounded dots and <=64 calls; record caps cannot be confused with positive pagination. Over-limit page is a separate negative. | N05, N02, L01 | Actual filesystem pagination not observed. | Freeze that fixture and exact expected name set/END; if unsupported, no positive-test PASS. | RESOLVED_BY_CONTRACT |
| IA-008 | 1, 5, 6 | Pending tests deferred to worker stage; earlier stages cannot borrow an unapproved worker or claim a hard interruption bound. | N06, O02, W01, W02, W03 | Risk/containment decision for ordinary possibly blocking Windows calls not made. | Explicit owner/design decision either accepts a narrowly bounded operational scope without that guarantee or approves a reviewed stage-order change; otherwise no run. | OPEN |
| IA-009 | 1, 3 | Distinct direct-error/stale-IOSB, pending-final-error, unknown-status, count-range and unsupported-class variants; synthetic binding policy is not OS evidence. | N03, N04, N05, N06, I02, X05 | Actual binding and reproducible OS outcomes unconfirmed. | Independently observe status authority/count behavior for each claim; unavailable actual responses remain unexecuted, not mock-filled. | BLOCKED_ON_WINDOWS_EVIDENCE |
| IA-010 | 3, 5 | Per-directory seen set counts dots/raw duplicates; permanent query charges and specific duplicate/progress refusal; no deduplication, restart or refund. | N05, C04, L01, L02 | Dispatcher/session integration not implemented. | Exact progress/duplicate and budget rules required before dispatch; uncertain cursor always halts. | RESOLVED_BY_CONTRACT |
| IA-011 | 4 | Separate before-open/after-open/after-validation/before-read mutation variants; no flag-combination guarantee assumed. | J01, J02 | Actual no-follow, tag mutation and held-object behavior not proven. | Approved Windows observations for each allowed interleaving/component, with no referent read evidence at the claimed tier. | BLOCKED_ON_WINDOWS_EVIDENCE |
| IA-012 | 4 | Identity-only replacement must preserve relevant bytes/size/metadata while independently differing in supported ID; guard identified before read. | M01, I01 | IDs/compare binding and observed race not tested. | Real independent identity mismatch rather than a size/type refusal is observed in an approved synthetic variant. | BLOCKED_ON_WINDOWS_EVIDENCE |
| IA-013 | 4 | Same-ID/same-length in-place and pre-existing mapping variants are separate; record actual sharing result without assuming mutation can or cannot occur. | M02, L03, X03 | Filesystem/map/share behavior varies. | Authorized Windows observation distinguishes content and identity stability; no stable-ID-to-stable-bytes inference. | BLOCKED_ON_WINDOWS_EVIDENCE |
| IA-014 | 4, 6 | Split zero/unsupported/width/volume comparison variants. Physical second-volume work excluded from current single-area scope and needs separate owned-area approval. | I01, I02, J01 | Actual identity/volume support not demonstrated. | Approved evidence for supported comparison variants; real cross-volume claim remains blocked until its separate scope and lab exist. | BLOCKED_ON_WINDOWS_EVIDENCE |
| IA-015 | 4 | Hardlink variant uses NEW names/bytes in one owned case only, with separate link permission; >1 link refuses, unavailable evidence BLOCKED. | I01, I02, M01 | Real link-count/alias behavior and mutation not tested. | Independent observed link-count guard on authorized synthetic hardlinks, never links to pre-existing data. | BLOCKED_ON_WINDOWS_EVIDENCE |
| IA-016 | 1, 2 | Explicit operation/token states, one owner, CRT transfer once, children before parents, no stale-value retries; independent lifetime evidence required. | O01, O02, O03 | Actual close/adoption/inheritance/leak observation remains absent. | Approved Windows evidence for acquisition/adoption/borrow/release variants; unknowable closure is retained, never fabricated as closed. | BLOCKED_ON_WINDOWS_EVIDENCE |
| IA-017 | 1, 5 | Every refusal/incomplete/blocked stops session and run; only independently proved expected REFUSED can support that guard's PASS, without automatic continuation. INCOMPLETE/BLOCKED never PASS. | O03, W04, N03 | Runtime state enforcement not implemented. | Result/resource/continuation table is unambiguous; later case requires fresh explicit direction, not retry or cleanup. | RESOLVED_BY_CONTRACT |
| IA-018 | 1, 2, 3 | Reserve query/record/byte/handle/borrow/observer/evidence resources before work; permanent submitted-call charges and reserved failure evidence; no cap-exhaustion success. | L01, L02, L03 | Real multi-role accounting and instrumentation untested. | Numeric caps and before-work points specified for all roles; any missing reservation blocks that action. | RESOLVED_BY_CONTRACT |
| IA-019 | 1, 2, 5, 6 | Separate startup, termination failure, missing exit, parent interruption and output-pressure variants; no PID/name kill, replacement or indefinite wait. | W01, W02, W03, W04 | Operational response to a surviving child/supervisor loss not selected. | Approve owned-process/observer/survivor-response protocol before worker implementation or execution. | OPEN |
| IA-020 | 2, 5, 6 | Synthetic prefix/temp/write-failure/destination/reparse variants require separate writes and observer; real install readiness/rollback expressly excluded. | V02, V03 | Physical partial-state behavior not observed; no production recovery claim. | Frozen byte/checkpoint oracle and explicit diagnostic-only acceptance; absent ready marker alone cannot pass. | RESOLVED_BY_CONTRACT |
| IA-021 | 4, 5, 6 | Freeze each UTF-16 name, path layer/length and exact expected success/refusal before creation; unsupported environment blocks preparation instead of changing expected results. | X01, X02 | Compatibility on real OS/observer untested. | Per-variant predeclared acceptance forbids post-failure shortening/normalization/settings changes. | RESOLVED_BY_CONTRACT |
| IA-022 | 4, 6 | Sharing, actual ACL denial and unsupported filesystem remain separate; no injected response substitutes for missing owned lab prerequisites. | X03, X04, X05 | Restricted fixture/qualifying filesystem and their authority not selected. | Owner supplies an already permissible lab scope or explicitly leaves those claims unexecuted; no protection/ACL/mount changes. | OPEN |
| IA-023 | 2, 5, 6 | Freeze each permissible branch/property before the run; capability failure means BLOCKED, never a newly invented positive outcome. | A02, W03, M02, V01 | Actual branches still need observation. | Every run card has a falsifiable acceptance branch and exact evidence; alternative unapproved outcomes cannot pass. | RESOLVED_BY_CONTRACT |
| IA-024 | 2, 3, 6 | All diagnostic roles count toward the two-process cap; concrete run cards must list each role/process/thread, observer, path, action, cap and stop owner. | A01, N01, W01, W04 | Actual role assignments/observer/toolchain and per-case cards not chosen. | Owner approves concrete cards within caps before any process/fixture/API operation; no extra helper process implied. | OPEN |

No remark is marked OUT_OF_SCOPE wholesale: identity, ownership and observation
protections remain requirements. Only the named physical cross-volume extension,
real installer/rollback acceptance, universal TOCTOU protection and guaranteed
kernel-I/O deadlines are explicitly outside the current claims; their exclusion
does not close the related in-scope requirements.

### Decisions still requiring separate agreement

- Independent observer, actual open/read visibility and evidence-storage anchor:
  IA-004/IA-005. A logging function name is not sufficient authority.
- Trusted synthetic-root/ancestor preparation and exact directory/no-follow API
  recipe: IA-002/IA-011. Windows evidence remains necessary where documentation
  does not establish the operational guarantee.
- Whether any stage-3/4 run is acceptable without an earlier approved worker,
  or whether a separately reviewed sequence change is needed: IA-008.
- Survivor/uncertain-close/parent-loss operational response: IA-019/IA-016.
  No automatic cleanup or PID-based recovery is selected.
- Available owned restricted fixtures/filesystems, optional paired-volume scope,
  hardlink/reparse privileges already present, existing ABI toolchain and actual
  role/process/run-card manifests: IA-014/IA-015/IA-022/IA-024.

Next steps: owner reviews these requirements and OPEN choices; settle documentable
choices without runtime work; obtain separate approval for any pure-code change;
prepare frozen run cards and unresolved-evidence criteria; only then seek the
stage-specific permissions above. This document grants none of those permissions.

### Document-only checks for this revision

Only REVIEW.md is edited. Verification uses strict UTF-8 decoding and table/ID/
reference checks; the old entire document is retained as an identical byte
prefix, thereby preserving the original matrix and audit, not merely their IDs.
Python tests, AST/compilation, Windows/Native API, worker, preflight and placement
are not run. No package/ZIP reads, fixtures, experiment areas, sentinels or new
artifact files; no configuration, system or production change.

Verification results for this contract revision: strict UTF-8 OK, all new tables
have consistent column counts, all 24 decision IDs are unique within the decision
table and match the 24 original audit IDs exactly; all case references exist in
the original 37-case matrix. Reuse of an IA ID across the original finding and
its decision is intentional traceability, not a newly duplicated finding.
10 RESOLVED_BY_CONTRACT; 9 BLOCKED_ON_WINDOWS_EVIDENCE; 5 OPEN; 0 OUT_OF_SCOPE.
The initial 118150 bytes have unchanged SHA-256
73f57a017d318afaef6e0e7ea32403b82c4fed81d7b146ecbebcabbb556b867b.
This hashes only REVIEW.md to establish document preservation, never a package.

Actual verification: PowerShell/.NET document-only commands, exit 0. The first
full check validated all tables, audit coverage and references. The final command
below repeats the preservation/decision checks after adding this verification
record. It reads only REVIEW.md and writes nothing. Working directory is
D:/nexus2/launcher-next; no Python interpreter, tests or compilation invoked.

```powershell
$path = Join-Path (Get-Location) 'desktop_placement_review/REVIEW.md'
$utf8 = [System.Text.UTF8Encoding]::new($false, $true)
$bytes = [System.IO.File]::ReadAllBytes($path)
$text = $utf8.GetString($bytes)
$sha = [System.Security.Cryptography.SHA256]::Create()
$hash = [System.BitConverter]::ToString($sha.ComputeHash($bytes, 0, 118150)).Replace('-', '').ToLowerInvariant()
$sha.Dispose()
if ($hash -ne '73f57a017d318afaef6e0e7ea32403b82c4fed81d7b146ecbebcabbb556b867b') { throw 'Original prefix changed' }
$old = $utf8.GetString($bytes, 0, 118150)
$cases = @($old -split "`n" | Where-Object { $_ -match '^\| [A-Z][0-9]{2} \|' } | ForEach-Object { $_.Trim().Trim('|').Split('|')[0].Trim() })
$findings = @($old -split "`n" | Where-Object { $_ -match '^\| IA-[0-9]{3} /' } | ForEach-Object { [regex]::Match($_, 'IA-[0-9]{3}').Value })
$contract = ($text -split '## Contract decisions for the 24 independent audit findings', 2)[1]
$rows = @($contract -split "`n" | Where-Object { $_ -match '^\| IA-[0-9]{3} \|' })
$ids = @()
$states = @()
foreach ($row in $rows) {
    $c = @($row.Trim().Trim('|').Split('|') | ForEach-Object { $_.Trim() })
    if ($c.Count -ne 7) { throw 'Decision column count invalid' }
    if ($c[6] -notin @('RESOLVED_BY_CONTRACT', 'OPEN', 'BLOCKED_ON_WINDOWS_EVIDENCE', 'OUT_OF_SCOPE')) { throw 'Status invalid' }
    $ids += $c[0]
    $states += $c[6]
    foreach ($ref in [regex]::Matches($c[3], '\b[A-Z][0-9]{2}\b')) {
        if ($ref.Value -notin $cases) { throw 'Unknown case reference' }
    }
}
if ($cases.Count -ne 37 -or $findings.Count -ne 24 -or $ids.Count -ne 24 -or @($ids | Sort-Object -Unique).Count -ne 24) { throw 'ID counts invalid' }
if (@(Compare-Object ($findings | Sort-Object) ($ids | Sort-Object)).Count) { throw 'Finding coverage mismatch' }
'UTF-8, original document prefix, 24 decisions and case references: OK'
$states | Group-Object | Sort-Object Name | ForEach-Object { $_.Name + '=' + $_.Count }
```
