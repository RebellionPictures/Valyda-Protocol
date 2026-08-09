# -*- coding: utf-8 -*-
"""
Die VALYDA-Akte: ein JSON je erzeugtem Clip, daneben ein Vorschaubild.

Die Akte ist das einzige Bindeglied zwischen allen Plattformen. Beide Knoten
(international und Sender) schreiben dieselbe Akte - der internationale zeigt
davon nur weniger.

Regel: kein Feld behauptet etwas, das nicht gemessen wurde. Fehlt ein Wert,
steht dort None und nicht ein Ersatzwert.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import time
import uuid
from typing import Any, Dict, List, Optional

FORMAT = "valyda-akte/1"

# Checksums of large weight files are cached - otherwise every run costs
# several minutes. Key: path + size + modification time.
_HASH_CACHE: Dict[str, str] = {}
_CACHE_DATEI = "valyda_hash_cache.json"


def _cache_laden(ordner: str) -> None:
    global _HASH_CACHE
    if _HASH_CACHE:
        return
    pfad = os.path.join(ordner, _CACHE_DATEI)
    try:
        with open(pfad, "r", encoding="utf-8") as f:
            _HASH_CACHE = json.load(f)
    except Exception:
        _HASH_CACHE = {}


#: How long to wait for the lock before giving up. The cache is only an
#: accelerator - skipping one write costs compute time, nothing else.
#: Waiting costs the user their lifetime.
_SPERRE_WARTEN_S = 2.0

#: Older than this, a lock is just the corpse of a crashed run.
_SPERRE_ALT_S = 30.0


def _sperre_holen(pfad: str) -> Optional[str]:
    """
    Holt die Schreibsperre - oder None, wenn sie nicht frei wird.

    O_EXCL ist der unteilbare Teil: entweder der Aufrufer legt die Datei an,
    oder jemand anderes hat sie schon. Ohne Sperre reicht das Zusammenfuehren
    nicht - zwei Laeufe lesen dann denselben Stand und der zweite ueberschreibt,
    was der erste ergaenzt hat.
    """
    sperre = pfad + ".sperre"
    ende = time.time() + _SPERRE_WARTEN_S
    while True:
        try:
            griff = os.open(sperre, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(griff)
            return sperre
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(sperre) > _SPERRE_ALT_S:
                    os.remove(sperre)          # crashed run
                    continue
            except OSError:
                pass
            if time.time() > ende:
                return None
            time.sleep(0.02)
        except OSError:
            return None


def _cache_sichern(ordner: str) -> None:
    """
    Legt den Zwischenspeicher ab - unter Sperre, unteilbar, ohne fremde
    Eintraege zu verlieren.

    Zwei Dinge gingen vorher schief, wenn zwei Laeufe gleichzeitig arbeiteten:
    die Datei war waehrend des Schreibens zeitweise ungueltig, und der letzte
    Schreiber ueberschrieb die Eintraege der anderen. Beides gemessen: 66 von
    4000 Lesungen trafen eine halbe Datei, und am Ende ueberlebten zwei von vier
    Prozessen.

    Deshalb drei Dinge: unter Sperre lesen und schreiben, dabei zusammenfuehren,
    was schon dasteht, und ueber eine Nebendatei umbenennen. Das Umbenennen ist
    unteilbar - ein Leser sieht immer entweder die alte oder die neue Datei, nie
    eine halbe.

    Verlorene Eintraege kosten nur Rechenzeit, keine Angabe im Protokoll. Aber
    ein Zwischenspeicher, der still zerfaellt, faellt niemandem auf.
    """
    pfad = os.path.join(ordner, _CACHE_DATEI)
    neben = "%s.%d.neu" % (pfad, os.getpid())
    try:
        os.makedirs(ordner, exist_ok=True)
    except OSError:
        return

    sperre = _sperre_holen(pfad)
    if sperre is None:
        return                          # another run is writing right now - fine
    try:
        zusammen: Dict[str, str] = {}
        try:
            with open(pfad, "r", encoding="utf-8") as f:
                vorhanden = json.load(f)
            if isinstance(vorhanden, dict):
                zusammen.update(vorhanden)
        except Exception:
            pass                        # unreadable or missing: rebuild it then
        zusammen.update(_HASH_CACHE)
        with open(neben, "w", encoding="utf-8") as f:
            json.dump(zusammen, f)
        # On Windows the rename fails while someone holds the target file open.
        # That is a matter of milliseconds - so retry briefly instead of
        # throwing the write away.
        for versuch in range(12):
            try:
                os.replace(neben, pfad)
                break
            except PermissionError:
                if versuch == 11:
                    raise
                time.sleep(0.03)
    except Exception:
        try:
            os.remove(neben)
        except OSError:
            pass
    finally:
        try:
            os.remove(sperre)
        except OSError:
            pass


def sha256_datei(pfad: str, cache_ordner: Optional[str] = None) -> Optional[str]:
    """SHA-256 ueber eine Datei. None, wenn die Datei nicht lesbar ist."""
    if not pfad or not os.path.isfile(pfad):
        return None
    try:
        st = os.stat(pfad)
        schluessel = "%s|%d|%d" % (os.path.abspath(pfad), st.st_size, int(st.st_mtime))
    except OSError:
        return None

    if cache_ordner:
        _cache_laden(cache_ordner)
    if schluessel in _HASH_CACHE:
        return _HASH_CACHE[schluessel]

    gross = st.st_size > 200 * 1024 * 1024
    if gross:
        print("[VALYDA] Computing checksum: %s (%.1f GB) - "
              "this happens once, the value is remembered afterwards."
              % (os.path.basename(pfad), st.st_size / 1024.0 ** 3))
    h = hashlib.sha256()
    try:
        with open(pfad, "rb") as f:
            for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
                h.update(block)
    except OSError:
        return None

    wert = h.hexdigest()
    _HASH_CACHE[schluessel] = wert
    if cache_ordner:
        _cache_sichern(cache_ordner)
    return wert


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- preview image
def vorschau_schreiben(bild_tensor, ziel: str, kante: int = 720) -> Optional[Dict[str, Any]]:
    """
    Schreibt ein Vorschaubild aus dem ersten Einzelbild des Ergebnisses.

    Das Vorschaubild ist der wichtigste Teil fuer grosse Projekte: man sieht
    sofort, auf welchen Clip sich die Akte bezieht.
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None

    try:
        daten = bild_tensor
        if hasattr(daten, "cpu"):
            daten = daten.cpu().numpy()
        daten = np.asarray(daten)
        if daten.ndim == 4:
            daten = daten[0]
        if daten.dtype != "uint8":
            daten = (np.clip(daten, 0.0, 1.0) * 255.0).round().astype("uint8")
        bild = Image.fromarray(daten)
        if bild.mode not in ("RGB", "L"):
            bild = bild.convert("RGB")
        bild.thumbnail((kante, kante), Image.LANCZOS)
        os.makedirs(os.path.dirname(ziel) or ".", exist_ok=True)
        bild.save(ziel, "JPEG", quality=88)
        return {"datei": os.path.basename(ziel), "breite": bild.width, "hoehe": bild.height}
    except Exception:
        return None


