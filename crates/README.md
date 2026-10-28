# Rust core migration

`nexus-core` implements bounded incremental SHA-256 transfer verification without
IO. `nexus-transport` implements public HTTPS downloads with a shared reqwest
connection pool and a two-worker Tokio runtime. `nexus-python` exposes both through
PyO3 as the optional `_nexus_launcher_core` extension. Python still owns retries,
staging handles, fsync and independent staged-file readback. Transaction phase
orchestration is now also in Rust, through the existing Python safe-IO adapter.

The updater uses the Rust verifier when the extension is installed. Without it,
the same contract has a Python compatibility implementation. An installed but
broken/incompatible extension is not silently ignored. This is an incremental
migration, not a completed launcher rewrite or a measured performance gain.

Public pack/manifest requests use Rust when the extension includes HTTP API v1.
Every redirect is checked before connection: exact allowed host, HTTPS, port 443,
no URL credentials or fragment. Only User-Agent, Accept and single open-ended
Range headers are allowed. Account/authenticated transport is not changed.
TLS certificate verification remains enabled, using the platform native TLS
backend (Schannel on Windows); redirects never forward credentials or Referer.
Compression is not enabled. Reads have an idle timeout and a total 300-second
request/redirect-chain deadline, a 1 GiB response cap, and a 1 MiB streaming read
cap. Buffered Python `read(n)` additionally supports bounded manifest limit+1
probes and collects fragmented responses until n bytes or EOF.

File-level parallel scheduling, cancellation, native delete operations,
Minecraft/Java setup, authentication, signed updater trust and the UI remain to be
migrated. Reusing the client pool does not itself make sequential installs parallel.

## Transaction migration boundary

`nexus-python/src/transaction.rs` executes the preparing/prepared/committed flow,
backup-before-replacement ordering, all-backups-before-rollback preflight and
cleanup/recovery orchestration. `file_transaction._TransactionIO` retains the
existing path checks, hashing, atomic copy, journal writes and
owned-tree removal. The caller still holds the existing update lock. Neither
the journal format nor signed updater metadata is replaced.

An extension with `TRANSACTION_API_VERSION=1` selects Rust orchestration. An older
extension or an absent extension keeps the Python implementation. An incompatible
API or native error never triggers a second attempt through the Python fallback.
Python `Exception` triggers recovery; `BaseException` interruption retains the
journal. A failed recovery retains the original error as exception context.
Success here confirms adapter behavior, not an independent durability guarantee.

```text
python -m pytest tests/test_native_transaction.py tests/test_file_transaction.py tests/test_updater.py
```

The new transaction tests compare Python and Rust backends against temporary
files. Native cases explicitly skip when that API is unavailable. Existing crash
tests terminate their own temporary child processes at journal/copy/cleanup
checkpoints; they must be run with the tested extension on the child process's
Python import path to cover the Rust path.

## Windows safe-IO migration boundary

`nexus-python/src/safe_io.rs` now owns ancestor directory handles through Rust
`OwnedHandle`. With `SAFE_IO_API_VERSION=1`, `safe_paths.pinned_directory` uses
this implementation; old/missing extensions retain the ctypes implementation.
Invalid API versions and native errors are propagated without retrying through
the fallback. Non-Windows behavior is unchanged.

The native pin opens root-to-leaf with FILE_LIST_DIRECTORY/FILE_READ_ATTRIBUTES,
OPEN_REPARSE_POINT and read/write sharing only (no DELETE sharing), checks each
opened handle for directory/reparse attributes, and releases leaf-to-root on
close, drop or partial constructor failure. The create-existing check uses
symlink_metadata rather than following the existing leaf. Mapped network drives,
UNC/device/relative/ambiguous DOS paths are rejected. This is handle lifetime
protection, not a substitute for root containment or verified leaf-file IO.

Unlink and tree traversal still use Python. The bulk-copy loop and source-handle
hashing/replacement have verified optional Rust implementations (see the CI
results below); older extensions still use Python for these operations.
No claim is made that safe-IO migration or long-path support
throughout the Python stack is complete. Long-path tests explicitly read back
using the extended Windows spelling instead of changing Windows policy.

```text
python -m pytest tests/test_native_safe_io.py tests/test_windows_pinning.py tests/test_file_transaction.py
```

`tests/test_native_replace.py` additionally checks source/target preservation,
hardlink replacement, configured size-limit forwarding, no fallback after native
errors, and actual Windows target-sharing conflicts. A persistent lock must
exhaust the bounded retry and release source/ancestor handles; a transient lock
must permit replacement after release. Python and Rust cases are separate;
Rust replacement cases skip when its capability is unavailable, so a passing
run with an older DLL is not evidence for the new replacement implementation.

`COPY_STREAM_API_VERSION=1` moves the bounded copy/hash loop to Rust. The Python
adapter keeps path validation, directory pins, exclusive temporary creation,
flush/fsync, expected-hash comparison, independent readback during replacement
and cleanup. Native code duplicates the two live OS handles without consuming
the originals, copies at most 256 KiB at a time, rejects a byte beyond the
configured limit (capped at 1 GiB) before writing that block, and checks a
300-second budget between synchronous IO calls. This is not a hard interrupt of
blocked kernel IO. Duplicates share file offsets; the private caller must supply
fresh, unused regular-file streams and keep originals open without concurrent
buffered IO. This API does not prove source snapshot consistency or containment.
Source mutation is not prevented by this copy helper; expected-hash comparison
and staged readback retain their existing roles.

An older extension keeps Python copying. Incompatible versions and native
errors propagate without fallback. `tests/test_native_copy.py` covers chunk
boundaries, empty files, hash/size refusals, temporary cleanup and dispatch.
Native-only cases also check original-handle survival and overflow rejection.
The copy implementation was built and exercised by the successful Windows CI
run below and by local tests against its installed wheel. Passing fallback tests
or tests using a previous DLL alone does not qualify this implementation.

## Development checks

### One-shot Windows CI verification

`.github/workflows/rust-core-verification.yml` runs only after a deliberate push
to `rust/verify-core`, on one standard `windows-2025` job with a 20-minute timeout
and read-only repository permissions. Normal progress backups and `main` do not
trigger it. Checkout/setup-python are pinned to full official action commits;
the Rust MSVC toolchain is pinned to 1.99.1. The job checks formatting/warnings,
executes core/transport Rust tests, builds the extension in release mode and
runs `packaging/verify_rust_core.py`. It does not publish a package or release.
The owner authorized one initial run and up to three corrective runs. That
initial allowance was exhausted; subsequent verification-branch pushes require
separate authorization (the archive slice below received one additional run).

The Python harness requires the fresh DLL's exact import location and every
native capability, including copy and handle replacement. Missing capabilities,
any skipped tests, collection/setup errors or changed checkout files prevent
PASS. It records actual pytest results and source SHA-256 comparisons outside
the checkout. Harness unit tests exercise these checks with synthetic objects;
they do not establish native correctness. Rust test/build failure stops the job
before Python verification. Preparing the workflow alone is not a passing build;
completed results are recorded below.

The first authorized run (2026-10-24,
[40110483826](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40110483826))
reached the Windows compiler and failed with E0277 at two SHA-256 formatting
sites: sha2 0.11's digest array does not implement LowerHex. Pure Rust tests,
release build and Python native tests did not run. The pending correction uses
explicit lowercase encoding of the finalized 32 bytes, without a new dependency;
its execution must be established by a later authorized run, not this failed one.
The owner subsequently authorized up to three additional correction/verification
runs with the same branch/job/time limits. The workflow retains private DLL/test
artifacts for one day; these are verification outputs, not a release publication.

