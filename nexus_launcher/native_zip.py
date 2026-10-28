"""Optional Rust DEFLATE inside the existing, fully consumed ZIP entry path.

Uses the tested ZipExtFile private decoder protocol. Other codecs keep their
existing implementations; a selected native decoder never falls back on error.
"""
from contextlib import contextmanager
import io
import time
import zipfile

from nexus_launcher.native_transfer import _native
from nexus_launcher.resource_limits import MAX_FILE_BYTES, copy_limited


def _codec_enabled(capability, limit):
    if not isinstance(limit, int) or not 0 <= limit <= 16 * 1024**3:
        raise ValueError("Invalid ZIP byte limit")
    enabled = _native is not None and hasattr(_native, capability)
    if enabled and getattr(_native, capability) != 1:
        raise ImportError("Incompatible NEXUS ZIP API")
    if limit != MAX_FILE_BYTES:
        if _native is not None and hasattr(_native, "ZIP_LIMITS_API_VERSION"):
            if _native.ZIP_LIMITS_API_VERSION != 1:
                raise ImportError("Incompatible NEXUS ZIP limits API")
        else:
            enabled = False  # Older extensions retain Python for explicit limits.
    return enabled


@contextmanager
def open_zip_entry(archive, member, *, limit=MAX_FILE_BYTES):
    enabled = _codec_enabled("ZIP_DEFLATE_API_VERSION", limit)
    if member.file_size > limit:
        raise ValueError("ZIP entry exceeds byte limit")
    with archive.open(member) as stream:
        decoder = None
        if enabled and member.compress_type == zipfile.ZIP_DEFLATED and not member.flag_bits & 1:
            if (not isinstance(stream, zipfile.ZipExtFile)
                    or getattr(stream, "_compress_type", None) != zipfile.ZIP_DEFLATED
                    or getattr(stream, "_left", None) != member.file_size
                    or getattr(stream, "_compress_left", None) != member.compress_size
                    or not all(hasattr(stream, name) for name in (
                        "_decompressor", "_readbuffer", "_offset", "_eof"))):
                raise ImportError("Unsupported ZipExtFile decoder protocol")
            decoder = _native.ZipDeflateDecoder(
                member.file_size, member.compress_size,
                **({"limit": limit} if limit != MAX_FILE_BYTES else {}))
            stream._decompressor = decoder
        yield stream
        if decoder is not None:
            if (not stream._eof or stream._left != 0
                    or stream._offset != len(stream._readbuffer)):
                raise ValueError("ZIP entry completion not proven: unread output")
            decoder.verify_complete()


@contextmanager
def write_zip_entry(archive, member, *, force_zip64=False, limit=MAX_FILE_BYTES):
    enabled = _codec_enabled("ZIP_ENCODE_API_VERSION", limit)
    stream = archive.open(member, "w", force_zip64=force_zip64)
    encoder = None
    try:
        if enabled:
            writer_type = getattr(zipfile, "_ZipWriteFile", None)
            if (writer_type is None or not isinstance(stream, writer_type)
                    or getattr(stream, "_file_size", None) != 0
                    or getattr(stream, "_compress_size", None) != 0
                    or not all(hasattr(stream, name) for name in ("_compressor", "_zinfo"))):
                raise ImportError("Unsupported ZipWriteFile encoder protocol")
            if stream._zinfo.compress_type == zipfile.ZIP_DEFLATED:
                level = getattr(stream._zinfo, "_compresslevel", None)
                encoder = _native.ZipDeflateEncoder(
                    6 if level in (None, -1) else level,
                    **({"limit": limit} if limit != MAX_FILE_BYTES else {}))
                stream._compressor = encoder
        yield stream
    except BaseException:
        try:
            stream.close()
        except BaseException:
            pass  # Preserve the original failure; caller discards its temp ZIP.
        raise
    else:
        stream.close()
        if encoder is not None:
            encoder.verify_complete(stream._file_size)


def write_zip_data(archive, member, data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not isinstance(member, zipfile.ZipInfo):
        member = zipfile.ZipInfo(member, time.localtime(time.time())[:6])
        member.compress_type = archive.compression
        member._compresslevel = archive.compresslevel
        member.external_attr = (0o40775 << 16) | 0x10 if member.is_dir() else 0o600 << 16
    member.file_size = len(data)
    with write_zip_entry(archive, member) as output:
        copy_limited(io.BytesIO(data), output, MAX_FILE_BYTES)


def write_zip_file(archive, path, name):
    member = zipfile.ZipInfo.from_file(path, name, strict_timestamps=archive._strict_timestamps)
    if member.is_dir() or member.file_size > MAX_FILE_BYTES:
        raise ValueError("ZIP export file exceeds policy")
    member.compress_type = archive.compression
    member._compresslevel = archive.compresslevel
    with path.open("rb") as source, write_zip_entry(archive, member) as output:
        copy_limited(source, output, MAX_FILE_BYTES)