def referenz_vorschau(quellpfad: str, ziel: str, kante: int = 360) -> Optional[str]:
    """Kleines Vorschaubild einer Eingabedatei (Referenz / Keyframe)."""
    try:
        from PIL import Image
        bild = Image.open(quellpfad)
        bild.thumbnail((kante, kante), Image.LANCZOS)
        if bild.mode not in ("RGB", "L"):
            bild = bild.convert("RGB")
        os.makedirs(os.path.dirname(ziel) or ".", exist_ok=True)
        bild.save(ziel, "JPEG", quality=85)
        return os.path.basename(ziel)
    except Exception:
        return None


# ---------------------------------------------------------------- building the record
def neue_akte(projekt: str, ersteller: str) -> Dict[str, Any]:
    return {
        "format": FORMAT,
        "akte_id": uuid.uuid4().hex[:16],
        "erzeugt_am": time.strftime("%Y-%m-%dT%H:%M:%S") + _zeitzone(),
        "erfasser": {"name": "comfyui", "version": None, "plugin": None},
        "werkzeug": {"name": "ComfyUI", "version": None, "art": None},
        "angabe_quelle": "automatisch",
        "projekt": projekt or None,
        # Deliberately NOT the Windows user name: a record must not collect
        # personal data nobody has provided.
        "ersteller": (ersteller or "").strip() or None,
        # Production company and rights holder of the PRODUCTION (not the software).
        # Both nodes write the same fields - there is ONE record format, so a
        # Creator project can later be bundled into the broadcast version
        # without any statement going missing.
        "produzent": None,
        "rechteinhaber": None,
        "geraet": platform.node() or None,
        "einsatz": {"szene": None, "zweck": None,
                    "timecode_start": None, "timecode_ende": None,
                    "transparenzpflicht": {"wert": None, "vorschlag": None, "begruendung": None}},
        "einstufung": {"wert": "unbekannt", "vorschlag": "unbekannt", "begruendung": None},
        "kennzeichnung": None,
        "herkunft": {"status": "unbekannt", "ableitung": None, "grad": None, "begruendung": None},
        "quellen": [],
        "modelle": [],
        "modifikatoren": [],
        "prompt": {"modus": None, "positiv": None, "negativ": None, "sha256": None},
        "parameter": {},
        # The compute steps one by one. In a two-stage setup (high and low
        # noise share), "parameter" holds only what is unambiguous; which step
        # generated, and with which seed, is recorded here.
        "sampler_stufen": [],
        # "bilder": how many frames this one run produced. Measured on the
        # image batch actually present, not derived from batch_size -
        # batch_size is an intention in the graph, not a result.
        "ergebnis": {"datei": None, "sha256": None, "vorschau": None, "bilder": None},
        "siegel": None,
    }


