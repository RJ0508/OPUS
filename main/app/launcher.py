"""
Launch the Opus Lease Summary Assistant.

Usage (dev):   micromamba run -n lease_summary python -m app.launcher
Usage (built): ./OpusLeaseSummary  (PyInstaller bundle)
"""
from __future__ import annotations

import base64
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


class FileDownloadAPI:
    """API exposed to JavaScript for handling file downloads in desktop mode."""

    def __init__(self, window):
        self.window = window

    def save_file(self, filename: str, data_base64: str) -> dict:
        """
        Save a file using native dialog.
        Called from JavaScript when download is needed.
        """
        try:
            import webview
            # Decode base64 data
            data = base64.b64decode(data_base64)

            # Use save dialog to get target path
            result = self.window.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=str(Path.home() / "Downloads"),
                save_filename=filename,
            )

            if result and len(result) > 0:
                # On macOS, result is a string path
                save_path = result[0] if isinstance(result, list) else result
                Path(save_path).write_bytes(data)
                return {"success": True, "path": save_path}
            return {"success": False, "error": "User cancelled"}
        except Exception as e:
            return {"success": False, "error": str(e)}


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(port: int) -> None:
    from app.main import start
    start(port)


def main() -> None:
    port = _find_free_port()
    url  = f"http://127.0.0.1:{port}"

    # Start FastAPI in background thread
    t = threading.Thread(target=_start_server, args=(port,), daemon=True)
    t.start()

    # Wait for server to be ready (max 8 s)
    for _ in range(80):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.1)

    # Try pywebview first; fall back to browser
    try:
        import webview  # pywebview

        # Create window first
        window = webview.create_window(
            "Opus Lease Summary Assistant",
            url,
            width=1280,
            height=820,
            resizable=True,
            min_size=(900, 600),
        )

        # Expose API for file downloads
        api = FileDownloadAPI(window)
        window.expose(api.save_file)

        # private_mode=True uses an ephemeral WKWebsiteDataStore — no disk cache
        # between launches, so JS/CSS changes are always picked up fresh.
        webview.start(private_mode=True)
    except ImportError:
        webbrowser.open(url)
        print(f"App running at {url}  (press Ctrl+C to quit)")
        try:
            t.join()
        except KeyboardInterrupt:
            sys.exit(0)


if __name__ == "__main__":
    main()
