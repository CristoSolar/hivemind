# Attachments — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Each task is TDD:
> write the failing test, watch it fail, implement, watch it pass, commit.

**Goal:** Attach images, documents and audio to messages. Files are copied into
`~/.local/share/hivemind/adjuntos/<thread>/`, listed in the agent prompt, readable by the agents
without asking, and audio is transcribed locally with ffmpeg and `voxtype transcribe`.

**Spec:** `docs/superpowers/specs/2026-09-25-attachments-design.md` holds the limits, the prompt
format and the notice text, which are the binding details.

**Deviation from the writing-plans template:** the steps name the tests and interfaces but do
not repeat full code. The spec already fixes every value, and the same session executes the
plan with TDD.

## Global constraints

- Limits: 50 MB per file and 10 files per message.
- Kinds are `imagen`, `audio`, `documento` and `archivo`.
- Errors are in Spanish, raised as `ValueError`, and nothing is posted when one is raised.
- Tests use stdlib `unittest`. GUI tests run on Broadway. Scratch files go in `~/.cache/tmp`.
- The transcriber is injectable, so tests never call `voxtype` or `ffmpeg`.

## Tasks

1. **Store.** Add an `attachments` column (JSON, default `[]`) with an idempotent migration.
   `add_message(thread, author, kind, content, attachments=None)` stores it. `history` and
   `add_message` return it parsed.
   Tests: migration of an old database; attachments round trip.
2. **`hivemind/attachments.py`.**
   - `root()`
   - `kind_of(path)`
   - `store(paths, thread) -> list[dict]`: validates and copies.
   - `remove_thread(thread)`
   - `prompt_lines(entries) -> str`
   - `async transcribe(path) -> str | None`: runs ffmpeg and voxtype, with a timeout.

   Tests: kinds; copy under the thread folder with a safe name; missing, directory, oversized
   and too-many files rejected; `remove_thread`; prompt format; transcribe returns None when
   `voxtype` is not on PATH.
3. **Hub.**
   - `send(thread, text, origin=None, attachments=None)` validates and copies before posting,
     transcribes audio through `self.transcriber`, and posts one notice when a transcript is
     missing.
   - The private prompt gets the attachments section, and the group history lines list
     attachments.
   - `clear_thread` removes the files.
   - The `Hub(transcriber=...)` parameter defaults to `attachments.transcribe`.

   Tests: private prompt has the section; empty text with files is allowed; empty text
   without files is rejected; audio transcript from a fake; notice on failure; group history
   lists the files; clear removes them.
4. **Runner.** Add `add_dirs=[attachments.root()]`, and always permit
   `Read(<root>/*)`.
   Test: the options carry `add_dirs`, and Read inside the root asks for no approval.
5. **Server.** `send` forwards `attachments`.
   Test: round trip with a real temporary file.
6. **GTK.**
   - Composer: pending chips with ✕, a 📎 button (`Gtk.FileDialog.open_multiple`), a
     `Gtk.DropTarget` for `Gdk.FileList`, and pasting an image with Ctrl+V (the clipboard
     texture is saved as a PNG in `~/.cache/tmp`).
   - `on_send(text, files)`.
   - Bubbles: a thumbnail (`Gtk.Picture`, 240 px) for images, and a chip for other files
     (the icon from `Gio.content_type_get_icon`, the name, the size). A click opens the file
     through `Gtk.FileLauncher`. Audio adds an expander with the transcript.

   Broadway tests: chips appear and ✕ removes them; send passes the paths and clears the
   chips; an image bubble has a `Gtk.Picture`; a document bubble has a chip.
7. **Docs, reinstall, live check.** Update the README (a section on attaching files) and
   AGENTS.md (`send` attachments). Reinstall, then have a throwaway Haiku agent describe a
   real image and read a PDF. Then run the final review, merge and push.
