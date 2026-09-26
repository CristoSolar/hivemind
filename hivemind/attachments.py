"""Files attached to messages: validated, copied next to HiveMind's data, and described to agents."""
import asyncio
import mimetypes
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

from hivemind import paths

MAX_BYTES = 50 * 1024 * 1024
MAX_FILES = 10
TRANSCRIBE_TIMEOUT = 120
_DOCUMENT_TYPES = {"application/pdf", "application/json", "application/xml", "application/rtf",
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                   "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                   "application/msword", "application/vnd.ms-excel",
                   "application/vnd.oasis.opendocument.text"}


def root():
    return paths.data_dir() / "adjuntos"


def kind_of(path):
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        return "documento" if Path(path).suffix.lower() in (".md", ".txt", ".csv", ".log") else "archivo"
    if mime.startswith("image/"):
        return "imagen"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("text/") or mime in _DOCUMENT_TYPES:
        return "documento"
    return "archivo"


def _safe(name):
    return re.sub(r"[^\w.-]+", "_", name).strip("._") or "archivo"


def store(sources, thread):
    """Validate every file first, then copy them all under adjuntos/<thread>/."""
    if len(sources) > MAX_FILES:
        raise ValueError(f"Puedes adjuntar hasta {MAX_FILES} archivos por mensaje.")
    files = []
    for src in sources:
        p = Path(src).expanduser()
        if not p.is_file():
            raise ValueError(f"No encuentro el archivo {p.name}.")
        if not os.access(p, os.R_OK):
            raise ValueError(f"No puedo leer {p.name}.")
        size = p.stat().st_size
        if size > MAX_BYTES:
            raise ValueError(f"{p.name} pesa más de {MAX_BYTES // (1024 * 1024)} MB.")
        files.append((p, size))
    folder = root() / _safe(thread)
    entries = []
    for p, size in files:
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{uuid.uuid4().hex[:8]}-{_safe(p.name)}"
        shutil.copy2(p, dest)
        entries.append({"name": p.name, "path": str(dest), "kind": kind_of(p.name), "size": size,
                        "transcript": None})
    return entries


def remove_thread(thread):
    shutil.rmtree(root() / _safe(thread), ignore_errors=True)


def prompt_lines(entries):
    if not entries:
        return ""
    lines = ["Adjuntos (ábrelos con la herramienta Read):"]
    for e in entries:
        line = f"- {e['kind']}: {e['path']}"
        if e.get("transcript"):
            line += f" — transcripción: «{e['transcript']}»"
        lines.append(line)
    return "\n".join(lines)


async def transcribe(path):
    """Speech to text on this machine: ffmpeg → 16 kHz mono WAV → `voxtype transcribe`.

    Returns None when a tool is missing or anything fails; the file is still attached."""
    if not (shutil.which("voxtype") and shutil.which("ffmpeg")):
        return None
    scratch = Path.home() / ".cache" / "tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as d:
        wav = Path(d) / "audio.wav"
        try:
            for cmd in (["ffmpeg", "-loglevel", "error", "-y", "-i", str(path), "-ar", "16000", "-ac", "1", str(wav)],
                        ["voxtype", "transcribe", str(wav)]):
                proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                            stderr=asyncio.subprocess.DEVNULL)
                try:
                    out, _ = await asyncio.wait_for(proc.communicate(), TRANSCRIBE_TIMEOUT)
                except asyncio.TimeoutError:
                    proc.kill()  # do not leave a runaway transcriber behind
                    await proc.wait()
                    return None
                if proc.returncode != 0:
                    return None
            text = out.decode(errors="replace").strip()
            return text or None
        except (OSError, asyncio.TimeoutError):
            return None
