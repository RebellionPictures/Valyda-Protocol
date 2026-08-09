# -*- coding: utf-8 -*-
"""
Die Knoten.

  VALYDA · AI Disclosure   - international, wenige Knoepfe, ein Blatt (EU AI Act)
  VALYDA · Protokoll       - Sender-Fassung je Einstellung (ARD/ZDF/ORF/ARTE)
  VALYDA · Protokoll buendeln - eine Produktion, ein PDF

Kein Knoten veraendert das Bild. Sie haengen hinter dem Speichern-Knoten und
lesen den ausgefuehrten Ablauf mit.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import akte as akte_mod
from . import graph as g
from . import pdf as pdf_mod

# ---------------------------------------------------------------- ComfyUI environment
try:  # present inside ComfyUI, absent outside - the package stays testable anyway
    import folder_paths  # type: ignore
except Exception:  # pragma: no cover
    folder_paths = None


_UMLAUTE = {"\u00e4": "ae", "\u00f6": "oe", "\u00fc": "ue", "\u00df": "ss",
            "\u00c4": "Ae", "\u00d6": "Oe", "\u00dc": "Ue"}


def projektkennung(name: str) -> str:
    """
    Aus dem Projektnamen einen Ordnernamen machen.

    Damit landen die Akten verschiedener Produktionen nicht in einem Topf -
    sonst würde das Buendeln fremde Clips mit einsammeln.
    """
    text = (name or "").strip()
    for a, b in _UMLAUTE.items():
        text = text.replace(a, b)
    rein = []
    for z in text:
        rein.append(z if (z.isalnum() or z in "-_") else "_")
    kurz = "".join(rein).strip("_")
    while "__" in kurz:
        kurz = kurz.replace("__", "_")
    return (kurz[:48] or "_ohne_projekt")


#: Windows cuts off at 260 characters as long as long paths are not enabled.
#: Some headroom remains: the folder later still receives a file name.
MAX_PFAD = 250

#: The longest file name this plugin produces:
#: valyda_YYYYMMDD_HHMMSS_xxxx_VALYDA-AI-PROTOCOL_Broadcast.pdf (60 characters);
#: the 62 stays as a small reserve.
LAENGSTER_DATEINAME = 62


def _kennung_einpassen(wurzel: str, unterordner: str, kennung: str) -> str:
    """
    Kuerzt den Produktionsordner, wenn der Pfad sonst zu lang würde.

    Gekuerzt wird deterministisch: derselbe Titel ergibt immer denselben Ordner,
    sonst faende das Buendeln seine eigenen Akten nicht wieder. Damit zwei lange
    Titel nach dem Kuerzen nicht im selben Ordner landen, haengt eine kurze
    Prüfsumme des vollen Namens an.
    """
    grund = len(os.path.join(wurzel, unterordner)) + 1 + 1 + LAENGSTER_DATEINAME
    platz = MAX_PFAD - grund
    if platz >= len(kennung):
        return kennung
    if platz < 12:
        return kennung          # shortening no longer helps here - see the message below
    import hashlib
    anhang = "_" + hashlib.sha256(kennung.encode("utf-8")).hexdigest()[:6]
    kurz = kennung[:platz - len(anhang)].rstrip("_") + anhang
    print("[VALYDA] Note: the production folder was shortened - the path would "
          "otherwise exceed %d characters: %s -> %s" % (MAX_PFAD, kennung, kurz))
    return kurz


def _ausgabeordner(projekt: str = "", unterordner: str = "valyda") -> str:
    """output/valyda/<Projekt>/ - je Produktion ein eigener Ordner."""
    if folder_paths is not None:
        wurzel = folder_paths.get_output_directory()
    else:
        wurzel = os.path.abspath("output")
    kennung = _kennung_einpassen(wurzel, unterordner, projektkennung(projekt))
    ordner = os.path.join(wurzel, unterordner, kennung)

    if len(ordner) + 1 + LAENGSTER_DATEINAME > MAX_PFAD:
        raise ValueError(
            "VALYDA: the output path is too long for Windows.\n"
            "        %s\n"
            "        That is %d characters, and the file name still comes on "
            "top. Windows allows at most %d here.\n"
            "        Remedy: move ComfyUI to a shorter path, or enable long "
            "paths in Windows."
            % (ordner, len(ordner), MAX_PFAD - LAENGSTER_DATEINAME - 1))

    try:
        os.makedirs(ordner, exist_ok=True)
    except OSError as fehler:
        raise ValueError(
            "VALYDA: the output folder could not be created.\n"
            "        %s\n"
            "        Reason: %s\n"
            "        Usually write permission is missing or the disk is full."
            % (ordner, fehler))
    return ordner


def _eingang_verbunden(prompt: Optional[Dict[str, Any]], eigene_id: Any) -> bool:
    """
    Traegt der eigene Knoten im uebergebenen Ablauf einen Verweis auf
    video/images/audio?

    Der Unterschied entscheidet, welche Fehlermeldung stimmt: "nichts
    angeschlossen" schickt jemanden, dessen Kabel laengst liegt, in die falsche
    Richtung - dessen Zulieferer steht auf Bypass oder ist stummgeschaltet,
    und es kommt deshalb nichts an.
    """
    eing = ((prompt or {}).get(str(eigene_id)) or {}).get("inputs") or {}
    for name in ("video", "images", "audio"):
        wert = eing.get(name)
        if isinstance(wert, (list, tuple)) and len(wert) == 2:
            return True
    return False


def _ordner_aus_angabe(angabe: str) -> str:
    """
    Macht aus der Angabe im Feld "Aktenordner" einen Pfad.

    Vorher lief eine relative Angabe durch _ausgabeordner("", angabe) - und das
    haengte die Kennung des LEEREN Projektnamens an, also "_ohne_projekt". Wer
    "valyda/NORDLICHT" eintippte, landete in "valyda/NORDLICHT/_ohne_projekt",
    wo nie eine Akte geschrieben wurde.
    """
    roh = (angabe or "").strip()
    if os.path.isabs(roh):
        return roh
    if folder_paths is not None:
        wurzel = folder_paths.get_output_directory()
    else:
        wurzel = os.path.abspath("output")
    return os.path.normpath(os.path.join(wurzel, roh))


def _modellpfad(dateiname: str) -> Optional[str]:
    """Sucht die echte Modelldatei, um die Prüfsumme bilden zu koennen."""
    if folder_paths is None:
        return None
    for art in ("checkpoints", "loras", "vae", "controlnet", "upscale_models",
                "clip", "unet", "diffusion_models", "embeddings", "gligen"):
        try:
            p = folder_paths.get_full_path(art, dateiname)
        except Exception:
            p = None
        if p and os.path.isfile(p):
            return p
    return None


def _eingabepfad(dateiname: str) -> Optional[str]:
    if folder_paths is None or not dateiname:
        return None
    try:
        p = folder_paths.get_annotated_filepath(dateiname)
    except Exception:
        p = None
    if p and os.path.isfile(p):
        return p
    try:
        p = os.path.join(folder_paths.get_input_directory(), dateiname)
        return p if os.path.isfile(p) else None
    except Exception:
        return None


def _comfy_version() -> Optional[str]:
    """
    Die Fassung von ComfyUI - oder nichts.

    Drei Versuche in dieser Reihenfolge. `comfy.__version__` allein reichte
    nicht: in der geprueften Installation (ComfyUI 0.28.0) gibt es das gar nicht,
    und im Protokoll stand deshalb immer "nicht angegeben". Die Fassung steht
    seit einiger Zeit in comfyui_version.py im Wurzelverzeichnis, das der
    Bauvorgang erzeugt.

    Bleibt es leer, bleibt es leer. Es wird nichts nachgeschlagen und nichts
    geraten - "nicht angegeben" ist eine richtige Aussage, eine erfundene
    Versionsnummer waere eine falsche.
    """
    try:
        import comfyui_version  # type: ignore
        fassung = getattr(comfyui_version, "__version__", None)
        if fassung:
            return str(fassung)
    except Exception:
        pass
    try:
        import comfy  # type: ignore
        fassung = getattr(comfy, "__version__", None)
        if fassung:
            return str(fassung)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- the survey

#: The declaration sheet is produced for these two only: Anlage 13 is the
#: form of ARD Degeto. Whether BR, WDR, NDR and the other broadcasters
#: demand the same sheet we do NOT know - they have their own contracts.
#: Producing a sheet the broadcaster does not even know would be worse
#: than none (Pit, 01.08.).
_BOGEN_SENDER = ("ARD Degeto", "ARD Das Erste")


def _braucht_erklaerungsbogen(broadcaster: str) -> bool:
    """
    Erklaerungsbogen ja/nein - am WIRKSAMEN Sender-Wert entschieden.

    - "ARD Degeto" und "ARD Das Erste" aus der Auswahl: ja.
    - Jeder andere Eintrag der Auswahl (WDR, ZDF, ARTE ...): nein - eigene
      Vertragswerke, siehe _BOGEN_SENDER.
    - Freitext (ueber 'andere / other' oder aus alten Akten): die
      Wortgrenzen-Pruefung bleibt - "ARD-Degeto Film GmbH" loest aus,
      "Standard Media" nicht ("ard" nur als Teil eines Wortes).
    """
    import re as _re
    b = (broadcaster or "").strip()
    if b in _BOGEN_SENDER:
        return True
    if b in SENDER_AUSWAHL:
        return False
    return bool(_re.search(r"\b(ard|degeto)\b", b, _re.IGNORECASE))


def _pdf_sicher(bauen, *args, **kwargs) -> str:
    """
    Erzeugt das Dokument. Geht dabei etwas schief, bricht NICHT der ganze
    Arbeitsablauf ab - die Datenakte ist ja schon geschrieben und enthaelt alles.
    Der Nutzer bekommt eine klare Meldung statt eines abgestuerzten Laufs.
    """
    try:
        return bauen(*args, **kwargs)
    except Exception as fehler:
        print("=" * 78)
        print("[VALYDA] The PDF could not be produced: %s" % fehler)
        print("[VALYDA] The data record (.valyda-akte.json) has still been written -")
        print("[VALYDA] everything is in there. Please report this message to the maker.")
        print("=" * 78)
        import traceback
        traceback.print_exc()
        return ""


#: How long before this node starts a file may have been written and
#: still count as a result of this run.
#:
#: It used to be two seconds. But the timestamp is only TAKEN once this
#: node runs - the save node was long finished by then. With a long video
#: encode, minutes lie in between, and our own result file silently fell
#: out of the window. Being generous is harmless here: with more than
#: one hit nothing is recorded anyway.
ERGEBNIS_VORLAUF_S = 30 * 60

#: Emergency brake for an output folder that sits on a network drive or
#: has grown over the years. If it trips, that is said on the console -
#: a silent cut would look like a complete search.
ERGEBNIS_MAX_DATEIEN = 60000
ERGEBNIS_MAX_SEKUNDEN = 8.0


def _namensmuster(prompt: Dict[str, Any], knoten: Optional[Iterable[str]]) -> List[str]:
    """
    Namensmuster der Speichern-Knoten.

    Nur aus den Knoten, die auch wirklich in unseren hineinlaufen. Ein zweiter,
    unbeteiligter Speichern-Knoten im selben Ablauf soll nicht dazu fuehren, dass
    zwei Dateien passen und deshalb keine eingetragen wird.
    """
    ids = list(knoten) if knoten else list(prompt.keys())
    muster: List[str] = []
    for kid in ids:
        for name, wert in ((prompt.get(str(kid)) or {}).get("inputs") or {}).items():
            if isinstance(wert, str) and "filename_prefix" in name.lower():
                kurz = wert.replace("\\", "/").split("/")[-1]
                if kurz and kurz not in muster:
                    muster.append(kurz)
    return muster


def _ergebnisdatei_finden(prompt: Dict[str, Any], seit: float,
                          vorfahren: Optional[Iterable[str]] = None) -> Optional[str]:
    """
    Sucht die gerade geschriebene Ergebnisdatei.

    Der Speichern-Knoten im Ablauf verraet sein Namensmuster (filename_prefix).
    Passt genau EINE frisch geschriebene Datei darauf, ist sie es. Bei mehreren
    oder keiner wird nichts behauptet - lieber kein Eintrag als ein falscher.
    """
    if folder_paths is None or not prompt:
        return None
    muster = _namensmuster(prompt, vorfahren)
    if not muster:
        return None
    try:
        wurzel = folder_paths.get_output_directory()
    except Exception:
        return None

    frueheste = seit - ERGEBNIS_VORLAUF_S
    spaeteste = seit + 2          # slack for coarse file-system timestamps

    treffer: List[str] = []
    gesehen = 0
    beginn = time.time()
    abgebrochen = False
    for ordner, unterordner, dateien in os.walk(wurzel):
        if os.path.basename(ordner) == "valyda" or os.sep + "valyda" + os.sep in ordner:
            unterordner[:] = []
            continue
        gesehen += len(dateien)
        if gesehen > ERGEBNIS_MAX_DATEIEN or (time.time() - beginn) > ERGEBNIS_MAX_SEKUNDEN:
            abgebrochen = True
            break
        for d in dateien:
            if not any(d.startswith(m) for m in muster):
                continue
            voll = os.path.join(ordner, d)
            try:
                wann = os.path.getmtime(voll)
            except OSError:
                continue
            if frueheste <= wann <= spaeteste:
                treffer.append(voll)

    if abgebrochen:
        print("[VALYDA] Note: the search for the result file was stopped after %d "
              "files / %.0f seconds - the output folder is very large or on a "
              "network drive. The file can be stated by hand in the node."
              % (gesehen, ERGEBNIS_MAX_SEKUNDEN))
        return None

    if len(treffer) == 1:
        print("[VALYDA] Result file detected: %s" % os.path.basename(treffer[0]))
        return treffer[0]
    if len(treffer) > 1:
        print("[VALYDA] Note: %d fresh files match the name pattern - "
              "none of them is recorded as the result file." % len(treffer))
    return None


def erheben(bilder, prompt: Dict[str, Any], eigene_id: str, projekt: str,
            Creator: str, ordner: str, name: str,
            prompt_modus: str = "vollstaendig",
            ergebnis_pfad: str = "", ton=None, video=None,
            beginn: Optional[float] = None) -> Dict[str, Any]:
    """Baut die Akte aus dem ausgefuehrten Ablauf. Das ist der Kern des Plugins."""
    a = akte_mod.neue_akte(projekt, Creator)
    medium = ("video" if video is not None
              else "bild+ton" if (bilder is not None and ton is not None)
              else "ton" if ton is not None else "bild")
    a["medium"] = medium
    a["werkzeug"]["version"] = _comfy_version()
    a["erfasser"]["plugin"] = pdf_mod.VERSION

    herk = g.herkunft(prompt or {}, eigene_id)
    vorfahren = herk.pop("vorfahren", [])
    quellen_roh = herk.pop("quellen", [])
    a["herkunft"] = herk
    a["werkzeug"]["art"] = g.werkzeugart(herk["status"], quellen_roh, medium)

    # references / keyframes - with a small preview so they can be recognised
    for q in quellen_roh:
        eintrag = {"typ": q.get("typ"), "datei": q.get("datei"),
                   "sha256": None, "vorschau": None}
        pfad = _eingabepfad(q.get("datei") or "")
        if pfad:
            eintrag["sha256"] = akte_mod.sha256_datei(pfad, ordner)
            ziel = os.path.join(ordner, "%s_ref_%d.jpg" % (name, len(a["quellen"]) + 1))
            eintrag["vorschau"] = akte_mod.referenz_vorschau(pfad, ziel)
        a["quellen"].append(eintrag)

    # Models with checksum (cached, otherwise too slow).
    # A model "laut Ablauf" has no file - there is nothing to look for and
    # nothing to hash; its `nachweis` says so in the document.
    for m in g.modelle(prompt or {}, vorfahren):
        pfad = _modellpfad(m["datei"]) if m.get("datei") else None
        m["sha256"] = akte_mod.sha256_datei(pfad, ordner) if pfad else None
        m.pop("knoten", None)
        m.pop("typ", None)
        a["modelle"].append(m)

    a["modifikatoren"] = g.modifikatoren(prompt or {}, vorfahren)
    a["parameter"] = g.parameter(prompt or {}, vorfahren)
    a["sampler_stufen"] = g.sampler_stufen(prompt or {}, vorfahren)
    erzeuger = [s for s in a["sampler_stufen"] if s.get("erzeugt") is True]
    if len(erzeuger) > 1:
        print("[VALYDA] Note: %d compute steps add noise. Seed, steps and CFG "
              "therefore appear per stage in the document, not as one value."
              % len(erzeuger))
    elif a["sampler_stufen"] and not erzeuger:
        print("[VALYDA] Note: which compute step generated was not determinable. "
              "Seed, steps and CFG stay empty - a guessed value would be worse "
              "than none.")

    texte = g.prompt_texte(prompt or {}, vorfahren)
    positiv = texte.get("positiv")
    ohne_rolle = texte.get("texte_ohne_rolle")
    a["prompt"] = {
        "modus": prompt_modus,
        "positiv": positiv if prompt_modus == "vollstaendig" else None,
        "negativ": texte.get("negativ") if prompt_modus == "vollstaendig" else None,
        "texte_ohne_rolle": ohne_rolle if prompt_modus == "vollstaendig" else None,
        "sha256": akte_mod.sha256_text(positiv) if positiv else None,
    }
    if ohne_rolle:
        print("[VALYDA] Note: %d text block(s) could not be assigned to either "
              "side and appear in the protocol without a role." % len(ohne_rolle))

    # Result file: claim only what is really there.
    # If none is given, ONE attempt is made to find it via the save node's
    # name pattern - and only if there is exactly one.
    pfad = (ergebnis_pfad or "").strip()
    if not pfad and beginn is not None:
        gefunden = _ergebnisdatei_finden(prompt or {}, beginn, vorfahren)
        if gefunden:
            pfad = gefunden
            a["ergebnis"]["gefunden"] = "ueber das Namensmuster des Speichern-Knotens"
    if pfad and os.path.isfile(pfad):
        a["ergebnis"]["datei"] = os.path.basename(pfad)
        a["ergebnis"]["sha256"] = akte_mod.sha256_datei(pfad, ordner)
    else:
        a["ergebnis"]["datei"] = None
        a["ergebnis"]["sha256"] = None
        if pfad:
            a["ergebnis"]["hinweis"] = "angegebene Datei nicht gefunden"

    # Preview - the recognition value in large projects.
    # Video: first frame. Image: first frame. Audio: waveform.
    vorschau = os.path.join(ordner, "%s_vorschau.jpg" % name)
    v = None
    if video is not None:
        befund = akte_mod.video_auswerten(video, vorschau)
        v = befund.get("vorschau")
        if v is None:
            print("[VALYDA] Note: no frame could be taken from the video (%s). "
                  "The protocol is still produced, only without a preview image."
                  % type(video).__name__)
        for schluessel, wert in (befund.get("parameter") or {}).items():
            a["parameter"].setdefault(schluessel, wert)
        if not a["ergebnis"].get("datei") and befund.get("datei"):
            a["ergebnis"]["datei"] = os.path.basename(str(befund["datei"]))
    if v is None and bilder is not None:
        v = akte_mod.vorschau_schreiben(bilder, vorschau)
    if v is None and ton is not None:
        v = akte_mod.wellenform_schreiben(ton, vorschau)
    a["ergebnis"]["vorschau"] = v

    # How many frames this run produced - measured on the batch actually
    # present. A run with batch size 8 yields ONE record: graph, models,
    # prompt and provenance are the same for all eight. But the sheet must
    # say what it refers to, otherwise it looks like a record of a single
    # image.
    if video is None and bilder is not None:
        try:
            anzahl = int(getattr(bilder, "shape", [0])[0])
            if anzahl > 0:
                a["ergebnis"]["bilder"] = anzahl
        except Exception:
            pass
        if (a["ergebnis"].get("bilder") or 0) > 1:
            print("[VALYDA] Note: this run produced %d images. ONE protocol is "
                  "written for them, and it says so."
                  % a["ergebnis"]["bilder"])
    return a


# ---------------------------------------------------------------- node 1
# ---------------------------------------------------------------- classification
# THE ONE PLACE where everything else follows from the type of
# disclosure (Disclosure_Type): the classification under Article 50 (4)
# and the transparency duty. The broadcast declaration and the sheet
# READ these values from the record - they never derive them themselves.
# Whoever changes something here changes all three paths at once (Pit, 01.08.).
#
# "not classified" stays UNDECIDED (None) throughout and NOWHERE turns
# into a "no" - nothing is ticked for such items. That has been a bug
# once already; that is why it stands here and in the checks.
DISCLOSURE_TYPES = [
    "not classified",
    "Realistic content - visible label",
    "Artistic work - discreet notice",
    "Clearly fantastical - no disclosure",
]

#: The record keeps its established keys: "deepfake" is the category of
#: Article 50 (4) (appears like something real), "ausserhalb" means
#: outside that definition.
_DISCLOSURE_SCHLUESSEL = {
    "Realistic content - visible label": "deepfake",
    "Artistic work - discreet notice": "kuenstlerisch",
    "Clearly fantastical - no disclosure": "ausserhalb",
}

_DISCLOSURE_TOOLTIP = (
    "Article 50 (4) EU AI Act - your assessment, the tool never decides "
    "this for you.\n\n"
    "The definition is broad: it covers persons, objects, places and events "
    "that COULD exist in reality. A realistic-looking car falls under it even "
    "if that exact car never existed. Only what is obviously impossible stays "
    "outside - dragons, people flying unaided.\n\n"
    "Realistic content - visible label: disclosure required.\n"
    "Artistic work - discreet notice: the duty remains, but the notice may "
    "be discreet, e.g. in the credits.\n"
    "Clearly fantastical - no disclosure: no obligation.\n"
    "not classified: nothing is decided, nothing will be ticked.")


def einstufung_aus_kennzeichnungsart(disclosure_type):
    """(einstufung_schluessel, transparenzpflicht) aus dem Disclosure_Type.

    Nimmt beide Schreibweisen an: einsprachig (Creator) und zweisprachig
    "EN / DE" (Broadcast) - verglichen wird immer die englische Haelfte.

    Transparenzpflicht: realistisch -> ja, kuenstlerisch -> ja (der Hinweis
    darf zurueckhaltend sein), offensichtlich fantastisch -> nein,
    nicht eingestuft -> None (unentschieden, NICHTS wird angekreuzt).
    """
    disclosure_type = (disclosure_type or "").split(" / ")[0].strip()
    schluessel = _DISCLOSURE_SCHLUESSEL.get(disclosure_type, "unbekannt")
    pflicht = (True if schluessel in ("deepfake", "kuenstlerisch")
               else False if schluessel == "ausserhalb" else None)
    return schluessel, pflicht


#: UI choice values (English) -> wording in the record (German, the
#: established record format).
_QUELLE_DEUTSCH = {"not stated": "nicht angegeben",
                   "real footage": "Realaufnahme (Eigendreh)",
                   "AI-generated itself": "selbst KI-erzeugt",
                   "mixed": "gemischt"}


def _wert_en(wert: str) -> str:
    """Die englische Haelfte eines zweisprachigen Auswahlwerts ('EN / DE').

    Broadcast- und Project-Knoten zeigen ihre Werte zweisprachig (Pit,
    01.08.) - gespeichert und verglichen wird aber IMMER die englische
    Haelfte: die Akte bleibt unveraendert, der Code vergleicht nie den
    deutschen Anzeigeteil. Einsprachige Werte (Creator) laufen unveraendert
    durch. NICHT anwenden auf Eigennamen (Broadcaster, Published_On) -
    'andere / other' und 'Website / own site' sind keine Sprachpaare.
    """
    return (wert or "").split(" / ")[0].strip()


#: Bilingual choice values (Broadcast/Project only; the Creator stays
#: monolingual English). Pattern: "EN / DE". For Disclosure_Type the
#: German half is shortened to the core term - the full wording would
#: otherwise put more than 75 characters on the line.
QUELLE_ZWEISPRACHIG = ["real footage / Realaufnahme",
                       "AI-generated itself / selbst KI-erzeugt",
                       "mixed / gemischt",
                       "not stated / nicht angegeben"]
DISCLOSURE_ZWEISPRACHIG = [
    "not classified / nicht eingestuft",
    "Realistic content - visible label / realistischer Inhalt",
    "Artistic work - discreet notice / künstlerisches Werk",
    "Clearly fantastical - no disclosure / offensichtlich fantastisch",
]
PROMPT_ZWEISPRACHIG = ["show prompt / Prompt zeigen",
                       "hide prompt / Prompt verbergen"]
ZUORDNUNG_ZWEISPRACHIG = ["automatic / automatisch",
                          "main text is the prompt / Haupttext ist der Prompt"]
VORSCHAU_ZWEISPRACHIG = ["on / an", "off / aus"]


# ---------------------------------------------------------------- Broadcaster
#: The broadcaster choices (Pit, 01.08., researched; extended late on
#: 01.08.: Article 50 applies to EVERY broadcaster - public service,
#: private, international). Values are proper names or abbreviations. For
#: broadcast groups the individual channels stand there: a production
#: contract is signed with a channel, not with the corporation. Order: ARD
#: family, ZDF family, joint programmes, German private channels, Austria/
#: Switzerland, Europe, streaming, the escape hatch. (The ComfyUI dropdown
#: cannot do separators - each would be selectable; the order is the grouping.)
ANDERER_SENDER = "andere / other"
SENDER_AUSWAHL = [
    "",                       # default: no broadcaster
    "ARD Degeto", "ARD Das Erste",
    "BR", "HR", "MDR", "NDR", "RB", "RBB", "SR", "SWR", "WDR", "DW",
    "ZDF", "ZDFneo", "ZDFinfo",
    "ARTE", "3sat", "PHOENIX", "KiKA", "funk", "Deutschlandradio",
    "RTL", "RTLZWEI", "VOX", "ntv", "NITRO", "ProSieben", "SAT.1",
    "kabel eins", "sixx", "Sport1", "WELT", "DMAX", "Tele 5",
    "ORF", "ServusTV", "SRF",
    "BBC", "ITV", "Channel 4", "France Télévisions", "ARTE France", "Canal+",
    "RAI", "Mediaset", "RTVE", "Atresmedia", "RTP", "NPO", "VRT", "RTBF",
    "DR", "SVT", "NRK", "YLE", "RÚV", "RTÉ", "TVP", "Česká televize", "RTVS",
    "MTVA", "ERT", "HRT", "RTVSLO", "BNT", "TVR", "LRT", "LTV", "ERR",
    "RTVA", "PBS Malta", "CyBC", "RTL Luxembourg", "EBU / Eurovision",
    "Netflix", "Amazon Prime Video", "Disney+", "Apple TV+", "Paramount+",
    "Sky / WOW", "Joyn", "RTL+",
    ANDERER_SENDER,
]

#: German-speaking clients (Pit, 01.08.): only for them does the
#: broadcast/project document carry the small German line. A BBC editor
#: needs no German sublines. Empty and free text stay German - Pit's
#: normal case.
_DEUTSCHSPRACHIG = frozenset([
    "ARD Degeto", "ARD Das Erste",
    "BR", "HR", "MDR", "NDR", "RB", "RBB", "SR", "SWR", "WDR", "DW",
    "ZDF", "ZDFneo", "ZDFinfo",
    "ARTE", "3sat", "PHOENIX", "KiKA", "funk", "Deutschlandradio",
    "RTL", "RTLZWEI", "VOX", "ntv", "NITRO", "ProSieben", "SAT.1",
    "kabel eins", "sixx", "Sport1", "WELT", "DMAX", "Tele 5",
    "ORF", "ServusTV", "SRF",
    "Joyn", "RTL+",
])


def _dokument_zweisprachig(broadcaster: str) -> bool:
    """EINE Bedingung, einmal ausgewertet, auf das ganze Dokument angewandt:
    deutsche Kleinzeile nur bei deutschsprachigen Auftraggebern. Leer oder
    Freitext ('andere / other') -> deutsch bleibt, das ist der Regelfall."""
    b = (broadcaster or "").strip()
    if not b or b in _DEUTSCHSPRACHIG:
        return True
    if b in SENDER_AUSWAHL:
        return False              # known, not German-speaking broadcaster
    return True                   # free text


# ---------------------------------------------------------------- publication channels
#: The Creator does not ask for a broadcaster - whoever delivers to one
#: takes the Broadcast node. It asks WHERE the work is published (Pit,
#: 01.08., researched by 2026 reach). NO dropdown for festivals: there
#: are thousands, any list would be arbitrary and quickly stale - and a
#: festival is named by name AND year ("Berlinale 2027"). Whoever picks
#: "Festival" enters the name in Published_On_Name.
#: Grouped via a prefix in the value (Pit, 01.08.): the ComfyUI dropdown
#: cannot do separator rows - they would be selectable and end up in the
#: record as a statement. The prefix groups and sorts at once; the
#: dropdown search filters with "contains" (PrimeVue default, read in
#: the frontend bundle), so "youtube" still finds "Social \u00b7 YouTube".
#: SAVED is only the part BEHIND the dot - the prefix is not a statement
#: (_ohne_rubrik).
PUBLIKATION_AUSWAHL = [
    "",                       # default
    "Social \u00b7 YouTube", "Social \u00b7 Instagram", "Social \u00b7 TikTok",
    "Social \u00b7 Facebook", "Social \u00b7 X (Twitter)", "Social \u00b7 LinkedIn",
    "Social \u00b7 Snapchat", "Social \u00b7 Pinterest", "Social \u00b7 Threads",
    "Social \u00b7 Twitch", "Social \u00b7 Reddit", "Social \u00b7 Bluesky",
    "Social \u00b7 Tumblr", "Social \u00b7 WhatsApp Channels",
    "Social \u00b7 Telegram",
    "Social \u00b7 andere Plattform / other platform",
    "Web \u00b7 Vimeo", "Web \u00b7 Website / own site",
    "Web \u00b7 Podcast / audio platform",
    "Web \u00b7 andere Seite / other site",
    "Auswertung \u00b7 Festival", "Auswertung \u00b7 Kino / theatrical release",
    "Auswertung \u00b7 Ausstellung / exhibition",
    "Auswertung \u00b7 Messe / trade show",
    "Auswertung \u00b7 andere Auswertung / other release",
    "other / sonstiges",
]

#: Where the name is mandatory: for all "andere" entries and wherever the
#: list entry alone says nothing usable (a festival is named with name AND
#: year, a website with its address). For named platforms the name is a
#: bonus - "YouTube" alone is a usable statement.
PUBLIKATION_PFLICHT = tuple(
    w for w in PUBLIKATION_AUSWAHL
    if "andere" in w or w in ("Auswertung \u00b7 Festival",
                              "Auswertung \u00b7 Kino / theatrical release",
                              "Auswertung \u00b7 Ausstellung / exhibition",
                              "Auswertung \u00b7 Messe / trade show",
                              "Web \u00b7 Website / own site",
                              "Web \u00b7 Podcast / audio platform",
                              "other / sonstiges"))


def _ohne_rubrik(wert: str) -> str:
    """"Social \u00b7 YouTube" -> "YouTube". Der Vorsatz gliedert die Liste,
    er ist keine Angabe und gehoert nicht in die Akte."""
    wert = (wert or "").strip()
    for rubrik in ("Social \u00b7 ", "Web \u00b7 ", "Auswertung \u00b7 "):
        if wert.startswith(rubrik):
            return wert[len(rubrik):]
    return wert

_PUBLISHED_ON_TOOLTIP = (
    "Where this clip is published. Delivering to a broadcaster? Use the "
    "Broadcast node instead - this node stores the prompt as a checksum "
    "by default, so a broadcaster record would be incomplete.\n\n"
    "Jede Rubrik hat ihr eigenes 'andere' - f\u00fcr eine Plattform, Seite "
    "oder Auswertung, die hier nicht steht. Das letzte 'other / sonstiges' "
    "ist f\u00fcr alles, was in keine der drei Rubriken passt (Intranet-"
    "Schulung, Firmenpr\u00e4sentation, Ausschreibungsbeitrag).\n\n"
    "Der Vorsatz (Social/Web/Auswertung) gliedert nur die Liste - in der Akte "
    "steht allein der Teil dahinter.")

_PUBLISHED_ON_OTHER_TOOLTIP = (
    "Welches genau?\n"
    "   Auswertung \u00b7 Festival        ->  Berlinale 2027\n"
    "   Social \u00b7 andere Plattform    ->  Mastodon\n"
    "   Web \u00b7 Website / own site     ->  rebellion-pictures.de\n"
    "   Social \u00b7 YouTube             ->  Kanal Rebellion Docs (freiwillig)\n"
    "\nBei allen 'andere'-Eintr\u00e4gen und bei Festival, Kino, Ausstellung, "
    "Messe, Website und Podcast n\u00f6tig. Bei benannten Plattformen "
    "freiwillig. Im Dokument steht beides als EINE Zeile: "
    "'Festival \u00b7 Berlinale 2027'.")


def _veroeffentlichung_aufloesen(auswahl: str, name: str) -> str:
    """Der wirksame Veroeffentlichungsweg - EINE Zeile aus beiden Feldern.

    Der Name ergaenzt jeden Listeneintrag ("Festival \u00b7 Berlinale 2027");
    ist er leer, steht nur der Eintrag. Der Rubrik-Vorsatz faellt weg - er
    gliedert die Liste, er ist keine Angabe. Bei den "andere"-Eintraegen
    und ueberall, wo der Eintrag allein nichts sagt, ist der Name Pflicht;
    fehlt er, nennt die Meldung BEIDE Zeilen, damit klar wird, dass sie
    zusammengehoeren (Pit, 01.08.).
    """
    auswahl = (auswahl or "").strip()
    name = (name or "").strip()
    if auswahl in PUBLIKATION_PFLICHT and not name:
        raise ValueError(
            "VALYDA: Published_On is set to '%s' - please add which one in "
            "the line below (Published_On_Name), e.g. 'Berlinale 2027'."
            % auswahl)
    eintrag = _ohne_rubrik(auswahl)
    # A bare "andere"/"other" says nothing - then only the name stands.
    if "andere" in eintrag or eintrag.startswith("other"):
        return name
    if eintrag and name:
        return "%s \u00b7 %s" % (eintrag, name)
    return eintrag or name

_BROADCASTER_TOOLTIP = (
    "Broadcaster or client - public, private or international; Article 50 "
    "applies to every broadcaster. Not listed? Choose 'andere / other' and "
    "type the name below - jeder Auftraggeber ist möglich. / Nicht in der "
    "Liste? 'andere / other' wählen und den Namen darunter eintragen.\n\n"
    "The declaration form (Erklärungsbogen KI) is generated ONLY for ARD "
    "Degeto and ARD Das Erste - it is their contract form; the other "
    "broadcasters have their own paperwork, there the main protocol is the "
    "basis.\n\n"
    "BR Bayerischer Rundfunk · HR Hessischer Rundfunk · MDR Mitteldeutscher "
    "Rundfunk · NDR Norddeutscher Rundfunk · RB Radio Bremen · RBB Rundfunk "
    "Berlin-Brandenburg · SR Saarländischer Rundfunk · SWR Südwestrundfunk · "
    "WDR Westdeutscher Rundfunk · DW Deutsche Welle · ORF Österreichischer "
    "Rundfunk · SRF Schweizer Radio und Fernsehen\n\n"
    "Bei ARD Degeto und ARD Das Erste entsteht zusätzlich der "
    "Erklärungsbogen KI - das Formular aus dem Anlieferungsvertrag, bereits "
    "ausgefüllt. Andere Sender haben eigene Formulare; dort dient das "
    "Hauptprotokoll als Grundlage.")

_BROADCASTER_OTHER_TOOLTIP = (
    "Welches genau? Redaktion oder genauer Auftraggeber - 'Redaktion "
    "Fiktion', 'ARD Degeto Nord'. Nicht in der Liste? 'andere / other' "
    "w\u00e4hlen und den Namen hier eintragen.\n\n"
    "Im Dokument steht beides als EINE Zeile: 'ARD Degeto \u00b7 Redaktion "
    "Fiktion'. Pflicht nur bei 'andere / other', sonst freiwillig.")


def _broadcaster_aufloesen(auswahl: str, freitext: str) -> str:
    """Der wirksame Sender-Wert (Nachtrag Pit, 01.08.): der Freitext
    ergaenzt JEDEN Listeneintrag - so laesst sich Redaktion oder
    Ansprechpartner mitgeben, im Dokument stehen beide zusammen
    ('ARD Degeto \u00b7 Redaktion Fiktion'). Der Freitext allein ist
    gleichberechtigt, kein Notbehelf - keine Liste kann vollstaendig sein
    (kleinere Sender, Produktionsfirmen, Werbekunden, Museen, Verlage).
    Pflicht ist er nur bei 'andere / other'; dort gewaehlt und leer ->
    klare Meldung statt stillem Leerlauf."""
    auswahl = (auswahl or "").strip()
    freitext = (freitext or "").strip()
    if auswahl == ANDERER_SENDER:
        if not freitext:
            raise ValueError(
                "VALYDA: Broadcaster is set to 'andere / other' - please add "
                "which one in the line below (Broadcaster_Name), e.g. "
                "'Sky Deutschland'.")
        return freitext
    if auswahl and freitext:
        return "%s \u00b7 %s" % (auswahl, freitext)
    return auswahl or freitext


class ValydaProtokollInternational:
    """VALYDA AI Protocol, internationale Fassung: eine Angabe, ein Blatt."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            # NOT a required field (Pit, 01.08., fix 1): this way there is no
            # required block that ComfyUI pulls to the front, and the fields
            # appear in table order - ONE order without exception across all
            # three nodes. ComfyUI accepts that (execution.py reads 'required'
            # with .get and an empty fallback). Disclosure_Type keeps the
            # default "not classified".
            "required": {},
            # SHARED FIELD ORDER of the three nodes (Pit, 01.08., version 2.0)
            # - after that it is FROZEN again: new fields go to the END only,
            # otherwise the values shift in all workflows the users have
            # already saved.
            "optional": {
                "video": ("VIDEO", {"tooltip": "Connect the VIDEO output of your save/combine node. "
                                               "Video, image or audio - one of them is enough."}),
                "images": ("IMAGE", {"tooltip": "Connect your result images."}),
                "audio": ("AUDIO", {"tooltip": "For synthetic voice or sound. A waveform is used as the preview."}),
                "Production": ("STRING", {"default": "", "multiline": False,
                                       "tooltip": "Groups clips of the same work into one folder. "
                                                  "Use the exact same spelling everywhere."}),
                "Scene": ("STRING", {"default": "", "multiline": False,
                    "tooltip": "Scene or shot designation, e.g. 'Scene 14 - sky replacement'"}),
                "Reason_for_AI_Use": ("STRING", {"default": "", "multiline": False,
                    "tooltip": "Why AI was used in this shot, e.g. 'weather match to the "
                               "adjacent scene'"}),
                "Disclosure_Type": (DISCLOSURE_TYPES, {
                    "default": "not classified",
                    "tooltip": "The one decision this node asks of you.\n\n"
                               + _DISCLOSURE_TOOLTIP}),
                "Timecode_In": ("STRING", {"default": "", "multiline": False,
                    "tooltip": "Start timecode in the final cut, entered by hand.\n"
                               "Format: hours:minutes:seconds:frames, e.g. 00:21:48:11\n"
                               "Dots or commas are turned into colons. Leave empty until "
                               "the edit is locked."}),
                "Timecode_Out": ("STRING", {"default": "", "multiline": False,
                    "tooltip": "End timecode in the final cut. If set, it is used as given; "
                               "if empty, it is calculated from frame rate and frame count "
                               "where possible."}),
                "Source_Footage": (["not stated", "real footage", "AI-generated itself", "mixed"],
                    {"default": "not stated",
                     "tooltip": "The tool only sees THAT an image entered the workflow - not "
                                "where it came from. An AI image looks like a photo to ComfyUI."
                                "\n\n'AI-generated itself' sets the status to fully generated. "
                                "This statement comes from YOU and is marked as such."}),
                "Creator": ("STRING", {"default": "", "multiline": False,
                                          "tooltip": "Your name or e-mail. Appears on the record."}),
                "Producer": ("STRING", {"default": "", "multiline": False,
                    "tooltip": "Production company. Left empty: 'not stated'."}),
                "Co_Producer": ("STRING", {"default": "", "multiline": False,
                    "tooltip": "Co-producing company, if any. Appears on the record only "
                               "when filled in."}),
                # Position 11 is "where does it go": for the Creator the publication
                # channel, for Broadcast the broadcaster - the same question in two
                # worlds (Pit, 01.08.). Whoever delivers to a broadcaster takes the
                # Broadcast node.
                "Published_On": (PUBLIKATION_AUSWAHL, {"default": "",
                    "tooltip": _PUBLISHED_ON_TOOLTIP}),
                "Published_On_Name": ("STRING", {"default": "", "multiline": False,
                    "tooltip": _PUBLISHED_ON_OTHER_TOOLTIP}),
                "Rights_Holder": ("STRING", {"default": "", "multiline": False,
                    "tooltip": "Rights holder of the PRODUCTION, not of this software."}),
                "Output_File": ("STRING", {"default": "", "multiline": False,
                    "tooltip": "Full path of the saved file. Only then does the "
                               "checksum bind the record to that exact file."}),
                "Label_Wording": ("STRING", {"default": "AI-generated content",
                                             "tooltip": "Plain-language label shown to the viewer. "
                                                        "Vague wording like 'enhanced media' fails "
                                                        "the clarity test."}),
                "Store_Prompt": (["hide prompt", "show prompt"],
                    {"default": "hide prompt",
                     "tooltip": "By default the prompt is hidden: only its checksum is "
                                "stored - your prompt stays private and is not printed. "
                                "Hidden means: nobody can read the prompt, but anyone "
                                "can verify that you did not change it afterwards. / "
                                "Verborgen heißt: niemand kann den Prompt lesen, aber "
                                "jeder kann prüfen, dass du ihn nachträglich nicht "
                                "geändert hast.\n\n"
                                "'show prompt' stores it in the record AND prints it on "
                                "the sheet. Choose it if you may later need a "
                                "broadcaster record: German public broadcasters require "
                                "the prompt in plain text, and it cannot be recovered "
                                "afterwards."}),
                "Preview_In_Node": (["on", "off"], {"default": "on",
                    "tooltip": "Shows the preview image inside the node. Some ComfyUI builds try "
                               "to load a video preview instead and report an error - switch to "
                               "'off' then. It does not affect the record."}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO",
                       "unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("pdf", "record")
    FUNCTION = "run"
    OUTPUT_NODE = True
    CATEGORY = "VALYDA"
    DESCRIPTION = ("USE THIS ONE if you publish on the web, social media or at festivals.\n\n"
                   "One page under Article 50 of the EU AI Act. Choose the Disclosure "
                   "type, press run, done. Everything else - model, checksums, prompt, "
                   "source - is read from the workflow automatically and kept in the "
                   "record file.\n\nThe prompt is printed on the page only if "
                   "Store_Prompt is set to 'show prompt'; by default it stays "
                   "hidden and only its checksum appears.")

    def run(self, Disclosure_Type="not classified", Production="",
            video=None, images=None, audio=None,
            Scene="", Reason_for_AI_Use="", Timecode_In="", Timecode_Out="",
            Source_Footage="not stated", Creator="", Producer="", Co_Producer="",
            Published_On="", Published_On_Name="", Rights_Holder="",
            Output_File="", Label_Wording="",
            Store_Prompt="hide prompt", Preview_In_Node="on",
            prompt=None, extra_pnginfo=None, unique_id=None):
        Veroeffentlichung = _veroeffentlichung_aufloesen(Published_On,
                                                         Published_On_Name)
        if images is None and audio is None and video is None:
            if _eingang_verbunden(prompt, unique_id):
                raise ValueError(
                    "VALYDA: The input is connected but nothing arrived. Most "
                    "likely a node upstream is bypassed or muted. Remove the "
                    "bypass and run again.")
            raise ValueError("VALYDA: connect video, images or audio - "
                             "there is nothing to record otherwise.")
        ordner = _ausgabeordner(Production)
        name = "valyda_%s_%s" % (time.strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:4])

        beginn = time.time()
        # Default: hide prompt - the prompt stays private. "show prompt" is
        # the choice for everyone who might later need a broadcast version:
        # the plain text cannot be reconstructed afterwards. Unknown values
        # (old workflows still carrying "full text"/"checksum only") fall to
        # the private side - hiding too much is recoverable, revealing is not.
        modus = "vollstaendig" if Store_Prompt == "show prompt" else "nur_pruefsumme"
        a = erheben(images, prompt or {}, str(unique_id), Production, Creator,
                    ordner, name, prompt_modus=modus,
                    ergebnis_pfad=Output_File, ton=audio, video=video, beginn=beginn)

        # The production fields - the same record fields as on the Broadcast
        # node, so the Project node can later build a broadcast version from
        # them.
        Timecode_In = _timecode_saeubern(Timecode_In)
        Timecode_Out = _timecode_saeubern(Timecode_Out)
        a["einsatz"].update({
            "szene": (Scene or "").strip() or None,
            "zweck": (Reason_for_AI_Use or "").strip() or None,
            "timecode_start": Timecode_In or None,
        })
        # If the end timecode is set, it applies (producer's statement like
        # the start); otherwise the calculation from frame rate and count stays.
        a["einsatz"]["timecode_ende"] = (Timecode_Out or
                                         _timecode_ende(Timecode_In,
                                                        a.get("parameter") or {}))
        a["produzent"] = (Producer or "").strip() or None
        a["co_produzent"] = (Co_Producer or "").strip() or None
        a["veroeffentlicht_auf"] = Veroeffentlichung or None
        a["rechteinhaber"] = (Rights_Holder or "").strip() or None

        _bildquelle_anwenden(a, _QUELLE_DEUTSCH.get(Source_Footage, "nicht angegeben"))

        # Classification and transparency duty from the ONE derivation point -
        # see einstufung_aus_kennzeichnungsart().
        schluessel, pflicht = einstufung_aus_kennzeichnungsart(Disclosure_Type)
        a["einstufung"] = {"wert": schluessel, "vorschlag": "unbekannt",
                           "begruendung": None}
        a["einsatz"]["transparenzpflicht"] = {
            "wert": pflicht, "vorschlag": pflicht,
            "begruendung": ("Aus der Art der Kennzeichnung abgeleitet - "
                            "Angabe des Produzenten."
                            if pflicht is not None else None),
        }
        if schluessel in ("deepfake", "kuenstlerisch"):
            a["kennzeichnung"] = {
                "erforderlich": True,
                "art": "on-screen + caption",
                "eu_symbol": ("fully AI-generated"
                              if a["herkunft"]["status"] == g.STATUS_VOLL
                              else "partially AI-modified"),
                "variante": "white 50 %",
                "wortlaut": Label_Wording or "AI-generated content",
                "sichtbar_ab": "first exposure",
            }
        elif schluessel == "ausserhalb":
            a["kennzeichnung"] = {"erforderlich": False}

        akte_pfad = akte_mod.schreiben(a, os.path.join(ordner, "%s.valyda-akte.json" % name))
        # Data file and its checksum go onto the sheet (WHERE IT COMES
        # FROM, Entwurf-3) - the same binding the broadcast sheet carries.
        akte_hash = akte_mod.sha256_datei(akte_pfad)
        pdf_pfad = _pdf_sicher(pdf_mod.fassung_k, a,
                               os.path.join(ordner, "%s_VALYDA-AI-PROTOCOL_Creator.pdf" % name),
                               ordner,
                               akte_datei=os.path.basename(akte_pfad),
                               akte_hash=akte_hash)

        print("[VALYDA] Protocol written: %s" % pdf_pfad)
        ui = _ui_bild(a, name, Production, pdf_pfad) if Preview_In_Node == "on" else {}
        return {"ui": ui, "result": (pdf_pfad, akte_pfad)}


# ---------------------------------------------------------------- node 2
class ValydaProtokollSender:
    """Sender-Fassung: je Einstellung eine Akte mit Prompt und Prüfsummen."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            # The four required fields ARE positions 1-4 of the shared field
            # order - required-first and table order coincide here, nothing
            # breaks visibly. Whoever delivers to a broadcaster needs them
            # anyway; an empty field would otherwise strike the editor later
            # instead of the producer. The former fields "Einstufung" and
            # "Transparenzpflicht" have merged into Disclosure_Type - the duty
            # follows from the ONE derivation point
            # einstufung_aus_kennzeichnungsart().
            "required": {
                "Production": ("STRING", {"default": "", "multiline": False,
                    "tooltip": "Title of the production. It holds the project together: "
                               "all clips with the same name go into one folder, and the "
                               "Project node combines them into one record at the end. "
                               "Always spell it identically."}),
                "Scene": ("STRING", {"default": "", "multiline": False,
                    "tooltip": "Designation of the shot, e.g. 'Scene 14 - sky replacement'. "
                               "Goes verbatim into the declaration form."}),
                "Reason_for_AI_Use": ("STRING", {"default": "", "multiline": False,
                    "tooltip": "Why AI was used, e.g. 'weather match'. Goes verbatim "
                               "into the declaration form."}),
                "Disclosure_Type": (DISCLOSURE_ZWEISPRACHIG, {
                    "default": "not classified / nicht eingestuft",
                    "tooltip": _DISCLOSURE_TOOLTIP}),
            },
            # SHARED FIELD ORDER of the three nodes (Pit, 01.08., version 2.0)
            # - after that it is FROZEN again: new fields only at the END.
            # ("Sprache" and the Part-A switch "Erklaerungsbogen" are gone -
            # the language is fixed, and the ticks ALWAYS come from the
            # producer's statements.)
            "optional": {
                "video": ("VIDEO", {"tooltip": "Connect the VIDEO output of your save/combine node. "
                                               "Video, image or audio - one of them is enough."}),
                "images": ("IMAGE", {"tooltip": "Connect your result images."}),
                "audio": ("AUDIO", {"tooltip": "For synthetic voice or sound. A waveform is used as the preview."}),
                "Timecode_In": ("STRING", {"default": "",
                    "tooltip": "Start timecode in the broadcast cut, entered by hand.\n"
                               "Format: hours:minutes:seconds:frames, e.g. 00:21:48:11\n"
                               "Dots or commas are turned into colons. Leave empty until "
                               "the edit is locked - it also sets the order in the "
                               "project record."}),
                "Timecode_Out": ("STRING", {"default": "",
                    "tooltip": "End timecode in the broadcast cut. If set, it is used as "
                               "given; if empty, it is calculated from frame rate and "
                               "frame count where possible."}),
                "Source_Footage": (QUELLE_ZWEISPRACHIG,
                    {"default": "not stated / nicht angegeben",
                     "tooltip": "The tool only sees THAT an image entered the workflow - not "
                                "where it came from. An AI image looks like a photo to ComfyUI."
                                "\n\n'AI-generated itself' sets the status to fully generated. "
                                "This statement comes from YOU and is marked as such."}),
                "Creator": ("STRING", {"default": "",
                    "tooltip": "Who created this shot."}),
                "Producer": ("STRING", {"default": "",
                    "tooltip": "Production company. Left empty, the document says "
                               "'not stated' - nothing is invented."}),
                "Co_Producer": ("STRING", {"default": "",
                    "tooltip": "Co-producing company, if any. Appears on the record only "
                               "when filled in."}),
                "Broadcaster": (SENDER_AUSWAHL, {"default": "",
                    "tooltip": _BROADCASTER_TOOLTIP}),
                "Broadcaster_Name": ("STRING", {"default": "",
                    "tooltip": _BROADCASTER_OTHER_TOOLTIP}),
                "Rights_Holder": ("STRING", {"default": "",
                    "tooltip": "Rights holder of the PRODUCTION - not the software rights "
                               "holder named in the footer."}),
                "Output_File": ("STRING", {"default": "",
                    "tooltip": "Full path of the saved file. Only then does the checksum "
                               "bind the record to that exact file. / Vollständiger Pfad "
                               "der gespeicherten Datei. Nur dann bindet die Prüfsumme "
                               "das Dokument an genau diese Datei."}),
                "Store_Prompt": (PROMPT_ZWEISPRACHIG,
                    {"default": "show prompt / Prompt zeigen",
                     "tooltip": "'show prompt' writes the prompt into the document - "
                                "broadcasters require it. 'hide prompt' keeps it "
                                "private: nobody can read the prompt, but anyone can "
                                "verify that you did not change it afterwards. / "
                                "Verborgen heißt: niemand kann den Prompt lesen, aber "
                                "jeder kann prüfen, dass du ihn nachträglich nicht "
                                "geändert hast."}),
                "Prompt_Assignment": (ZUORDNUNG_ZWEISPRACHIG,
                    {"default": "automatic / automatisch",
                     "tooltip": "Some workflows do not reveal which text is the prompt and "
                                "which the negative prompt. Both then appear side by side "
                                "in the document, unlabelled.\n\n'main text is the prompt': "
                                "you state that the long text is the prompt. It is printed "
                                "as such, marked as your statement."}),
                "Preview_In_Node": (VORSCHAU_ZWEISPRACHIG,
                    {"default": "on / an",
                    "tooltip": "Shows the preview image inside the node. Some ComfyUI builds "
                               "try to load a video preview instead and report an error - "
                               "switch to 'off' then. It does not affect the record."}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO",
                       "unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("pdf", "akte")
    FUNCTION = "run"
    OUTPUT_NODE = True
    CATEGORY = "VALYDA"
    DESCRIPTION = ("ONLY NEEDED if you deliver to a broadcaster - public, private "
                   "or international (ARD, ZDF, RTL, BBC, Netflix ...). Article 50 "
                   "applies to every broadcaster.\n"
                   "Für die Anlieferung an jeden Sender - öffentlich-rechtlich, "
                   "privat, international.\n\n"
                   "Detailed record with prompt, model checksums, references, "
                   "scene, reason and timecode - the delivery contracts require "
                   "them.\n\nFor social media and the web, use the Creator node.")

    def run(self, Production, Scene, Reason_for_AI_Use, Disclosure_Type,
            video=None, images=None, audio=None, Timecode_In="", Timecode_Out="",
            Source_Footage="not stated", Creator="", Producer="", Co_Producer="",
            Broadcaster="", Broadcaster_Name="", Rights_Holder="", Output_File="",
            Store_Prompt="show prompt", Prompt_Assignment="automatic",
            Preview_In_Node="on", prompt=None, extra_pnginfo=None, unique_id=None):
        # Sheet and language decisions hang on the CHOICE; the combined value
        # (with free-text suffix "\u00b7 Redaktion ...") goes into record and header.
        _sender_basis = (Broadcaster or "").strip()
        Broadcaster = _broadcaster_aufloesen(Broadcaster, Broadcaster_Name)
        if _sender_basis in ("", ANDERER_SENDER):
            _sender_basis = Broadcaster
        # Bring bilingual display values down to their English half - record
        # and comparisons know only that (_wert_en).
        Source_Footage = _wert_en(Source_Footage)
        Store_Prompt = _wert_en(Store_Prompt)
        Prompt_Assignment = _wert_en(Prompt_Assignment)
        Preview_In_Node = _wert_en(Preview_In_Node)
        if images is None and audio is None and video is None:
            if _eingang_verbunden(prompt, unique_id):
                raise ValueError(
                    "VALYDA: The input is connected but nothing arrived. Most "
                    "likely a node upstream is bypassed or muted (purple or "
                    "dark). Remove the bypass and run again.")
            raise ValueError("VALYDA: connect video, images or audio - "
                             "there is nothing to record otherwise.")
        ordner = _ausgabeordner(Production)
        name = "valyda_%s_%s" % (time.strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:4])

        beginn = time.time()
        modus = "vollstaendig" if Store_Prompt == "show prompt" else "nur_pruefsumme"
        a = erheben(images, prompt or {}, str(unique_id), Production, Creator,
                    ordner, name, prompt_modus=modus,
                    ergebnis_pfad=Output_File, ton=audio, video=video, beginn=beginn)

        # User decision: the longest text counts as the prompt. It is marked
        # as such - the tool does not claim it on its own.
        offen = (a.get("prompt") or {}).get("texte_ohne_rolle") or []
        if Prompt_Assignment != "automatic" and offen:
            a["prompt"]["positiv"] = offen[0]
            a["prompt"]["sha256"] = akte_mod.sha256_text(offen[0])
            a["prompt"]["zuordnung"] = "nutzer"
            a["prompt"]["texte_ohne_rolle"] = offen[1:] or None
            print("[VALYDA] Prompt role set by the user (longest text).")

        Timecode_In = _timecode_saeubern(Timecode_In)
        Timecode_Out = _timecode_saeubern(Timecode_Out)
        # If the end timecode is set, it applies; otherwise the calculation
        # from frame rate and frame count stays.
        a["einsatz"]["timecode_ende"] = (Timecode_Out or
                                         _timecode_ende(Timecode_In,
                                                        a.get("parameter") or {}))
        a["produzent"] = (Producer or "").strip() or None
        a["co_produzent"] = (Co_Producer or "").strip() or None
        a["auftraggeber"] = (Broadcaster or "").strip() or None
        a["rechteinhaber"] = (Rights_Holder or "").strip() or None
        _bildquelle_anwenden(a, _QUELLE_DEUTSCH.get(Source_Footage, "nicht angegeben"))

        # Classification and transparency duty from the ONE derivation point -
        # see einstufung_aus_kennzeichnungsart(). "not classified" stays
        # undecided; the declaration then ticks nothing.
        schluessel, pflicht = einstufung_aus_kennzeichnungsart(Disclosure_Type)
        a["einstufung"] = {"wert": schluessel, "vorschlag": "unbekannt",
                           "begruendung": None}
        a["einsatz"].update({
            "szene": Scene or None,
            "zweck": Reason_for_AI_Use or None,
            "timecode_start": Timecode_In or None,
            "transparenzpflicht": {
                "wert": pflicht, "vorschlag": pflicht,
                "begruendung": ("Aus der Art der Kennzeichnung abgeleitet - "
                                "Angabe des Produzenten."
                                if pflicht is not None else None),
            },
        })

        akte_pfad = akte_mod.schreiben(a, os.path.join(ordner, "%s.valyda-akte.json" % name))
        akte_hash = akte_mod.sha256_datei(akte_pfad)
        pdf_pfad = _pdf_sicher(
            pdf_mod.fassung_s,
            [a], os.path.join(ordner, "%s_VALYDA-AI-PROTOCOL_Broadcast.pdf" % name),
            {"projekt": Production, "auftraggeber": Broadcaster,
             "co_produzent": Co_Producer,
             "akte_datei": os.path.basename(akte_pfad), "akte_hash": akte_hash,
             "produzent": Producer, "rechteinhaber": Rights_Holder,
             "kennung": pdf_mod.kennung_bauen(a),
             "erstellt_am": a["erzeugt_am"].replace("T", " ")[:19]},
            ordner, zweisprachig=_dokument_zweisprachig(_sender_basis))

        print("[VALYDA] Protocol written: %s" % pdf_pfad)

        # Declaration sheet as its own document - automatic for ARD/Degeto,
        # no switch. It reads the ticks from the record (one derivation).
        bogen_pfad = ""
        if _braucht_erklaerungsbogen(_sender_basis):
            bogen_pfad = _pdf_sicher(
                pdf_mod.erklaerungsbogen, [a],
                os.path.join(ordner, "%s_Erklaerungsbogen-KI.pdf" % name),
                {"projekt": Production, "produzent": Producer,
                 "kennung": pdf_mod.kennung_bauen(a),
                 "erstellt_am": a["erzeugt_am"].replace("T", " ")[:19]},
                ordner)
            if bogen_pfad:
                print("[VALYDA] Declaration sheet written: %s" % bogen_pfad)

        vorschau = (a.get("ergebnis") or {}).get("vorschau") or {}
        print("[VALYDA] Preview image: %s" % (vorschau.get("datei") or "none written"))
        ui = _ui_bild(a, name, Production, pdf_pfad) if Preview_In_Node == "on" else {}
        if bogen_pfad and ui.get("valyda_pdf"):
            ui["valyda_pdf"].append(_ui_dokument(bogen_pfad))
        return {"ui": ui, "result": (pdf_pfad, akte_pfad)}


def _aus_akten_uebernehmen(akten: List[Dict[str, Any]], feld: str,
                           eigener_wert: str, anzeige: str) -> str:
    """
    Produzent/Rechteinhaber fuer den Kopf der gebuendelten Fassung.

    Reihenfolge: das eigene Feld des Buendeln-Knotens gilt. Ist es leer und
    nennen die Akten, die einen Wert tragen, einstimmig denselben, wird der
    uebernommen. Sind sie uneinig, steht im Dokument "nicht angegeben" und die
    Konsole nennt, was gefunden wurde - nichts wird zusammengefasst, nichts
    mehrheitlich entschieden. Uneinigkeit ist eine Tatsache, kein Problem, das
    das Werkzeug loesen darf.
    """
    wert = (eigener_wert or "").strip()
    if wert:
        return wert
    gefunden = sorted({(a.get(feld) or "").strip()
                       for a in akten if (a.get(feld) or "").strip()})
    if len(gefunden) == 1:
        return gefunden[0]
    if len(gefunden) > 1:
        print("[VALYDA] Note: the records name different values for %s - "
              "the document therefore records it as not stated. Found: %s"
              % (anzeige, " | ".join(gefunden)))
    return ""


def _aus_akten_aufzaehlen(akten, feld: str) -> str:
    """
    Einstimmig -> der Wert. Uneinig -> die Werte werden GENANNT:

        mehrere - ARD Degeto (3), ZDF (1)

    Wer das liest, sieht sofort, was los ist: echte Koproduktion oder
    Tippfehler bei einem Clip - ohne blaettern zu muessen (Pit, 01.08.).
    Mehr als drei Verschiedene: die drei haeufigsten, dann "und N weitere".
    Der Umbruch langer Zeilen ist Sache der Paragraph-Zellen (Etappe 0).
    """
    from collections import Counter
    zaehler = Counter((a.get(feld) or "").strip()
                      for a in akten if (a.get(feld) or "").strip())
    if not zaehler:
        return ""
    if len(zaehler) == 1:
        return next(iter(zaehler))
    haeufigste = sorted(zaehler.items(), key=lambda kv: (-kv[1], kv[0]))
    teile = ["%s (%d)" % (wert, anzahl) for wert, anzahl in haeufigste[:3]]
    if len(haeufigste) > 3:
        teile.append("und %d weitere" % (len(haeufigste) - 3))
    return "mehrere - " + ", ".join(teile)


def _akten_auskunft_felder(akten: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """
    Die Akten-Auskunft fuer die ANZEIGE am Buendeln-Knoten (Pit, 08.08.):
    was WUERDEN die Akten fuer Producer/Co-Producer/Rights-Holder liefern?

    Reine Auskunft. Kein Feld wird beschrieben - die Uebernahme beim
    Ausfuehren (_aus_akten_uebernehmen, _aus_akten_aufzaehlen) bleibt die
    Wahrheit und rechnet weiter auf dem leeren Feld. probelauf.py wacht
    darueber, dass Auskunft und Uebernahme nicht auseinanderlaufen.

    Wortlaut (Pit, 08.08.): englische Zeile traegt den Wert, deutsche
    Kleinzeile ohne Wert.
    """
    from collections import Counter
    raus: Dict[str, Dict[str, str]] = {}
    for widget, feld in (("Producer", "produzent"),
                         ("Co_Producer", "co_produzent"),
                         ("Rights_Holder", "rechteinhaber")):
        zaehler = Counter((a.get(feld) or "").strip()
                          for a in akten if (a.get(feld) or "").strip())
        if not zaehler:
            raus[widget] = {"stand": "leer",
                            "en": "Records: no entry",
                            "de": "Akten: keine Angabe"}
        elif len(zaehler) == 1:
            raus[widget] = {"stand": "einstimmig",
                            "en": "Records agree: %s" % next(iter(zaehler)),
                            "de": "Akten einstimmig"}
        else:
            # dieselbe Reihung wie _aus_akten_aufzaehlen: haeufigster zuerst,
            # hoechstens drei, dann "und N weitere" (Waechter in probelauf.py)
            haeufigste = sorted(zaehler.items(), key=lambda kv: (-kv[1], kv[0]))
            teile = ["%s (%d)" % (wert, anzahl) for wert, anzahl in haeufigste[:3]]
            if len(haeufigste) > 3:
                teile.append("und %d weitere" % (len(haeufigste) - 3))
            raus[widget] = {"stand": "uneinig",
                            "en": "Records differ: %s" % ", ".join(teile),
                            "de": "Akten uneinig"}
    return raus


KEIN_PROJEKT = "kein Projekt gefunden"

#: First entry and default of the production dropdown. The normal course
#: is: render, then bundle - so the project is ALWAYS new, and any list
#: built at load time is structurally at a disadvantage. This entry is
#: resolved AT RUN TIME on the server: there the folder state is always
#: current - no reloading, no cache, no Ctrl+F5.
NEUESTES_PROJEKT = "— neuestes Projekt —"

#: The guidance for the state "no project folder yet". ONE wording for
#: three places: the two run-time errors in Buendeln.run and the hint the
#: production dropdown shows BEFORE running (C, Pit 08.08.) -
#: probelauf.py guards that they never drift apart.
HINWEIS_ERST_CLIPS = ("Record the individual clips first - "
                      "they create the folder.")

_FASSUNG: Optional[str] = None


def _plugin_fassung() -> str:
    """Die Plugin-Version aus pyproject.toml - einmal gelesen, dann gemerkt."""
    global _FASSUNG
    if _FASSUNG is not None:
        return _FASSUNG
    pfad = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "pyproject.toml")
    fassung = ""
    try:
        import re as _re
        with open(pfad, "r", encoding="utf-8") as f:
            treffer = _re.search(r'^version\s*=\s*"([^"]+)"', f.read(), _re.M)
        if treffer:
            fassung = treffer.group(1)
    except OSError:
        pass
    _FASSUNG = fassung
    return fassung


def _neuestes_projekt() -> Optional[str]:
    """
    Der Projektordner mit der juengsten Akte - oder None.

    Massgeblich ist die juengste .valyda-akte.json, nicht das Ordnerdatum:
    ein Ordner kann alt sein und trotzdem gerade eine neue Akte bekommen haben.
    """
    try:
        if folder_paths is not None:
            wurzel = os.path.join(folder_paths.get_output_directory(), "valyda")
        else:
            wurzel = os.path.join(os.path.abspath("output"), "valyda")
        bester, beste_zeit = None, -1.0
        for name in os.listdir(wurzel):
            voll = os.path.join(wurzel, name)
            if not os.path.isdir(voll):
                continue
            for datei in os.listdir(voll):
                if not datei.endswith(".valyda-akte.json"):
                    continue
                try:
                    wann = os.path.getmtime(os.path.join(voll, datei))
                except OSError:
                    continue
                if wann > beste_zeit:
                    bester, beste_zeit = name, wann
        return bester
    except OSError:
        return None


def _projektordner() -> List[str]:
    """
    Die vorhandenen Projektordner unter output/valyda - neueste zuerst.

    Fuer die Auswahlliste des Buendeln-Knotens: er kann nur zusammenfassen, was
    schon auf der Platte liegt. Ein freies Textfeld war die falsche Bauform -
    ein Tippfehler erzeugte keinen Fehler, sondern ein leeres Protokoll.

    Die Liste entsteht, wenn die Oberflaeche die Knotenliste abruft (Laden bzw.
    "Refresh node definitions") - wie bei den Modell-Listen, mit derselben
    Grenze: ein Ordner, der danach entsteht, erscheint erst nach dem
    Aktualisieren.
    """
    try:
        if folder_paths is not None:
            wurzel = os.path.join(folder_paths.get_output_directory(), "valyda")
        else:
            wurzel = os.path.join(os.path.abspath("output"), "valyda")
        eintraege = []
        for name in os.listdir(wurzel):
            voll = os.path.join(wurzel, name)
            if os.path.isdir(voll):
                try:
                    eintraege.append((os.path.getmtime(voll), name))
                except OSError:
                    eintraege.append((0.0, name))
        eintraege.sort(key=lambda e: (-e[0], e[1]))
        return [name for _, name in eintraege]
    except OSError:
        return []


# ---------------------------------------------------------------- node 3
class ValydaProtokollBuendeln:
    """Alle Akten einer Produktion zu einem Dokument."""

    @classmethod
    def INPUT_TYPES(cls):
        # "neuestes Projekt" always stands first and is the default - the list
        # behind it is mere convenience for deliberately picking an older
        # project, no longer a prerequisite.
        ordner = [NEUESTES_PROJEKT] + _projektordner()
        return {
            # Required are Production and Producer (Pit, 01.08.). Required-first
            # pulls Producer ahead of positions 2-8 of the shared order - but
            # this node does not have those, and the relative order of the
            # fields that exist is preserved.
            "required": {
                "Production": (ordner, {
                    "tooltip": "The production whose records are combined into ONE "
                               "document - the choices are the existing folders under "
                               "output/valyda, newest first. The list refreshes itself "
                               "when the node is clicked; if a fresh project is missing, "
                               "press Ctrl+F5 in the browser."}),
                "Producer": ("STRING", {"default": "",
                    "tooltip": "Production company. Left empty: taken from the records "
                               "if they agree unanimously, otherwise 'not stated'."}),
            },
            # SHARED FIELD ORDER of the three nodes (Pit, 01.08., version 2.0)
            # - after that it is FROZEN again: new fields only at the END.
            # (The Part-A switch "Erklaerungsbogen" is gone - the ticks ALWAYS
            # come from the producer's statements.)
            # This node does NOT ask for a broadcaster (Pit, 01.08.): it must
            # not ask what the records already know - in a broadcaster
            # production the broadcaster is entered on every clip anyway.
            # Client and publication channel come from the records; dissent is
            # named in the document (_aus_akten_aufzaehlen).
            "optional": {
                "Co_Producer": ("STRING", {"default": "",
                    "tooltip": "Co-producing company, if any. Left empty: taken from "
                               "the records if they agree unanimously; appears on the "
                               "record only when filled."}),
                "Rights_Holder": ("STRING", {"default": "",
                    "tooltip": "Rights holder of the PRODUCTION - not the software "
                               "rights holder named in the footer. Left empty: taken "
                               "from the records if they agree unanimously."}),
                "Reference_File": ("STRING", {"default": "",
                    "tooltip": "Full path of the final master this record refers to - "
                               "usually the broadcast cut. If the file exists, its "
                               "checksum is taken. / Vollständiger Pfad der fertigen "
                               "Fassung, auf die sich dieses Projektprotokoll bezieht - "
                               "meist die Sendefassung. Liegt die Datei vor, wird ihre "
                               "Prüfsumme gebildet."}),
                "Version": ("STRING", {"default": "",
                    "tooltip": "Which cut this record refers to, e.g. 'final cut v3' / "
                               "'Sendefassung R3'."}),
                "Multiple_Runs": (["keep all clips / alle behalten",
                                   "newest clip per scene / neuester je Szene"],
                    {"default": "keep all clips / alle behalten",
                     "tooltip": "If a shot was rendered several times, there are several "
                                "records for it. 'newest clip per scene' keeps only the "
                                "latest of each - provided the scene is spelled "
                                "identically."}),
                "Output": (["both / beide", "Broadcast", "Creator"],
                    {"default": "both / beide",
                    "tooltip": "Which edition to write. 'both' delivers the Creator "
                               "sheet AND the Broadcast record from the same material."}),
                "External_1": ("STRING", {"default": "",
                    # NOT Kling/Veo/Runway: since 02.08. those are captured as
                    # API nodes (graph.modelle, path 2) and land in the record
                    # by themselves - only without a checksum. Naming them here
                    # would tell the user to enter by hand what the workflow
                    # already knows. What stays outside is another program - or
                    # one of those same services in its own web app, which the
                    # example below shows.
                    "tooltip": "Items created OUTSIDE ComfyUI (Photoshop, Topaz, "
                               "DaVinci - or one of the cloud services in its own "
                               "web app instead of as a node). Format:\n"
                               "Scene | AI system | Reason | Timecode | disclosure "
                               "yes/no\nExample:\nScene 2 harbour | Kling 2.5 Pro | "
                               "establishing shot | 00:04:12:07 | no\n"
                               "Appears in the document as a MANUAL ENTRY, not "
                               "machine-verified."}),
                "External_2": ("STRING", {"default": "", "tooltip": "same as External_1"}),
                "External_3": ("STRING", {"default": "", "tooltip": "same as External_1"}),
                "External_4": ("STRING", {"default": "", "tooltip": "same as External_1"}),
                "External_5": ("STRING", {"default": "", "tooltip": "same as External_1"}),
                "Records_Folder": ("STRING", {"default": "",
                    "tooltip": "Escape hatch for special cases: folder holding the "
                               "records, absolute or relative to output. Leave empty - "
                               "then the selection above applies."}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("pdf",)
    FUNCTION = "run"
    OUTPUT_NODE = True
    CATEGORY = "VALYDA"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # This node has no inputs. Without this hint ComfyUI considers the
        # result unchanged and does not run it a second time - although new
        # records may have arrived in the folder meanwhile.
        return float("NaN")
    DESCRIPTION = ("Einmal am Ende der Produktion: sammelt alle Akten eines Projekts und "
                   "schreibt EIN Protokoll mit Bilduebersicht.\n\n"
                   "Once at the end: collects all records of a Project and writes ONE "
                   "document with a contact sheet.")

    def run(self, Production, Producer="",
            Multiple_Runs="keep all clips / alle behalten",
            Output="both / beide", Co_Producer="",
            Rights_Holder="", Reference_File="", Version="",
            Records_Folder="", External_1="", External_2="", External_3="",
            External_4="", External_5=""):
        Output = _wert_en(Output)
        # Internally the established German name stays - it runs through
        # folder logic and messages; only the UI says Production.
        Produktion = Production
        if Produktion.strip() == NEUESTES_PROJEKT:
            # Resolve at run time: on the server the state is always current.
            gewaehlt = _neuestes_projekt()
            if gewaehlt is None:
                raise ValueError(
                    "VALYDA: No project folder found. " + HINWEIS_ERST_CLIPS)
            Produktion = gewaehlt
            print("[VALYDA] Newest project chosen: %s" % gewaehlt)

        if Produktion.strip() == KEIN_PROJEKT:
            raise ValueError(
                "VALYDA: No project folder found. " + HINWEIS_ERST_CLIPS
                + " If a fresh project does not "
                "show in the list, press Ctrl+F5 in the browser.")

        # Without a statement the folder is derived from the production name -
        # exactly the one the per-clip nodes wrote into. The dropdown returns
        # the FOLDER NAME; projektkennung() is idempotent for such names,
        # which is why a hand-typed title from old workflows keeps working
        # too.
        if Records_Folder.strip():
            ordner = _ordner_aus_angabe(Records_Folder)
        else:
            ordner = _ausgabeordner(Produktion)

        if not os.path.isdir(ordner):
            raise ValueError(
                "VALYDA: the records folder does not exist.\n"
                "        %s\n"
                "        Without a statement it is derived from the production "
                "name - the name must then match the one in the per-clip nodes "
                "character for character." % ordner)

        akten: List[Dict[str, Any]] = []
        fremd = 0
        for datei in sorted(os.listdir(ordner)):
            if not datei.endswith(".valyda-akte.json"):
                continue
            try:
                a = akte_mod.lesen(os.path.join(ordner, datei))
            except Exception:
                continue
            # Second latch: if the record names a different production, it stays
            # out. Compared via the id, because the dropdown returns the folder
            # name ("ROUNDTRIP_AT") while the record has the title ("ROUNDTRIP (AT)").
            if Produktion.strip() and (a.get("projekt") or "").strip() \
                    and projektkennung(a["projekt"]) != projektkennung(Produktion):
                fremd += 1
                continue
            akten.append(a)

        # merge repeatedly rendered shots on request
        if Multiple_Runs.startswith("newest"):
            neueste: Dict[str, Dict[str, Any]] = {}
            for a in sorted(akten, key=lambda x: x.get("erzeugt_am") or ""):
                schluessel = ((a.get("einsatz") or {}).get("szene") or "").strip().lower()
                neueste[schluessel or a.get("akte_id", "")] = a
            entfernt = len(akten) - len(neueste)
            akten = list(neueste.values())
            if entfernt:
                print("[VALYDA] %d older version(s) of the same scene left out." % entfernt)

        # The document gets the TITLE of the production as the records carry
        # it - not the folder name from the dropdown ("ROUNDTRIP (AT)" instead
        # of "ROUNDTRIP_AT").
        titel = next((a.get("projekt") for a in akten if a.get("projekt")),
                     Produktion)

        # items from outside - clearly marked as manual entries
        for zeile in (External_1, External_2, External_3, External_4, External_5):
            eintrag = _hand_eintrag(zeile, titel)
            if eintrag:
                akten.append(eintrag)

        # order: by timecode, else by creation time
        akten.sort(key=lambda a: (((a.get("einsatz") or {}).get("timecode_start") or "zzz"),
                                  a.get("erzeugt_am") or ""))

        print("[VALYDA] %d record(s) taken from %s%s"
              % (len(akten), ordner,
                 (", %d skipped as belonging to another production" % fremd) if fremd else ""))
        if not akten:
            raise ValueError(
                "VALYDA: no records found in %s. Does the per-clip node write "
                "with the same production name? If a fresh project does not "
                "show in the dropdown, press Ctrl+F5 in the browser." % ordner)

        # Timestamp PLUS four random characters - the same construction as in
        # the per-clip nodes. Until the evening of 02.08. only the clock to
        # the second stood here: two runs in the same second produced the
        # same file name, and the second overwrote the first (measured, two
        # runs -> ONE file). An evidence tool must not silently lose
        # evidence; the quick guide moreover promises that nothing is ever
        # overwritten.
        #
        # ONE mark for the whole run: the up to three documents (Creator,
        # Broadcast, declaration sheet) belong together and should remain
        # recognisable side by side in the folder as one run.
        marke = "%s_%s" % (time.strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:4])
        erzeugt = []

        # PROJECT_ in front (Pit, 09.08.): the folder shows at a glance
        # which file is the collection and which the single clip - the
        # per-clip nodes keep their valyda_..._VALYDA-AI-PROTOCOL_... names.
        if Output in ("Creator", "both"):
            ziel_k = os.path.join(ordner,
                                  "PROJECT_VALYDA-AI-PROTOCOL_Creator_%s.pdf"
                                  % marke)
            pdf_mod.fassung_k(akten, ziel_k, ordner, projekt=titel)
            erzeugt.append(ziel_k)

        # Client and publication channel come from the RECORDS - unanimous
        # takes the value, dissent the named enumeration. Producer and rights
        # holder keep their own fields (own field wins, else unanimous
        # adoption).
        auftraggeber = _aus_akten_aufzaehlen(akten, "auftraggeber")
        produzent = _aus_akten_uebernehmen(akten, "produzent",
                                           Producer, "den Produzenten")
        veroeffentlicht = _aus_akten_aufzaehlen(akten, "veroeffentlicht_auf")
        # Language decision: with exactly ONE broadcaster stem (choice part
        # before the suffix) that one counts; with several or none it stays
        # German - the normal case.
        _staemme = {(a.get("auftraggeber") or "").split(" \u00b7 ")[0].strip()
                    for a in akten if (a.get("auftraggeber") or "").strip()}
        zweisprachig = (_dokument_zweisprachig(next(iter(_staemme)))
                        if len(_staemme) == 1 else True)

        if Output in ("Broadcast", "both"):
            ziel = os.path.join(ordner,
                                "PROJECT_VALYDA-AI-PROTOCOL_Broadcast_%s.pdf"
                                % marke)
            pdf_mod.fassung_s(akten, ziel, {
                "projekt": titel,
                "auftraggeber": auftraggeber,
                "co_produzent": _aus_akten_uebernehmen(akten, "co_produzent",
                                                       Co_Producer,
                                                       "den Co-Produzenten"),
                "fassung": Version,
                "produzent": produzent,
                "rechteinhaber": _aus_akten_uebernehmen(akten, "rechteinhaber",
                                                        Rights_Holder,
                                                        "den Rechteinhaber"),
                "veroeffentlicht_auf": veroeffentlicht,
                "bezugsdatei": _bezugsdatei_mit_pruefsumme(Reference_File, ordner),
                "kennung": pdf_mod.kennung_bauen(akten=akten),
                "erstellt_am": time.strftime("%Y-%m-%d %H:%M"),
            }, ordner, zweisprachig=zweisprachig, projektblatt=True)
            erzeugt.append(ziel)

        # Declaration sheet as its own document - automatic as soon as ONE
        # record goes to ARD Degeto or ARD Das Erste (the Degeto items need
        # their form, in mixed projects too). No switch.
        if any(_braucht_erklaerungsbogen(a.get("auftraggeber") or "")
               for a in akten):
            bogen = _pdf_sicher(
                pdf_mod.erklaerungsbogen, akten,
                os.path.join(
                    ordner,
                    "PROJECT_VALYDA-AI-PROTOCOL_Erklaerungsbogen-KI_%s.pdf"
                    % marke),
                {"projekt": titel, "produzent": produzent,
                 "kennung": pdf_mod.kennung_bauen(akten=akten),
                 "erstellt_am": time.strftime("%Y-%m-%d %H:%M")},
                ordner)
            if bogen:
                print("[VALYDA] Declaration sheet written: %s" % bogen)
                erzeugt.append(bogen)

        # The "PDF saved" box - like on the per-clip nodes, only without a
        # preview image (this node produces none) and without a switch (the
        # display is always on here). With output "beide" two entries: one
        # per produced document. The project protocol of all things is the
        # sheet that goes to the broadcaster - it must be findable.
        ui = {"valyda_pdf": [_ui_dokument(p) for p in erzeugt]}
        return {"ui": ui, "result": (" | ".join(erzeugt),)}


# ---------------------------------------------------------------- helpers
def _timecode_saeubern(wert: str) -> str:
    """
    Macht aus dem, was jemand tippt, einen lesbaren Timecode.

    Punkte, Kommas und Semikolons werden zu Doppelpunkten, Leerzeichen fallen weg.
    Sieht es danach nicht wie ein Timecode aus, bleibt der Text unveraendert stehen
    und es gibt einen Hinweis - erfunden wird nichts.
    """
    import re as _re
    roh = (wert or "").strip()
    if not roh:
        return ""
    # a bare digit string as editing tools emit it: 01552224 / 015522
    nur_ziffern = _re.sub(r"\D", "", roh)
    if nur_ziffern == roh.replace(" ", "") and len(nur_ziffern) in (6, 8):
        paare = [nur_ziffern[i:i + 2] for i in range(0, len(nur_ziffern), 2)]
        while len(paare) < 4:
            paare.append("00")
        return ":".join(paare)

    sauber = _re.sub(r"[.,;\s]+", ":", roh)
    if _re.fullmatch(r"\d{1,2}:\d{1,2}:\d{1,2}(:\d{1,3})?", sauber):
        teile = sauber.split(":")
        while len(teile) < 4:
            teile.append("00")
        return ":".join(t.zfill(2) for t in teile)
    print("[VALYDA] Note: %r does not look like a timecode "
          "(expected 00:21:48:11). The text is taken over unchanged." % roh)
    return roh


def _hand_eintrag(zeile: str, projekt: str) -> Optional[Dict[str, Any]]:
    """
    Macht aus einer Zeile eine Position, die AUSSERHALB von ComfyUI entstanden ist.

    Form: Szene | KI-System | Zweck | Timecode | Transparenzpflicht ja/nein
    Alles davon ist eine Angabe des Produzenten - nichts wurde gemessen. Genau so
    steht es dann auch im Dokument.
    """
    roh = (zeile or "").strip()
    if not roh:
        return None
    teile = [t.strip() for t in roh.split("|")]
    while len(teile) < 5:
        teile.append("")
    a = akte_mod.neue_akte(projekt, "")
    a["angabe_quelle"] = "hand"
    a["werkzeug"] = {"name": teile[1] or "außerhalb von ComfyUI", "version": None,
                     "art": "Hand-Eintrag"}
    a["herkunft"] = {"status": "unbekannt", "ableitung": "hand",
                     "begruendung": "Außerhalb von ComfyUI erzeugt; Angaben des Produzenten, "
                                    "nicht maschinell geprüft.",
                     "begruendung_en": "Produced outside ComfyUI; entries by the producer, "
                                       "not machine-verified.", "grad": None}
    pflicht = teile[4].strip().lower()
    a["einsatz"] = {"szene": teile[0] or None, "zweck": teile[2] or None,
                    "timecode_start": _timecode_saeubern(teile[3]) or None,
                    "timecode_ende": None,
                    "transparenzpflicht": {
                        "wert": True if pflicht in ("ja", "yes", "j") else
                                False if pflicht in ("nein", "no", "n") else None,
                        "vorschlag": None,
                        "begruendung": "Angabe des Produzenten (Hand-Eintrag)."}}
    print("[VALYDA] Manual entry taken over: %s" % (teile[0] or roh[:40]))
    return a


def _bezugsdatei_mit_pruefsumme(pfad: str, ordner: str) -> str:
    """Haengt die Prüfsumme an, wenn die Datei wirklich da ist."""
    roh = (pfad or "").strip()
    if not roh or not os.path.isfile(roh):
        return roh
    h = akte_mod.sha256_datei(roh, ordner)
    if not h:
        return roh
    return "%s \u00b7 SHA-256 %s\u2026%s" % (os.path.basename(roh), h[:12], h[-4:])


def _timecode_ende(start: str, parameter: Dict[str, Any]) -> Optional[str]:
    """
    Rechnet den Ausstieg aus Einstieg, Dauer und Bildrate.

    Fehlt eines davon, wird nichts gerechnet - ein erfundener Ausstieg waere
    schlimmer als ein leeres Feld.
    """
    import re as _re
    if not start or not _re.fullmatch(r"\d{2}:\d{2}:\d{2}:\d{2}", start or ""):
        return None
    rate = (parameter.get("bildrate") or parameter.get("frame_rate")
            or parameter.get("fps"))
    bilder = (parameter.get("bilder") or parameter.get("length")
              or parameter.get("batch_size"))
    if not rate:
        return None
    try:
        rate = float(rate)
        if bilder:
            gesamt_bilder = int(bilder)
        elif parameter.get("dauer_s"):
            gesamt_bilder = int(round(float(parameter["dauer_s"]) * rate))
        else:
            return None
        h, m, sek, b = (int(x) for x in start.split(":"))
        ganz = int(round(rate))
        summe = ((h * 3600 + m * 60 + sek) * ganz + b) + gesamt_bilder
        b2 = summe % ganz
        rest = summe // ganz
        return "%02d:%02d:%02d:%02d" % (rest // 3600, (rest % 3600) // 60, rest % 60, b2)
    except Exception:
        return None


def _bildquelle_anwenden(a: Dict[str, Any], angabe: str) -> None:
    """
    Beruecksichtigt, was der Hersteller ueber die HERKUNFT der Bildquelle sagt.

    Das Werkzeug sieht nur, DASS ein Bild in den Ablauf ging. Ob dieses Bild eine
    Kameraaufnahme oder selbst schon KI war, kann es nicht sehen - fuer ComfyUI
    sieht beides gleich aus. Ohne diese Angabe würde ein durchgehend generierter
    Clip als blosse Veraenderung gefuehrt, und das Dokument UNTERTRIEBE den
    KI-Anteil. Deshalb fragt der Knoten nach; die Antwort wird als Angabe des
    Herstellers gekennzeichnet, nie als Messung.
    """
    if not angabe or angabe == "nicht angegeben":
        return

    herk = a.setdefault("herkunft", {})
    a["quellen_herkunft"] = {"wert": angabe, "quelle": "produzent"}

    if not (a.get("quellen") or []):
        return   # without an image source there is nothing to refine

    if angabe == "selbst KI-erzeugt":
        herk["status"] = g.STATUS_VOLL
        herk["ableitung"] = "ablauf + Angabe des Herstellers"
        zusatz = ("Die Bildquelle ist laut Angabe des Produzenten selbst KI-erzeugt; "
                  "das Ergebnis gilt damit als vollständig generiert.")
        zusatz_en = ("The image source is AI-generated itself according to the producer; "
                     "the result therefore counts as fully generated.")
    elif angabe == "gemischt":
        herk["ableitung"] = "ablauf + Angabe des Herstellers"
        zusatz = ("Die Bildquelle enthaelt laut Angabe des Produzenten reale und "
                  "KI-erzeugte Anteile.")
        zusatz_en = ("The image source contains both real and AI-generated parts "
                     "according to the producer.")
    else:
        zusatz = "Die Bildquelle ist laut Angabe des Produzenten eine Realaufnahme."
        zusatz_en = "The image source is real footage according to the producer."

    herk["begruendung"] = ((herk.get("begruendung") or "") + " " + zusatz).strip()
    herk["begruendung_en"] = ((herk.get("begruendung_en") or "") + " " + zusatz_en).strip()


# The former keyword suggestion for the transparency duty
# (_pflicht_vorschlag) was dropped on 01.08.: the duty now follows
# exclusively from the ONE derivation point
# einstufung_aus_kennzeichnungsart() - the producer's statement, no
# guessing from prompt words.


def _ui_dokument(pfad: str) -> Dict[str, str]:
    """
    Ein Eintrag fuer den PDF-Kasten im Knoten.

    Die Uhrzeit steht dabei, weil JEDER Lauf eine NEUE Datei schreibt (der
    Name traegt Zeitstempel und Zufallsteil, siehe die Namensbildung in den
    drei Knoten). Wer in der Maske etwas aendert und neu ausfuehrt, bekommt
    also nicht dieselbe Datei mit neuem Inhalt, sondern eine zweite. Wer
    dann die zuvor geoeffnete Datei ansieht, sieht den alten Stand -
    genau das hat Pit am 02.08. abends beobachtet. Nachgemessen mit
    ComfyUIs eigenem Zwischenspeicher: eine Aenderung in der Maske
    aendert die Signatur des Knotens, er wird also wirklich neu
    ausgefuehrt; das Schreiben dauert rund 0,12 s. Es fehlte nur die
    Auskunft, WELCHE Datei gerade entstanden ist.
    """
    return {"pfad": pfad,
            "datei": os.path.basename(pfad),
            "ordner": os.path.dirname(pfad),
            "zeit": time.strftime("%H:%M:%S")}


def _ui_bild(a: Dict[str, Any], name: str, projekt: str = "",
             pdf_pfad: str = "") -> Dict[str, Any]:
    """
    Vorschaubild im Knoten.

    WICHTIG: Der Schluessel heisst bewusst NICHT "images". Die Oberflaeche baut aus
    "images" selbst eine Vorschau - bei einem Knoten mit VIDEO-Eingang eine
    VIDEOvorschau, die an unserem JPEG scheitert ("Video failed to load").
    Unter einem eigenen Namen ignoriert sie die Angabe; unsere Erweiterung liest sie.
    Ohne Vorschau wird gar nichts zurueckgegeben - lieber kein Bild als eine kaputte Adresse.
    """
    raus: Dict[str, Any] = {}
    if pdf_pfad:
        raus["valyda_pdf"] = [_ui_dokument(pdf_pfad)]
    v = (a.get("ergebnis") or {}).get("vorschau") or {}
    datei = str(v.get("datei") or "").strip()
    if datei:
        raus["valyda_vorschau"] = [{"filename": datei,
                                    "subfolder": "valyda/%s" % projektkennung(projekt),
                                    "type": "output"}]
    return raus


NODE_CLASS_MAPPINGS = {
    "ValydaProtokollInternational": ValydaProtokollInternational,
    "ValydaProtokollSender": ValydaProtokollSender,
    "ValydaProtokollBuendeln": ValydaProtokollBuendeln,
}

# Display names (Pit, 01.08.): AI PROTOCOL everywhere, "Buendeln"/
# "bundle" vanish from everything the user sees. The KEYS of these
# tables are frozen, though: saved workflows reference the node by
# exactly this name ("class_type" in the API format, "type" in the
# UI format) - renaming would break every saved workflow.
NODE_DISPLAY_NAME_MAPPINGS = {
    "ValydaProtokollInternational":
        "VALYDA AI PROTOCOL \u00b7 EU AI Act \u00b7 Creator (web, social, festival)",
    "ValydaProtokollSender":
        "VALYDA AI PROTOCOL \u00b7 EU AI Act \u00b7 Broadcast (ARD, ZDF, RTL, BBC and others)",
    "ValydaProtokollBuendeln":
        "VALYDA AI PROTOCOL \u00b7 EU AI Act \u00b7 Project (all clips)",
}


# ---------------------------------------------------------------- the open path
# For security reasons a browser may not open a file on the disk. But
# ComfyUI has its own small server - that is the way. Opening happens
# strictly inside the output folder, nothing else.
def _mit_system_oeffnen(pfad: str) -> bool:
    import subprocess
    import sys as _sys
    try:
        if _sys.platform.startswith("win"):
            os.startfile(pfad)                                    # noqa: S606
        elif _sys.platform == "darwin":
            subprocess.Popen(["open", pfad])
        else:
            subprocess.Popen(["xdg-open", pfad])
        return True
    except Exception as fehler:
        print("[VALYDA] could not be opened: %s" % fehler)
        return False


#: What may be opened. Exactly the file types this plugin writes itself.
#: Whatever else lands in the output folder is none of this path's business.
OEFFNEN_ENDUNGEN = (".pdf", ".json", ".jpg", ".jpeg", ".png", ".webp")


def _im_ausgabeordner(pfad: str) -> Tuple[bool, str]:
    """
    Liegt der Pfad wirklich im Ausgabeordner?

    Frueher wurde die Pruefung UEBERSPRUNGEN, wenn der Ausgabeordner nicht
    bestimmbar war - also genau dann durchgelassen, wenn nichts nachpruefbar war.
    Das war herum. Ohne pruefbaren Ausgabeordner wird jetzt verweigert.
    """
    if folder_paths is None:
        return False, "the output folder is not determinable"
    try:
        wurzel = os.path.realpath(folder_paths.get_output_directory())
    except Exception:
        return False, "the output folder is not determinable"
    if not wurzel or not os.path.isdir(wurzel):
        return False, "the output folder is not determinable"

    try:
        # realpath, not abspath: a link inside the output folder must not
        # lead outside.
        ziel = os.path.realpath(pfad)
    except (OSError, ValueError):
        return False, "the path cannot be resolved"

    w = os.path.normcase(wurzel)
    z = os.path.normcase(ziel)
    try:
        # On different drives commonpath throws. That is not a caller error
        # but the answer: does not lie inside.
        gemeinsam = os.path.commonpath([w, z])
    except ValueError:
        return False, "outside the output folder"
    if gemeinsam != w:
        return False, "outside the output folder"
    return True, ""


try:  # only present inside ComfyUI
    from server import PromptServer  # type: ignore
    from aiohttp import web  # type: ignore

    @PromptServer.instance.routes.post("/valyda/oeffnen")
    async def _valyda_oeffnen(request):
        try:
            daten = await request.json()
        except Exception:
            return web.json_response({"ok": False, "grund": "no data given"}, status=400)

        roh = str(daten.get("pfad") or "").strip()
        if not roh:
            return web.json_response({"ok": False, "grund": "no data given"}, status=400)

        erlaubt, grund = _im_ausgabeordner(roh)
        if not erlaubt:
            return web.json_response({"ok": False, "grund": grund}, status=403)

        pfad = os.path.realpath(roh)
        if daten.get("ordner"):
            pfad = os.path.dirname(pfad)
            # The parent folder must lie inside as well - otherwise "open folder"
            # could work its way out of the output folder.
            erlaubt, grund = _im_ausgabeordner(pfad)
            if not erlaubt:
                return web.json_response({"ok": False, "grund": grund}, status=403)
        elif os.path.splitext(pfad)[1].lower() not in OEFFNEN_ENDUNGEN:
            return web.json_response(
                {"ok": False, "grund": "this file type is not opened"}, status=403)

        if not os.path.exists(pfad):
            return web.json_response({"ok": False, "grund": "not found"}, status=404)

        return web.json_response({"ok": _mit_system_oeffnen(pfad)})

    @PromptServer.instance.routes.get("/valyda/projekte")
    async def _valyda_projekte(request):
        """
        Die vorhandenen Projektordner - fuer die Auswahlliste des
        Buendeln-Knotens, zur Laufzeit nachgeladen.

        Grund: Clips rechnen, dann buendeln ist der normale Ablauf. Der
        Projektordner entsteht also fast immer NACH dem Laden der Oberflaeche,
        und eine Liste, die nur beim Laden entsteht, sagt dann "kein Projekt
        gefunden", obwohl das Projekt existiert.

        Sicherheit wie beim Oeffnen-Weg: es kommen nur ORDNERNAMEN unterhalb
        des Ausgabeordners zurueck - keine Pfade, nichts wird geschrieben.

        "auswahl" ist die fertige Liste fuer das Auswahlfeld (mit dem
        "neuestes Projekt"-Eintrag vorn) - so muss die Oberflaeche den
        Wortlaut des Eintrags nicht kennen.
        """
        projekte = _projektordner()
        antwort = {"projekte": projekte,
                   "auswahl": [NEUESTES_PROJEKT] + projekte}
        if not projekte:
            # C (Pit, 08.08.): die Auskunft, die bisher erst als Fehler beim
            # Ausfuehren kam, wird VORHER am Knoten sichtbar - derselbe
            # Wortlaut, keine neue Formulierung.
            antwort["hinweis"] = HINWEIS_ERST_CLIPS
        return web.json_response(antwort)

    @PromptServer.instance.routes.get("/valyda/akten_auskunft")
    async def _valyda_akten_auskunft(request):
        """
        Was die Akten eines Projekts fuer Producer/Co-Producer/Rights-Holder
        liefern wuerden - fuer die ANZEIGE am Buendeln-Knoten (Pit, 08.08.).

        NUR LESEND: der Pfad wird aus dem Ordnernamen gebaut statt ueber
        _ausgabeordner (das legt Ordner an), und geschrieben wird nichts.
        Sicherheit wie /valyda/projekte: angenommen werden nur Namen, die
        _projektordner() wirklich unter output/valyda gefunden hat - damit
        gibt es keinen Weg zu fremden Pfaden.
        """
        name = str(request.rel_url.query.get("projekt") or "").strip()
        if not name or name == NEUESTES_PROJEKT:
            name = _neuestes_projekt() or ""
        if not name or name not in _projektordner():
            return web.json_response({"projekt": name, "anzahl": 0,
                                      "felder": {}})
        if folder_paths is not None:
            wurzel = folder_paths.get_output_directory()
        else:
            wurzel = os.path.abspath("output")
        ordner = os.path.join(wurzel, "valyda", name)
        akten: List[Dict[str, Any]] = []
        try:
            for datei in sorted(os.listdir(ordner)):
                if not datei.endswith(".valyda-akte.json"):
                    continue
                try:
                    a = akte_mod.lesen(os.path.join(ordner, datei))
                except Exception:
                    continue
                # dieselbe zweite Klinke wie beim Ausfuehren (Buendeln.run):
                # Akten einer anderen Produktion bleiben draussen.
                if (a.get("projekt") or "").strip() \
                        and projektkennung(a["projekt"]) != projektkennung(name):
                    continue
                akten.append(a)
        except OSError:
            pass
        return web.json_response({"projekt": name, "anzahl": len(akten),
                                  "felder": _akten_auskunft_felder(akten)})

    @PromptServer.instance.routes.get("/valyda/fassung")
    async def _valyda_fassung(request):
        """Die Plugin-Version - damit jeder sieht, welche Fassung laeuft."""
        return web.json_response({"fassung": _plugin_fassung()})
except Exception:  # pragma: no cover
    pass
