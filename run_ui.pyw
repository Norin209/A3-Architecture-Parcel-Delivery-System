"""Open the graphical workspace without a command-line window on Windows."""

import ctypes
import os
import traceback
from pathlib import Path

from norin_delivery.web import main

if __name__ == "__main__":
    try:
        result = main()
        if result and os.name == "nt":
            ctypes.windll.user32.MessageBoxW(
                0, "Unable to open the workspace. Run python run_ui.py for details.",
                "Your Order We Deliver", 0x10,
            )
    except Exception:
        log = Path(__file__).resolve().parent / "ui-startup-error.log"
        log.write_text(traceback.format_exc(), encoding="utf-8")
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(
                0, f"Unable to open the workspace. Details are in {log.name}.",
                "Your Order We Deliver", 0x10,
            )