def _zeitzone() -> str:
    versatz = -time.timezone if not time.daylight else -time.altzone
    zeichen = "+" if versatz >= 0 else "-"
    versatz = abs(versatz)
    return "%s%02d:%02d" % (zeichen, versatz // 3600, (versatz % 3600) // 60)


def schreiben(akte: Dict[str, Any], pfad: str) -> str:
    """
    Schreibt die Akte.

    Geht das schief, wird der Grund in Klartext gemeldet. Die Akte ist das
    tragende Stueck - hier darf nichts stillschweigend danebengehen. Ein
    OSError mit Rueckverfolgung nennt einen Pfad, aber nicht die Ursache.
    """
    # Fields with a leading underscore are working values within one run and
    # do NOT belong in the record. This lets the prompt travel through the
    # survey in plain text without ending up in the file when the user
    # chose "nur_pruefsumme".
    sauber = {k: v for k, v in akte.items() if not str(k).startswith("_")}
    try:
        os.makedirs(os.path.dirname(pfad) or ".", exist_ok=True)
        with open(pfad, "w", encoding="utf-8") as f:
            json.dump(sauber, f, ensure_ascii=False, indent=2)
    except OSError as fehler:
        raise ValueError(
            "VALYDA: the data record could not be written.\n"
            "        %s\n"
            "        Reason: %s\n"
            "        Usually the disk is full, write permission is missing, "
            "or the path is too long." % (pfad, fehler))
    return pfad


def lesen(pfad: str) -> Dict[str, Any]:
    with open(pfad, "r", encoding="utf-8") as f:
        akte = json.load(f)
    if akte.get("format") != FORMAT:
        raise ValueError("Unknown record format: %r" % akte.get("format"))
    return akte


def wellenform_schreiben(audio, ziel: str, breite: int = 720, hoehe: int = 200) -> Optional[Dict[str, Any]]:
    """
    Zeichnet die Tonspur als Wellenform.

    Auch Ton braucht ein Wiedererkennungsbild: bei einer Stimme sieht man in der
    Akte sofort, um welchen Take es geht.
    """
    try:
        import numpy as np
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    try:
        welle = audio.get("waveform") if isinstance(audio, dict) else audio
        rate = int(audio.get("sample_rate", 0)) if isinstance(audio, dict) else 0
        if hasattr(welle, "cpu"):
            welle = welle.cpu().numpy()
        w = np.asarray(welle, dtype="float32")
        while w.ndim > 1:
            w = w.mean(axis=0)
        if w.size == 0:
            return None

        bild = Image.new("RGB", (breite, hoehe), (20, 22, 26))
        d = ImageDraw.Draw(bild)
        d.line([(0, hoehe // 2), (breite, hoehe // 2)], fill=(60, 64, 70))
        schritte = max(1, w.size // breite)
        mitte = hoehe / 2.0
        for x in range(breite):
            teil = w[x * schritte:(x + 1) * schritte]
            if teil.size == 0:
                continue
            a = float(np.abs(teil).max())
            a = min(1.0, a) * (mitte - 4)
            # Neutraler Hellton statt des Markengruens: das Bild landet auf
            # dem Blatt, und dort gilt die Farbregel des Entwurf-3 (Gruen
            # nur zweimal - Kopfband-Akzent und Pillen-Kontur).
            d.line([(x, mitte - a), (x, mitte + a)], fill=(178, 188, 200))

        os.makedirs(os.path.dirname(ziel) or ".", exist_ok=True)
        bild.save(ziel, "JPEG", quality=86)
        dauer = round(w.size / rate, 2) if rate else None
        return {"datei": os.path.basename(ziel), "breite": breite, "hoehe": hoehe,
                "art": "wellenform", "dauer_s": dauer, "abtastrate": rate or None}
    except Exception:
        return None


def _bild_speichern(bild, ziel: str, kante: int = 720) -> Optional[Dict[str, Any]]:
    """Ein fertiges Bild als Vorschau ablegen."""
    try:
        from PIL import Image
        if bild.mode not in ("RGB", "L"):
            bild = bild.convert("RGB")
        bild.thumbnail((kante, kante), Image.LANCZOS)
        os.makedirs(os.path.dirname(ziel) or ".", exist_ok=True)
        bild.save(ziel, "JPEG", quality=88)
        return {"datei": os.path.basename(ziel), "breite": bild.width,
                "hoehe": bild.height}
    except Exception:
        return None


def _stream_quelle(video):
    """
    Die Datei bzw. der Puffer hinter einem VIDEO - oder None.

    Nur ein dateigestuetztes Video hat eine. Ein Video, das gerade erst aus
    Einzelbildern entstanden ist (CreateVideo, SaveVideo), hat keine: dessen
    Bilder liegen ohnehin schon im Arbeitsspeicher.
    """
    holen = getattr(video, "get_stream_source", None)
    if holen is None:
        return None
    try:
        quelle = holen()
    except Exception:
        return None
    if isinstance(quelle, str) and quelle:
        return quelle
    if hasattr(quelle, "read") and hasattr(quelle, "seek"):
        return quelle
    return None


def _erstes_einzelbild(quelle):
    """
    Holt NUR das erste Einzelbild aus einer Videodatei.

    Der Grund: `get_components()` dekodiert ein dateigestuetztes Video
    vollstaendig in den Arbeitsspeicher - bei zehn Minuten in HD sind das
    hunderte Gigabyte. Fuer ein Wiedererkennungsbild wird ein einziges Bild
    gebraucht.

    Der Decoder wird erst hier geladen und nur, wenn er da ist. Fehlt er,
    entsteht kein Vorschaubild - und sonst nichts. Das Protokoll haengt nicht
    daran.

    Rueckgabe: (Bild oder None, Bildrate oder None, Anzahl Bilder oder None,
                Grund als Text oder None)
    """
    try:
        import av  # only here, and only if present
    except Exception:
        return None, None, None, ("der Video-Decoder ist in dieser Installation "
                                  "nicht vorhanden")
    try:
        if hasattr(quelle, "seek"):
            quelle.seek(0)
        with av.open(quelle, mode="r") as behaelter:
            strom = next((s for s in behaelter.streams if s.type == "video"), None)
            if strom is None:
                return None, None, None, "die Datei enthaelt keine Bildspur"
            rate = None
            try:
                if strom.average_rate:
                    rate = float(strom.average_rate)
            except Exception:
                rate = None
            anzahl = None
            try:
                anzahl = int(strom.frames) or None
            except Exception:
                anzahl = None
            for einzelbild in behaelter.decode(strom):
                return einzelbild.to_image(), rate, anzahl, None
            return None, rate, anzahl, "die Bildspur war leer"
    except Exception as fehler:
        return None, None, None, str(fehler)


def video_auswerten(video, ziel: str, kante: int = 720) -> Dict[str, Any]:
    """
    Nimmt ein ComfyUI-VIDEO entgegen und holt heraus, was das Protokoll braucht:
    ein Vorschaubild aus dem ersten Einzelbild, dazu Laenge, Bildrate und Aufloesung.

    Zwei Wege, weil es zwei Arten von VIDEO gibt:

      - aus Einzelbildern entstanden (CreateVideo, SaveVideo): die Bilder liegen
        schon im Speicher, es kostet nichts, sie zu nehmen
      - aus einer Datei geladen (LoadVideo): dann wird NUR das erste Einzelbild
        geholt. Frueher lief auch dieser Fall ueber `get_components()` und
        dekodierte das ganze Video in den Arbeitsspeicher.

    Die Video-Schnittstelle von ComfyUI hat mehrere Auspraegungen. Deshalb wird
    hier vorsichtig gefragt und nichts behauptet, was nicht geantwortet hat.
    """
    ergebnis: Dict[str, Any] = {"vorschau": None, "parameter": {}, "datei": None}
    if video is None:
        return ergebnis

    # 1) dimensions and duration - both read only the file header
    for name, schluessel in (("get_dimensions", None), ("get_duration", "dauer_s")):
        holen = getattr(video, name, None)
        if holen is None:
            continue
        try:
            wert = holen()
        except Exception:
            continue
        if schluessel:
            try:
                ergebnis["parameter"][schluessel] = round(float(wert), 3)
            except Exception:
                pass
        elif isinstance(wert, (tuple, list)) and len(wert) == 2:
            ergebnis["parameter"]["aufloesung"] = "%dx%d" % (int(wert[0]), int(wert[1]))

    # 2) is there a file behind it?
    quelle = _stream_quelle(video)
    if isinstance(quelle, str):
        ergebnis["datei"] = quelle
    else:
        for name in ("path", "file", "filename"):
            wert = getattr(video, name, None)
            try:
                wert = wert() if callable(wert) else wert
            except Exception:
                wert = None
            if isinstance(wert, str) and wert:
                ergebnis["datei"] = wert
                break

    # 3) images that are already in memory anyway
    bilder = getattr(video, "images", None)

    if bilder is None and quelle is not None:
        # --- file-based: only the first frame, no full decode
        bild, rate, anzahl, grund = _erstes_einzelbild(quelle)
        if rate:
            ergebnis["parameter"].setdefault("bildrate", round(rate, 3))
        if anzahl:
            ergebnis["parameter"].setdefault("bilder", anzahl)
        if bild is not None:
            ergebnis["vorschau"] = _bild_speichern(bild, ziel, kante)
        elif grund:
            print("[VALYDA] No preview image from the video: %s. The protocol "
                  "is still produced." % grund)
        return ergebnis

    # 4) otherwise the previous path: decomposed parts from memory
    if bilder is None:
        for name in ("get_components", "components"):
            holen = getattr(video, name, None)
            if holen is None:
                continue
            try:
                teile = holen() if callable(holen) else holen
            except Exception:
                continue
            bilder = getattr(teile, "images", None)
            rate = getattr(teile, "frame_rate", None)
            if rate is not None:
                try:
                    ergebnis["parameter"]["bildrate"] = round(float(rate), 3)
                except Exception:
                    pass
            break

    if bilder is not None:
        try:
            anzahl = int(getattr(bilder, "shape", [0])[0])
            if anzahl:
                ergebnis["parameter"]["bilder"] = anzahl
        except Exception:
            pass
        ergebnis["vorschau"] = vorschau_schreiben(bilder, ziel, kante)

    return ergebnis
