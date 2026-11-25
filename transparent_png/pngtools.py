# -*- coding: utf-8 -*-
"""Generate fully transparent PNGs efficiently, with no QGIS dependency."""
from pathlib import Path
import os
import logging
from pathlib import PurePosixPath, PureWindowsPath
import shutil
import struct
import tempfile
import zlib

from .translator import tr

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


class CancelledError(Exception):
    """The user canceled the operation."""


def read_png_dimensions(path):
    """Read PNG dimensions from IHDR without decoding the pixel data."""
    path = Path(path)
    with path.open('rb') as fh:
        header = fh.read(33)
    if len(header) != 33 or header[:8] != PNG_SIGNATURE:
        raise ValueError(tr('Not a valid PNG file: {}').format(path.name))
    length, chunk_name = struct.unpack('>I4s', header[8:16])
    if length != 13 or chunk_name != b'IHDR':
        raise ValueError(tr('Invalid PNG header: {}').format(path.name))
    if (zlib.crc32(header[12:29]) & 0xffffffff) != struct.unpack('>I', header[29:33])[0]:
        raise ValueError(tr('PNG header CRC mismatch: {}').format(path.name))
    width, height = struct.unpack('>II', header[16:24])
    if not (0 < width < 2**31 and 0 < height < 2**31):
        raise ValueError(tr('Invalid PNG dimensions: {}').format(path.name))
    return width, height


def _chunk(fh, tag, data=b''):
    fh.write(struct.pack('>I', len(data)))
    fh.write(tag)
    fh.write(data)
    fh.write(struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))


