"""Local GUI bridge. Token arrives through an anonymous stdin pipe, never argv.

Reuses the hardened CLI engine. Emits JSON lines containing progress only.
No browser credentials or footage are sent to the GUI process through stdout.
"""
import ast
import io
import json
import signal
import sys

import tesla_dashcam_decrypt as engine


def event(kind, **fields):
    sys.__stdout__.write(json.dumps({"kind": kind, **fields}) + "\n")
    sys.__stdout__.flush()


class Progress(io.TextIOBase):
    def __init__(self):
        self.pending = ""

    def write(self, text):
        self.pending += text
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            if line.startswith(("Scan: ", "Results: ")):
                counts = ast.literal_eval(line.split(": ", 1)[1])
                event("scan" if line.startswith("Scan:") else "summary", counts=counts)
            elif line:
                event("progress", message=line)
        return len(text)

    def flush(self):
        pass


def interrupt(_signal, _frame):
    raise KeyboardInterrupt


def main():
    signal.signal(signal.SIGTERM, interrupt)
    token = ""
    if "--scan" not in sys.argv[1:]:
        # The native app closes the pipe after one message. Bound its size.
        message = sys.stdin.buffer.readline(16385)
        if len(message) > 16384:
            raise ValueError("Authentication message too large")
        payload = json.loads(message)
        token = payload.get("token", "").strip()
        if token.startswith("Bearer "):
            token = token[7:].strip()
        if not token or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError("Invalid token format")
        del message, payload
        engine.prompt_token = lambda: token
    sys.stdout = Progress()
    try:
        code = engine.main(sys.argv[1:])
        event("finished", code=code)
        return code
    finally:
        token = ""
        engine.prompt_token = lambda: ""


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        event("cancelled", message="Stopped. Completed files retained; scan again to resume.")
        raise SystemExit(130)
    except Exception as exc:
        # Avoid emitting exception bodies or tracebacks with credentials.
        event("error", message="Operation failed: " + type(exc).__name__)
        raise SystemExit(1)
