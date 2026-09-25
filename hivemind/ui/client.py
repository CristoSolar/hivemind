import json
import traceback

from gi.repository import Gio, GLib

from hivemind import paths


class Client:
    def __init__(self, on_event, on_state):
        self.on_event, self.on_state = on_event, on_state
        self.conn = self.out = self.inp = None
        self.n, self.callbacks = 0, {}

    def connect(self):
        addr = Gio.UnixSocketAddress.new(str(paths.socket_path()))
        Gio.SocketClient().connect_async(addr, None, self._connected)

    def _connected(self, sc, res):
        try:
            self.conn = sc.connect_finish(res)
        except GLib.Error:
            self.on_state(False)
            GLib.timeout_add_seconds(2, lambda: self.connect() and False)
            return
        self.out = self.conn.get_output_stream()
        self.inp = Gio.DataInputStream.new(self.conn.get_input_stream())
        self.on_state(True)
        self._read()

    def _read(self):
        self.inp.read_line_async(GLib.PRIORITY_DEFAULT, None, self._line)

    def _line(self, stream, res):
        try:
            line, _ = stream.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:
            self.conn, self.callbacks = None, {}
            self.on_state(False)
            GLib.timeout_add_seconds(2, lambda: self.connect() and False)
            return
        try:
            msg = json.loads(line)
            if "event" in msg:
                self.on_event(msg["event"])
            elif (cb := self.callbacks.pop(msg.get("id"), None)):
                cb(msg.get("result"), msg.get("error"))
        except Exception:
            # A UI bug in one handler must not stop the read loop.
            traceback.print_exc()
        self._read()

    def call(self, method, params=None, callback=None):
        if not self.conn:
            if callback:
                callback(None, "El daemon no está conectado.")
            return
        self.n += 1
        if callback:
            self.callbacks[self.n] = callback
        data = (json.dumps({"id": self.n, "method": method, "params": params or {}}) + "\n").encode()
        self.out.write_all(data, None)
