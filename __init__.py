# -*- coding: utf-8 -*-
"""
VALYDA PROTOKOLL fuer ComfyUI
(c) Rebellion Pictures Berlin

Erzeugt den Nachweis, den der EU AI Act und die Sender verlangen -
aus dem tatsaechlich ausgefuehrten Ablauf, nicht aus Eingaben von Hand.
"""

# If a dependency is missing, the WHOLE package must not vanish. ComfyUI
# would then only say "IMPORT FAILED" and leave the user in the dark.
# Instead: a clear console message naming what is missing.
try:
    from .valyda_protokoll import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
except ImportError as fehler:
    fehlend = str(fehler).split("'")[1] if "'" in str(fehler) else str(fehler)
    print("=" * 78)
    print("[VALYDA PROTOKOLL] The package could not be loaded.")
    print("[VALYDA PROTOKOLL] Missing: %s" % fehlend)
    print("[VALYDA PROTOKOLL] Please install into ComfyUI's own Python:")
    print("[VALYDA PROTOKOLL]     python_embeded\\python.exe -m pip install reportlab")
    print("[VALYDA PROTOKOLL] Then restart ComfyUI.")
    print("=" * 78)
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
