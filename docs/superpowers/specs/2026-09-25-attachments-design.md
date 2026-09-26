# Attachments: images, documents and audio

Date: 2026-09-25. Status: approved in conversation.

## Goal

Attach files to any message: images, documents and audio. Agents receive them in a form they
can use. Claude sees images and reads PDF and text through its `Read` tool. Audio is transcribed
locally first, because Claude cannot listen to it.

## User experience

- **Adding files:** a 📎 button next to the composer opens the system file picker (several files
  at once). Files can also be dropped onto the chat, and **Ctrl+V** pastes an image from the
  clipboard, such as a screenshot.
- **Before sending:** attachments show as chips above the composer, each with its name and an ✕
  to remove it. A message may be files only, with no text.
- **In the conversation:**
  - Images show as thumbnails (at most 240 px on their long side).
  - Other files show as a chip with an icon, the name and the size.
  - A click opens the file with the default app.
  - Audio also shows its transcript when there is one, in an expander.
- **Limits:** 50 MB per file and 10 files per message. A file over the limit, missing or
  unreadable is rejected with a Spanish toast, and nothing is sent.

## Storage

- Files are **copied** to
  `~/.local/share/hivemind/adjuntos/<thread>/<8 hex>-<safe name>`, so the message keeps working if
  the original is moved or deleted.
- `messages` gains an `attachments` column: JSON, default `[]`. Each entry is
  `{name, path, kind, size, transcript}`, where `kind` is `imagen`, `audio`, `documento` or
  `archivo` (from `mimetypes`) and `transcript` is set for audio only.
- Clearing a conversation (`clear_thread`) also deletes its attachment folder.

## Agents

- The prompt of the turn a message triggers ends with an attachments section:
  ```
  Adjuntos (ábrelos con la herramienta Read):
  - imagen: /…/adjuntos/<thread>/ab12cd34-captura.png
  - documento: /…/informe.pdf
  - audio: /…/nota.m4a — transcripción: «…»
  ```
- In a group, the recent-history lines that carry attachments list them the same way, so every
  member who answers can open them.
- The runner passes the attachments root in `add_dirs`, and always permits
  `Read(<attachments root>/*)`, the same way the board tools are always permitted. Other
  folders keep their normal rules.

## Audio transcription

- When an audio file is attached, the daemon runs these steps before routing the message:
  1. `ffmpeg -i <file> -ar 16000 -ac 1 <tmp>.wav` (any input format becomes 16 kHz mono).
  2. `voxtype transcribe <tmp>.wav`, with a 120 s timeout. The transcript is stdout, trimmed.
- The transcriber is injectable (`Hub(transcriber=...)`) so tests do not need `voxtype`.
- If `voxtype` or `ffmpeg` is missing, or transcription fails, the file is still attached with
  no transcript. The conversation gets one system notice: "No pude transcribir el audio: instala
  Voxtype desde el menú de Omarchy (Instalar → Voxtype) y elige un modelo multilingüe para
  audios en español."
- Nothing leaves the machine.

## Protocol

- `send {thread, text, attachments?: [local file paths]}`. The GUI runs on the same machine, so
  it passes paths, and the daemon validates and copies them.
- Pasted images are first saved by the GUI to `~/.cache/tmp/hivemind-pegado-<time>.png`, and
  then sent as a path like any other file.
- `message.attachments` travels in the `message` events and in `history`.

## Testing

- **Store:** the migration adds the column; round trip of attachments.
- **Hub:**
  - valid files are copied, and their `kind` is detected;
  - missing, directory, oversized or too many files are rejected with a Spanish error and
    nothing is posted;
  - text can be empty when there are attachments;
  - the prompt holds the attachments section;
  - group history lists attachments;
  - audio gets its transcript from a fake transcriber;
  - a failing transcriber posts the notice once and still attaches;
  - `clear_thread` removes the files.
- **Runner:** `add_dirs` holds the attachments root, and `Read` inside it is auto-permitted.
- **Server:** `send` with attachments does a round trip.
- **GTK (Broadway):**
  - the composer shows chips for pending files, removes them with ✕, and sends paths with the
    text;
  - image bubbles render a thumbnail;
  - other bubbles render a chip.
