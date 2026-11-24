"""Normalize legacy Word uploads once, before any version-bound extraction."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import shutil
import signal
import subprocess
import threading
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from .parser import MAX_FILE, parse_docx

DOC_MAGIC = bytes.fromhex('d0cf11e0a1b11ae1')
CONVERSION_TIMEOUT = 60
_slots = threading.BoundedSemaphore(2)


def converter_path():
    configured = os.getenv('RIXIN_SOFFICE_PATH')
    executable = shutil.which(configured or 'soffice') or (None if configured else shutil.which('libreoffice'))
    if not executable and not configured:
        candidate = Path('/Applications/LibreOffice.app/Contents/MacOS/soffice')
        if candidate.is_file():
            executable = str(candidate)
    if not executable:
        raise HTTPException(503, 'DOC 转换服务未配置，请联系管理员配置 LibreOffice，或另存为 DOCX 后上传。')
    return executable


def convert_doc(content):
    executable = converter_path()
    if not _slots.acquire(timeout=1):
        raise HTTPException(503, 'DOC 转换服务繁忙，请稍后重试。')
    try:
        with TemporaryDirectory(prefix='rixin-doc-') as directory:
            root = Path(directory)
            source = root / 'source.doc'
            source.write_bytes(content)
            profile = root / 'profile'
            (profile / 'user').mkdir(parents=True)
            # Isolated noninteractive profile: do not execute document macros or update links.
            (profile / 'user/registrymodifications.xcu').write_text('''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
<item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>2</value></prop></item>
</oor:items>''')
            output = root / 'output'
            output.mkdir()
            command = [executable, '-env:UserInstallation='+profile.as_uri(), '--headless', '--nologo',
                       '--nodefault', '--norestore', '--infilter=MS Word 97',
                       '--convert-to', 'docx:Office Open XML Text', '--outdir', str(output), str(source)]
            try:
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           start_new_session=True)
                try:
                    process.wait(timeout=CONVERSION_TIMEOUT)
                except subprocess.TimeoutExpired:
                    if os.name == 'posix':
                        try: os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                    else:
                        process.kill()
                    process.wait()
                    raise HTTPException(422, 'DOC 转换超时；请检查文件是否加密或损坏，另存为 DOCX 后重试。') from None
            except OSError:
                raise HTTPException(503, 'DOC 转换程序无法启动，请联系管理员检查配置。') from None
            target = output / 'source.docx'
            if process.returncode != 0 or not target.is_file():
                raise HTTPException(422, 'DOC 无法转换，请确认文件未加密且能正常打开，或另存为 DOCX 后重试。')
            if target.stat().st_size > MAX_FILE:
                raise HTTPException(413, '转换后的 DOCX 超过 20 MB，请缩小文件后重试。')
            normalized = target.read_bytes()
            try: parse_docx(normalized)
            except Exception:
                raise HTTPException(422, 'DOC 转换后未能读取正文，请检查文件；扫描件需要 OCR。') from None
            return normalized
    finally:
        _slots.release()


def normalize_document(store, name, content):
    name = (name or '').replace('\\', '/').split('/')[-1]
    suffix = Path(name).suffix.lower()
    if suffix not in ('.doc', '.docx'):
        raise HTTPException(415, '仅支持 DOC 或 DOCX 格式的 Word 合同。')
    if len(content) > MAX_FILE:
        raise HTTPException(413, '合同文件超过 20 MB。')
    source_digest = sha256(content).hexdigest()
    converted = suffix == '.doc'
    if converted:
        if not content.startswith(DOC_MAGIC):
            raise HTTPException(422, '文件不是有效的 DOC，请用 Word 或 WPS 另存为 DOCX 后上传。')
        with store.connect() as db:
            cached = db.execute('SELECT normalized FROM document_conversions WHERE source_sha256=?', (source_digest,)).fetchone()
        if cached:
            normalized = cached['normalized']
        else:
            normalized = convert_doc(content)
            # The first successful conversion is canonical, even under concurrent requests.
            with store.connect() as db:
                db.execute('INSERT OR IGNORE INTO document_conversions VALUES(?,?,?,?,?)',
                           (source_digest, content, normalized, sha256(normalized).hexdigest(), datetime.now(timezone.utc).isoformat()))
                normalized = db.execute('SELECT normalized FROM document_conversions WHERE source_sha256=?', (source_digest,)).fetchone()['normalized']
        original_name = name
        name = name[:-4] + '.docx'
        content = normalized
    try:
        parsed = parse_docx(content)
    except Exception as exc:
        raise HTTPException(422, '正文无法解析；请使用可读取文字的 Word 合同，扫描件需要 OCR。') from exc
    if converted:
        parsed['source_document'] = {'filename': original_name, 'sha256': source_digest, 'format': 'doc'}
        parsed['limitations'].append('原始 DOC 已转换为 DOCX；版式、编号、批注和修订请结合原文件核对。')
    return name, content, parsed


async def document(file, store):
    try:
        content = await file.read(MAX_FILE + 1)
    finally:
        await file.close()
    return await run_in_threadpool(normalize_document, store, file.filename, content)
