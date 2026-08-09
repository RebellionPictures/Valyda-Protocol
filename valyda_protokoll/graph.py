# -*- coding: utf-8 -*-
"""
Misst den ausgefuehrten ComfyUI-Ablauf.

Grundsatz: Es wird NICHT nach Knotennamen einer Liste gesucht, sondern nach der
STRUKTUR des Ablaufs. Damit faellt auch jeder kuenftige erzeugende Knoten darunter,
ohne dass hier etwas nachgezogen werden muss.

Sperrender Vorgabewert: Was nicht eindeutig feststellbar ist, heisst "unbekannt".
Es wird nie geraten.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# ---------------------------------------------------------------- recognition traits
# Not a name register but traits. The lists only speed up the naming of
# roles - the derivation itself hangs on the structure (see below).

_BILDQUELLE_MERKMALE = ("loadimage", "load_image", "loadvideo", "load_video",
                        "vhs_loadvideo", "loadimagemask", "imagefrombatch",
                        "loadimagesfromdir", "webcam", "loadalpha",
                        "loadaudio", "load_audio", "vhs_loadaudio")

_GEWICHT_ENDUNGEN = (".safetensors", ".ckpt", ".pth", ".pt", ".bin", ".gguf", ".onnx")

_ROLLEN = (
    ("lora", "lora"),
    ("controlnet", "controlnet"),
    ("control_net", "controlnet"),
    ("vae", "vae"),
    ("clip", "textmodell"),
    ("upscale", "hochrechnung"),
    ("esrgan", "hochrechnung"),
    ("gfpgan", "gesichter"),
    ("codeformer", "gesichter"),
    ("ipadapter", "bildfuehrung"),
)

_RAUSCH_SCHLUESSEL = ("denoise", "denoising_strength", "strength", "weight")
_SEED_SCHLUESSEL = ("seed", "noise_seed")


# ---------------------------------------------------------------- helpers
def _ist_verweis(wert: Any) -> bool:
    """ComfyUI verdrahtet als [knoten_id, ausgang_index]."""
    return (isinstance(wert, (list, tuple)) and len(wert) == 2
            and isinstance(wert[0], (str, int)) and isinstance(wert[1], int))


def _eingaenge(prompt: Dict[str, Any], knoten_id: str) -> Dict[str, Any]:
    return (prompt.get(str(knoten_id)) or {}).get("inputs", {}) or {}


def _typ(prompt: Dict[str, Any], knoten_id: str) -> str:
    return (prompt.get(str(knoten_id)) or {}).get("class_type", "") or ""


def _vorgaenger(prompt: Dict[str, Any], knoten_id: str) -> List[str]:
    raus = []
    for wert in _eingaenge(prompt, knoten_id).values():
        if _ist_verweis(wert):
            raus.append(str(wert[0]))
    return raus


def alle_vorfahren(prompt: Dict[str, Any], start_id: str) -> List[str]:
    """Alle Knoten, die (auch ueber Zwischenstufen) in start_id hineinlaufen."""
    gesehen: Set[str] = set()
    stapel = [str(start_id)]
    reihenfolge: List[str] = []
    while stapel:
        aktuell = stapel.pop()
        if aktuell in gesehen:
            continue
        gesehen.add(aktuell)
        reihenfolge.append(aktuell)
        stapel.extend(_vorgaenger(prompt, aktuell))
    return reihenfolge


# ---------------------------------------------------------------- image sources
def bildquellen(prompt: Dict[str, Any], vorfahren: Iterable[str]) -> List[Dict[str, Any]]:
    """
    Knoten, die ein reales Bild oder Video in den Ablauf holen.

    Merkmal 1 (stark): der Knotentyp traegt ein Lade-Merkmal.
    Merkmal 2 (ergaenzend): ein Eingabewert sieht aus wie ein Dateiname mit
    Bild-/Videoendung und ist kein Modellgewicht.
    """
    treffer = []
    for kid in vorfahren:
        typ = _typ(prompt, kid)
        tl = typ.lower()
        werte = _eingaenge(prompt, kid)

        merkmal = any(m in tl for m in _BILDQUELLE_MERKMALE)
        datei = None
        for name, wert in werte.items():
            if isinstance(wert, str) and re.search(
                    r"\.(png|jpe?g|webp|tiff?|bmp|exr|dpx|mov|mp4|mxf|avi|mkv|prores"
                    r"|wav|mp3|flac|aac|m4a|aiff?|ogg)$",
                    wert, re.I):
                if not wert.lower().endswith(_GEWICHT_ENDUNGEN):
                    datei = wert
                    break

        if merkmal or (datei and any(k in tl for k in ("image", "video", "audio"))):
            treffer.append({"knoten": kid, "typ": typ, "datei": datei})
    return treffer


# ---------------------------------------------------------------- models
#: What "gemessen" versus "laut Ablauf" versus "unbekannt" says decides
#: how much the document is allowed to claim.
NACHWEIS_DATEI = "gemessen"          #: file loaded, checksum computed over it
NACHWEIS_ABLAUF = "laut Ablauf"      #: name stood in the graph, there is no file
NACHWEIS_UNBEKANNT = "unbekannt"     #: old record without this key

#: A key of this kind names the model itself, not one of its settings -
#: "model.name" yes, "model.resolution" no.
_MODELL_BLATT = ("name", "id", "version", "variant")

#: Role when none can be determined. NOT "generator": an undecided
#: value must never become a decision.
ROLLE_OFFEN = "nicht zugeordnet"


def _modellschluessel(name: str) -> bool:
    """
    Benennt dieser Widget-Schluessel das MODELL - oder nur seine Stellgroessen?

    Entschieden wird am LETZTEN Glied der Punktschreibweise. Sonst schriebe
    ein Cloud-Knoten mit `model.resolution: 720p` und
    `model.aspect_ratio: 16:9` die Werte "720p" und "16:9" als Modelle ins
    Protokoll - gemessen an einem echten Kling-Knoten, 02.08.

        model · model_name · unet_model · model.name   ->  ja
        model.resolution · model.aspect_ratio          ->  nein
    """
    glieder = name.lower().split(".")
    if "model" in glieder[-1]:
        return True
    return glieder[-1] in _MODELL_BLATT and any("model" in t for t in glieder[:-1])


def _modellwert(wert: Any) -> bool:
    """Sieht dieser Wert wie ein Modellname aus - und ist er keine Datei?"""
    if not isinstance(wert, str):
        return False
    rein = wert.strip()
    if not rein or len(rein) >= 80 or "\n" in rein:
        return False
    if rein.lower().endswith(_GEWICHT_ENDUNGEN):
        return False
    if "/" in rein or "\\" in rein:            # a path, not a model name
        return False
    return bool(re.search(r"[A-Za-z]", rein))  # "16:9" is not a model name


def _rolle(typ_klein: str, feldname: str) -> Optional[str]:
    for merkmal, r in _ROLLEN:
        if merkmal in typ_klein or merkmal in feldname.lower():
            return r
    return None


def modelle(prompt: Dict[str, Any], vorfahren: Iterable[str]) -> List[Dict[str, Any]]:
    """
    Jedes im Ablauf benutzte Modell - mit abgeleiteter Rolle.

    Zwei Wege, und der Unterschied wird MITGESCHRIEBEN:

    1. Eine geladene Gewichtsdatei. Ueber sie laesst sich eine Pruefsumme
       bilden -> `nachweis = "gemessen"`.
    2. Ein Modellname, der als Widget-Wert im Ablauf steht, aber keine Datei
       ist: so arbeiten die Cloud-Dienste (Kling, Veo, Runway, Gemini,
       ByteDance) und die Knoten, die ihr Modell erst zur Laufzeit holen
       (rembg). Ohne diesen Weg behauptete das Dokument "ComfyUI" als
       KI-System und liesse die Modellzeile leer - fuer einen Sender ist das
       die wichtigste Angabe. Hier gibt es keine Datei und also keine
       Pruefsumme -> `nachweis = "laut Ablauf"`.

    Bewusst KEINE Herstellerliste: die waere am Tag nach dem naechsten neuen
    Dienst unvollstaendig. Entschieden wird am Schluessel, nicht am Namen.
    """
    gefunden: List[Dict[str, Any]] = []
    bekannt: Set[Tuple[str, str]] = set()
    tiefe: Dict[str, int] = {}

    def eintragen(bezeichnung, datei, rolle, kid, typ, staerke, nachweis):
        schluessel = (bezeichnung, rolle)
        if schluessel in bekannt:
            return
        bekannt.add(schluessel)
        if kid not in tiefe:
            tiefe[kid] = len(alle_vorfahren(prompt, kid))
        gefunden.append({"datei": datei, "rolle": rolle, "knoten": kid,
                         "typ": typ, "staerke": staerke, "sha256": None,
                         # New keys go at the END - old records stay readable.
                         "bezeichnung": bezeichnung, "nachweis": nachweis,
                         "_tiefe": tiefe[kid]})

    for kid in vorfahren:
        typ = _typ(prompt, kid)
        tl = typ.lower()
        eing = _eingaenge(prompt, kid)

        staerke = None
        for sname, swert in eing.items():
            if isinstance(swert, (int, float)) and "strength" in sname.lower():
                staerke = float(swert)
                break

        for name, wert in eing.items():
            # --- path 1: loaded weight file
            if isinstance(wert, str) and wert.lower().endswith(_GEWICHT_ENDUNGEN):
                eintragen(wert, wert, _rolle(tl, name) or "generator",
                          kid, typ, staerke, NACHWEIS_DATEI)
                continue

            # --- path 2: model name without a file
            if not (_modellschluessel(name) and _modellwert(wert)):
                continue
            rolle = _rolle(tl, name)
            if rolle is None:
                # Does this node generate itself? Then it is the generator.
                # Otherwise it stays open - no guessing.
                rolle = "generator" if _ist_sampler_stufe(eing) else ROLLE_OFFEN
            eintragen(wert.strip(), None, rolle, kid, typ, staerke,
                      NACHWEIS_ABLAUF)

    # In graph order: fewer ancestors means it ran earlier.
    # `alle_vorfahren` returns a stack whose order is determined by the
    # wiring, not by meaning - if the models stood in the document like
    # that, the "Name KI-System" line would name the second of two
    # generators first (measured 02.08.).
    gefunden.sort(key=lambda m: (m["_tiefe"], str(m["knoten"])))
    for m in gefunden:
        m.pop("_tiefe", None)
    return gefunden


# ---------------------------------------------------------------- texts
def _rollen(prompt: Dict[str, Any], kid: str) -> Dict[str, List[str]]:
    """Eingangsnamen dieses Knotens nach Seite sortiert - auch Teilnamen zaehlen."""
    raus: Dict[str, List[str]] = {"pos": [], "neg": []}
    for name, wert in _eingaenge(prompt, kid).items():
        if not _ist_verweis(wert):
            continue
        n = name.lower()
        if "neg" in n or "uncond" in n:
            raus["neg"].append(name)
        elif "pos" in n or n in ("cond", "conditioning"):
            raus["pos"].append(name)
    return raus


def _weiche(prompt: Dict[str, Any], vorfahren: List[str]) -> Optional[str]:
    """
    Der Knoten, der beide Seiten zusammenfuehrt - Sampler oder Guider.

    Gibt es mehrere (Sampler UND ein ControlNet davor), gewinnt der hinterste:
    er hat die meisten Vorfahren. Von ihm aus wird rueckwaerts gegangen.
    """
    beide = [k for k in vorfahren
             if _rollen(prompt, k)["pos"] and _rollen(prompt, k)["neg"]]
    if not beide:
        return None
    return max(beide, key=lambda k: (len(alle_vorfahren(prompt, k)), str(k)))


def _seite(prompt: Dict[str, Any], kid: str, seite: str) -> Set[str]:
    """
    Alle Knoten auf EINER Seite des Schritts - astgetreu verfolgt.

    Der Punkt, an dem die fruehere Fassung scheiterte: ein Zwischenglied wie
    ControlNetApplyAdvanced fuehrt beide Seiten zugleich und gibt sie getrennt
    wieder aus. Wer dort einfach alle Vorfahren einsammelt, bekommt auf beiden
    Seiten dieselbe Menge - und nach dem Abziehen bleibt nichts uebrig. Deshalb
    wird an solchen Knoten NUR der Ast weiterverfolgt, der zur eigenen Seite
    gehoert.
    """
    stapel: List[str] = []
    eing = _eingaenge(prompt, kid)
    for name in _rollen(prompt, kid)[seite]:
        wert = eing.get(name)
        if _ist_verweis(wert):
            stapel.append(str(wert[0]))

    gesehen: Set[str] = set()
    while stapel:
        aktuell = stapel.pop()
        if aktuell in gesehen:
            continue
        gesehen.add(aktuell)
        r = _rollen(prompt, aktuell)
        e = _eingaenge(prompt, aktuell)
        if r["pos"] and r["neg"]:
            for name in r[seite]:              # only our own branch
                wert = e.get(name)
                if _ist_verweis(wert):
                    stapel.append(str(wert[0]))
        else:
            for wert in e.values():
                if _ist_verweis(wert):
                    stapel.append(str(wert[0]))
    return gesehen


def prompt_texte(prompt: Dict[str, Any], vorfahren: Iterable[str]) -> Dict[str, Any]:
    """
    Positiv- und Negativtext bestimmen.

    Verfahren: vom zusammenfuehrenden Schritt (Sampler oder Guider) aus wird jede
    Seite einzeln rueckwaerts verfolgt - ast-, nicht mengenweise. Dann werden die
    gefundenen Texte den Seiten zugeordnet.

    Laesst sich eine Rolle nicht bestimmen, wird NICHTS behauptet: der Text steht
    dann unter "texte_ohne_rolle". Ein Negativ-Prompt, der als Prompt im Protokoll
    stuende, waere eine Falschaussage.

    Und: was uebrig bleibt, faellt NIE still weg. Auch wenn der Prompt erkannt
    wurde, gehoeren die restlichen Textbausteine ins Dokument. Ein Protokoll, das
    unvollstaendig ist und vollstaendig aussieht, ist schlechter als eines, das
    die Luecke benennt.
    """
    vorfahren = list(vorfahren)

    # --- collect text candidates WITH their field names. One node can
    # carry SEVERAL texts: Flux runs clip_l and t5xxl side by side, SDXL
    # text_g and text_l.
    kandidaten: List[Tuple[str, str, str]] = []
    for kid in vorfahren:
        for name, text in _texte_mit_namen(prompt, kid):
            kandidaten.append((kid, name, text))

    def laengster(menge: Set[str]) -> Optional[str]:
        treffer = [t for k, _n, t in kandidaten if k in menge]
        return max(treffer, key=len) if treffer else None

    positiv: Optional[str] = None
    negativ: Optional[str] = None

    kid = _weiche(prompt, vorfahren)
    if kid is not None:
        positiv_seite = _seite(prompt, kid, "pos")
        negativ_seite = _seite(prompt, kid, "neg")
        nur_positiv = positiv_seite - negativ_seite
        nur_negativ = negativ_seite - positiv_seite

        # A text that sits on BOTH sides is the prompt: the negative side is
        # then a derived version of it (ConditioningZeroOut and relatives).
        # It is NOT turned into a negative prompt.
        positiv = laengster(nur_positiv) or laengster(positiv_seite)
        negativ = laengster(nur_negativ)
    else:
        # --- second survey path, same pattern as the models (02.08./08.08.):
        # a cloud node (Kling, Gemini, Runway ...) has no wired pos/neg
        # junction to walk back from - its prompt is a WIDGET on the
        # generating node, or a wired input whose NAME says the side
        # ("prompt", "negative_prompt"). The role then comes from the
        # field name, decided at the last dotted segment. Without this
        # path Pits Kling record said "none · keine" although the prompt
        # stood in the workflow (measured 08.08.).
        pos_texte: List[str] = []
        neg_texte: List[str] = []
        for k, name, text in kandidaten:
            seite = _rolle_aus_name(name)
            if seite == "pos":
                pos_texte.append(text)
            elif seite == "neg":
                neg_texte.append(text)
        for k in vorfahren:
            for name, wert in _eingaenge(prompt, k).items():
                seite = _rolle_aus_name(name)
                if seite is None or not _ist_verweis(wert):
                    continue
                # the longest text of that branch carries the input's role
                menge = set(alle_vorfahren(prompt, str(wert[0])))
                text = laengster(menge)
                if text is not None:
                    (pos_texte if seite == "pos" else neg_texte).append(text)
        positiv = max(pos_texte, key=len) if pos_texte else None
        negativ = max(neg_texte, key=len) if neg_texte else None
        if negativ is not None and negativ == positiv:
            negativ = None      # one text never carries both sides

    if positiv is None and negativ is None \
            and len({t for _, _n, t in kandidaten}) == 1:
        positiv = kandidaten[0][2]

    # --- everything not assigned to either side gets named.
    zugeordnet = {t for t in (positiv, negativ) if t}
    ungeklaert = [t for _, _n, t in kandidaten if t not in zugeordnet]
    # identical texts only once
    einmalig: List[str] = []
    for t in ungeklaert:
        if t not in einmalig:
            einmalig.append(t)
    einmalig.sort(key=len, reverse=True)

    return {"positiv": positiv, "negativ": negativ,
            "texte_ohne_rolle": einmalig or None}


_TEXTFELDER = ("text", "prompt", "string", "text_g", "text_l", "positive_prompt",
               "negative_prompt", "value", "caption", "description",
               # Flux and relatives carry the prompt under the name of the text
               # model, not under "text".
               "clip_l", "clip_g", "t5xxl", "t5", "llama",
               # further common names from third-party nodes
               "instruction", "text_positive", "text_negative",
               "positive_text", "negative_text", "prompt_text")


def _textfeld(name: str) -> bool:
    """
    Benennt dieser Widget-Schluessel einen TEXT?

    Entschieden am LETZTEN Glied der Punktschreibweise - dasselbe Muster
    wie bei den Modellen (`_modellschluessel`, 02.08.). Ein Cloud-Knoten
    traegt seinen Prompt als `multi_shot.storyboard_1_prompt` (gemessen
    an Pits echtem Kling-Lauf, 08.08.) - wer den vollen Namen gegen die
    Liste haelt, laesst genau diesen Text lautlos verschwinden, und im
    Blatt stand "none · keine".

        prompt · negative_prompt · storyboard_1_prompt  ->  ja
        multi_shot · prompt_mode (Ein-Wort-Wert)        ->  nein bzw.
                                                            faellt am Wert
    """
    letzt = name.lower().split(".")[-1]
    return letzt in _TEXTFELDER or "prompt" in letzt


def _rolle_aus_name(name: str) -> Optional[str]:
    """
    Die SEITE (pos/neg), wenn der Feldname sie selbst ausspricht.

    Nur Namen, die "prompt", "positive" oder "negative" tragen, sagen
    etwas aus - "text" oder "t5xxl" behaupten keine Seite. Entschieden
    wird wie ueberall am letzten Glied der Punktschreibweise.
    """
    letzt = name.lower().split(".")[-1]
    if "prompt" not in letzt and "positive" not in letzt and "negative" not in letzt:
        return None
    if "neg" in letzt or "uncond" in letzt:
        return "neg"
    return "pos"

#: A single string without whitespace made of identifier characters: that is
#: a file name, a model name or a choice value - not prose.
_EIN_WORT = re.compile(r"^[A-Za-z0-9_.\-/\\:]+$")


def _texte_mit_namen(prompt: Dict[str, Any], kid: str) -> List[Tuple[str, str]]:
    """
    ALLE Texte, die IN diesem Knoten stehen, mit ihrem FELDNAMEN - keine
    Suche ueber Verbindungen.

    Bewusst alle, nicht der erste: Flux fuehrt clip_l und t5xxl nebeneinander,
    SDXL text_g und text_l. Wer nur den ersten nimmt, laesst den zweiten
    lautlos verschwinden.

    Frueher musste ein Text ein Leerzeichen enthalten. Das schloss jede Sprache
    ohne Wortzwischenraum aus - und WANs mitgelieferter Negativ-Prompt ist
    chinesisch. Statt des Leerzeichens wird jetzt geprueft, ob die Zeichenkette
    wie EIN Bezeichner aussieht (Dateiname, Modellname, Auswahlwert). Der
    Feldname hat ohnehin schon aussortiert, was gar kein Textfeld ist - und
    ein Ein-Wort-Wert wie `prompt_mode: professional` faellt am Wert.
    """
    # The RECORDER is not part of the recorded workflow: the VALYDA node's
    # own switches ("Store_Prompt", "Prompt_Assignment") carry "prompt" in
    # their name and would otherwise stand in the protocol as "texts
    # without a role" (measured 08.08. on Pits Kling record).
    if _typ(prompt, kid).startswith("ValydaProtokoll"):
        return []
    raus: List[Tuple[str, str]] = []
    for name, wert in _eingaenge(prompt, kid).items():
        if not isinstance(wert, str):
            continue
        if not _textfeld(name):
            continue
        rein = wert.strip()
        if len(rein) < 8:
            continue
        if _EIN_WORT.match(rein):
            continue
        if rein.lower().endswith(_GEWICHT_ENDUNGEN):
            continue
        if re.search(r"\.(png|jpe?g|webp|mov|mp4|wav|mp3|safetensors|pth)$", rein, re.I):
            continue
        if rein not in [t for _, t in raus]:
            raus.append((name, rein))
    return raus


def _direkte_texte(prompt: Dict[str, Any], kid: str) -> List[str]:
    """Die Texte dieses Knotens ohne die Feldnamen - fuer Aufrufer von aussen."""
    return [t for _, t in _texte_mit_namen(prompt, kid)]


def _direkter_text(prompt: Dict[str, Any], kid: str) -> Optional[str]:
    """Der laengste Text dieses Knotens - fuer Aufrufer, die nur einen wollen."""
    texte = _direkte_texte(prompt, kid)
    return max(texte, key=len) if texte else None


# ---------------------------------------------------------------- parameters
#: Settings that belong to one sampler step.
_STELLGROESSEN = ("steps", "cfg", "sampler_name", "scheduler", "denoise",
                  "start_at_step", "end_at_step", "add_noise")

#: Inputs that feed a sampler its parts. With SamplerCustomAdvanced the
#: seed does not sit in the sampler but in the noise node before it; cfg
#: sits in the guider, the sampler name in the selector, steps in the schedule.
_ZULIEFERER = ("noise", "guider", "sampler", "sigmas")

#: Inputs carrying a latent image - that is how a compute step is recognised.
_LATENT_EINGAENGE = ("latent_image", "samples", "latent")

_JA = ("enable", "enabled", "true", "yes")
_NEIN = ("disable", "disabled", "false", "no")


def _ist_sampler_stufe(eing: Dict[str, Any]) -> bool:
    """
    Ein Rechenschritt, der etwas erzeugt.

    Zwei Merkmale, weil es zwei Bauarten gibt:

    1. Oertlich gerechnet: es liegt ein Latentbild an UND es gibt entweder eine
       Stellgroesse oder einen Zulieferer. Damit faellt VAEDecode heraus
       (Latentbild, aber nichts zu stellen) und ein blosser Zeitplan-Knoten
       ebenfalls (Stellgroesse, aber kein Latentbild).

    2. In der Ferne gerechnet: ein Cloud-Knoten (Gemini, ByteDance, Kling ...)
       kennt kein Latentbild, hat aber einen Seed und bekommt Bild oder Text
       hineingereicht. Der Seed ist dort genauso die Stellgroesse der Erzeugung.
       Verlangt wird mindestens EIN verdrahteter Eingang - sonst waere auch ein
       blosser Rausch-Knoten, der nur seinen Seed traegt, ein Rechenschritt.
    """
    hat_latent = any(k in eing for k in _LATENT_EINGAENGE)
    hat_stellgroesse = any(k in eing for k in _STELLGROESSEN)
    hat_zulieferer = any(k in eing for k in _ZULIEFERER)
    if hat_latent and (hat_stellgroesse or hat_zulieferer):
        return True

    hat_seed = any(k.lower() in _SEED_SCHLUESSEL for k in eing)
    hat_verdrahtung = any(_ist_verweis(w) for w in eing.values())
    return hat_seed and hat_verdrahtung


def _konstante(prompt: Dict[str, Any], wert: Any, tiefe: int = 0) -> Any:
    """
    Loest einen Verweis auf, WENN dahinter zweifelsfrei ein fester Wert steht.

    Aufgeloest wird nur, was eindeutig ist: ein Knoten, dessen einziger
    beweglicher Teil ein Wert ist (PrimitiveInt und Verwandte), oder ein reiner
    Durchreicher. Alles andere - Schalter, Rechner, Ausdruecke - bleibt
    unaufgeloest und liefert None. Ein geratener Wert waere schlimmer als keiner.
    """
    if not _ist_verweis(wert):
        return wert
    if tiefe > 4:
        return None
    eing = _eingaenge(prompt, str(wert[0]))
    if not eing:
        return None
    feste = {n: w for n, w in eing.items() if not _ist_verweis(w)}
    verweise = {n: w for n, w in eing.items() if _ist_verweis(w)}

    if len(feste) == 1 and not verweise:
        return list(feste.values())[0]
    if not feste and len(verweise) == 1:                 # pass-through
        return _konstante(prompt, list(verweise.values())[0], tiefe + 1)
    if "value" in feste and not verweise:
        return feste["value"]
    return None


def _stufe_einsammeln(prompt: Dict[str, Any], kid: str,
                      werte: Dict[str, Any], offen: List[str],
                      gesehen: Set[str], tiefe: int = 0) -> None:
    """Stellgroessen dieses Schritts und seiner unmittelbaren Zulieferer."""
    if kid in gesehen or tiefe > 3:
        return
    gesehen.add(kid)
    eing = _eingaenge(prompt, kid)

    for name, roh in eing.items():
        n = name.lower()
        if n in _SEED_SCHLUESSEL:
            fest = _konstante(prompt, roh)
            if fest is not None:
                werte.setdefault("seed", fest)
            elif "seed" not in werte and "seed" not in offen:
                offen.append("seed")
        elif n in ("steps", "cfg", "sampler_name", "scheduler", "denoise",
                   "start_at_step", "end_at_step", "add_noise"):
            fest = _konstante(prompt, roh)
            if fest is not None:
                werte.setdefault(n, fest)
            elif n not in werte and n not in offen:
                offen.append(n)

    # Take suppliers along, but never run into another compute step
    for name, roh in eing.items():
        if name.lower() not in _ZULIEFERER or not _ist_verweis(roh):
            continue
        quelle = str(roh[0])
        if _ist_sampler_stufe(_eingaenge(prompt, quelle)):
            continue
        _stufe_einsammeln(prompt, quelle, werte, offen, gesehen, tiefe + 1)


def sampler_stufen(prompt: Dict[str, Any], vorfahren: Iterable[str]) -> List[Dict[str, Any]]:
    """
    Die Rechenschritte des Ablaufs, in Ausfuehrungsreihenfolge.

    Je Schritt steht dabei, ob er Rauschen HINZUFUEGT - denn nur ein solcher
    erzeugt. Der zweistufige Aufbau (hoher und niedriger Rauschanteil), wie ihn
    WAN 2.2 verwendet, hat zwei Schritte, von denen genau einer erzeugt. Wer
    beide in einen Topf wirft, schreibt den Seed des falschen ins Protokoll.
    """
    vorfahren = list(vorfahren)
    stufen: List[Dict[str, Any]] = []

    for kid in vorfahren:
        eing = _eingaenge(prompt, kid)
        if not _ist_sampler_stufe(eing):
            continue
        werte: Dict[str, Any] = {}
        offen: List[str] = []
        _stufe_einsammeln(prompt, kid, werte, offen, set())

        # Does this step add noise?
        roh = werte.get("add_noise")
        erzeugt: Optional[bool]
        if roh is None:
            # No such switch at all -> simple sampler that always adds noise.
            # Switch present but unreadable -> unknown, do not guess.
            erzeugt = None if "add_noise" in offen else True
        elif isinstance(roh, bool):
            erzeugt = roh
        elif isinstance(roh, str):
            r = roh.strip().lower()
            erzeugt = True if r in _JA else False if r in _NEIN else None
        else:
            erzeugt = None

        stufen.append({
            "knoten": kid,
            "typ": _typ(prompt, kid),
            "erzeugt": erzeugt,
            "werte": werte,
            "nicht_bestimmbar": offen,
            "_tiefe": len(alle_vorfahren(prompt, kid)),
        })

    # Order: fewer ancestors means it runs earlier.
    stufen.sort(key=lambda s: (s["_tiefe"], str(s["knoten"])))
    for s in stufen:
        s.pop("_tiefe", None)
    return stufen


#: Settings that may only come from the generating step.
_NUR_VOM_ERZEUGER = ("seed", "steps", "cfg", "sampler_name", "scheduler")


def parameter(prompt: Dict[str, Any], vorfahren: Iterable[str]) -> Dict[str, Any]:
    """
    Sammelt die Stellgroessen.

    Seed, Schritte, CFG, Sampler und Zeitplan kommen AUSSCHLIESSLICH vom
    erzeugenden Schritt. Gibt es mehrere davon oder laesst er sich nicht
    bestimmen, bleiben diese Felder hier leer - die Einzelheiten stehen dann in
    `sampler_stufen()` und werden im Dokument stufenweise ausgewiesen.

    Bildmasse und Rauschwert werden weiterhin ueber den ganzen Ablauf gesammelt;
    am Rauschwert haengt die Herkunfts-Einstufung.
    """
    vorfahren = list(vorfahren)
    werte: Dict[str, Any] = {}
    rausch: Optional[float] = None

    for kid in vorfahren:
        for name, wert in _eingaenge(prompt, kid).items():
            if _ist_verweis(wert):
                continue
            n = name.lower()
            if n == "denoise" and isinstance(wert, (int, float)):
                rausch = float(wert) if rausch is None else min(rausch, float(wert))
            elif n in ("width", "height", "length", "batch_size", "frame_rate",
                       "fps"):
                werte.setdefault(n, wert)
            # Cloud nodes state their image size not in pixels but as tier and
            # format (720p, 16:9) - and carry them in dotted notation under the
            # model ("model.resolution"). Without these two, a Kling run would
            # leave no resolution in the protocol (02.08.). Recorded under the
            # last segment.
            elif n.split(".")[-1] in ("aspect_ratio", "resolution"):
                werte.setdefault(n.split(".")[-1], wert)

    erzeuger = [s for s in sampler_stufen(prompt, vorfahren) if s["erzeugt"] is True]
    if len(erzeuger) == 1:
        for schluessel in _NUR_VOM_ERZEUGER:
            wert = erzeuger[0]["werte"].get(schluessel)
            if wert is not None:
                werte[schluessel] = wert

    if rausch is not None:
        werte["denoise"] = rausch
    return werte


# ---------------------------------------------------------------- the derivation
#: Below this denoise value a change counts as retouching, not as hybrid.
RETUSCHE_GRENZE = 0.40

STATUS_VOLL = "vollgeneriert"
STATUS_HYBRID = "hybrid"
STATUS_RETUSCHE = "retusche"
STATUS_UNBEKANNT = "unbekannt"

STATUS_TEXT = {
    STATUS_VOLL: ("100 % KI-generiert", "Fully AI-generated"),
    STATUS_HYBRID: ("Realaufnahme modifiziert (Hybridform)", "Partially AI-modified"),
    STATUS_RETUSCHE: ("Realaufnahme retuschiert", "AI-retouched"),
    STATUS_UNBEKANNT: ("nicht feststellbar", "not determinable"),
}


def herkunft(prompt: Dict[str, Any], eigene_id: str) -> Dict[str, Any]:
    """
    Leitet ab, ob das Ergebnis vollgeneriert, hybrid oder retuschiert ist.

    Regel:
      Bildquelle im Ablauf   -> hybrid, bei geringem Rauschwert retusche
      keine Bildquelle       -> vollgeneriert
      Ablauf nicht lesbar    -> unbekannt   (sperrender Vorgabewert)
    """
    if not prompt or str(eigene_id) not in prompt:
        return {"status": STATUS_UNBEKANNT, "ableitung": "ablauf_nicht_lesbar",
                "grad": None, "begruendung": "Der Ablauf konnte nicht gelesen werden.",
                "begruendung_en": "The workflow could not be read.",
                "quellen": [], "vorfahren": []}

    vorfahren = alle_vorfahren(prompt, eigene_id)
    quellen = bildquellen(prompt, vorfahren)
    par = parameter(prompt, vorfahren)
    grad = par.get("denoise")

    if quellen:
        if grad is not None and grad <= RETUSCHE_GRENZE:
            status = STATUS_RETUSCHE
            grund = ("Bildquelle am erzeugenden Schritt erkannt, Rauschwert %.2f "
                     "unterhalb der Retusche-Grenze %.2f." % (grad, RETUSCHE_GRENZE))
            grund_en = ("Image input detected at the generating step, denoise %.2f "
                        "below the retouch threshold %.2f." % (grad, RETUSCHE_GRENZE))
        else:
            status = STATUS_HYBRID
            grund = "Bildquelle am erzeugenden Schritt erkannt."
            grund_en = "Image input detected at the generating step."
            if grad is not None:
                grund += " Rauschwert %.2f." % grad
                grund_en += " Denoise %.2f." % grad
    else:
        status = STATUS_VOLL
        grund = "Keine Bildquelle im Ablauf - reine Texteingabe."
        grund_en = "No image input in the workflow - text only."

    return {"status": status, "ableitung": "ablauf", "grad": grad,
            "begruendung": grund, "begruendung_en": grund_en,
            "quellen": quellen, "vorfahren": vorfahren}


def werkzeugart(status: str, quellen: List[Dict[str, Any]], medium: str = "bild") -> str:
    """
    Text-zu-Bild, Bild-zu-Video, Video-zu-Video, Ton - fuer die Zeile 'Werkzeug'.

    Die AUSGABE-Seite kommt aus `medium`, die EINGABE-Seite aus den gefundenen Quellen.
    """
    if medium == "ton":
        return "Text-zu-Ton" if status == STATUS_VOLL else "Ton-zu-Ton (Stimme/Klang)"

    ziel = "Video" if medium == "video" else "Bild"
    if status == STATUS_VOLL:
        return "Text-zu-%s" % ziel

    quelle_video = any("video" in (q.get("typ", "") or "").lower()
                       or re.search(r"\.(mov|mp4|mxf|avi|mkv|webm)$", (q.get("datei") or ""), re.I)
                       for q in quellen)
    return "%s-zu-%s" % ("Video" if quelle_video else "Bild", ziel)


def modifikatoren(prompt: Dict[str, Any], vorfahren: Iterable[str]) -> List[str]:
    """Angewandte Zusatzverfahren in Klartext - fuer die Zeile 'Modifikatoren'."""
    raus: List[str] = []
    for kid in vorfahren:
        typ = _typ(prompt, kid)
        tl = typ.lower()
        for merkmal, klartext in (
            ("lora", "LoRA"), ("controlnet", "ControlNet"), ("control_net", "ControlNet"),
            ("ipadapter", "Bildfuehrung (IPAdapter)"), ("upscale", "Hochrechnung"),
            ("esrgan", "Hochrechnung (ESRGAN)"), ("mask", "Maskierung"),
            ("inpaint", "Inpainting"), ("outpaint", "Outpainting"),
            ("colormatch", "Farbangleichung"), ("interpolat", "Zwischenbildberechnung"),
            ("gfpgan", "Gesichtsverbesserung"), ("codeformer", "Gesichtsverbesserung"),
            ("faceswap", "Gesichtstausch"), ("reactor", "Gesichtstausch"),
        ):
            if merkmal in tl and klartext not in raus:
                raus.append(klartext)
    return raus