The first corrective run
([40111650902](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40111650902))
passed Rust formatting/clippy, six core tests, eight transport tests and the
release DLL build. Python execution reported 178 passed, two failed, zero
skipped and 28 passing subtests, with no checkout changes. Both failures exposed
an obsolete Python-only crash injection: native copying bypassed copy_limited,
so the child never crashed. The corrected test keeps exit 73 mandatory, models
an incomplete temporary file at a backend-independent stream boundary, checks
its bytes and preparing journal, and separately calls the real copy primitive
before crashing before fsync. This does not establish native mid-write fault
injection or storage/power-loss durability. The retained DLL's hash is checked
against the report before local use.
With that DLL and the corrected tests, the local Windows regression run reported
198 passed, zero skipped and 28 passing subtests (including 16 harness tests).
This was an ordinary import from a fresh artifact directory, with no local
Application Control changes and without replacing the earlier development DLL.
The next authorized CI correction also builds a private wheel with maturin,
installs it into an isolated temporary target without network/dependencies and
checks the installed module's origin, capabilities and a SHA-256 known vector.
A completed wheel check is required before claiming that package works.
The next CI run
([40117002563](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40117002563))
confirmed all 198 Python checks with zero skips, 28 passing subtests and the same
14 Rust tests. Its source-preservation check passed. Wheel linking then failed
with LNK1181 for python3.lib: maturin's final rustc invocation lacked the Python
library search directory. The wheel command now verifies the existing Python
installation's libs/python3.lib and forwards `-L native=<that directory>` to the
final crate. It downloads no replacement library and suppresses no warnings.
This is an ordinary linker search path, as described by the
[MSVC linker documentation](https://learn.microsoft.com/en-us/cpp/build/reference/libpath-additional-libpath).

Official references: [push event and branch filtering](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
[checkout 4.2.2](https://github.com/actions/checkout/commit/11bd71901bbe5b1630ceea73d27597364c9af683),
[setup-python 5.6.0](https://github.com/actions/setup-python/commit/a26af69be951a213d495a4c3e4e4022e16d87065).

From the repository root, with Rust/Cargo and the platform linker available:

```text
cargo test --locked -p nexus-core -p nexus-transport
cargo check --locked -p nexus-python
python -m unittest discover -s tests -p test_native_transfer.py -v
python -m unittest discover -s tests -p test_native_http.py -v
```

The unittest output explicitly skips native cases when the extension is absent.
For native verification, build/install the extension in a dedicated development
Python environment, then run the same unittest command and require zero skips:

```text
python -m pip install maturin
python -m maturin develop --release --locked --manifest-path crates/nexus-python/Cargo.toml
```

No compiled extension is committed. Existing PyInstaller/release configurations
are not migrated by this slice; shipping the native extension requires a separate
packaging check on each supported platform. No TUF/signature/identity/state format
or trust decision is replaced by this module.

### Windows GNU toolchain without a system GCC installation

The local check also used the GNU Rust toolchain's bundled LLD and CPython's
existing import library. These are process-local settings, not global PATH or
launcher configuration changes. With `CARGO_HOME` / `RUSTUP_HOME` pointing to the
installed tools and `PYO3_PYTHON` pointing to the development Python executable:

```powershell
$toolchain = "$env:RUSTUP_HOME\toolchains\stable-x86_64-pc-windows-gnu"
$env:RUSTFLAGS = "-C linker=$toolchain\lib\rustlib\x86_64-pc-windows-gnu\bin\rust-lld.exe -C link-self-contained=yes"
$env:PYO3_USE_RAW_DYLIB = '0'
$env:PYO3_BUILD_EXTENSION_MODULE = '1'
& "$env:CARGO_HOME\bin\cargo.exe" build --locked -p nexus-python
```

This requires the selected Python installation to include `libs/python3.lib`.
The Windows networking dependencies also require a working GNU or LLVM `dlltool`
(and assembler for GNU dlltool). If it is not already on the process PATH, use
`-C dlltool=<absolute-path>` in RUSTFLAGS and put its dependency directory on that
process's PATH. The Rust-only verifier did not require this extra networking build
dependency. These tools are build tools, not launcher runtime dependencies.
For a local import check, copy the generated `_nexus_launcher_core.dll` to a fresh
directory outside the repository as `_nexus_launcher_core.pyd`, put that directory
on the test process's `PYTHONPATH`, and run the unittest command above. Do not ship
this manually copied development artifact as a release package.

The optional Windows `HANDLE_REPLACE_API_VERSION = 1` implementation moves
source-handle SHA-256 readback and replacement into Rust. Both parent chains
remain pinned, the leaf denies writes/deletes, verification keeps the configured
byte limit and 300-second budget, and replacement retries only sharing/access
errors for two seconds. Older extensions retain the Python implementation;
native errors never trigger a fallback. Copy has a separate optional Rust path;
unlink and tree cleanup remain in Python. The historical local debug build was
blocked by Application Control while starting dependency build scripts
(`os error 4551`). The later authorized Windows CI and installed-wheel tests
below exercise the native implementation. Fallback tests alone do not verify it.

The local Windows release-wheel build is currently blocked by Application
Control (`os error 4551` while executing a dependency build script). A later new
transport test executable was also blocked. This has not been bypassed and the
system policy has not been changed. Successful debug checks do not establish
release-package or clean-machine compatibility; continue those checks in an
authorized build environment before shipping the extension.

## Completed Windows core verification

The final authorized corrective run
([40117737586](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40117737586)),
source commit `5f9151ad4efef180aa7616246b3191cd8dbe680b`, passed formatting,
clippy, 14 Rust tests, release extension build, and 198 Python tests with zero
skips and 28 passing subtests. Checkout hashes were unchanged. Maturin built
the wheel and its isolated installation smoke check passed.

The downloaded private artifact digest matched GitHub's recorded digest; the
wheel RECORD entries were verified. On the local Windows machine the wheel
was installed into a fresh isolated directory without dependencies or network.
Import selected the Rust backend from that directory, and the same selected
Python regression suite passed: 198 tests, 28 subtests, exit 0 (53.74 seconds).
No earlier development DLL or global Python installation was replaced.

Package: `nexus_launcher_core-0.1.0-cp311-abi3-win_amd64.whl`
(Windows x64, Python 3.11 or newer). SHA-256:
`621a82316eebb4912e1b05713586e911e4722cd29ca115c26f916e4a5dfad790`.
This is a development core package, not a complete launcher installer or a
production release. UI, authentication, Java/Minecraft setup, instance services,
and remaining Python filesystem operations still need migration. Other target
platforms and clean-machine launcher packaging have not been verified here.
Local Application Control remains unchanged; successful CI does not remove
that local build restriction. No performance improvement is claimed without
measurements.

## Archive metadata policy migration

`nexus-core::archive::validate_sizes` implements the existing entry-count, per-file
size and total extracted-size policy without IO, archive parsing or allocation.
The PyO3 `ARCHIVE_API_VERSION=1` bridge bounds metadata conversion by the current
entry limit and releases the GIL for the Rust policy check. The Python
`resource_limits.validate_archive` adapter forwards its current limits. Old or
missing extensions retain Python validation; incompatible versions and native
errors never downgrade. Directory entries continue to count toward the limit.

This checks declared ZIP metadata only. Callers still own path/symlink checks,
bounded decompression, actual-byte limits and rollback; it does not prove archive
trust or source consistency. No extraction or installer parallelism is added.

New tests cover exact limits, negative/oversized integers, total limits, repeated
refusals, unchanged metadata, runtime limit forwarding, old-extension compatibility
and an in-memory ZIP. Rust-only cases skip explicitly until a fresh extension is
available. The CI gate now requires the archive capability and its tests; an old
wheel cannot qualify this slice. Local core compilation succeeded, but Windows
Application Control blocked test execution and PyO3 build scripts (os error 4551).
The available local Python subset passed 56 tests and skipped 14 native cases.
The broader audit module could not collect because keyring is absent in that
validation environment; no dependency was installed. One additional Windows CI
run was authorized specifically for this slice. It completed successfully:
[40175144860](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40175144860),
source commit `841ee9ec8db94a1e7758c9bf69a63ea0f2fb57dd`. Formatting/clippy,
19 Rust tests (including five new archive tests), 232 Python tests with zero
skips and 28 subtests, wheel build and isolated installation smoke all passed.
The CI checkout hashes were unchanged.

After that snapshot, review tightened the Python dispatch for an explicitly
`None` API version: it now refuses instead of falling back. A regression was
added; Rust sources and the wheel were unchanged by this Python-only correction.
Against the verified installed wheel, the final local suite included this
regression and the instance-transfer tests: 238 passed, zero failures/errors/
skips, 28 passing subtests, exit 0 (49.60 seconds). All 384 project files had
identical before/after hashes during that run.

The new wheel uses the same development package name/version and platform tag
as the previous slice; identify it by its source commit and SHA-256, not by
filename alone. Its SHA-256 is
`f328685b7033d5ee48c798c59504176f5e67db65424c3c40d2b1a96383334fcf`.
The downloaded artifact archive matched GitHub digest, and the wheel RECORD
entries were verified before an isolated local install. No global Python
installation, previous wheel, local application-control policy or installed
launcher was replaced. This remains an incremental core migration, without a
performance claim or a complete launcher release.

## Bounded stream orchestration migration

`nexus-python/src/stream_io.rs` moves bounded response assembly and the generic
copy loop behind `STREAM_IO_API_VERSION=1`. `resource_limits.read_limited` and
`copy_limited` dispatch to it when available; older extensions retain the Python
implementation. An incompatible capability or native error never retries through
the fallback. Limits must be nonnegative u64-sized integers and time budgets
finite/nonnegative before any stream IO. The existing monotonic clock is passed
as a callback, retaining deterministic deadline tests.

Read requests remain capped at 64 KiB (responses) / 256 KiB (copies), including
a one-byte overflow probe. No overflow block is written or hashed. Response
reads check deadlines before and after each read; copies retain their original
check after nonempty reads (including accepting a late empty EOF). Callbacks may
block, so these are not hard wall-clock interrupts. Streams remain caller-owned
and open. Read/write/digest exceptions propagate; the helper does not roll back
already written bytes or provide fsync/atomic replacement.

A confirmed old-path defect was also fixed in both implementations: a short write
could previously return a full copy count and hash bytes never written. A
reproduction of the previous committed function reported three bytes after only
one was written. Both backends now refuse short/None/invalid write counts before
updating the digest, without retrying the write.

The source reader, destination writer, digest and clock are Python callbacks.
ZIP parsing/decompression and filesystem path/rollback policy are not migrated
by this slice. The callback orchestration does not claim a speedup or remove the
Python runtime; the existing OS-handle copy API remains separate.

New tests cover byte/chunk boundaries, read1 preference, fragmented reads, total
deadlines, late EOF, short writes, original exception identity, real stored/
deflated ZIP streams and CRC refusal, stream lifetime and fail-closed dispatch.
Local compatibility verification: 103 passed, 35 native cases explicitly skipped
with the older wheel. One new Windows CI run was separately authorized for this
slice. It completed successfully:
[40176299051](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40176299051),
source commit `e3e987d48b4f3c748c51f8c9ea35e4fdd1d4f2f8`. Formatting/clippy,
19 Rust tests, release extension build, 324 Python/native tests with zero
skips and 28 passing subtests, wheel build and installation smoke all passed.
This includes 81 new stream cases (37 Python, 37 Rust, seven dispatch cases),
the existing release-deadline tests and instance-transfer tests. The CI source
checkout hashes were unchanged.

The artifact archive matched GitHub's digest and wheel RECORD hashes were
verified before a fresh isolated local installation without dependencies or
network. The installed wheel selected the Rust backend. The same 324 tests and
28 subtests passed locally with zero failures/errors/skips, exit 0
(50.19 seconds); all 386 project files had matching before/after SHA-256.
No source changes were needed after the CI snapshot; this documentation records
the completed results.

Development wheel SHA-256:
`a55685cfa08b8ad766e66b34cb4d8f4c5a06dad2604e3a4297d2e487c8f012b4`.
The filename/version remains `nexus_launcher_core-0.1.0-cp311-abi3-win_amd64.whl`;
use its source commit and hash to distinguish it from earlier slices. No global
Python installation, earlier wheel or installed launcher was replaced.
Windows Application Control, launcher trust and release behavior were unchanged.
ZIP codecs, service/UI migration and whole-launcher release packaging remain
outside this completed stream-orchestration slice.

## Bounded stream hashing migration

`STREAM_HASH_API_VERSION=1` exposes incremental SHA-256/SHA-512 through the
existing sha2 dependency. `resource_limits.digest_limited` dispatches to it when
available. Missing/old extensions retain the bounded hashlib implementation;
incompatible versions and native errors never downgrade. No new dependencies
or integrity/authentication algorithm policy are introduced.

Hash reads request at most 256 KiB and probe one overflow byte. A digest is
returned only after EOF within the configured byte/time limits; deadline checks
run before and after each read including EOF. CPU hashing runs outside the GIL
while immutable Python bytes stay alive. Stream ownership remains with the
caller, and a blocked IO call is not interrupted by these deadline checks.
The digest is neither a source snapshot guarantee nor an authenticity proof.

Local JAR import now hashes the written destination through an open stream
instead of allocating the entire file with read_bytes. Its existing 1 GiB
copy/input policy is retained. The updater sha256_file helper uses the same
Rust path, retaining the legacy practical u64 file-size range (other updater
layers still enforce transport/extraction limits). It now has a 300-second
between-read time budget; a very slow file may fail closed instead of hashing
indefinitely. Backup/readback ordering, signed metadata and file replacement
logic are unchanged. Other Python hashing sites remain to migrate.

Tests cover both algorithms against hashlib vectors, empty/chunk boundaries,
fragmented read1, overflow and deadlines including late EOF, error propagation,
invalid limits/algorithms, old extensions and incompatible capabilities. The
JAR integration test forbids Path.read_bytes, checks that the written destination
is read and verifies the saved SHA-512 identifier. Updater hash strings retain
their existing lowercase hexadecimal format.

The first local test attempt had setup errors because a large bytes fixture was
used as a pytest parameter ID, exceeding Windows environment-variable limits.
The test now parametrizes by size. The corrected compatibility run passed
71 tests and explicitly skipped 22 cases needing the new native capability.
The separately authorized Windows CI run completed successfully:
[40178666959](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40178666959),
source commit `a14c587db92566b2258d103ed87e1af928a078f2`. Formatting/clippy,
19 Rust tests, release extension build, 374 Python/native tests with zero
skips and 28 passing subtests, wheel build and installation smoke all passed.
The new hash test file contributes 48 cases: 22 Python, 22 Rust and four
compatibility/dispatch cases. CI checkout hashes were unchanged.

The downloaded archive matched GitHub's artifact digest; the wheel RECORD
hashes were verified before installing it into a fresh isolated local folder
without dependencies or network. The installed wheel selected the Rust backend.
All 374 tests and 28 subtests passed locally with zero failures/errors/skips,
exit 0 (50.98 seconds). All 387 source/project files had matching before/after
SHA-256 during the run. No source correction was needed after the CI snapshot.

Development wheel SHA-256:
`ce334b1d48c1423d43124a8757f8e808545c640d358109d083a7451fa5398cbf`.
Its filename is `nexus_launcher_core-0.1.0-cp311-abi3-win_amd64.whl`; identify the
slice by source commit and hash, since the development version is unchanged.
No global Python install, older wheel or installed launcher was replaced.
No Application Control or launcher trust/release policy was changed. ZIP codecs,
other hashing sites, service/UI migration and whole-launcher release packaging
remain outside this completed hashing slice.

## ZIP DEFLATE codec migration

`ZIP_DEFLATE_API_VERSION=1` adds a bounded raw DEFLATE decoder using flate2
1.1.10 with default features disabled and rust_backend selected. Cargo.lock adds
flate2, miniz_oxide, crc32fast, adler2 and simd-adler32; all previously locked
package versions/checksums are preserved. No C zlib backend is selected.
References: [Decompress API](https://docs.rs/flate2/1.1.10/flate2/struct.Decompress.html)
and [feature mapping](https://docs.rs/crate/flate2/1.1.10/features).

`native_zip.open_zip_entry` installs the Rust codec into a fresh ZipExtFile for
unencrypted DEFLATE entries. Updater staging, instance ZIP import and CurseForge
overrides use this entry path. The existing Python ZIP parser, local-header
checks, CRC, path/symlink policy, file ownership and caller rollback remain in
place. Stored entries, encrypted entries and other compression methods retain
their existing implementations; native errors never retry through zlib. Old or
missing extensions retain the original ZIP path. Incompatible capability versions
and an unrecognized private ZipExtFile protocol fail closed.

This deliberately uses a private CPython decoder protocol. Its shape is checked
before replacement, and the supported Windows/Python combination must pass the
new integration tests. This is not a portable replacement for every zlib API or
a rewrite of the whole ZIP parser. Other interpreter versions/platforms remain
unverified. Decoding runs outside the GIL, with at most 1 MiB input/output chunks
plus a boundary probe and the codec window. It refuses entries above 1 GiB output
or 4 GiB compressed input; existing caller/archive limits still apply. Existing
stream deadlines check between reads, not as a hard interrupt of decoding.

Normal context exit requires that no output remains unread in ZipExtFile, the
raw stream reached its real end, exact compressed/decompressed sizes match and
no trailing bytes remain. Truncation, overproduction, trailing input and unknown
outcomes are errors; decoder errors are terminal. This is intentionally stricter
than treating a declared byte count or CRC alone as complete. Exceptions during
reading propagate unchanged and still close the entry. No authenticity, source
snapshot, durability or production-release claim follows from codec completion.

Tests cover real DEFLATE sizes and chunk boundaries, high compression ratios,
ZIP64, CRC/header refusals, byte limits, fragmented raw input, truncated/trailing
streams, declared-size conflicts, unread output, protocol/version refusal and
no fallback after native failure. Real updater tests check installation and
retention of installed bytes on CRC failure. Local compatibility verification:
64 passed, 21 native cases skipped with the previous wheel. One additional
Windows CI run, including retrieval of the five newly pinned Rust dependencies,
was authorized and completed successfully:
[40180904464](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40180904464),
source commit `d433a8a5d14f5983f46f82ba9bb1c32dfebe69f3`. Formatting/clippy,
19 Rust tests, release extension build, 416 Python/native tests with zero skips
and 28 passing subtests, wheel build and installed DEFLATE smoke all passed.
The new ZIP test file contributes 40 cases: 14 Python, 21 native-dependent and
five compatibility/dispatch cases. CI checkout hashes were unchanged.

The artifact archive digest matched GitHub metadata, and wheel RECORD entries
were checked before a fresh isolated local install without dependencies/network.
The installed wheel selected the Rust backend. All 416 tests and 28 subtests
passed locally, zero failures/errors/skips, exit 0 (56.57 seconds); all 390
project files had matching before/after SHA-256 during execution. No source
correction was required after the CI snapshot.

Development wheel SHA-256:
`bfa1f8b0fcc406181fa2c6bd83a9a1ec4762c93c6f8a30e827bce819bba61cf8`.
The filename/version remains `nexus_launcher_core-0.1.0-cp311-abi3-win_amd64.whl`;
identify this slice by source commit/hash. Windows/Python 3.12 was tested here.
No global Python install, previous wheel or installed launcher was replaced.
No system policy, signed trust or release configuration was changed. ZIP parsing,
archive creation, other codecs, service/UI migration and full-launcher release
packaging remain outside this completed DEFLATE slice. No speedup was measured.


### Streaming ZIP creation (verified Windows development slice)

`ZipDeflateEncoder` reuses the existing pinned flate2 Rust backend, with no
new dependencies. It compresses raw DEFLATE outside the GIL, with 1 MiB input
calls, a bounded output buffer and a 1 GiB per-entry input limit. Finalization
must reach StreamEnd with the expected input count; errors are terminal.
Instance exports and local Studio exports use it when the new capability is
present. The Python ZIP writer retains framing, CRC, timestamps and attributes;
caller-owned temporary archives and final replacement remain unchanged.
Instance export now explicitly enforces the same 1 GiB per-file policy as import.
Missing encoder capability preserves Python compression; incompatible versions
and unsupported private ZipWriteFile protocols refuse. Native failure never
retries through Python. Other compression methods remain unchanged.

Tests cover standard-reader roundtrips, empty/chunk-boundary/large entries,
levels 0/6/9, incompressible raw data, ZIP64, metadata, Unicode, finalization,
size/version refusals and preservation of an existing export after encoder
failure. The CI suite selects the existing classified Studio export test by
node ID; the separate privilege-dependent symlink test is not selected. Its
local run skipped because Windows symlink privileges were unavailable, and is
not claimed as verified. CI still rejects every skip in the selected suite.
Private CPython writer compatibility is verified only on Windows/Python 3.12;
other platforms/interpreters remain unverified.
This slice does not claim byte-identical compressed archives or measured speedup.

The selected compatibility checks with the previous wheel passed 95 cases and
skipped 25 native-encoder cases. One additional Windows CI run was authorized:
[40182537872](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40182537872),
source commit `72ad8ccdd0038cad0d80665617061bd7356d1480`. Formatting/clippy,
19 Rust tests, release build, 466 Python/native tests and 28 subtests, wheel
build and installed compression/decompression smoke all passed. The selected
suite had zero failures, errors or skips. The encoder test file contributes
47 cases; the existing classified Studio export case is selected explicitly.

The downloaded artifact SHA-256 matched GitHub metadata, and every hashed wheel
RECORD entry and size was checked. A fresh isolated local install selected Rust
and passed the same 466 tests and 28 subtests, zero skips/errors/failures, exit 0
(55.42 seconds). All 392 project files matched before/after execution. The
privilege-dependent creator symlink case remains outside this verified selection.

Development wheel SHA-256:
`f52620b62da1d93fe17cfce14e76cf11da537519171ef4111caa7e8bc931f373`.
The wheel retains version 0.1.0; distinguish it by source commit and SHA-256.
No global install, previous wheel, installed launcher, system policy or release
configuration was replaced. Publishing, UI/services and complete launcher
release packaging remain outside this slice. No performance claim is made.


### Publishing artifact digests (existing Rust wheel reuse)

SubmissionPackage creation and inventory readback now reuse the existing
`stream_digest_limited` dispatcher for SHA-256 instead of independent Python
loops. The already verified ZIP-encoder wheel provides this capability; no
Rust source, dependency, lockfile or extension ABI changes are needed. Missing
capability retains the existing bounded Python digest implementation; native
errors and incompatible versions refuse without fallback.

The per-artifact hash limit is explicitly 16 GiB (`MAX_PACKAGE_BYTES`), rather
than the generic 1 GiB stream default. Hashing has a 300-second elapsed budget,
checked between reads; it is not cancellation of a blocked callback. Oversized
readback inventory members now refuse instead of being hashed without a
per-entry bound. Output digest format, package JSON/schema, nested ZIP checks,
unsigned/local trust status and final temporary-file replacement are preserved.
Hash equality does not establish authenticity or protect against source changes
between hashing and packaging. ZIP creation/readback here still uses Python's
codec: the current native ZIP entry limit is lower than this path's 16 GiB limit.

New tests check Python/native digest parity, chunk boundaries, live byte limits,
actual client/server/presentation package inventory, dispatch of the full 16 GiB
limit, refusal of incompatible versions, propagation of native failures without
retry and retention of an existing destination. Existing publication workflow
tests are included in the selected regression suite. Targeted verification with
the existing wheel passed 74 tests, zero skips/errors/failures, exit 0.

Full selected local regression verification reused the wheel built from
`72ad8ccdd0038cad0d80665617061bd7356d1480` (SHA-256
`f52620b62da1d93fe17cfce14e76cf11da537519171ef4111caa7e8bc931f373`).
All 492 tests and 28 subtests passed, zero skips/errors/failures, exit 0
(59.93 seconds). All 393 source files matched before/after execution.
The added publishing test file contributes 17 cases and the existing publication
workflow file contributes nine. No new native build or CI run was performed
for this Python dispatch integration; earlier CI evidence belongs to its
original source snapshot. Whole-launcher/UI migration remains incomplete.


### Explicit publishing ZIP limits (verified Windows development slice)

`ZIP_LIMITS_API_VERSION=1` adds an optional keyword-only per-entry `limit` to
the existing decoder/encoder constructors. Their default remains 1 GiB. Explicit
limits are bounded at 16 GiB, with unchanged 1 MiB chunk/output budgets; larger
declared sizes do not allocate matching buffers. Decoder compressed input keeps
its previous 4 GiB ceiling for limits up to 1 GiB, and uses a 16 GiB ceiling for
explicit larger limits. Encoder counts actual input and fails terminally on
overflow. This is a resource bound, not protection against every CPU-heavy input.

SubmissionPackage uses the new explicit regime for client/server/presentation
entries, the existing 2 MiB metadata policy for readback, and ZIP64 writers for
unknown-length artifact streams. Standard ZIP framing/CRC, inventory SHA-256,
path/nested-archive checks and final replacement remain with their existing
owners. Metadata creation still uses the ordinary default writer. An older
extension without the new capability keeps Python for explicit-limit operations;
wrong capability versions refuse. Selected native failures never retry. Python
callers still enforce actual copy/hash byte limits in the compatibility path.

Local compatibility with the previous wheel passed 120 cases and skipped ten
new native cases, exit 0. An initial new-test import-path collection error was
corrected before that successful run. Tests cover real submission roundtrip,
standard ZIP-reader compatibility, exact policy forwarding, empty/small explicit
bounds, terminal overflow, large declarations without large allocation, old-DLL
compatibility and temporary archive cleanup on native failure. No 16 GiB fixture
was processed; boundary declarations are not large-file execution evidence.

One of three authorized ZIP verification attempts was needed; no retry was used.
CI [40186758640](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40186758640)
verified source `5a2b4676ec36b509437e13c5a08584d937277bfb`: formatting/clippy,
19 Rust tests, release build, 510 Python/native tests and 28 subtests, wheel build
and installed smoke all passed. There were zero failures/errors/skips.
Artifact digest and wheel RECORD checks passed. A fresh isolated local wheel
install passed the same 510 tests and 28 subtests, exit 0 (57.65 seconds), with
all 394 project files unchanged during execution. The new test file contributes
17 cases; the new capability also adds one harness rejection case.

Development wheel SHA-256:
`ad12443816d65cd332d2b59086999fdfc54041bdae064b1be7632fff765e729c`.
No release/global install, system policy, main branch or installed launcher was
changed. This confirms the selected small-fixture paths, not real 16 GiB IO,
other platforms, all service/UI flows or complete migration.


### Local inventory digest consumers

BuildManager.sha256, CurseForgeImporter.sha256_file and StudioService inventory
digest now reuse `resource_limits.digest_file` and the existing native stream
SHA-256 capability. This adapter opens the source once, requires an ordinary
file, and derives its live byte limit from fstat on that handle. Unlike assigning
the generic 1 GiB default, this retains the prior accepted file sizes. A source
growing beyond the opened size refuses; shrinking or concurrent in-place edits
are not made snapshot-consistent by this helper. A 300-second deadline is checked
between callbacks, not as kernel-IO cancellation. Handle ownership remains in
Python and context cleanup closes it on native exceptions. Missing capability
uses the established bounded Python path; selected native errors never retry.

Tests cover three real consumer entrypoints on both backends, empty/small/chunk
boundary files, descriptor-derived bounds rather than a second pathname stat,
synthetic changed-size/nonregular metadata and handle cleanup after native errors.
No real file-growth race or unusual storage/alias protection is claimed. Existing
build publication/rollback tests act only on temporary local data; no remote
publishing/signing is enabled. Targeted tests passed 36 cases, exit 0, no skips.
An editing-script locale error was corrected against hash-matched baseline bytes
using explicit UTF-8 before final verification; no old report was rewritten.

The full selected suite with the existing explicit-ZIP-limits wheel passed
545 tests and 28 subtests, zero failures/errors/skips, exit 0 (60.13 seconds).
All 395 project files matched before/after execution. This consumer-only slice
did not compile Rust or start CI; its native wheel comes from verified commit
`5a2b4676ec36b509437e13c5a08584d937277bfb`. New inventory tests contribute
25 cases; existing build/CurseForge tests add ten to the prior selection.


### Pure launch policy (verified Windows development slice)

`nexus-core::launch` owns the existing ASCII username rule, uppercase environment
key allowlist and exact Java command-log redaction. A typed PyO3 bridge exposes
`LAUNCH_POLICY_API_VERSION=1`; process_utils and MinecraftLauncher call it when
present. Older extensions retain the same Python rules. Wrong API versions,
native errors and malformed environment masks refuse rather than falling back.
Core code has no filesystem, process, credential-issuance or network APIs.
Environment values never cross this bridge: Python normalizes key case with
its existing Unicode mapping and fetches only allowed values after policy success.
The actual short-lived ticket is still obtained after installation and added by
the existing caller. A fresh ticket is not inherited from the source environment.

The bootstrap hidden-process helper does not import the native extension: lookup
is lazy inside the three policy consumers. Command redaction preserves existing
exact-argument semantics, including existing limitations on equals-form access
tokens; this is not a generic secret detector. It returns a copy and never
changes the command supplied to the subprocess. Username/launch wiring and
log behavior are tested with synthetic installer/process dependencies. They do
not prove compatibility with minecraft-launcher-lib or actual Java/game startup.

Local compatibility with the prior wheel passed 58 tests and skipped 18 new
native cases, exit 0. New tests cover all allowlisted names, excluded injection
variables, unread secret values, Unicode key normalization, source preservation,
username boundaries, exact redaction and fail-closed policy errors. Three pure
Rust tests also specify key boundaries and source-command preservation; they
were executed successfully in the verification below. No new dependencies or lock changes were needed.

The first of three authorized launch-policy CI attempts passed; no build/test
retry was needed. CI [40213852917](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40213852917)
verified source `83e6e9b9df64545a7268b3697bf14e3682a95566`: formatting/clippy,
22 Rust tests, release extension build, 593 Python/native tests and 28 subtests,
wheel build and installed policy smoke all passed. Zero failures/errors/skips.
Artifact SHA-256 and wheel RECORD checks passed. A read-only monitor connection
reset was retried without dispatching another CI job.

The freshly installed isolated wheel passed the same 593 tests and 28 subtests
locally, exit 0 (63.24 seconds); all 398 project files remained unchanged during
execution. The new policy file contributes 42 cases, two existing environment
tests are selected, and four new capability/entrypoint rejection cases execute.
No real Java/Minecraft, installer, game account, cloud resource or release ran.
The missing external installer was explicitly stubbed only in synthetic wiring
tests; those tests are not minecraft-launcher-lib integration evidence.

Development wheel SHA-256:
`74e4b24fe47b6867e469b63165d696d03f4b8963c6c57b5d324fe032e3ea43b6`.
Whole-launcher migration, full command generation, Java/loader installation,
account/trust migration, UI replacement and release parity are still incomplete.


### Catalog compatibility prerequisite — owner decision 2026-10-25

Before translating catalog models into Rust, the owner chose legacy server IDs,
dual JSON-key read support and refusal of conflicts. ProjectCatalog reads
`projects` and `nexus_launcher.projects`, returns canonical `main`, and writes
legacy `projects` on explicit save. Raw divergent dual-key values are not merged.
Duplicate JSON members, ambiguous identities and unsupported versions refuse
before a temporary file/default replacement. Unknown fields on retained root,
project and server objects survive explicit save. This does not provide
cross-process write serialization or a rollback/durability guarantee.

The existing reader also omitted the already declared `java_major` field; it
now roundtrips that field instead of resetting a saved override to zero.
Known UI identity/artwork projections and Gearmorph maintenance-state keys use
`main`; their values, action grammar, visual tokens and privilege refusal remain
unchanged. Selected/pinned/recent aliases normalize in memory without reading or
writing a config file. Existing save actions remain the persistence owner.
Role/permission string compatibility and account data have not been changed.

Targeted catalog/config tests passed 25 cases, exit 0. The maintained UX contract
records the owner's decision and exact verification limits. No installed user
catalog was read or migrated. The frontend premium strict static audit exited 1
with 42 findings (40 actionless-button, one empty-href, one WebKit-only scrollbar).
All six referenced files match the pre-change hashes; these findings require
separate UI/runtime review and are not declared resolved. Qt/browser navigation,
visual, keyboard and DPI verification did not run. Static model/grammar parity
is not UI acceptance, and this compatibility repair is not a Rust catalog port.

The full selected local suite passed 618 tests and 28 subtests, exit 0
(67.52 seconds), with zero failures/errors/skips and all 399 project files
unchanged during execution. The prior launch-policy wheel was reused; no Rust
source/dependency, native build or CI changed for this compatibility prerequisite.
The selected count includes 16 new compatibility cases and nine existing catalog/
config cases. The strict UI audit remains FAIL and live UI remains NOT RUN.


### Native catalog JSON preflight (verified Windows development slice)

`CATALOG_API_VERSION=1` selects a pure Rust parser/preflight through the existing
ProjectCatalog read owner. Rust checks root/version shape, repeated object keys
at every level, exact dual-format consistency and project/server identities.
Namespaced server aliases participate in duplicate detection. It returns JSON
with the legacy root key; Python still constructs existing dataclasses, applies
official-server synchronization and owns every save/merge/replace. This is not
a complete typed Rust catalog/store, a second writer or migration of accounts.
Native errors do not retry through the Python parser or load default projects.
Old extensions retain the established compatibility reader.

The new direct dependencies are pinned serde 1.0.229 (already locked) and
serde_json 1.0.154 with raw_value. Resolution added only serde_json 1.0.154,
memchr 2.8.3 and zmij 1.0.23. All 166 old package identities/checksums stayed
unchanged; only nexus-core dependency metadata changed. This is ordinary registry
integrity metadata, not an independently qualified toolchain/provenance claim.
Official API references: https://docs.rs/serde_json/latest/serde_json/ and
https://docs.rs/serde_json/latest/serde_json/value/struct.RawValue.html .

Unknown values are retained as borrowed RawValue spans instead of being converted
to serde_json::Value. This avoids rounding arbitrary-size unknown JSON integers
and avoids treating a user property named $serde_json::private::Number as a
numeric authority tag. Unique-key validation walks the borrowed spans. Dual-key
equality preserves integer/float/bool distinctions, object-order independence
and signed float zero in the existing canonical-JSON policy. Raw data, IDs and
unknown values never appear in native error messages.

The native input profile is standard JSON with Unicode scalar strings and at
most 128 nesting levels. Legacy Python-only inputs containing NaN, lone UTF-16
surrogate escapes or deeper metadata are unsupported and must refuse without
rewriting the file. There is no claim of parity for these non-profile inputs.
No fixed catalog-byte ceiling or bounded-memory guarantee is introduced here;
input is still read by the existing local-file owner. No existing live catalog
was inspected. Tests use temporary files and synthetic native faults.

Before dependency resolution, Python compatibility passed 76 tests and skipped
15 native cases; Rustfmt and inline wheel-smoke Python AST passed. The later
escaped-duplicate/profile cases still require the next verification run.
Dependency retrieval and up to three bounded Windows CI attempts were approved
separately by the owner; native compilation/tests are recorded below.

The final Python compatibility run passed 77 tests and skipped 18 new native
cases. The first authorized CI attempt
[40216459075](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40216459075)
stopped at two collapsible-if clippy errors; native tests did not run there.
Only those two conditionals changed for the second attempt. No warning was
suppressed, no old dependency was upgraded and first-attempt logs were retained.

CI [40216681213](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40216681213),
source `aabfd14312a2fffc123e8df92d11d916965f7a2f`, passed formatting/clippy,
25 Rust tests, release extension build, 656 Python/native tests and 28 subtests,
wheel build and installed smoke. Zero failures/errors/skips. The third approved
attempt was not used. Artifact digest and wheel RECORD verification passed.
The isolated local installed wheel passed the same 656 tests and 28 subtests,
exit 0 (70.89 seconds); all 402 project files matched before/after execution.
The new catalog test file contributes 36 cases; two capability/entrypoint
rejection cases account for the other increase. Windows/Python 3.12 is tested;
other platforms, full typed Rust storage and UI/release parity remain unverified.

Development wheel SHA-256:
`3e08a16904618096638ac7f15c28a7b43a8343e2bbcb60fb53c72f163859fac2`.
The strict UI audit remains unresolved and no catalog/profile/account in an
installed launcher was migrated. No production trust or release gate changed.


### Minecraft command assembly (verified development module)

`nexus-core::minecraft_command` accepts an owned typed plan and returns an argument
vector only. A strict PyDict bridge exposes MINECRAFT_COMMAND_API_VERSION=1.
The real MinecraftLauncher.launch consumer now calls native_minecraft, selecting
this implementation when present. Missing capability retains the public 8.0
library command function; bad capability/version or selected-native failure does
not retry. The native profile explicitly requires minecraft-launcher-lib 8.0.

Existing Python/library owners still read profiles, resolve inheritance, apply
OS/feature rules, construct classpaths and resolve the configured Java executable.
Rust owns command ordering and sequential placeholder expansion. User JVM
options, fallback JVM fields, logging, main class and tail/extras retain their
original raw/literal behavior; only metadata argument strings expand. Empty
metadata JVM lists differ from missing JVM lists. There is no shell/string
execution, install, credential issuance, game process or permission grant here.
Tickets remain obtained after command preparation by the existing launch owner.

Expansion length is checked before allocating a replacement result. The core
refuses NUL, empty executable/main class, more than 64 replacements, over 10,000
parts, arguments above 1 MiB or aggregate input/output above 16 MiB. These are
core-stage bounds after typed extraction, not a global memory/CPU deadline or
proof that the vector fits the operating-system command-line limit.
Errors contain no supplied command data; the secret-bearing plan has no Debug
implementation. No performance improvement or actual launch safety is inferred.

The 8.0 reference wheel was retrieved for source inspection only (SHA-256
ff17960c62e21ca7e21329303ae56bdefc0246de3bc9a5e1578dfa8df6604746);
it was not installed/imported. BSD-2-Clause source/license fixtures and hashes
are retained under tests/fixtures/minecraft-launcher-lib-8.0. Tests compile only
reviewed function definitions, never package imports or top-level startup/network
code. Rule context/runtime/native-classifier dependencies are explicitly
controlled, so these fixtures do not qualify actual Java/native-library loading
or all OS profiles. Three Rust tests cover ordering, missing/empty JVM semantics
and refusal before oversized expansion. Verification results follow.

Local Python compatibility passed 101 tests and skipped 26 new native cases,
exit 0. Cases cover modern/legacy/fallback/empty/inherited/runtime profiles,
ordered substitutions, logging/tails, source preservation, typed-plan refusals,
error redaction and ticket/spawn suppression after a native refusal. Existing
synthetic launch-policy tests now patch the new command adapter seam. No source
assertion was removed. Up to three bounded Windows CI attempts for this block
were separately authorized; no new dependencies or lock changes are required.


CI attempt 1 (40219234351) passed 28 Rust tests and the native build, but
Python verification failed with 43 fixture-hash setup errors (664 passed,
28 subtests passed): Windows checkout changed LF source fixtures to CRLF.
The original hashes/checks were retained. A narrowly scoped .gitattributes
rule preserves reference bytes; no global Git setting was changed.

CI [40219998483](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40219998483),
source da5700ad87e44e2b141faa621d8c8ce30c3e526d, passed formatting/clippy,
28 Rust tests, release extension build, 707 Python/native tests and 28 subtests,
wheel build and installed smoke. Zero failures/errors/skips. Two of the three
authorized attempts were used. Artifact digest and wheel RECORD checks passed.
The isolated local installed wheel also passed 707 tests and 28 subtests,
exit 0; all 411 project files matched before/after execution. The new command
test file contributes 49 cases. No Java, Minecraft, installer, real account,
game network, release or main-branch change was exercised by these tests.

Development wheel SHA-256:
5a15aac64b83ac04c5bd65186c0c581e9a0de9cb6feeeedd721f153631291d82.
This verifies command-vector assembly on the tested Windows/Python profile;
profile/rule/classpath ownership, UI parity and full Rust migration remain open.


### Minecraft profile inheritance (verified development module)

`nexus-core::minecraft_profile` now implements the one-level inheritance merge
from the pinned minecraft-launcher-lib 8.0 reference. With
MINECRAFT_PROFILE_API_VERSION=1, native_minecraft retains parent-file selection
and reading but delegates merging to Rust. Older extensions keep the existing
library merge. Incompatible capability or selected-native errors refuse without
retry. The existing 8.0 library-version guard remains in the command consumer.

Child libraries precede parent libraries; only identities already in the child
suppress parent entries. Parent duplicates remain. Root lists are child+parent;
nested lists are parent+child; nested child scalar/dict fields are ignored just
as in 8.0. This intentionally preserves reference quirks, not an independent
claim about the correct general Minecraft inheritance specification. A parent's
own inheritsFrom is not traversed. No additional profile reads are introduced.
Unknown JSON values remain raw, retaining large integers and negative zero.
The bridge serializes decoded profiles, preserving the established reader's
last-key-wins behavior; duplicate raw object keys are not a new supported contract.

Inputs are limited to 8 MiB each, combined library entries to 10,000, and serialized
output to 16 MiB. These are native-stage bounds, not limits on prior Python JSON
loading/serialization or a complete memory/time bound. Native merge additionally
requires a nonempty string inheritsFrom and valid library/merged-array shapes.
Nonfinite JSON numbers are refused by the bridge instead of being emitted as
nonstandard JSON. No fallback occurs after these selected-native refusals.

Two Rust unit tests and 21 native-dependent Python cases were executed successfully.
The Python/reference compatibility run passed 98 cases with 21 native skips,
exit 0. The initial collection attempt failed due to the test fixture import
path; corrected to the existing tests package before the successful rerun.
No new dependencies or lockfile changes. OS/feature/regex rules, classpath paths,
native classifier selection, Java resolution, install and spawn remain with their
existing owners. Verification results and CI usage follow.


CI [40229987359](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40229987359),
source 9d8e7acb86cbf82e2c4543df2a56ec4f171648ae, passed formatting/clippy,
30 Rust tests, release extension build, 735 Python/native tests and 28 subtests,
wheel build and installed smoke. Zero failures/errors/skips; one of three
approved CI attempts used. Artifact archive digest and wheel RECORD verified.
The isolated local installed wheel also passed 735 tests and 28 subtests,
exit 0; all 414 source files matched before/after execution. The new profile
test file contributes 26 cases (21 require the new capability); two new gate
cases account for the remaining increase from the prior 707-test suite.

The first local wheel runner invocation stopped before importing/testing the
extension due to a misescaped Windows path in the outside-repository helper.
Only that helper path was corrected; the initial diagnostic log was retained.
No launcher source or wheel changed for the successful rerun.

Development wheel SHA-256:
f26a6f31c4facc340aca4ceb44f70cc14024d3e230bf627e7ecb98269b577646.
This is verified one-level merge behavior on synthetic inputs, not completed
profile/rule/classpath migration, full launcher parity or a production release.
No Java, game, installer, real account or game network was exercised here.


### Minecraft classpath planning (verified development module)

`nexus-core::minecraft_classpath` owns ordered classpath entries, Maven coordinate
layout, classifier-download path selection, the exact 8.0 fallback coordinate
spelling and final jar/id selection. MINECRAFT_CLASSPATH_API_VERSION=1 exposes
ordered path-component vectors. The actual command adapter invokes this planner,
then uses host os.path.join and the existing classpath separator to render them.
There is no filesystem access, path canonicalization or existence/loadability
check in the planner. Absolute/relative classifier paths retain the old join
semantics; this module does not establish containment or trust in a library.

Existing Python owners still evaluate library OS/version/feature rules with
empty options (the 8.0 behavior) and select native classifiers. Excluded entries
never invoke native-classifier selection. None denotes an excluded entry;
Some(empty string) denotes an included library without a native. The vector
must have one selection for every library. No supplied selection is an execution
grant. Rule regex semantics are deliberately unchanged. Missing native capability
keeps library.get_libraries; bad API or selected-native failure does not retry.

Inputs are capped at 8 MiB, 10,000 libraries, 64 coordinate colon-parts and 250
group segments. NUL and components above 1 MiB are refused. Aggregate component
bytes are capped at 16 MiB. These are core-stage limits, not bounds on prior
Python extraction/serialization, rendered path size, OS command-line capacity or
total process memory. The existing command-vector limits still apply afterward.
Unknown fields remain opaque JSON. No new dependencies or lockfile changes.

Two Rust tests and 42 native-dependent Python cases were executed successfully. The local
compatibility set passed 125 cases with 42 native skips, exit 0. The new test file
contains 48 cases, including pinned-reference comparison using Windows/POSIX
path renderers, duplicates, exclusions, classifier fallbacks and malformed data.
Path-renderer coverage does not qualify native Linux/macOS operation or actual
Java/native-library loading. No Java, installer, game or account is launched.


CI [40308318666](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40308318666),
source 1b0a19e5e5a37d111a52bb29fe86e20e1a667752, passed formatting/clippy,
32 Rust tests, release extension build, 785 Python/native tests and 28 subtests,
wheel build and installed smoke. Zero failures/errors/skips; one of three
approved CI attempts used. Artifact digest and wheel RECORD were verified.
The isolated local installed wheel also passed 785 tests and 28 subtests,
exit 0; all 417 project files matched before/after execution. The new classpath
test file contributes 48 cases; two new capability/entrypoint gate cases account
for the remaining increase from the previous 735-test suite.

Development wheel SHA-256:
6ba8ed5cba24fd57da4137c3e9a47017d3505deddcf6a45b89be3b9a2aecdcf7.

No Java, game, installer, real account or game network was exercised. Existing
rule/native-classifier owners remain Python; no independent rule-engine or
Linux/macOS/production qualification is inferred from path-renderer parity.


### Minecraft rule evaluation (verified development module)

`nexus-core::minecraft_rules` owns allow/disallow control flow, OS-name/x86
conditions, six normalized feature-presence flags and the all-rules conjunction
used by the pinned 8.0 reference. Both argument rule names and classpath library
rules now invoke the native evaluator with MINECRAFT_RULES_API_VERSION=1.
Libraries still use empty launch options. Unknown feature/OS keys and feature
values retain the reference's behavior; this does not assert equivalence to a
general Mojang rule engine or fix quirks in 8.0.

The existing host retains platform.system(), lazy architecture identification
and Python regex/OS-version matching. Regex calls use the original library's
version-only rule predicate, not a replacement regex engine. A version regex or
architecture predicate is called only when reached. OS field insertion order
and list short-circuit are preserved, including errors before/after a failed
condition. Host Python exceptions propagate without compatibility fallback.
The bridge retains the GIL to make these callbacks; no latency improvement,
regex execution timeout or complete Rust-only rule implementation is claimed.

The core accepts at most 1 MiB of rule JSON and 1,024 rules; system context is
limited to 128 bytes without NUL, feature vector length exactly six. Reached
known OS values must be strings and actions allow/disallow; invalid shapes
refuse. These are bounded decoded-input contracts, not limits on prior Python
normalization or regex complexity. The bridge receives decoded dictionary/list
input (existing last-key-wins JSON policy), not arbitrary duplicate-key syntax.
No host operation, trust decision, process creation or permission is implemented
by this evaluator. Existing native-classifier selection remains Python.

Two Rust tests and 349 native-dependent cases were executed successfully. The new test
file has 355 cases, including 336 synthetic context/option/rule combinations,
regex error ordering, lazy predicates, malformed shapes, refusal and wiring.
The local compatibility set passed 173 tests with 349 native skips, exit 0.
Four system/architecture contexts use controlled predicates, not real Linux/macOS
execution. Dependencies and Cargo.lock are unchanged; no Java/game/account is
used. Native verification is separately authorized before a CI run.


CI [40310380497](https://github.com/robloxksergg-creator/nexus-launcher-pre-rust-backup-20261024/actions/runs/40310380497),
source cfc108b93c14db3b9610d59d628b47d0859c86c2, passed formatting/clippy,
34 Rust tests, release extension build, 1,142 Python/native tests and 28 subtests,
wheel build and installed smoke. Zero failures/errors/skips; one of three
approved CI attempts used. Artifact digest and wheel RECORD were verified.
The isolated local installed wheel also passed 1,142 tests and 28 subtests,
exit 0; all 420 project files matched before/after execution. The new rules
test file contributes 355 cases; two capability/entrypoint gate cases account
for the remaining increase from the prior 785-test suite.

No Java, game, installer, real account or game network was exercised. Host
architecture, OS identification and Python regex predicates remain with their
existing owners. Synthetic context coverage does not qualify native Linux/macOS,
security/trust enforcement, regex time bounds or complete Rust migration.

Development wheel SHA-256:
fb9bc412739f5f8e06b55ace33e437336594c362c8b69894dc77414374989a7e.


### Basic account/portable integration verification (2026-10-26)

The practical milestone is a runnable hybrid development candidate, not a
completed Rust rewrite. Existing portable registration now continues to the
real login UI only after profile confirmation, with nickname prefilled and a
fresh masked password field. Cancel/pending states do not authenticate. Fixed
an obsolete function-code name in the tester handoff tests. Keyring failures
are controlled, failed saves clear the provisional binding, and the startup
restore worker reports failure rather than stranding the account controls.

An existing Qt 6.8.3 build environment was reused without upgrading it. The
combined installed-Rust-wheel + account/security/launch regression set passed
1,231 tests and 28 subtests, exit 0, zero failures/errors/skips; all 422 project
files matched before/after execution (123.88 seconds). Seven portable handoff
checks include a real WebEngine register action, native form and return to login.
A focused account/environment set passed 62 cases. Initial stale-test/dependency
and renderer-test boolean errors were retained in outside-repository logs and
corrected; they are not reported as successful runs.

For packaging only, the project's existing exact pins tuf 7.0.1,
securesystemslib 1.5.1 and urllib3 2.8.0 were downloaded to an isolated directory;
wheel RECORDs and SHA-256 values were checked against PyPI. Other project pins
were already available. No requirements/lockfile or existing environment changed.
79 TUF/package/signed-update tests passed with those selected runtime packages.

A separate PyInstaller development build completed, exit 0, using an outside
copy of the existing portable spec with a development name, explicit checkout
root and native-core inclusion. The packaged executable completed two offline
self-test launches, exit 0: renderer loaded, image present, no script errors,
off-record browser profile. Its live process was observed loading the exact
Rust DLL from the verified wheel (SHA-256
86fa38065f8ab8e38dbb6b9ca0211fac5d4e937a813a31ca2a4ee622c079e884).
The first integrity attempt incorrectly compared to the standalone cargo DLL;
execution stopped, then the wheel payload was used as the correct baseline.
This is main-window smoke evidence, not a full frozen registration/login test.

The existing strict UI audit still returns exit 1 with 42 findings in six assets
files, all byte-identical to the pre-change baseline; no complete UI audit PASS
is claimed. Source/Qt account tests use synthetic service results; no production
account, verification email, Java/game process or deployment was created. A
credential-free live GET to the existing profile endpoint returned JSON 401,
confirming reachability only. Rust, account and release trust boundaries remain;
this development candidate does not complete migration or qualify production.


### Frozen HTTPS resource regression remediation (2026-10-27)

A real registration attempt exposed a packaging defect not covered by the earlier
main-window smoke. The build interpreter's ssl.py loads codex-rejected-cas.pem
next to itself during SSLContext construction. The portable package included
ssl.py but omitted that public policy resource: frozen HTTPS failed with
FileNotFoundError before any HTTP response, despite the same source client
working. Certificate-store enumeration itself was available.

packaging/hooks/hook-ssl.py now collects the exact adjacent resource; the portable
spec enables the hook. A referenced but missing build resource fails packaging.
Standard interpreters without that policy do not add it. No ssl.py, CA policy,
hostname verification, system store or transport fallback was modified. The
resource SHA-256 is c916ce1b14ed8ca69e9b5c9fab22799a900dd610d6d4ec9b1347f4fd48e53718.
The existing development folder received only that missing file; prior binary
and diagnostic evidence were retained unchanged.

The explicit --connection-check-report mode performs only a credential-free
profile GET and an empty registration-code POST (expected 401/400). It never
passes an email/password/device ID, requests a message, creates an account or
opens the GUI/storage. Reports contain bounded exception types/codes and stack
function locations, not exception messages or user credentials.

Frozen diagnostic reproduction failed on both routes before the resource was
added and returned expected 401/400 afterward. A clean rebuilt package using
the hook automatically includes a byte-identical resource and passes those same
transport probes. 62 targeted packaging/registration/account tests passed, exit
0. This validates TLS transport, not successful email delivery or account creation.
No deployment, production database write or automatic registration retry occurred.
