"""Double-click launcher. Windows opens .pyw with pythonw, which has no console window."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "console" / "server.py"), run_name="__main__")