def make_transparent_png(src, dst, progress=None, overwrite=False):
    """Write true RGBA PNG with alpha=0 for every pixel; return (width, height).

    Only the source PNG's 33-byte header is read. The output is a new
    lossless PNG, encoded row by row, using O(width) memory.
    The RGB values are 0 too. Never write in place.
    """
    src = Path(src)
    dst = Path(dst)
    if os.path.normcase(str(src.resolve())) == os.path.normcase(str(dst.resolve())):
        raise ValueError(tr('The original PNG file cannot be overwritten.'))
    if dst.exists() and not overwrite:
        raise FileExistsError(tr('A file with the same name already exists at the destination: {}').format(dst))
    w, h = read_png_dimensions(src)
    if not dst.parent.is_dir():
        raise FileNotFoundError(tr('Output folder does not exist: {}').format(dst.parent))

    temp_file = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=str(dst.parent),
                                         prefix='.transparent_tmp_', suffix='.png',
                                         delete=False) as fh:
            temp_file = Path(fh.name)
            fh.write(PNG_SIGNATURE)
            _chunk(fh, b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            # PNG filter type 0, then RGBA (0, 0, 0, 0) repeated.
            row = b'\x00' * (w * 4 + 1)
            compressor = zlib.compressobj(level=1)
            buffered = bytearray()
            for y in range(h):
                buffered.extend(compressor.compress(row))
                if len(buffered) >= 256 * 1024:
                    _chunk(fh, b'IDAT', bytes(buffered))
                    buffered.clear()
                if progress and (y % 256 == 0 or y == h - 1):
                    if progress(y + 1, h) is False:
                        raise CancelledError(tr('Processing cancelled.'))
            buffered.extend(compressor.flush())
            if buffered:
                _chunk(fh, b'IDAT', bytes(buffered))
            _chunk(fh, b'IEND')
        # Do not overwrite if another process created the target in the meantime.
        if dst.exists() and not overwrite:
            raise FileExistsError(tr('A file with the same name already exists at the destination: {}').format(dst))
        if overwrite:
            os.replace(str(temp_file), str(dst))
            temp_file = None
        else:
            # Exclusive creation: never overwrite a destination created concurrently.
            with temp_file.open('rb') as inp:
                out = dst.open('xb')
                try:
                    with out:
                        shutil.copyfileobj(inp, out)
                except OSError:
                    dst.unlink()
                    raise
        return w, h
    finally:
        if temp_file is not None:
            try:
                temp_file.unlink()
            except OSError as exc:
                logging.getLogger(__name__).warning("Temporary PNG cleanup failed: %s", exc)


def preserve_georeference(src, dst):
    """Copy existing sidecars without parsing or replacing files."""
    src, dst = Path(src), Path(dst)
    pairs = [(src.with_suffix(s), dst.with_suffix(s))
             for s in ('.pgw', '.pngw', '.wld', '.prj')]
    pairs += [(Path(str(src) + s), Path(str(dst) + s))
              for s in ('.wld', '.aux.xml')]
    for old, new in pairs:
        if old.is_file() and not new.exists() and not new.is_symlink():
            with old.open('rb') as inp, new.open('xb') as out:
                shutil.copyfileobj(inp, out)


def prepare_pairs(paths, source_root, output_root):
    """Require separate, non-overlapping roots and reject output aliases."""
    root = Path(source_root).resolve()
    out = Path(output_root).resolve()
    if not out.is_dir():
        raise ValueError(tr('Select an existing output folder.'))
    if root == out or root in out.parents or out in root.parents:
        raise ValueError(tr('Source and output folders must not overlap.'))
    pairs = []
    for path in paths:
        src = Path(path).resolve()
        dst = out / src.relative_to(root)
        if dst.resolve() != dst or out not in dst.resolve().parents:
            raise ValueError(tr('Unsafe output path: {}').format(dst))
        pairs.append((src, dst))
    return pairs


# -------------------- Relative-path list import --------------------
def read_relative_png_list(list_file, source_root):
    """Resolve only listed relative PNG paths; do not traverse the source tree.

    Supports UTF-8 (including BOM), CP932/Shift-JIS, and UTF-16 BOM TXT.
    Slashes and Windows backslashes both work. Invalid or outside-root paths
    are rejected. Returns paths plus diagnostic details.
    """
    list_file = Path(list_file)
    if not list_file.is_file():
        raise ValueError(tr('TXT list not found: {}').format(list_file))
    root = Path(source_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(tr('Source root folder not found: {}').format(root))

    data = list_file.read_bytes()
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        lines = data.decode('utf-16').splitlines()
    else:
        try:
            lines = data.decode('utf-8-sig').splitlines()
        except UnicodeDecodeError:
            try:
                lines = data.decode('cp932').splitlines()
            except UnicodeDecodeError as exc:
                raise ValueError(tr('Cannot decode the TXT file (supported: UTF-8 / CP932 / UTF-16): {}').format(exc))

    found, missing, invalid, duplicate = [], [], [], []
    seen = set()
    total = 0
    headers = {'完全透過対象pngファイル', '相対パス', 'ファイル名',
               'path', 'filepath', 'filename', 'relative path', 'relative_path',
               'png files to make fully transparent'}
    for line_num, raw in enumerate(lines, 1):
        value = raw.strip().strip('\ufeff').strip()
        # Allow a heading, blank rows and comment lines.
        if not value or value.startswith('#') or value.lower() in headers:
            continue
        if len(value) > 1 and value[0] == value[-1] == '"':
            value = value[1:-1].strip()
        total += 1
        normalized = value.replace('\\', '/')
        winpath = PureWindowsPath(value)
        posixpath = PurePosixPath(normalized)
        parts = [part for part in normalized.split('/') if part not in ('', '.')]
        if (not parts or normalized.startswith('/') or winpath.drive
                or winpath.is_absolute() or posixpath.is_absolute()
                or '..' in parts or ':' in normalized):
            invalid.append((line_num, value, tr('Absolute paths, parent directory references and invalid paths are not allowed')))
            continue
        if not normalized.lower().endswith('.png') or parts[-1].lower().endswith('.png') is False:
            invalid.append((line_num, value, tr('Not a PNG path')))
            continue
        rel = '/'.join(parts)
        key = rel.casefold()  # Case-insensitive for typical Windows sources.
        if key in seen:
            duplicate.append((line_num, rel))
            continue
        seen.add(key)
        candidate = root.joinpath(*parts)
        # Detect Windows junctions and symlinks pointing outside the root.
        candidate_real = candidate.resolve()
        try:
            candidate_real.relative_to(root)
        except ValueError:
            invalid.append((line_num, rel, tr('The file is outside the source root')))
            continue
        if candidate_real.is_file():
            found.append(str(candidate_real))
        else:
            missing.append((line_num, rel))

    return {
        'source_root': str(root), 'list_file': str(list_file),
        'total': total, 'paths': found, 'missing': missing,
        'invalid': invalid, 'duplicates': duplicate,
    }


def read_selected_pngs(paths, source_root=''):
    """Validate direct selections, infer their common parent if no root is given."""
    root = Path(source_root).expanduser().resolve() if source_root else None
    if root is not None and not root.is_dir():
        raise ValueError(tr('Source root folder not found: {}').format(root))
    found, missing, invalid, duplicate = [], [], [], []
    seen = set()
    for value in paths:
        candidate = Path(value).expanduser().resolve()
        if candidate.suffix.lower() != '.png':
            invalid.append(value)
            continue
        if root is not None and root not in candidate.parents:
            raise ValueError(tr('Selected PNG is outside the source root: {}').format(value))
        key = os.path.normcase(str(candidate))
        if key in seen:
            duplicate.append(value)
            continue
        seen.add(key)
        if candidate.is_file():
            found.append(str(candidate))
        else:
            missing.append(value)
    if root is None:
        if not found:
            root = Path.cwd()
        else:
            try:
                root = Path(os.path.commonpath([str(Path(path).parent) for path in found]))
            except ValueError as exc:
                raise ValueError(tr('Select PNG files from the same drive or shared folder.')) from exc
    return {'source_root': str(root), 'paths': found, 'missing': missing,
            'invalid': invalid, 'duplicates': duplicate}
