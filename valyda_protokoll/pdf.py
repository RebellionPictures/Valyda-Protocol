# -*- coding: utf-8 -*-
"""
Erzeugt die Dokumente. EINZIGE Stelle im ganzen Paket, die ein PDF schreibt.

Zwei Fassungen aus derselben Akte:
  fassung_k  - Creator, eine Seite, englisch, ohne Prompt (EU AI Act, Art. 50)
  fassung_s  - Sender, ausfuehrlich, deutsch, mit Prompt (ARD/Degeto, ZDF, ORF, ARTE)

Markenfuehrung: jedes Dokument traegt oben den VALYDA-Balken mit dem Emblem,
auf jeder Seite eine Kopfzeile und in der Fusszeile den Rechteinhaber.

DIE LAYOUT-REGEL (Pit, 01.08.2026 - gilt für JEDES PDF aus diesem Paket):

  1. Nie drawString mit ungemessenem Text. Vor jeder Ausgabe die Breite mit
     stringWidth bestimmen und gegen den verfügbaren Platz pruefen.
  2. Passt es nicht, wird umbrochen, nicht abgeschnitten. In Tabellenzellen
     gehoeren Paragraph-Objekte mit Umbruch, keine gezeichneten Zeichenketten.
     Die Zellhoehe waechst mit dem Inhalt.
  3. Zwei Textstuecke in einer Zeile (fett + normal) werden aneinandergesetzt,
     indem die Breite des ersten gemessen wird - nie mit geschaetzten
     Abstaenden.
  4. Kopf- und Fusszeile: linker und rechter Block duerfen sich nie beruehren.
     Vorher messen, sonst den linken kuerzen.
  5. Kein Text ausserhalb des Satzspiegels. pruefung/randpruefung.py misst
     Überläufe UND Überlappungen und muss für jedes erzeugte Dokument
     0 und 0 melden.

Der Anlass war ein Entwurf mit überlappenden Schriften: Text an feste Stellen
gezeichnet, ohne vorher seine Breite zu messen.
"""

from __future__ import annotations

import io
import json
import os
import time
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Flowable, Frame,
                                Image as PdfBild,
                                KeepTogether, PageBreak, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

from .graph import (NACHWEIS_ABLAUF, NACHWEIS_DATEI, NACHWEIS_UNBEKANNT,
                    ROLLE_OFFEN, STATUS_TEXT, STATUS_UNBEKANNT, STATUS_VOLL)

# ---------------------------------------------------------------- the brand
DUNKEL = colors.HexColor("#14161A")
GRUEN = colors.HexColor("#B5D93A")
TINTE = colors.HexColor("#111111")
GRAU = colors.HexColor("#666666")
HELL = colors.HexColor("#EFEFEF")
LINIE = colors.HexColor("#B8B8B8")
SAND = colors.HexColor("#FDF3E3")
SANDR = colors.HexColor("#C8892B")

SATZBREITE = 174 * mm
# Der Rechteinhaber der SOFTWARE, wie ihn die LICENSE nennt (MIT,
# "Copyright (c) 2026 Peter Nix") - und wie ihn der abgenommene
# Entwurf-3 in der Fusszeile fuehrt ("© 2026 Peter Nix"). Vorher stand
# hier die Firma; Fusszeile und Lizenz nannten damit zwei verschiedene
# Inhaber.
RECHTEINHABER = "Peter Nix"
COPYRIGHT_JAHR = "2026"
VERSION = "2.3"

_LOGO_MITTE = None
_LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "assets", "valyda_logo.png")


# ---------------------------------------------------------------- cell log
# Text against cell (Pit, 01.08.): do not guess along lines in the
# finished PDF but write down while building where every cell lies -
# the cell borders are known here anyway, we draw them ourselves.
# pruefung/randpruefung.py then checks each word lies ENTIRELY in its cell.
#
# Enabled only in the test environment (VALYDA_ZELLPRUEFUNG=1): then a
# <name>.pdf.zellen.json lies next to every PDF. User runs write nothing.
# Coordinates: points, counted from the SHEET BOTTOM (as the canvas returns them).
_ZELLEN: List[Dict[str, float]] = []


def _zellpruefung_an() -> bool:
    return bool(os.environ.get("VALYDA_ZELLPRUEFUNG"))


class Tabelle(Table):
    """Table, die beim Zeichnen die absolute Lage jeder Zelle mitschreibt."""

    def _drawCell(self, cellval, cellstyle, pos, size):
        if _zellpruefung_an():
            try:
                x0, y0 = self.canv.absolutePosition(pos[0], pos[1])
                x1, y1 = self.canv.absolutePosition(pos[0] + size[0],
                                                    pos[1] + size[1])
                _ZELLEN.append({"seite": self.canv.getPageNumber(),
                                "x0": round(min(x0, x1), 2),
                                "x1": round(max(x0, x1), 2),
                                "y0": round(min(y0, y1), 2),
                                "y1": round(max(y0, y1), 2)})
            except Exception:
                pass                      # the log must never topple the build
        Table._drawCell(self, cellval, cellstyle, pos, size)


def _zellen_schreiben(pfad: str) -> None:
    """Nach doc.build(): die Mitschrift neben das PDF legen (nur Pruefumgebung)."""
    if _zellpruefung_an() and _ZELLEN:
        with open(pfad + ".zellen.json", "w", encoding="utf-8") as f:
            json.dump(_ZELLEN, f)
    _ZELLEN.clear()


def _st(name, **kw):
    b = dict(fontName="Helvetica", fontSize=8.6, leading=11.6, textColor=TINTE)
    b.update(kw)
    return ParagraphStyle(name, **b)


S_TITEL = _st("t", fontName="Helvetica-Bold", fontSize=16, leading=19)
S_SUB = _st("s", fontSize=9.3, leading=12.6, textColor=GRAU)
S_TXT = _st("x", fontSize=8.7, leading=12)
S_LAB = _st("l", fontSize=7.3, leading=9.4, textColor=GRAU)
S_WERT = _st("w", fontSize=8.5, leading=11)
S_TH = _st("th", fontName="Helvetica-Bold", fontSize=7.6, leading=9.6)
S_TD = _st("td", fontSize=7.7, leading=9.8)
S_MONO = _st("m", fontName="Courier", fontSize=7.4, leading=9.8)
S_KLEIN = _st("k", fontSize=7.2, leading=9.4, textColor=GRAU)
S_H2 = _st("h", fontName="Helvetica-Bold", fontSize=9.6, leading=12)
#: like S_H2 but stays together with the following element - a table
#: heading alone at the foot of a page looks like a mistake.
S_H2_ZUSAMMEN = _st("hz", fontName="Helvetica-Bold", fontSize=9.6, leading=12,
                    keepWithNext=1)


def _logo_mitte() -> float:
    """
    Anteil (von oben), auf dem die optische Mitte des Emblems liegt.

    Geometrisch liegt sie bei 0,5 - die Schriftmasse sitzt aber oben, deshalb
    wirkt ein geometrisch zentriertes Emblem nach oben verschoben. Gewichtet
    aus Flaechenmitte und Massenschwerpunkt.
    """
    global _LOGO_MITTE
    if _LOGO_MITTE is not None:
        return _LOGO_MITTE
    _LOGO_MITTE = 0.5
    try:
        from PIL import Image as PilBild
        import numpy as np
        with PilBild.open(_LOGO) as b:
            a = np.array(b.convert("RGBA"))[..., 3].astype("float32")
        zeilen = np.arange(a.shape[0])[:, None]
        schwer = float((a * zeilen).sum() / max(a.sum(), 1.0)) / a.shape[0]
        sichtbar = np.where(a.max(axis=1) > 20)[0]
        flaeche = ((sichtbar.min() + sichtbar.max()) / 2.0) / a.shape[0]
        _LOGO_MITTE = 0.85 * schwer + 0.15 * flaeche
    except Exception:
        pass
    return _LOGO_MITTE


#: The header-bar labels in all three document versions: (version bold,
#: version small, English only). The Creator has the widest version
#: block, the bilingual broadcast the longest legal line - both limit
#: the emblem, each in its own way.
_KOPF_FASSUNGEN = (
    ("Creator", "for creators publishing in the EU", True),
    ("Broadcast", "broadcast delivery", False),
    ("Broadcast", "broadcast delivery", True),
)

#: The legal lines right of the hairline - three lines, on the purely
#: English sheet only the last one (language rule 01.08.).
_KOPF_ZEILEN_DE = ("KI-Protokoll", "Artikel 50 KI-Verordnung (EU) 2024/1689",
                   "Article 50 Regulation (EU) 2024/1689")
_KOPF_ZEILEN_EN = ("Article 50 Regulation (EU) 2024/1689",)

#: The set wordmark in the header bar.
_KOPF_MARKE, _KOPF_SPERRUNG, _KOPF_GRAD = "VALYDA AI PROTOCOL", 2.2, 15

_EMBLEM_BREITE = None


def _emblem_breite() -> float:
    """
    Die Breite des Emblems im Kopfbalken - in ALLEN Fassungen dieselbe.

    Pit-Grundsatz vom 29.07.: das abgegebene Papier sieht immer gleich aus.
    Also bekommt der Balken nicht je Dokument eine eigene Emblembreite,
    sondern die groesste, die in JEDE der drei Fassungen passt, ohne dass
    - die Wortmarke umbricht oder verkleinert werden muss,
    - der Fassungsblock rechts angetastet wird,
    - eine Rechtszeile in den Fassungsblock laeuft.
    Gerechnet statt eingetragen: aendert sich ein Wortlaut, zieht die
    Breite von selbst nach, und Layout-Regel 1 bleibt gewahrt.
    """
    global _EMBLEM_BREITE
    if _EMBLEM_BREITE is not None:
        return _EMBLEM_BREITE
    from reportlab.pdfbase.pdfmetrics import stringWidth
    rand = SATZBREITE - 10 * mm
    marke = (stringWidth(_KOPF_MARKE, "Helvetica-Bold", _KOPF_GRAD)
             + _KOPF_SPERRUNG * len(_KOPF_MARKE))
    breiten = []
    for fassung_de, fassung_en, nur_englisch in _KOPF_FASSUNGEN:
        zeilen = _KOPF_ZEILEN_EN if nur_englisch else _KOPF_ZEILEN_DE
        legal = max(stringWidth(z, "Helvetica", 7.1) for z in zeilen)
        fass = max(stringWidth(fassung_de.upper(), "Helvetica-Bold", 7.4),
                   stringWidth(fassung_en, "Helvetica", 7.1))
        # After the emblem come a 10 mm gap, the hairline and 8 mm - plus the
        # left margin of 10 mm: 28 mm next to the emblem in total.
        breiten.append(min(rand - 4 * mm - marke - 28 * mm,
                           rand - 6 * mm - fass - legal - 28 * mm))
    _EMBLEM_BREITE = max(10 * mm, min(breiten))
    return _EMBLEM_BREITE


def _gesperrt(c, x, y, text, schrift, groesse, farbe, sperrung):
    """Text mit Sperrung zeichnen - Canvas kennt setCharSpace nicht, Textobjekt schon."""
    t = c.beginText(x, y)
    t.setFont(schrift, groesse)
    t.setFillColor(farbe)
    t.setCharSpace(sperrung)
    t.textOut(text)
    t.setCharSpace(0)          # IMPORTANT: otherwise the letter spacing bleeds
    c.drawText(t)              # into all further text on the page and everything overflows
    return c.stringWidth(text, schrift, groesse) + sperrung * len(text)


class Kopfbalken(Flowable):
    """
    Der Kopf des Dokuments.

    Das Emblem steht für sich allein auf dunklem Grund, davon getrennt durch
    eine gruene Haarlinie der Schriftzug VALYDA AI PROTOCOL in ruhiger
    Versalschrift, darunter klein KI-Protokoll (Namensregel Pit, 01.08.).
    """

    def __init__(self, fassung_de: str, fassung_en: str, breite: float = SATZBREITE,
                 hoehe: float = 32 * mm, nur_englisch: bool = False):
        Flowable.__init__(self)
        self.width = breite
        self.height = hoehe
        self.fassung_de = fassung_de
        self.fassung_en = fassung_en
        # The Creator sheet is English WITHOUT EXCEPTION (Pit, 01.08.):
        # "KI-Protokoll" and the German regulation line are dropped there.
        self.nur_englisch = nur_englisch

    def draw(self):
        c = self.canv
        b, h = self.width, self.height
        mitte = h / 2.0

        c.setFillColor(DUNKEL)
        c.rect(0, 0, b, h, stroke=0, fill=1)

        # --- emblem, standing alone and OPTICALLY centred.
        #     The width comes from _emblem_breite() and is the same in all
        #     three versions; the hairline moves right accordingly
        #     (Pit, 02.08. - variant B).
        x = 10 * mm
        breite_emblem = _emblem_breite()
        if os.path.isfile(_LOGO):
            try:
                from PIL import Image as PilBild
                with PilBild.open(_LOGO) as bild:
                    verh = bild.height / float(bild.width)
                lw = breite_emblem
                lh = lw * verh
                y = mitte - (1.0 - _logo_mitte()) * lh
                y = max(2.5 * mm, min(y, h - lh - 2.5 * mm))
                c.drawImage(_LOGO, x, y, width=lw, height=lh, mask="auto")
                x += lw + 10 * mm
            except Exception:
                x += 5 * mm
        else:
            c.setFillColor(GRUEN)
            c.setFont("Helvetica-Bold", 16)
            c.drawString(x, mitte - 5, "VALYDA")
            x += breite_emblem

        # --- green hairline as separation
        c.setStrokeColor(GRUEN)
        c.setLineWidth(0.8)
        c.line(x, 7 * mm, x, h - 7 * mm)
        x += 8 * mm

        # --- type block, set as a group around the band centre.
        #     The wordmark is measured BEFORE drawing (layout rule 1); if
        #     space is tighter than expected the type shrinks instead of
        #     overrunning on the right.
        rand = b - 10 * mm
        marke, sperrung, grad = _KOPF_MARKE, _KOPF_SPERRUNG, _KOPF_GRAD
        while grad > 9 and (c.stringWidth(marke, "Helvetica-Bold", grad)
                            + sperrung * len(marke)) > rand - x - 4 * mm:
            grad -= 1
        _gesperrt(c, x, mitte + 3.4 * mm, marke,
                  "Helvetica-Bold", grad, colors.white, sperrung)

        # below it, small, the German name, then the legal reference in both
        # languages - three lines with equal spacing. On the purely English
        # Creator sheet only the English regulation line remains.
        c.setFillColor(colors.HexColor("#9AA3AE"))
        c.setFont("Helvetica", 7.1)
        texte = _KOPF_ZEILEN_EN if self.nur_englisch else _KOPF_ZEILEN_DE
        hoehen = ((mitte - 7.6 * mm,) if self.nur_englisch
                  else (mitte - 1.2 * mm, mitte - 4.4 * mm, mitte - 7.6 * mm))
        zeilen = list(zip(hoehen, texte))
        for y, text in zeilen:
            c.drawString(x, y, text)

        # --- version on the right, on the two sublines. The safety gap is
        #     checked: if it does not fit, we shorten instead of overprinting.
        platz = rand - (x + max(c.stringWidth(text, "Helvetica", 7.1)
                                for _, text in zeilen)) - 6 * mm
        de = self.fassung_de.upper()
        en = self.fassung_en
        while de and c.stringWidth(de, "Helvetica-Bold", 7.4) > platz:
            de = de[:-1]
        while en and c.stringWidth(en, "Helvetica", 7.1) > platz:
            en = en[:-1]
        c.setFillColor(GRUEN)
        c.setFont("Helvetica-Bold", 7.4)
        c.drawRightString(rand, mitte - 4.4 * mm, de)
        c.setFillColor(colors.HexColor("#9AA3AE"))
        c.setFont("Helvetica", 7.1)
        c.drawRightString(rand, mitte - 7.6 * mm, en)

        # --- closing line
        c.setStrokeColor(GRUEN)
        c.setLineWidth(2)
        c.line(0, 0, b, 0)


class Titelzeile(Flowable):
    """Grosse Dokumentzeile unter dem Kopf - gibt dem Blatt einen Anfang."""

    def __init__(self, deutsch: str, englisch: str, breite: float = SATZBREITE):
        Flowable.__init__(self)
        self.width = breite
        self.height = 15 * mm
        self.deutsch = deutsch
        self.englisch = englisch

    def draw(self):
        c = self.canv
        c.setFillColor(TINTE)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(0, 8.4 * mm, self.deutsch)
        c.setFillColor(GRAU)
        c.setFont("Helvetica", 9)
        c.drawString(0, 3.4 * mm, self.englisch)
        c.setStrokeColor(colors.HexColor("#DDDDDD"))
        c.setLineWidth(0.5)
        c.line(0, 0.8 * mm, self.width, 0.8 * mm)


# Kopf- und Fusszeile der neuen Gestalt: _rahmen_neu/_dok_neu (weiter
# unten). Die alten _rahmen/_dok sind mit Entwurf-3 entfallen - der
# Erklaerungsbogen behaelt sein eigenes Blatt (_bogen_rahmen).


# ---------------------------------------------------------------- building blocks


# ---------------------------------------------------------------- language
# ONE source for both languages. The mode decides what gets printed:
#   "de"    German only
#   "en"    English only
#   "beide" German, English small below      (the declaration sheet)
#   "en+de" English, small grey German below (document default)
#
# Since 01.08. the language is fixed, there is no choice field any more:
# Creator English only; broadcast and project documents English with the
# small German line. The only exception is the declaration sheet
# (section 4) - German on top and English small below, because its
# wording is a quotation from the broadcaster's annex: whoever signs a
# translation signs something else.
SPRACHEN = ("de", "en", "beide", "en+de")


def _sp(modus: str, de: str, en: str, klein: bool = True) -> str:
    if modus == "en":
        return en
    if modus == "beide" and en and en != de:
        if klein:
            return '%s<br/><font size="6.6" color="#777777">%s</font>' % (de, en)
        return "%s \u00b7 %s" % (de, en)
    if modus == "en+de":
        if not de or de == en:
            return en
        if klein:
            return '%s<br/><font size="6.6" color="#777777">%s</font>' % (en, de)
        return "%s \u00b7 %s" % (en, de)
    return de


def _status_farbe(status: str):
    # Blau- und Grautoene statt der frueheren Oliv-Gruentoene: die
    # Farbregel des Entwurf-3 laesst Gruen nur zweimal auf dem Blatt zu
    # (Kopfband-Akzent, Pillen-Kontur). Die Farbe traegt ohnehin nie
    # allein - Haken und Beschriftung stehen daneben (Pit, 02.08.).
    return {"vollgeneriert": colors.HexColor("#1F4E79"),
            "hybrid": colors.HexColor("#46627A"),
            "retusche": colors.HexColor("#6E7B8A")}.get(status, colors.HexColor("#8A8A8A"))


def _kontaktbogen(akten: List[Dict[str, Any]], ordner: str, spalten: int = 4,
                  zweisprachig: bool = True) -> List[Any]:
    """
    Bildübersicht über alle Einstellungen eines Projekts.

    Bei einem langen Projekt ist die Wiedererkennung über das Bild schneller als
    über jeden Dateinamen. Deshalb steht der Kontaktbogen VOR der Tabelle.
    """
    zellbreite = SATZBREITE / spalten
    bildbreite = zellbreite - 4 * mm
    zeilen: List[List[Any]] = []
    aktuell: List[Any] = []

    for i, a in enumerate(akten, 1):
        erg = a.get("ergebnis") or {}
        eins = a.get("einsatz") or {}
        herk = a.get("herkunft") or {}
        status = herk.get("status") or "unbekannt"

        bild = _bild((erg.get("vorschau") or {}).get("datei"), ordner, bildbreite)
        if bild is None:
            bild = Tabelle([[Paragraph("<i>keine Vorschau</i>", S_KLEIN)]],
                         colWidths=[bildbreite], rowHeights=[bildbreite * 0.5])
            bild.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F2F2")),
                                      ("BOX", (0, 0), (-1, -1), 0.4, LINIE),
                                      ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                      ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))

        marke = Tabelle([[""]], colWidths=[bildbreite], rowHeights=[1.6 * mm])
        marke.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _status_farbe(status))]))

        # Caption: if the timecode is missing it is dropped rather than
        # claiming a blank - for a caption that is the right one of the two
        # states.
        kopf = Paragraph(" ".join(t for t in ("<b>#%d</b>" % i,
                                              eins.get("timecode_start")) if t), S_TD)
        bezeichner = (eins.get("szene") or erg.get("datei") or "")[:58]
        name = Paragraph(bezeichner or "<i>%s</i>" % _fehlt(), S_KLEIN)

        zelle = Tabelle([[bild], [marke], [kopf], [name]], colWidths=[bildbreite])
        zelle.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                   ("TOPPADDING", (0, 0), (0, 0), 0),
                                   ("TOPPADDING", (0, 1), (0, 1), 2),
                                   ("TOPPADDING", (0, 2), (0, 3), 2),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        # Die Kachel steht mittig in ihrer Spalte (Pit, 09.08.).
        zelle.hAlign = "CENTER"
        aktuell.append(zelle)
        if len(aktuell) == spalten:
            zeilen.append(aktuell)
            aktuell = []

    if aktuell:
        while len(aktuell) < spalten:
            aktuell.append("")
        zeilen.append(aktuell)

    if not zeilen:
        return []

    t = Tabelle(zeilen, colWidths=[zellbreite] * spalten)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                           ("TOPPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))

    # Boxes instead of a colour legend (Pit, 02.08.). In black and white,
    # colour carries nothing - it must never be the only carrier of a
    # statement. The tick is drawn, the colour patch merely stands next
    # to it. And what gets listed is what OCCURS, not what would be
    # selectable: a complete list of choices says nothing about this
    # document.
    sp_l = (lambda de, en: _sp("en+de" if zweisprachig else "en", de, en, False))
    vorhanden = {(a.get("herkunft") or {}).get("status") or STATUS_UNBEKANNT
                 for a in akten}
    _namen = ((STATUS_VOLL, "vollst\u00e4ndig generiert", "fully generated"),
              ("hybrid", "Realaufnahme ver\u00e4ndert", "real footage modified"),
              ("retusche", "retuschiert", "retouched"),
              (STATUS_UNBEKANNT, "nicht feststellbar", "not determinable"))
    felder = []
    for schluessel, de, en in _namen:
        if schluessel not in vorhanden:
            continue
        farbe = Tabelle([[""]], colWidths=[3.4 * mm], rowHeights=[3.4 * mm])
        farbe.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1),
                                    _status_farbe(schluessel)),
                                   ("BOX", (0, 0), (-1, -1), 0.3, LINIE)]))
        felder += [_kaestchen(True), farbe,
                   Paragraph(sp_l(de, en), S_KLEIN)]
    if not felder:
        return [t]
    breiten = []
    for i in range(len(felder) // 3):
        breiten += [5 * mm, 5 * mm, (SATZBREITE - 10 * mm * (len(felder) // 3))
                    / (len(felder) // 3)]
    legende = Tabelle([felder], colWidths=breiten)
    legende.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                 ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                                 ("TOPPADDING", (0, 0), (-1, -1), 0),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return [t, Spacer(1, 1 * mm), legende]


def _felder(zeilen, breiten=(34 * mm, 140 * mm)) -> Table:
    # The value may also be a finished element (the model table in the
    # evidence section has one). The label column on the left stays text.
    t = Tabelle([[Paragraph(a, S_LAB),
                  b if hasattr(b, "wrap") else Paragraph(b, S_WERT)]
                 for a, b in zeilen],
              colWidths=breiten)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _kasten(inhalt, fuell=colors.HexColor("#F7F7F7"), rand=LINIE, pad=6, breite=SATZBREITE) -> Table:
    t = Tabelle([[inhalt]], colWidths=[breite])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fuell),
                           ("BOX", (0, 0), (-1, -1), 0.5, rand),
                           ("LEFTPADDING", (0, 0), (-1, -1), pad),
                           ("RIGHTPADDING", (0, 0), (-1, -1), pad),
                           ("TOPPADDING", (0, 0), (-1, -1), pad),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), pad)]))
    return t


class Kaestchen(Flowable):
    """
    Ankreuzfeld mit einem GEZEICHNETEN Haken.

    Nicht als Schriftzeichen: die Haken-Glyphe wird je nach Anzeigeprogramm
    unterschiedlich abgebildet und kam als schwarzes Quadrat heraus. Zwei Linien
    sind überall dasselbe.
    """

    def __init__(self, gesetzt: bool, kante: float = 3.8 * mm, farbe=None):
        Flowable.__init__(self)
        self.gesetzt = bool(gesetzt)
        self.width = kante
        self.height = kante
        # On a dark background ink would be invisible - white is drawn
        # there. A tick nobody can see is not a tick.
        self.farbe = farbe or TINTE

    def draw(self):
        c = self.canv
        k = self.width
        c.setStrokeColor(self.farbe)
        c.setLineWidth(0.7)
        c.rect(0, 0, k, k, stroke=1, fill=0)
        if not self.gesetzt:
            return
        # classic tick: short downstroke, long upstroke, slightly past the edge
        c.setLineWidth(1.0)
        c.setLineCap(1)
        c.setLineJoin(1)
        pfad = c.beginPath()
        pfad.moveTo(0.17 * k, 0.55 * k)
        pfad.lineTo(0.41 * k, 0.24 * k)
        pfad.lineTo(0.92 * k, 0.86 * k)
        c.drawPath(pfad, stroke=1, fill=0)


def _kaestchen(gesetzt: bool, kante: float = 3.8 * mm, farbe=None) -> Kaestchen:
    return Kaestchen(gesetzt, kante, farbe)


def _bild(pfad: Optional[str], ordner: str, breite: float) -> Optional[PdfBild]:
    if not pfad:
        return None
    voll = pfad if os.path.isabs(pfad) else os.path.join(ordner, pfad)
    if not os.path.isfile(voll):
        return None
    try:
        from PIL import Image as PilBild
        with PilBild.open(voll) as b:
            verh = b.height / float(b.width)
        bild = PdfBild(voll, width=breite, height=breite * verh)
        # In jedem breiteren Rahmen mittig, nicht links angeklebt (Pit, 09.08.).
        bild.hAlign = "CENTER"
        return bild
    except Exception:
        return None


def _fehlt(sp=None, gemessen: bool = False) -> str:
    """
    Was an der Stelle eines fehlenden Wertes steht.

    Ein Gedankenstrich sagt zweierlei zugleich und damit nichts. Es gibt
    genau zwei Zustaende, und sie werden ausgeschrieben (Pit, 02.08.):

      "nicht angegeben"  niemand hat es gesagt - die Angabe fehlt
      "keine"            das Werkzeug hat nachgesehen und nichts gefunden

    `sp` ist die Sprachfunktion des Dokuments; ohne sie (Creator-Blatt)
    steht nur Englisch. Wo auch das zu viel waere, faellt die ZEILE weg -
    dafuer gibt es diese Funktion nicht.
    """
    de, en = ("keine", "none") if gemessen else ("nicht angegeben", "not specified")
    return sp(de, en, klein=False) if sp else en


#: These values of `herkunft.ableitung` prove the graph was read.
#: "ablauf_nicht_lesbar" does not, "hand" neither - there was no
#: graph at all there. Old records carry None and count as open.
_GELESEN = ("ablauf", "ablauf + Angabe des Herstellers")


def zitiert_anlage_13(auftraggeber: str) -> bool:
    """
    Traegt dieses Dokument den ZITIERTEN Erklaerungsbogen der ARD Degeto?

    Nur bei ARD Degeto und ARD Das Erste - die Anlage 13 ist ihr Formular.
    Jedem anderen Sender legt man nicht den Vordruck eines fremden Hauses
    vor; dort steht unsere eigene Erklaerung (Pit, 02.08.).

    Die Wortgrenzen-Pruefung entscheidet: "ARD-Degeto Film GmbH" loest
    aus, "Standard Media" nicht ("ard" nur als Teil eines Wortes). Gegen
    alle 84 Eintraege der Sender-Auswahl gemessen - sie entscheidet dort
    genau wie `nodes._braucht_erklaerungsbogen`, das ueber die Liste
    geht. Deshalb steht das Kriterium hier und nicht doppelt.
    """
    import re as _re
    return bool(_re.search(r"\b(ard|degeto)\b", (auftraggeber or "").strip(),
                           _re.IGNORECASE))


def _ablauf_gelesen(a: Dict[str, Any]) -> bool:
    """
    Wurde der Ablauf wirklich gelesen?

    "keine" ist eine MESSAUSSAGE und darf nur stehen, wenn belegt ist,
    dass es etwas zu messen gab (Pit, 02.08.). Sonst heisst es "nicht
    angegeben". Ein eigenes Aktenfeld braucht es dafuer nicht: das Signal
    steht seit jeher in `herkunft.ableitung` - graph.herkunft() setzt
    "ablauf_nicht_lesbar", wenn der Ablauf fehlt oder der eigene Knoten
    nicht darin steht, und "hand" markiert einen Eintrag ohne jeden
    Ablauf.
    """
    if a.get("angabe_quelle") == "hand":
        return False
    return (a.get("herkunft") or {}).get("ableitung") in _GELESEN


def _status_text(status: str, englisch: bool = True) -> str:
    """Der Status in Klartext - unbekannt heisst 'nicht feststellbar'."""
    return STATUS_TEXT.get(status, STATUS_TEXT[STATUS_UNBEKANNT])[1 if englisch else 0]


def _kurz(h: Optional[str], n: int = 12) -> str:
    if not h:
        return _fehlt()
    return h[:n] + "\u2026" + h[-4:]


# ---------------------------------------------------------------- the new shape
# Entwurf-3 (Pit, 08.08.): quiet full-width section bands instead of black
# bars, letterspaced small caps for labels, values WITHOUT bold - the
# difference comes from size and colour. Green appears on the sheet only
# TWICE: the accent in the head band and the outline of the disclosure
# pill (Farbregel, Pit).
GRAU_ZART = colors.HexColor("#9A9A9A")
BAND_FUELL = colors.HexColor("#F4F4F4")
BAND_LINIE = colors.HexColor("#CFCFCF")
KASTEN_FUELL = colors.HexColor("#FAFAFA")

S_WERT_NEU = _st("wn", fontSize=9.3, leading=12.4)
S_WERT_UNTER = _st("wu", fontSize=7.0, leading=9.4, textColor=GRAU)
S_LAB_DE = _st("ld", fontSize=5.9, leading=7.6, textColor=GRAU_ZART)
S_MONO_GRAU = _st("mg", fontName="Courier", fontSize=6.9, leading=9.2,
                  textColor=GRAU)
S_PROMPT_NEU = _st("pn", fontSize=8.8, leading=12.6)
S_NEG_NEU = _st("ng", fontSize=7.8, leading=10.4, textColor=GRAU)
S_BELEG = _st("bg", fontSize=8.4, leading=12.4)
S_PILLE_UNTER = _st("pu", fontSize=6.4, leading=8.6, textColor=GRAU,
                    alignment=TA_RIGHT)


def _gesperrt_breite(text: str, schrift: str, grad: float,
                     sperrung: float) -> float:
    from reportlab.pdfbase.pdfmetrics import stringWidth
    return stringWidth(text, schrift, grad) + sperrung * len(text)


class Gesperrt(Flowable):
    """
    Gesperrte Versalien als Flowable.

    reportlab kann keine Sperrung im Paragraph; gesperrter Satz wird
    deshalb als Textobjekt gezeichnet (_gesperrt). Gemessen wird VOR dem
    Zeichnen (Layout-Regel 1): passt der Text nicht, weicht erst die
    Sperrung, dann der Grad.
    """

    def __init__(self, text: str, grad: float = 6.4, farbe=GRAU,
                 sperrung: float = 0.9, schrift: str = "Helvetica",
                 breite: Optional[float] = None):
        Flowable.__init__(self)
        self.text = (text or "").upper()
        self.grad, self.farbe, self.sperrung = grad, farbe, sperrung
        self.schrift = schrift
        self.breite_vorgabe = breite

    def wrap(self, availWidth, availHeight):
        ziel = self.breite_vorgabe if self.breite_vorgabe is not None \
            else availWidth
        while (self.sperrung > 0.25 and _gesperrt_breite(
                self.text, self.schrift, self.grad, self.sperrung) > ziel):
            self.sperrung -= 0.1
        while (self.grad > 5.0 and _gesperrt_breite(
                self.text, self.schrift, self.grad, self.sperrung) > ziel):
            self.grad -= 0.2
        self.width = min(ziel, _gesperrt_breite(self.text, self.schrift,
                                                self.grad, self.sperrung))
        self.height = self.grad + 1.8
        return self.width, self.height

    def draw(self):
        _gesperrt(self.canv, 0, 1.0, self.text, self.schrift, self.grad,
                  self.farbe, self.sperrung)


class Rubrikband(Flowable):
    """
    Die Rubrik: ein ruhiges Band ueber die volle Breite - sehr helle
    Fuellung, feine graue Kontur, Titel links in gesperrten Versalien,
    die deutsche Entsprechung klein rechts im selben Band (Entwurf-3).
    Keine schwarzen Balken mehr, kein Gruen.
    """

    def __init__(self, haupt: str, klein: str = "", breite: float = SATZBREITE,
                 hoehe: float = 6.8 * mm):
        Flowable.__init__(self)
        self.haupt = (haupt or "").upper()
        self.klein = klein or ""
        self.width, self.height = breite, hoehe

    def draw(self):
        c = self.canv
        b, h = self.width, self.height
        c.setFillColor(BAND_FUELL)
        c.setStrokeColor(BAND_LINIE)
        c.setLineWidth(0.5)
        c.rect(0, 0, b, h, stroke=1, fill=1)
        grad, sperrung = 7.6, 1.5
        breite_haupt = _gesperrt_breite(self.haupt, "Helvetica-Bold", grad,
                                        sperrung)
        while sperrung > 0.4 and breite_haupt > b - 6 * mm:
            sperrung -= 0.1
            breite_haupt = _gesperrt_breite(self.haupt, "Helvetica-Bold",
                                            grad, sperrung)
        y = h / 2.0 - grad * 0.36
        _gesperrt(c, 3 * mm, y, self.haupt, "Helvetica-Bold", grad, TINTE,
                  sperrung)
        if self.klein:
            klein = self.klein
            c.setFont("Helvetica", 6.6)
            c.setFillColor(GRAU)
            platz = b - 3 * mm - (3 * mm + breite_haupt) - 4 * mm
            while klein and c.stringWidth(klein, "Helvetica", 6.6) > platz:
                klein = klein[:-1]
            c.drawRightString(b - 3 * mm, h / 2.0 - 2.2, klein)


class Pille(Flowable):
    """
    Die Kennzeichnungs-Pille, rechtsbuendig in ihrer Spalte.

    Nur die KONTUR ist gruen - die zweite der zwei erlaubten Gruenstellen
    des Blatts (Farbregel Pit, 08.08.). Der Text bleibt Tinte.
    """

    def __init__(self, text: str, breite: float):
        Flowable.__init__(self)
        self.text = (text or "").upper()
        self.width = breite
        self.height = 6.6 * mm

    def draw(self):
        c = self.canv
        grad, sperrung = 6.8, 1.0
        tb = _gesperrt_breite(self.text, "Helvetica-Bold", grad, sperrung)
        while sperrung > 0.3 and tb + 6 * mm > self.width:
            sperrung -= 0.1
            tb = _gesperrt_breite(self.text, "Helvetica-Bold", grad, sperrung)
        while grad > 5.2 and tb + 6 * mm > self.width:
            grad -= 0.2
            tb = _gesperrt_breite(self.text, "Helvetica-Bold", grad, sperrung)
        w = min(self.width, tb + 6 * mm)
        h = self.height
        x0 = self.width - w
        c.setStrokeColor(GRUEN)
        c.setLineWidth(1.1)
        c.roundRect(x0, 0.6, w, h - 1.2, (h - 1.2) / 2.0, stroke=1, fill=0)
        _gesperrt(c, x0 + (w - tb) / 2.0, h / 2.0 - grad * 0.34, self.text,
                  "Helvetica-Bold", grad, TINTE, sperrung)


class Kopfband(Flowable):
    """
    Der Kopf des Blatts nach Entwurf-3: dunkles Band, links die gesperrte
    Wortmarke, rechts die Dokumentart in Gruen mit der Kennung darunter,
    am rechten Rand der gruene Akzentstreifen - die erste der zwei
    Gruenstellen des Blatts.
    """

    def __init__(self, art: str, kennung: str, breite: float = SATZBREITE,
                 hoehe: float = 19 * mm):
        Flowable.__init__(self)
        self.art = (art or "").upper()
        self.kennung = kennung or ""
        self.width, self.height = breite, hoehe

    def draw(self):
        c = self.canv
        b, h = self.width, self.height
        c.setFillColor(DUNKEL)
        c.rect(0, 0, b, h, stroke=0, fill=1)
        c.setFillColor(GRUEN)
        c.rect(b - 1.6 * mm, 0, 1.6 * mm, h, stroke=0, fill=1)
        _gesperrt(c, 6 * mm, h / 2.0 + 1.4 * mm, "VALYDA",
                  "Helvetica-Bold", 12.5, colors.white, 3.4)
        _gesperrt(c, 6 * mm, h / 2.0 - 4.4 * mm, "AI PROTOCOL",
                  "Helvetica", 6.6, colors.HexColor("#9AA3AE"), 2.9)
        rand = b - 1.6 * mm - 4 * mm
        grad, sperrung = 7.6, 1.6
        aw = _gesperrt_breite(self.art, "Helvetica-Bold", grad, sperrung)
        _gesperrt(c, rand - aw, h / 2.0 + 1.4 * mm, self.art,
                  "Helvetica-Bold", grad, GRUEN, sperrung)
        c.setFont("Helvetica", 6.4)
        c.setFillColor(colors.HexColor("#9AA3AE"))
        c.drawRightString(rand - sperrung, h / 2.0 - 3.6 * mm, self.kennung)


class TitelNeu(Flowable):
    """Die Dokumentzeile unter dem Kopfband - englisch gross, die deutsche
    Entsprechung (oder der Rechtsverweis) klein darunter. Ohne Linie und
    ohne Fettdruck - der Unterschied kommt aus Groesse und Farbe."""

    def __init__(self, haupt: str, klein: str, breite: float = SATZBREITE):
        Flowable.__init__(self)
        self.haupt, self.klein = haupt, klein
        self.width = breite
        self.height = 11 * mm

    def draw(self):
        c = self.canv
        grad = 13.5
        while grad > 9 and c.stringWidth(self.haupt, "Helvetica", grad) > self.width:
            grad -= 0.5
        c.setFillColor(TINTE)
        c.setFont("Helvetica", grad)
        c.drawString(0, 5.2 * mm, self.haupt)
        c.setFillColor(GRAU)
        c.setFont("Helvetica", 8.4)
        klein = self.klein
        while klein and c.stringWidth(klein, "Helvetica", 8.4) > self.width:
            klein = klein[:-1]
        c.drawString(0, 1.0 * mm, klein)


class Unterschriftzeile(Flowable):
    """PLACE, DATE, SIGNATURE gesperrt - mit der deutschen Entsprechung
    dahinter, wo das Blatt zweisprachig ist."""

    def __init__(self, zweisprachig: bool, breite: float = SATZBREITE):
        Flowable.__init__(self)
        self.zweisprachig = zweisprachig
        self.width = breite
        self.height = 4 * mm

    def draw(self):
        c = self.canv
        w = _gesperrt(c, 0, 1.0, "PLACE, DATE, SIGNATURE", "Helvetica", 6.2,
                      GRAU, 0.9)
        if self.zweisprachig:
            c.setFont("Helvetica", 6.2)
            c.setFillColor(GRAU_ZART)
            c.drawString(w + 4, 1.0, "\u00b7  Ort, Datum, Unterschrift")


class _SeitenKanvas(Canvas):
    """Schreibt unten rechts "X / Y" (Entwurf-3) - Y kennt man erst, wenn
    die letzte Seite gebaut ist; dasselbe Verfahren wie _BlattKanvas."""

    def __init__(self, *args, **kwargs):
        Canvas.__init__(self, *args, **kwargs)
        self._blaetter = []

    def showPage(self):
        self._blaetter.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        gesamt = len(self._blaetter)
        for stand in self._blaetter:
            self.__dict__.update(stand)
            self.setFont("Helvetica", 6.8)
            self.setFillColor(GRAU)
            self.drawRightString(A4[0] - 18 * mm, 10.5 * mm,
                                 "%d / %d" % (self._pageNumber, gesamt))
            Canvas.showPage(self)
        Canvas.save(self)


def _rahmen_neu(dokumentart: str, kopf_rechts: str, mit_kopfzeile: bool):
    """
    Kopf- und Fusszeile der neuen Gestalt.

    Die Fusszeile folgt dem Entwurf: eine englische Zeile, rechts bleibt
    Platz fuer "X / Y" (das schreibt _SeitenKanvas beim Speichern). Das
    Ein-Clip-Blatt traegt KEINE Kopfzeile - Marke und Kennung stehen im
    Kopfband; die mehrseitigen Projektfassungen behalten sie, denn dort
    muss die Kennung auf jeder Seite stehen (Pit, 02.08.).
    """
    def zeichnen(c, d):
        c.saveState()
        b, h = A4
        if mit_kopfzeile:
            c.setStrokeColor(LINIE)
            c.setLineWidth(0.4)
            c.line(18 * mm, h - 16 * mm, b - 18 * mm, h - 16 * mm)
            breite_marke = _gesperrt(c, 18 * mm, h - 14.2 * mm,
                                     "VALYDA AI PROTOCOL",
                                     "Helvetica-Bold", 6.8, GRAU, 0.9)
            c.setFillColor(GRAU)
            c.setFont("Helvetica", 6.8)
            art = dokumentart
            links_x = 18 * mm + breite_marke + 8
            platz = (b - 18 * mm) - c.stringWidth(kopf_rechts, "Helvetica",
                                                  6.8) - links_x - 8
            while art and c.stringWidth(art, "Helvetica", 6.8) > platz:
                art = art[:-1]
            c.drawString(links_x, h - 14.2 * mm, art)
            c.drawRightString(b - 18 * mm, h - 14.2 * mm, kopf_rechts)

        c.setStrokeColor(LINIE)
        c.setLineWidth(0.4)
        c.line(18 * mm, 14 * mm, b - 18 * mm, 14 * mm)
        c.setFillColor(GRAU)
        c.setFont("Helvetica", 6.8)
        fuss = ("VALYDA AI PROTOCOL %s  \u00b7  \u00a9 %s %s  \u00b7  "
                "Self-declaration by the producer, not a proof of authenticity"
                % (VERSION, COPYRIGHT_JAHR, RECHTEINHABER))
        platz = (b - 18 * mm) - c.stringWidth("8 / 8", "Helvetica", 6.8) \
            - 18 * mm - 8
        while fuss and c.stringWidth(fuss, "Helvetica", 6.8) > platz:
            fuss = fuss[:-1]
        c.drawString(18 * mm, 10.5 * mm, fuss)
        c.restoreState()
    return zeichnen


def _dok_neu(pfad: str, titel: str, dokumentart: str, kopf_rechts: str,
             mit_kopfzeile: bool) -> BaseDocTemplate:
    doc = BaseDocTemplate(pfad, pagesize=A4, leftMargin=18 * mm,
                          rightMargin=18 * mm, topMargin=22 * mm,
                          bottomMargin=18 * mm, title=titel,
                          author=RECHTEINHABER, creator="VALYDA AI Protocol")
    doc.addPageTemplates([PageTemplate(
        id="s", frames=[Frame(18 * mm, 18 * mm, A4[0] - 36 * mm,
                              A4[1] - 40 * mm, id="n", leftPadding=0,
                              rightPadding=0, topPadding=0, bottomPadding=0)],
        onPage=_rahmen_neu(dokumentart, kopf_rechts, mit_kopfzeile))])
    return doc


def _zfelder(zeilen: List[Any], zweisprachig: bool,
             labelbreite: float = 40 * mm,
             gesamt: float = SATZBREITE) -> Table:
    """
    Die Feldzeilen der neuen Gestalt: Beschriftung links in gesperrten
    Versalien, die deutsche Entsprechung darunter noch kleiner, der Wert
    rechts daneben - ohne Fettdruck (Entwurf-3).

    `zeilen`: (label_en, label_de, inhalt). Inhalt darf Text, ein
    Flowable oder eine Liste von Flowables sein.
    """
    daten = []
    for en, de, inhalt in zeilen:
        label: List[Any] = [Gesperrt(en, breite=labelbreite - 2 * mm)]
        if zweisprachig and de:
            label.append(Paragraph(de, S_LAB_DE))
        if isinstance(inhalt, str):
            inhalt = Paragraph(inhalt, S_WERT_NEU)
        daten.append([label, inhalt])
    t = Tabelle(daten, colWidths=[labelbreite, gesamt - labelbreite])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 2.2),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    return t


#: Die Werkzeugart der Akte ist deutsch verzeichnet ("Bild-zu-Video") -
#: das Blatt fuehrt sie englisch (Entwurf-3: "image-to-video").
_ART_WOERTER = {"text": "text", "bild": "image", "video": "video",
                "ton": "audio"}


def _werkzeugart_en(art: Optional[str]) -> Optional[str]:
    if not art:
        return None
    if art == "Hand-Eintrag":
        return "manual entry"
    kern = art.replace(" (Stimme/Klang)", "")
    teile = [_ART_WOERTER.get(t.lower(), t.lower()) for t in kern.split("-zu-")]
    raus = "-to-".join(teile) if len(teile) > 1 else kern.lower()
    if "(Stimme/Klang)" in art:
        raus += " (voice/sound)"
    return raus


def _parameter_zeile(par: Dict[str, Any]) -> str:
    """
    Die Parameter als EINE ruhige Zeile (Entwurf-3): erst die sprechenden
    Groessen, dann alles Uebrige als "name wert" - KEINE gemessene Angabe
    faellt weg.
    """
    par = dict(par or {})
    teile: List[str] = []
    if par.get("seed") is not None:
        teile.append("seed %s" % par.pop("seed"))
    if par.get("width") and par.get("height"):
        teile.append("%s \u00d7 %s" % (par.pop("width"), par.pop("height")))
    elif par.get("aufloesung"):
        teile.append(str(par.pop("aufloesung")).replace("x", " \u00d7 "))
    for schluessel, form in (("steps", "steps %s"), ("cfg", "cfg %s"),
                             ("sampler_name", "%s"), ("scheduler", "%s"),
                             ("denoise", "denoise %s")):
        if par.get(schluessel) is not None:
            teile.append(form % par.pop(schluessel))
    for schluessel in ("bildrate", "frame_rate", "fps"):
        if par.get(schluessel) is not None:
            teile.append("%g fps" % float(par.pop(schluessel)))
    if par.get("dauer_s") is not None:
        teile.append("%.1f s" % float(par.pop("dauer_s")))
    if par.get("bilder") is not None:
        teile.append("%s frames" % par.pop("bilder"))
    if par.get("resolution") is not None:
        teile.append(str(par.pop("resolution")))
    if par.get("aspect_ratio") is not None:
        teile.append(str(par.pop("aspect_ratio")))
    for schluessel in sorted(par):
        teile.append("%s %s" % (schluessel, par[schluessel]))
    return " \u00b7 ".join(_schuetzen(t) for t in teile)


def _pille_daten(akte: Dict[str, Any]) -> Tuple[str, str]:
    """(Pillentext, Unterzeile) aus der Einstufung - dreiwertig, offen
    bleibt offen und wird nie zu einem Nein."""
    einst = (akte.get("einstufung") or {}).get("wert") or "unbekannt"
    if einst == "deepfake":
        return "DISCLOSURE REQUIRED", "Article 50 (4) \u00b7 visible label"
    if einst == "kuenstlerisch":
        return "DISCLOSURE REQUIRED", "Article 50 (4) \u00b7 discreet notice"
    if einst == "ausserhalb":
        return "NO DISCLOSURE", "Article 50 (4) \u00b7 outside the definition"
    return "NOT CLASSIFIED", "Article 50 (4) \u00b7 not decided"


def _drei_zeilen(akte: Dict[str, Any]) -> List[str]:
    """WHAT THIS PROVES - die drei Zeilen des Entwurfs. Die erste weicht
    nur, wo ihr Wortlaut nicht stimmen wuerde."""
    if akte.get("angabe_quelle") == "hand":
        z1 = ("All entries come from the producer; no workflow was "
              "recorded for this item.")
    elif _ablauf_gelesen(akte):
        z1 = ("Model, prompt, settings and checksums were recorded while "
              "the workflow ran.")
    else:
        z1 = ("The workflow was not readable; the technical entries could "
              "not be recorded from it.")
    return [z1,
            "Scene, timecode, classification and source origin are the "
            "producer\u2019s statements.",
            "A self-declaration \u2014 not a proof of authenticity, not "
            "legal advice."]


def _prompt_inhalt(akte: Dict[str, Any], sp, gelesen: bool) -> List[Any]:
    """
    Der Inhalt des Prompt-Rahmens - der PROMPT-MODUS entscheidet, nicht
    die Blattart (Pit, 09.08.):

      vollstaendig    der volle Wortlaut steht im Rahmen, dazu der
                      Negativ-Prompt; die Pruefsumme klein darunter
      nur_pruefsumme  nur der Pruefsummensatz - der Text bleibt privat

    Bis zum 09.08. druckte das Creator-Blatt auch bei sichtbarem Prompt
    (damals "full text", heute "show prompt") nur den Verweis auf die
    Datendatei - Pits Blatt aus Akte 71cb zeigte den Prompt nicht,
    obwohl er in der Akte lag.
    """
    pr = akte.get("prompt") or {}
    inhalt: List[Any] = []
    if pr.get("modus") == "nur_pruefsumme":
        if pr.get("sha256"):
            satz = sp("Nicht offengelegt. Pr\u00fcfsumme SHA-256 %s \u2013 belegt, "
                      "dass der Text nachtr\u00e4glich nicht ge\u00e4ndert wurde."
                      % _kurz(pr.get("sha256"), 16),
                      "Not disclosed. Checksum SHA-256 %s \u2014 proves the "
                      "text was not changed afterwards."
                      % _kurz(pr.get("sha256"), 16))
            inhalt.append(Paragraph(satz, S_MONO_GRAU))
        elif gelesen:
            inhalt.append(Paragraph(
                sp("Im Ablauf stand kein Prompt-Text. Es gibt deshalb auch "
                   "keine Pr\u00fcfsumme dar\u00fcber.",
                   "The workflow carried no prompt text. There is therefore "
                   "no checksum over one."), S_MONO_GRAU))
        else:
            inhalt.append(Paragraph(
                sp("Der Ablauf lag nicht in lesbarer Form vor - kein "
                   "Prompt erhoben.",
                   "The workflow was not readable \u2014 no prompt was "
                   "recorded."), S_MONO_GRAU))
        return inhalt

    _leer = "<i>%s</i>" % _fehlt(sp, gemessen=gelesen)
    inhalt.append(Paragraph(_schuetzen(pr.get("positiv"))
                            if pr.get("positiv") else _leer, S_PROMPT_NEU))
    if pr.get("zuordnung") == "nutzer":
        inhalt.append(Paragraph(sp("Zuordnung durch den Produzenten",
                                   "assigned by the producer", klein=False),
                                S_LAB_DE))
    inhalt.append(Spacer(1, 2))
    neg = Tabelle([[Gesperrt("NEGATIVE", grad=6.0, sperrung=0.8,
                             breite=20 * mm),
                    Paragraph(_schuetzen(pr.get("negativ"))
                              if pr.get("negativ") else _leer, S_NEG_NEU)]],
                  colWidths=[22 * mm, SATZBREITE - 12 - 22 * mm])
    neg.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                             ("TOPPADDING", (0, 0), (-1, -1), 1),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    inhalt.append(neg)
    ohne = pr.get("texte_ohne_rolle") or []
    if ohne:
        inhalt.append(Spacer(1, 2))
        inhalt.append(Paragraph(
            sp("Texte aus dem Ablauf \u2013 Prompt und Negativ-Prompt waren "
               "nicht zu unterscheiden",
               "Texts from the workflow \u2013 prompt and negative prompt "
               "could not be told apart", klein=False), S_LAB_DE))
        for t in ohne[:4]:
            inhalt.append(Paragraph(_schuetzen(t), S_NEG_NEU))
    if pr.get("sha256"):
        # klein darunter: die Pruefsumme bindet den gedruckten Wortlaut
        inhalt.append(Spacer(1, 2))
        inhalt.append(Paragraph("SHA-256  %s" % _kurz(pr["sha256"], 16),
                                S_MONO_GRAU))
    return inhalt


# ------------------------------------------------- harmonische Seitenteilung
#: Stauchstufen fuer die Abstaende, wenn das Blatt knapp nicht auf eine
#: Seite passt. Untergrenze 0,5: die Luft darf bis zur Haelfte schrumpfen,
#: darunter kleben die Rubriken aneinander. Schriftgroessen und Inhalt
#: bleiben IMMER unangetastet (Pit, 09.08.).
_STAUCHUNG = (0.85, 0.7, 0.6, 0.5)


def _rubriken_binden(e: List[Any]) -> List[Any]:
    """
    Der Seitenumbruch faellt nur auf eine Rubrik-Grenze (Pit, 09.08.).

    Jede Rubrik (Band + Inhalt bis zum naechsten Band) wird EIN
    KeepTogether; ein bereits gebundener Block wird eingeflochten, nie
    verschachtelt (Regel 8: zwei ineinander liegende KeepTogether
    kosteten eine ganze Seite). Weil der Schlussblock (WHAT THIS PROVES
    mit der Unterschrift) als gebundener Block HINTER der letzten Rubrik
    steht, geht er in deren Bindung auf - eine Folgeseite traegt damit
    immer eine vollstaendige Rubrik PLUS den Schlussblock, nie den
    Schlussblock allein. Eine Rubrik, die hoeher ist als eine ganze
    Seite, teilt reportlab weiterhin - ein langer Prompt macht ein
    Blatt zu Recht zweiseitig.
    """
    aus: List[Any] = []
    offen: Optional[List[Any]] = None
    for f in e:
        if isinstance(f, Rubrikband):
            if offen is not None:
                aus.append(KeepTogether(offen))
            offen = [f]
        elif offen is None:
            aus.append(f)
        elif isinstance(f, KeepTogether):
            offen.extend(f._content)
        else:
            offen.append(f)
    if offen is not None:
        aus.append(KeepTogether(offen))
    return aus


def _spacer_stauchen(teile: List[Any], faktor: float) -> None:
    """Setzt jede Spacer-Hoehe auf Entwurfswert mal `faktor` - nur die
    Luft schrumpft, nie die Schrift und nie ein Inhalt."""
    for f in teile:
        if isinstance(f, KeepTogether):
            _spacer_stauchen(f._content, faktor)
        elif isinstance(f, Spacer):
            if not hasattr(f, "_entwurf_hoehe"):
                f._entwurf_hoehe = f.height
            f.height = f._entwurf_hoehe * faktor


def _seitenzahl_probe(story: List[Any]) -> int:
    """
    Baut die Geschichte probeweise in einen Puffer und ZAEHLT die
    Seiten - gemessen, nicht aus Wickelhoehen geschaetzt: reportlab
    entscheidet den Umbruch selbst, also fragt man reportlab.
    Gleiche Rahmengeometrie wie _dok_neu, ohne Kopf- und Fusszeile
    (die stehen ausserhalb des Satzspiegels und tragen nicht).
    """
    d = BaseDocTemplate(io.BytesIO(), pagesize=A4, leftMargin=18 * mm,
                        rightMargin=18 * mm, topMargin=22 * mm,
                        bottomMargin=18 * mm)
    d.addPageTemplates([PageTemplate(id="m", frames=[Frame(
        18 * mm, 18 * mm, A4[0] - 36 * mm, A4[1] - 40 * mm, id="m",
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])])
    d.build(list(story))
    return d.page


def _seiten_harmonisch(e: List[Any]) -> List[Any]:
    """
    Pit-Regel vom 09.08.: Das Blatt verteilt sich harmonisch.

      - Passt alles auf EINE Seite, bleibt es eine. Reicht es knapp
        nicht, schrumpfen die Abstaende stufenweise (_STAUCHUNG) -
        keine Schrift wird kleiner, nichts faellt weg.
      - Braucht es zwei Seiten, stehen die Entwurfsabstaende wieder
        auf ihrem Wert, der Umbruch faellt auf eine Rubrik-Grenze
        (_rubriken_binden), und die Folgeseite traegt eine
        vollstaendige Rubrik plus den Schlussblock.

    Die Probebauten schreiben in die Zellmitschrift hinein; der
    Aufrufer leert _ZELLEN vor dem endgueltigen Bau.
    """
    e = _rubriken_binden(e)
    if _seitenzahl_probe(e) > 1:
        for faktor in _STAUCHUNG:
            _spacer_stauchen(e, faktor)
            if _seitenzahl_probe(e) == 1:
                break
        else:
            _spacer_stauchen(e, 1.0)
    return e


def _einclip(akte: Dict[str, Any], pfad: str, ordner: str, art: str,
             kopfdaten: Dict[str, Any], zweisprachig: bool) -> str:
    """
    Das Ein-Clip-Blatt nach Entwurf-3 (Pit, 08.08.) - EINE Gestalt fuer
    Creator und Broadcast.

    Reihenfolge: Kopfdaten \u00b7 WHAT THIS CLIP IS \u00b7 MADE WITH \u00b7 PROMPT \u00b7
    WHERE IT COMES FROM \u00b7 WHAT THIS PROVES \u00b7 Unterschrift. Keine
    schwarzen Balken, keine Nummern, kein Fettdruck bei den Werten.
    Gruen nur zweimal: Kopfband-Akzent und Pillen-Kontur.

    Keine gemessene Angabe faellt weg: Modifikatoren und Rechenschritte
    stehen unter MADE WITH, nicht zuordenbare Texte im Prompt-Rahmen,
    jede Pruefsumme klein in Schreibmaschinenschrift.
    """
    _ZELLEN.clear()
    sp = lambda de, en, klein=True: _sp("en+de" if zweisprachig else "en",
                                        de, en, klein)
    kennung = kopfdaten.get("kennung") or kennung_bauen(akte)
    doc = _dok_neu(pfad, "VALYDA AI Protocol \u2013 %s" % art, art.upper(),
                   kennung, mit_kopfzeile=False)
    e: List[Any] = []

    herk = akte.get("herkunft") or {}
    status = herk.get("status") or "unbekannt"
    eins = akte.get("einsatz") or {}
    erg = akte.get("ergebnis") or {}
    gelesen = _ablauf_gelesen(akte)
    hand = akte.get("angabe_quelle") == "hand"
    offen = "<i>%s</i>" % _fehlt(sp)
    keine = "<i>%s</i>" % _fehlt(sp, gemessen=gelesen)

    e.append(Kopfband(art, kennung))
    e.append(Spacer(1, 6 * mm))
    if art.lower() == "creator":
        e.append(TitelNeu("Record of AI classification and labelling",
                          "Article 50 Regulation (EU) 2024/1689"))
    else:
        e.append(TitelNeu("Record of generative AI used in production",
                          "Nachweis \u00fcber den Einsatz generativer Verfahren"
                          if zweisprachig
                          else "Article 50 Regulation (EU) 2024/1689"))
    e.append(Spacer(1, 3 * mm))

    # ---------- Kopfdaten: Produktion \u00b7 Szene mit Timecode \u00b7 Fuer wen
    _tc = " \u2013 ".join(t for t in (eins.get("timecode_start"),
                                 eins.get("timecode_ende")) if t)
    szene: List[Any] = [Paragraph(_schuetzen(eins.get("szene"))
                                  if eins.get("szene") else offen, S_WERT_NEU)]
    if _tc:
        szene.append(Paragraph(_tc, S_WERT_UNTER))
    kopf_zeilen: List[Any] = [
        ("PRODUCTION", "Produktion",
         _schuetzen(akte.get("projekt")) if akte.get("projekt") else offen),
        ("SCENE", "Szene", szene),
    ]
    if art.lower() == "creator":
        if (akte.get("veroeffentlicht_auf") or "").strip():
            kopf_zeilen.append(("PUBLISHED ON", None,
                                _schuetzen(akte.get("veroeffentlicht_auf"))))
    else:
        kopf_zeilen.append(("FOR", "F\u00fcr",
                            _schuetzen(kopfdaten.get("auftraggeber"))
                            if (kopfdaten.get("auftraggeber") or "").strip()
                            else offen))
    # Produzent, Rechteinhaber und Zweck stehen wieder im Kopfdaten-Block
    # (Pit, 09.08.: der Entwurf war eine Anmutung, keine Inhaltsvorgabe).
    # Leere Felder drucken keine Zeile. Quelle ist die AKTE - beide
    # Knoten schreiben dieselben Felder.
    if (akte.get("produzent") or "").strip():
        kopf_zeilen.append(("PRODUCER", "Produzent",
                            _schuetzen(akte["produzent"])))
    if (akte.get("rechteinhaber") or "").strip():
        kopf_zeilen.append(("RIGHTS HOLDER", "Rechteinhaber",
                            _schuetzen(akte["rechteinhaber"])))
    if (eins.get("zweck") or "").strip():
        kopf_zeilen.append(("REASON FOR AI USE", "Grund f\u00fcr den KI-Einsatz",
                            _schuetzen(eins["zweck"])))
    stapel = _stapel_hinweis(akte, "en+de" if zweisprachig else "en")
    if stapel:
        kopf_zeilen.append(("SCOPE", "Umfang",
                            Paragraph(stapel, S_WERT_UNTER)))
    # Das Vorschaubild des Clips steht rechts neben den Kopfdaten - die
    # einzige Zone mit freier rechter Flanke; kein Rubrikband wird
    # unterbrochen, und die Wiedererkennung kommt zuerst (ihr Zweck laut
    # akte.py). Ohne Bild bleibt der Kopf einspaltig - kein leerer Kasten.
    vorschau_bild = _bild((erg.get("vorschau") or {}).get("datei"),
                          ordner, 50 * mm)
    if vorschau_bild is not None:
        kopf_tab = Tabelle(
            [[_zfelder(kopf_zeilen, zweisprachig,
                       gesamt=SATZBREITE - 58 * mm), vorschau_bild]],
            colWidths=[SATZBREITE - 58 * mm, 58 * mm])
        kopf_tab.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 4),
            ("BOX", (1, 0), (1, 0), 0.5, BAND_LINIE),
            # Das Bild sitzt MITTIG in seinem Kasten, nicht oben links
            # angeklebt (Pit, 09.08.) - der Kasten ist so hoch wie die
            # Kopfdaten links und damit hoeher als das Bild.
            ("ALIGN", (1, 0), (1, 0), "CENTER"),
            ("VALIGN", (1, 0), (1, 0), "MIDDLE"),
            ("LEFTPADDING", (1, 0), (1, 0), 4),
            ("RIGHTPADDING", (1, 0), (1, 0), 4),
            ("TOPPADDING", (1, 0), (1, 0), 4),
            ("BOTTOMPADDING", (1, 0), (1, 0), 4)]))
        e.append(kopf_tab)
    else:
        e.append(_zfelder(kopf_zeilen, zweisprachig))
    e.append(Spacer(1, 3 * mm))

    # ---------- WHAT THIS CLIP IS
    e.append(Rubrikband("WHAT THIS CLIP IS",
                        "Was dieser Clip ist" if zweisprachig else ""))
    e.append(Spacer(1, 2 * mm))
    if hand:
        wert_block: List[Any] = [
            Paragraph("Manual entry", S_WERT_NEU),
            Paragraph(herk.get("begruendung_en") or herk.get("begruendung")
                      or "Entries by the producer, not machine-verified.",
                      S_WERT_UNTER)]
    else:
        wert_block = [Paragraph(_status_text(status), S_WERT_NEU),
                      Paragraph(herk.get("begruendung_en")
                                or herk.get("begruendung") or "",
                                S_WERT_UNTER)]
    pille_text, pille_unter = _pille_daten(akte)
    kz = akte.get("kennzeichnung") or {}
    pille_block: List[Any] = [Pille(pille_text, 50 * mm),
                              Spacer(1, 1.5),
                              Paragraph(pille_unter, S_PILLE_UNTER)]
    if kz.get("erforderlich") is True and kz.get("wortlaut"):
        pille_block.append(Paragraph(
            "\u201e%s\u201c \u00b7 from %s" % (_schuetzen(kz.get("wortlaut")),
                                kz.get("sichtbar_ab") or "first exposure"),
            S_PILLE_UNTER))
    label_ki: List[Any] = [Gesperrt("AI INVOLVEMENT", breite=38 * mm)]
    if zweisprachig:
        label_ki.append(Paragraph("KI-Anteil", S_LAB_DE))
    t = Tabelle([[label_ki, wert_block, pille_block]],
                colWidths=[40 * mm, 82 * mm, SATZBREITE - 122 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 2.2),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (0, 1), 4),
                           ("RIGHTPADDING", (2, 0), (2, 0), 0)]))
    e.append(t)
    e.append(Spacer(1, 2.5 * mm))

    # ---------- MADE WITH
    e.append(Rubrikband("MADE WITH", "Womit" if zweisprachig else ""))
    e.append(Spacer(1, 2 * mm))
    wertbreite = SATZBREITE - 40 * mm
    modelle = akte.get("modelle") or []
    if modelle:
        modell_block: List[Any] = []
        for m in modelle:
            name = _umbrechen(_schuetzen(_modellname(m)), wertbreite - 8,
                              grad=9.3)
            if m.get("rolle") and m.get("rolle") != "generator":
                name += " (%s)" % _rolle_text(m, sp)
            modell_block.append(Paragraph(name, S_WERT_NEU))
            modell_block.append(Paragraph(
                _nachweis_text(m, sp, abschnitt2=False), S_WERT_UNTER))
            if m.get("sha256"):
                modell_block.append(Paragraph(
                    "SHA-256  %s" % _kurz(m["sha256"], 16), S_MONO_GRAU))
    else:
        modell_block = [Paragraph(keine, S_WERT_NEU)]
    _wz = akte.get("werkzeug") or {}
    werkzeug = " \u00b7 ".join(t for t in (
        " ".join(x for x in (_wz.get("name"), _wz.get("version")) if x),
        _werkzeugart_en(_wz.get("art"))) if t)
    made_zeilen: List[Any] = [
        ("MODEL", "Modell", modell_block),
        ("TOOL", "Werkzeug", werkzeug or offen),
        ("SETTINGS", "Parameter",
         _parameter_zeile(akte.get("parameter")) or keine),
    ]
    if akte.get("modifikatoren"):
        made_zeilen.append(("MODIFIERS", "Modifikatoren",
                            _schuetzen(" \u00b7 ".join(akte["modifikatoren"]))))
    stufen_text = _stufen_zeile(akte, sp)
    if stufen_text:
        made_zeilen.append(("STAGES", "Rechenschritte",
                            Paragraph(stufen_text, S_WERT_UNTER)))
    e.append(_zfelder(made_zeilen, zweisprachig))
    e.append(Spacer(1, 2.5 * mm))

    # ---------- PROMPT
    e.append(Rubrikband("PROMPT", "Prompt" if zweisprachig else ""))
    e.append(Spacer(1, 2 * mm))
    e.append(_kasten(_prompt_inhalt(akte, sp, gelesen),
                     fuell=KASTEN_FUELL, rand=BAND_LINIE, pad=6))
    e.append(Spacer(1, 2 * mm))
    quellen = akte.get("quellen") or []
    _quelle_wert = (akte.get("quellen_herkunft") or {}).get("wert")
    if quellen:
        # Referenzen mit Bild stehen als kleine, ruhige Kachel mit ihrem
        # Dateinamen darunter (Pit, 09.08. - "wie vorher auch"); ohne
        # Bild bleibt die Textzeile. Kein leerer Kasten.
        ref_block: List[Any] = []
        kacheln: List[Any] = []
        for q in quellen:
            rb = _bild(q.get("vorschau"), ordner, 24 * mm)
            if rb is not None:
                name = _umbrechen(_schuetzen(q.get("datei") or q.get("typ")
                                             or "?"), 24 * mm, grad=5.9)
                kachel = Tabelle([[rb], [Paragraph(name, S_LAB_DE)]],
                                 colWidths=[24 * mm])
                kachel.setStyle(TableStyle(
                    [("LEFTPADDING", (0, 0), (-1, -1), 0),
                     ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                     ("TOPPADDING", (0, 0), (0, 0), 0),
                     ("TOPPADDING", (0, 1), (0, 1), 1.5),
                     ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
                # Die Kachel steht mittig in ihrer Spalte (Pit, 09.08.).
                kachel.hAlign = "CENTER"
                kacheln.append(kachel)
            else:
                ref_block.append(Paragraph(
                    _schuetzen(q.get("datei") or q.get("typ") or "?"),
                    S_WERT_NEU))
        if kacheln:
            while len(kacheln) % 5:
                kacheln.append("")
            for i in range(0, len(kacheln), 5):
                # 5 x 26,5 mm = 132,5 mm - bleibt unter der Wertspalte
                # von 134 mm (Layout-Regel 1: erst messen).
                kt = Tabelle([kacheln[i:i + 5]], colWidths=[26.5 * mm] * 5)
                kt.setStyle(TableStyle(
                    [("VALIGN", (0, 0), (-1, -1), "TOP"),
                     ("LEFTPADDING", (0, 0), (-1, -1), 0),
                     ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                     ("TOPPADDING", (0, 0), (-1, -1), 1),
                     ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
                ref_block.append(kt)
        if _quelle_wert:
            ref_block.append(Paragraph(
                "stated by the producer: %s" % _schuetzen(
                    {"Realaufnahme (Eigendreh)": "real footage",
                     "selbst KI-erzeugt": "AI-generated itself",
                     "gemischt": "mixed"}.get(_quelle_wert, _quelle_wert)),
                S_WERT_UNTER))
    else:
        ref_block = [Paragraph(keine, S_WERT_NEU)]
    e.append(_zfelder([("REFERENCE", "Referenz", ref_block)], zweisprachig))
    e.append(Spacer(1, 2.5 * mm))

    # ---------- WHERE IT COMES FROM
    e.append(Rubrikband("WHERE IT COMES FROM",
                        "Woher es stammt" if zweisprachig else ""))
    e.append(Spacer(1, 2 * mm))
    if erg.get("datei"):
        erg_block: List[Any] = [Paragraph(_schuetzen(erg["datei"]),
                                          S_WERT_NEU)]
        if erg.get("sha256"):
            erg_block.append(Paragraph("SHA-256  %s"
                                       % _kurz(erg["sha256"], 16),
                                       S_MONO_GRAU))
    else:
        erg_block = [Paragraph(sp("<i>nicht \u00fcbergeben</i>",
                                  "<i>not supplied</i>", klein=False),
                               S_WERT_NEU)]
    erstellt = (akte.get("erzeugt_am") or "").replace("T", " ")[:19]
    if erstellt and akte.get("ersteller"):
        erstellt = "%s   by %s" % (erstellt, _schuetzen(akte["ersteller"]))
    woher_zeilen: List[Any] = [
        ("RESULT FILE", "Ergebnisdatei", erg_block),
        ("CREATED", "Erstellt am", erstellt or offen),
    ]
    if kopfdaten.get("akte_datei"):
        akte_block: List[Any] = [Paragraph(
            _schuetzen(kopfdaten["akte_datei"]), S_WERT_NEU)]
        if kopfdaten.get("akte_hash"):
            akte_block.append(Paragraph(
                "SHA-256  %s" % _kurz(kopfdaten["akte_hash"], 16),
                S_MONO_GRAU))
        woher_zeilen.append(("DATA FILE", "Datendatei", akte_block))
    e.append(_zfelder(woher_zeilen, zweisprachig))
    e.append(Spacer(1, 2.5 * mm))

    # ---------- WHAT THIS PROVES - drei Zeilen (Entwurf-3) - und die
    # Unterschrift IN DERSELBEN Bindung: sie darf nie allein auf einer
    # Seite stehen (dieselbe abgenommene Regel wie am 02.08.).
    _linie = Tabelle([["", ""]], colWidths=[85 * mm, 89 * mm],
                     rowHeights=[9 * mm])
    _linie.setStyle(TableStyle([("LINEBELOW", (0, 0), (0, 0), 0.5, TINTE)]))
    e.append(KeepTogether(
        [Rubrikband("WHAT THIS PROVES",
                    "Was das belegt" if zweisprachig else ""),
         Spacer(1, 2 * mm)]
        + [Paragraph("\u2013&nbsp; %s" % zeile, S_BELEG)
           for zeile in _drei_zeilen(akte)]
        + [Spacer(1, 7 * mm), _linie, Spacer(1, 1 * mm),
           Unterschriftzeile(zweisprachig)]))

    e = _seiten_harmonisch(e)
    _ZELLEN.clear()  # die Probebauten der Seitenteilung haben mitgeschrieben
    doc.build(e, canvasmaker=_SeitenKanvas)
    _zellen_schreiben(pfad)
    return pfad


# ---------------------------------------------------------------- version K
def fassung_k(akte, pfad: str, ordner: Optional[str] = None,
              projekt: Optional[str] = None, akte_datei: Optional[str] = None,
              akte_hash: Optional[str] = None) -> str:
    """
    Creator, englisch.

    Eine Akte -> ein Ein-Clip-Blatt nach Entwurf-3. Eine Liste von Akten
    -> Projektfassung mit Bildübersicht und einer Zeile je Position.

    Der Prompt-Rahmen folgt dem PROMPT-MODUS der Akte (Pit, 09.08.):
    "show prompt" druckt den vollen Wortlaut, "hide prompt" nur den
    Pruefsummensatz.
    """
    ordner = ordner or os.path.dirname(pfad) or "."
    _ZELLEN.clear()
    if isinstance(akte, (list, tuple)):
        return _fassung_k_projekt(list(akte), pfad, ordner, projekt)
    return _einclip(akte, pfad, ordner, "Creator",
                    {"kennung": kennung_bauen(akte),
                     "akte_datei": akte_datei, "akte_hash": akte_hash},
                    zweisprachig=False)


# ---------------------------------------------------------------- version S
def fassung_s(akten: List[Dict[str, Any]], pfad: str, kopfdaten: Dict[str, Any],
              ordner: Optional[str] = None, zweisprachig: bool = True,
              projektblatt: bool = False) -> str:
    """
    Broadcast-Fassung, ausführlich. Nimmt eine oder viele Akten.

    `projektblatt` sagt, dass der PROJECT-Knoten ruft (Pit, 09.08.): dann
    traegt auch das Ein-Clip-Blatt eines Ein-Akten-Projekts das Kopfband
    BROADCAST · PROJECT - Dateiname (PROJECT_...) und Band duerfen sich
    nie widersprechen. Viele Akten sind IMMER eine Sammlung; dort steht
    das Band ohne Rueckfrage.

    Die Sprache liegt seit dem 01.08. fest: englisch, darunter klein grau
    deutsch. `zweisprachig` ist EINE Bedingung, einmal in nodes.py
    ausgewertet und auf das ganze Dokument angewandt: die deutsche
    Kleinzeile erscheint nur bei deutschsprachigen Auftraggebern - ein
    BBC-Redakteur braucht sie nicht; leer und Freitext bleiben deutsch.
    Einzige Ausnahme ist der Erklärungsbogen (Abschnitt 4): dort steht Deutsch
    oben und Englisch klein darunter - sein Wortlaut ist ein Zitat aus der
    Anlage des Senders, und wer eine Übersetzung unterschreibt,
    unterschreibt etwas anderes.
    """
    ordner = ordner or os.path.dirname(pfad) or "."
    # ONE clip -> the Ein-Clip-Blatt (Entwurf-3, Pit 08.08.). The project
    # structure below is for MANY clips; the Degeto quotation lives in
    # the standalone declaration sheet, which the node builds alongside.
    if len(akten) == 1:
        return _einclip(akten[0], pfad, ordner,
                        "Broadcast · Project" if projektblatt
                        else "Broadcast",
                        kopfdaten, zweisprachig)
    _ZELLEN.clear()
    sp = lambda de, en, klein=True: _sp("en+de" if zweisprachig else "en",
                                        de, en, klein)
    zitat = lambda de, en, klein=True: _sp("beide", de, en, klein)
    # The section bars follow the language ORDER of the document (08.08.):
    # English first, German small behind - or English only where the
    # recipient reads no German. The ONE exception is the quoted
    # declaration sheet section, which stays German first; it is built
    # below with _balken directly, not through this helper.
    bal = lambda en, de: _balken(en, de) if zweisprachig else _balken(en)
    kennung = kopfdaten.get("kennung") or kennung_bauen(akten=akten)
    # Mehrere Akten sind eine Sammlung - das Band sagt es (Pit, 09.08.).
    # Gemessen: BROADCAST \u00b7 PROJECT ist 42,8 mm breit und laesst 94,3 mm
    # Luft zur Wortmarke im 174-mm-Band.
    doc = _dok_neu(pfad, "VALYDA AI Protocol \u2013 Broadcast \u00b7 Project",
                   "BROADCAST \u00b7 PROJECT", kennung, mit_kopfzeile=True)
    e: List[Any] = []

    e.append(Kopfband("Broadcast \u00b7 Project", kennung))
    e.append(Spacer(1, 6 * mm))
    e.append(TitelNeu("Record of generative AI used in production",
                      "Nachweis \u00fcber den Einsatz generativer Verfahren"
                      if zweisprachig
                      else "Article 50 Regulation (EU) 2024/1689"))
    e.append(Spacer(1, 3 * mm))

    # The header block names only what the recipient needs (Pit, 02.08.):
    #   - no storage path. It has no permanence and shows a stranger the
    #     folder structure of the producer.
    #   - no empty lines. A "-" proves nothing; where nothing is known,
    #     no line appears any more. The exception are the fields whose
    #     very ABSENCE is the information.
    #   - id and data file are technical and stand at the end.
    def _wenn(bedingung, beschriftung_de, beschriftung_en, wert):
        return [(sp(beschriftung_de, beschriftung_en), wert)] if bedingung else []

    e.append(_felder([
        # No bold values (Entwurf-3): the difference comes from size and
        # colour - here from the label column alone.
        (sp("Produktion", "Production"),
         kopfdaten.get("projekt") or "<i>%s</i>" % _fehlt(sp)),
        # Producer and rights holder stay, even empty: that nobody is named
        # is, on a record, a statement.
        (sp("Sender / Auftraggeber", "Broadcaster / client"),
         kopfdaten.get("auftraggeber") or "<i>%s</i>" % _fehlt(sp)),
        (sp("Produzent", "Producer"),
         kopfdaten.get("produzent") or "<i>%s</i>" % _fehlt(sp)),
        *_wenn((kopfdaten.get("co_produzent") or "").strip(),
               "Co-Produzent", "Co-producer", kopfdaten.get("co_produzent")),
        *_wenn((kopfdaten.get("veroeffentlicht_auf") or "").strip(),
               "Ver\u00f6ffentlicht auf", "Published on",
               kopfdaten.get("veroeffentlicht_auf")),
        (sp("Rechteinhaber", "Rights holder"),
         kopfdaten.get("rechteinhaber") or "<i>%s</i>" % _fehlt(sp)),
        *_wenn((kopfdaten.get("fassung") or "").strip(),
               "Schnittfassung", "Cut version", kopfdaten.get("fassung")),
        *_wenn((kopfdaten.get("bezugsdatei") or "").strip(),
               "Fertige Fassung (Datei)", "Delivered file",
               kopfdaten.get("bezugsdatei")),
        (sp("Erstellt am", "Created"),
         kopfdaten.get("erstellt_am") or "<i>%s</i>" % _fehlt(sp)),
    ]))
    e.append(Spacer(1, 5 * mm))
    # A sheet about ONE clip does not count - it says what this clip is.
    # Counting happens only in the project protocol. Both are separate
    # texts, not one function with a switch: that they used to share one
    # was the reason for "1 Position(en), davon 1 ...".
    e.append(_kasten([
        Paragraph(sp("Zusammenfassung", "Summary", klein=False), S_H2), Spacer(1, 2),
        Paragraph(_zusammenfassung(akten, "en"), S_TXT),
        Spacer(1, 2 if zweisprachig else 0),
        Paragraph(_zusammenfassung(akten, "de") if zweisprachig else "", S_KLEIN),
    ], fuell=colors.HexColor("#F2F6FA"), rand=colors.HexColor("#1F4E79")))
    e.append(Spacer(1, 6 * mm))

    # ---------- The blocks are BUILT first and then assembled in the
    # order in which one reads them: first show what was made, then
    # explain, then sign.
    # (Pit, 02.08. - before, the declaration stood before the evidence.)
    _haupt = e

    _uebersicht: List[Any] = []
    e = _uebersicht
    # Only where there is something to survey: with a single clip the
    # overview showed the same tile that appears again two pages later
    # in the evidence.
    kontakt = _kontaktbogen(akten, ordner, zweisprachig=zweisprachig)
    if kontakt:
        # bar + first image row (the contact sheet supplies table, spacing
        # and legend - the table is its first piece).
        e.append(_kopf_mit_inhalt(bal("OVERVIEW", "\u00dcbersicht"),
                                  Spacer(1, 4 * mm), kontakt[0]))
        e += kontakt[1:]
        e.append(Spacer(1, 6 * mm))
        if len(akten) > 8:
            e.append(PageBreak())

    _nachweis: List[Any] = []
    e = _nachweis
    # ---------- Section 1: one evidence block per shot.
    _bal1 = bal("1 \u00b7 ITEM-BY-ITEM RECORD",
                "Einzelnachweis je Einstellung")
    for i, a in enumerate(akten, 1):
        # The bar hangs on the FIRST evidence block - inside the same binding,
        # not around it. It otherwise stood alone at the foot of page 1 while
        # the evidence only began on page 2.
        e.append(_einzelnachweis(
            i, a, ordner, zweisprachig=zweisprachig,
            vorspann=[_bal1, Spacer(1, 4 * mm)] if i == 1 else None))
        e.append(Spacer(1, 6 * mm))

    _modelle: List[Any] = []
    e = _modelle
    # ---------- Section 2: the model directory
    # Two groups because two different things are proven: a loaded file
    # carries its checksum, a model according to the graph carries only
    # its name. Throwing both into one table would make one look like
    # the other. An empty group is dropped; if nothing is there at all,
    # only the sentence remains - a table of dashes proves nothing.
    e.append(PageBreak())
    dateien, laut_ablauf = [], []
    gesehen = set()
    for a in akten:
        for m in a.get("modelle") or []:
            sch = (_modellname(m), m.get("rolle"))
            if sch in gesehen:
                continue
            gesehen.add(sch)
            (dateien if m.get("datei") else laut_ablauf).append(m)

    # The bar ALWAYS stays - even without a model. A document that skips
    # a number looks damaged, and section 3 refers to the sections before
    # it. Only the table stays empty, and a sentence stands in its place
    # (Pit, 02.08.).
    _bal2 = bal("2 \u00b7 MODEL INDEX", "Modellverzeichnis")
    if not dateien and not laut_ablauf:
        # Here too: "loaded nothing" is a measured statement. If no graph
        # was readable, nothing was measured - merely nothing was found.
        if all(_ablauf_gelesen(a) for a in akten):
            _kein_modell = sp("Es konnte kein Modell erhoben werden: der Ablauf "
                              "hat weder eine Gewichtsdatei geladen noch einen "
                              "Modellnamen mitgef\u00fchrt.",
                              "No model could be recorded: the workflow neither "
                              "loaded a weights file nor carried a model name.")
        else:
            _kein_modell = sp("Es konnte kein Modell erhoben werden. Der Ablauf "
                              "lag nicht in lesbarer Form vor; ob Modelle "
                              "benutzt wurden, ist damit nicht festgestellt.",
                              "No model could be recorded. The workflow was not "
                              "available in readable form, so whether models "
                              "were used has not been established.")
        e.append(_kopf_mit_inhalt(_bal2, Spacer(1, 4 * mm),
                                  Paragraph(_kein_modell, S_TXT)))
        e.append(Spacer(1, 8 * mm))

    if dateien:
        _kopf1 = Paragraph(sp("Geladene Modelldateien mit Pr\u00fcfsumme",
                              "Model files loaded, with checksum", klein=False), S_H2)
        _ein1 = Paragraph(sp("Die Pr\u00fcfsumme wurde \u00fcber die tats\u00e4chlich "
                             "geladene Datei gebildet.",
                             "The checksum was taken from the file that was "
                             "actually loaded."), S_TXT)
        daten = [[Paragraph(x, S_TH) for x in
                  (sp("Datei", "File"), sp("Rolle", "Role"), "SHA-256")]]
        for m in dateien:
            daten.append([Paragraph(_schuetzen(_modellname(m)), S_TD),
                          Paragraph(_rolle_text(m, sp), S_TD),
                          Paragraph(m.get("sha256")
                                    or sp("nicht pr\u00fcfbar", "not verifiable",
                                          klein=False), S_MONO)])
        # The section bar here hangs on the FIRST group; the group heading
        # in turn on its table. Bound are the header line and the first
        # three rows - enough for the binding to carry without nailing down
        # a long table.
        _kopf_spalten, _rest = _tabelle_teilen(daten, 4)
        e.append(_kopf_mit_inhalt(_bal2, Spacer(1, 4 * mm), _kopf1, _ein1,
                                  Spacer(1, 2 * mm), _kopf_spalten))
        if _rest is not None:
            e.append(_rest)
        e.append(Spacer(1, 5 * mm))
        _bal2 = None            # the bar is placed

    if laut_ablauf:
        _kopf2 = Paragraph(sp("Modelle laut Ablauf \u2013 ohne Datei, ohne Pr\u00fcfsumme",
                              "Models per workflow \u2013 no file, no checksum",
                              klein=False), S_H2)
        _ein2 = Paragraph(sp("Diese Namen standen im ausgef\u00fchrten Ablauf. Es "
                              "wurde keine Datei geladen, \u00fcber die sich eine "
                              "Pr\u00fcfsumme bilden liesse \u2013 so arbeiten Dienste "
                              "ausserhalb des eigenen Rechners und Knoten, die ihr "
                              "Modell erst zur Laufzeit holen.",
                              "These names appeared in the executed workflow. No "
                              "file was loaded that a checksum could be taken from "
                             "\u2013 that is how off-machine services work, and "
                             "nodes that fetch their model at runtime."), S_TXT)
        daten = [[Paragraph(x, S_TH) for x in
                  (sp("Modell", "Model"), sp("Rolle", "Role"),
                   sp("Nachweis", "Evidence"))]]
        for m in laut_ablauf:
            nachweis = _modellnachweis(m)
            daten.append([Paragraph(_schuetzen(_modellname(m)), S_TD),
                          Paragraph(_rolle_text(m, sp), S_TD),
                          Paragraph(sp("Herkunft der Angabe unbekannt",
                                       "origin of this entry unknown", klein=False)
                                    if nachweis == NACHWEIS_UNBEKANNT else
                                    sp("laut Ablauf, keine Datei",
                                       "per workflow, no file", klein=False), S_TD)])
        _kopf_spalten, _rest = _tabelle_teilen(daten, 4)
        e.append(_kopf_mit_inhalt(_bal2, Spacer(1, 4 * mm) if _bal2 else None,
                                  _kopf2, _ein2, Spacer(1, 2 * mm), _kopf_spalten))
        if _rest is not None:
            e.append(_rest)
        e.append(Spacer(1, 5 * mm))

    if dateien or laut_ablauf:
        e.append(Spacer(1, 3 * mm))

    _grenzen: List[Any] = []
    e = _grenzen
    # ---------- Section 3: reach and limits
    e.append(_kopf_mit_inhalt(
        bal("3 \u00b7 SCOPE AND LIMITS", "Reichweite und Grenzen"),
        Spacer(1, 4 * mm),
        Paragraph(sp("Was dieses Dokument belegt",
                     "What this document proves", klein=False), S_H2)))

    # Z-2: measured and stated are named, not thrown into one pot.
    # If the document contains manual entries, that is said as well.
    hand_dabei = any(a.get("angabe_quelle") == "hand" for a in akten)
    _z2_de = ("Die gemessenen Angaben \u2013 Modell, Prüfsummen, Parameter, "
              "Prompt-Texte und Quellen \u2013 stammen unverändert aus dem "
              "tatsächlich ausgeführten Arbeitsablauf und wurden zum Zeitpunkt "
              "der Erzeugung mitgeschrieben. Szene, Zweck, Timecode, Produzent, "
              "Rechteinhaber, Einstufung, Transparenzpflicht und Herkunft der "
              "Bildquelle sind Angaben des Produzenten.")
    _z2_en = ("The measured entries \u2013 model, checksums, parameters, prompt "
              "texts and sources \u2013 come unchanged from the workflow that was "
              "actually executed and were recorded at generation time. Scene, "
              "purpose, timecode, producer, rights holder, classification, "
              "disclosure obligation and source origin are statements by the "
              "producer.")
    if hand_dabei:
        _z2_de += (" Positionen mit dem Vermerk Hand-Eintrag stammen aus keinem "
                   "protokollierten Ablauf.")
        _z2_en += " Items marked as manual entries come from no logged workflow."

    # Z-3: the producer's statement precedes the derivation - and that is stated.
    _z3_de = ("Die Unterscheidung <i>vollgeneriert</i> gegenüber <i>veränderte "
              "Realaufnahme</i> ist aus dem Aufbau des Ablaufs abgeleitet. Hat "
              "der Produzent die Herkunft der Bildquelle angegeben, geht diese "
              "Angabe vor und ist beim jeweiligen Eintrag vermerkt.")
    _z3_en = ("The distinction <i>fully generated</i> versus <i>modified real "
              "footage</i> is derived from the structure of the workflow. Where "
              "the producer stated the origin of the image source, that "
              "statement takes precedence and is noted with the respective "
              "entry.")

    # Models without a file: the item appears only if such models exist -
    # a sentence about something that does not occur in the document
    # would itself be false information.
    _ohne_datei = any(_modellnachweis(m) == NACHWEIS_ABLAUF
                      for a in akten for m in (a.get("modelle") or []))
    _z6_de = ("Modelle, die ein Dienst ausserhalb dieses Rechners gestellt oder "
              "die der Ablauf erst zur Laufzeit geholt hat, tragen ihren Namen "
              "so, wie der Ablauf ihn nennt - aber keine Pr\u00fcfsumme, weil daf\u00fcr "
              "keine Datei geladen wurde. Sie sind als solche gekennzeichnet.")
    _z6_en = ("Models supplied by a service off this machine, or fetched by the "
              "workflow at runtime, carry the name the workflow gives them - but "
              "no checksum, because no file was loaded to take one from. They are "
              "marked as such.")

    _punkte_de = [_z2_de, _z3_de, _bindung_zeile(akten, "de")]
    _punkte_en = [_z2_en, _z3_en, _bindung_zeile(akten, "en")]
    if _ohne_datei:
        _punkte_de.append(_z6_de)
        _punkte_en.append(_z6_en)
    _belegt_de = "<br/>".join("\u2022&nbsp; %s" % p for p in _punkte_de)
    _belegt_en = "<br/>".join("\u2022&nbsp; %s" % p for p in _punkte_en)
    # The storage path is gone here (Pit, 02.08.) - it has no permanence,
    # and a stranger reads the producer's folder structure from it. What
    # the data record contains stays: that is a statement about the
    # evidence, not a signpost to someone else's disk.
    e.append(_kasten([
        Paragraph(sp("Was in der Datendatei steht",
                     "What the data file holds", klein=False), S_H2),
        Paragraph(sp(_datenakte_satz(akten, "de"),
                     _datenakte_satz(akten, "en")), S_TXT),
    ]))
    e.append(Spacer(1, 4 * mm))
    e.append(Paragraph(_belegt_en, S_TXT))
    if zweisprachig:
        e.append(Paragraph(_belegt_de, S_KLEIN))
    e.append(Spacer(1, 3 * mm))
    e.append(Paragraph(sp("Was dieses Dokument nicht belegt",
                          "What this document does not prove", klein=False), S_H2))
    _grenze_de = ("\u2022&nbsp; Es ist eine <b>Selbstauskunft des Produzenten</b>. Es weist nach, "
                  "was das Werkzeug aufgezeichnet hat \u2013 nicht, dass daneben nichts anderes "
                  "geschehen ist.<br/>"
                  "\u2022&nbsp; Eintr\u00e4ge mit dem Vermerk \u201eHand-Eintrag\u201c beruhen "
                  "auf Angaben des Produzenten und sind nicht maschinell gepr\u00fcft.<br/>"
                  "\u2022&nbsp; Die Einsch\u00e4tzung zur Transparenzpflicht ist eine Bewertung "
                  "des Produzenten, keine Rechtsauskunft.<br/>"
                  "\u2022&nbsp; Das Dokument trifft keine Aussage \u00fcber Material, das nicht "
                  "durch die protokollierten Werkzeuge gelaufen ist.")
    _grenze_en = ("\u2022&nbsp; This is a <b>self-declaration by the producer</b>. It proves what "
                  "the tool recorded \u2013 not that nothing else happened alongside.<br/>"
                  "\u2022&nbsp; Entries marked as manual are statements by the producer and are "
                  "not machine-verified.<br/>"
                  "\u2022&nbsp; The assessment of the disclosure obligation is the producer\u2019s "
                  "judgement, not legal advice.<br/>"
                  "\u2022&nbsp; The document says nothing about material that did not pass through "
                  "the logged tools.")
    e.append(Paragraph(_grenze_en, S_TXT))
    if zweisprachig:
        e.append(Paragraph(_grenze_de, S_KLEIN))

    _technik: List[Any] = []
    e = _technik
    # ---------- Technical details, small and at the very end.
    # Id and data file do not belong in the header block: the id is in
    # the header line of EVERY page anyway, and the file name of the
    # data record only interests whoever actually looks for the record
    # (Pit, 02.08.).
    e.append(Spacer(1, 8 * mm))
    _technisch = [(sp("Kennung", "Record ID"), kennung)]
    if kopfdaten.get("akte_datei"):
        _technisch.append((sp("Datendatei", "Data file"),
                           _schuetzen(kopfdaten.get("akte_datei"))))
    if kopfdaten.get("akte_hash"):
        _technisch.append(("SHA-256",
                           '<font name="Courier" size="7.4">%s</font>'
                           % kopfdaten.get("akte_hash")))
    e.append(_kasten([
        Paragraph(sp("Technische Angaben", "Technical details", klein=False), S_LAB),
        Spacer(1, 1.5 * mm),
        _felder(_technisch, breiten=(30 * mm, SATZBREITE - 30 * mm - 12)),
    ]))

    _erklaerung: List[Any] = []
    e = _erklaerung
    # ---------- Section 4: the declaration, in TWO renditions.
    # Until today the quoted ARD Degeto sheet stood here without any
    # condition - even in an English BBC document. You do not present one
    # broadcaster with another broadcaster's form.
    degeto = zitiert_anlage_13(kopfdaten.get("auftraggeber") or "")
    _art50_de = "Artikel 50 (4) der Verordnung (EU) 2024/1689"
    _art50_en = "Article 50 (4) of Regulation (EU) 2024/1689"

    # Read three-valued - _pflichtwert() is the ONE place for that.
    pflichtig = [a for a in akten if _pflichtwert(a) is True]
    ohne_pflicht = [a for a in akten if _pflichtwert(a) is False]
    unentschieden = [a for a in akten if _pflichtwert(a) is None]

    if degeto:
        # EXCEPTION to the document's fixed language order: in the
        # declaration sheet German is ON TOP and English small below. The
        # wording is a quotation from the broadcaster's annex - whoever signs
        # a translation signs something else. Hence `zitat` instead of `sp`.
        # NOTHING about this gets changed.
        e.append(_kopf_mit_inhalt(
            _balken("4 \u00b7 ERKL\u00c4RUNGSBOGEN KI",
                    "4 \u00b7 AI declaration form"),
            Spacer(1, 4 * mm),
            Paragraph("In der Produktion <b>%s</b> ist/sind"
                      % (kopfdaten.get("projekt")
                         or "<i>nicht angegeben</i>"), S_TXT),
            Paragraph("The declaration below is quoted from the "
                      "broadcaster\u2019s form and therefore stays in "
                      "German. In the production named above there "
                      "is/are:", S_KLEIN)))
        e.append(Spacer(1, 3 * mm))

        # In mixed productions BOTH sub-items are true - then both get
        # ticked. The form does not rule that out, and anything else would
        # be an incomplete declaration.
        #   The ticks ALWAYS come from the producer's statements (the former
        #   switch "leer zum Ankreuzen" was dropped on 01.08.). Nothing is
        #   ever ticked that was never decided - "not classified" stays
        #   undecided and leaves both boxes empty.
        #   The form line "keinerlei KI generierter Inhalt" is dropped HERE:
        #   this record only comes about when AI was involved. Whoever needs
        #   the sheet WITHOUT AI takes the broadcaster's blank form.
        #   CAUTION, no contradiction to the declaration sheet: there the
        #   line does appear, for that sheet is a QUOTATION of Anlage 13.
        #   Section 4 is our own rendition (Pit, 01.08.).
        kreuz = [
            (None, "<b>KI generierte Inhalte enthalten</b>, wie unten stehend "
                   "aufgelistet,"),
            (bool(ohne_pflicht),
             "&nbsp;&nbsp;&nbsp;&nbsp;die <b>keine</b> Transparenzpflicht nach "
             "Artikel 50 (4) KI-Verordnung (Verordnung (EU) 2024/1689) "
             "begr\u00fcnden"),
            (bool(pflichtig),
             "&nbsp;&nbsp;&nbsp;&nbsp;die <b>eine</b> Transparenzpflicht nach "
             "Artikel 50 (4) KI-Verordnung (Verordnung (EU) 2024/1689) "
             "begr\u00fcnden"),
        ]
    else:
        # OUR own declaration (Pit, 02.08.). Not a quotation - so no
        # reference to Anlage 13 and no quotation exception for the
        # language: this text follows the document's normal language order.
        # Three items instead of the Degeto sheet's four; we do not rebuild
        # its subdivision. "In the producer's assessment" stands in BOTH
        # duty items: the sheet is a self-declaration, not legal
        # information.
        e.append(_kopf_mit_inhalt(
            bal("4 \u00b7 PRODUCER\u2019S DECLARATION ON THE USE OF AI",
                "Erkl\u00e4rung des Produzenten zum KI-Einsatz"),
            Spacer(1, 4 * mm),
            Paragraph(sp("In der Produktion <b>%s</b> sind"
                         % (kopfdaten.get("projekt")
                            or "<i>nicht angegeben</i>"),
                         "In the production <b>%s</b> there are"
                         % (kopfdaten.get("projekt")
                            or "<i>not specified</i>")), S_TXT)))
        e.append(Spacer(1, 3 * mm))
        kreuz = [
            # The first item always stays empty: this record only comes about
            # when AI was involved. It is there so that the declaration is
            # complete.
            (False, sp("keine mit k\u00fcnstlicher Intelligenz erzeugten "
                       "Inhalte enthalten",
                       "no contents generated with artificial intelligence")),
            (bool(ohne_pflicht),
             sp("mit k\u00fcnstlicher Intelligenz erzeugte Inhalte enthalten, "
                "die nach Einsch\u00e4tzung des Produzenten <b>keine</b> "
                "Transparenzpflicht nach %s begr\u00fcnden" % _art50_de,
                "contents generated with artificial intelligence which, in "
                "the producer\u2019s assessment, do <b>not</b> require "
                "disclosure under %s" % _art50_en)),
            (bool(pflichtig),
             sp("mit k\u00fcnstlicher Intelligenz erzeugte Inhalte enthalten, "
                "die nach Einsch\u00e4tzung des Produzenten <b>eine</b> "
                "Transparenzpflicht nach %s begr\u00fcnden" % _art50_de,
                "contents generated with artificial intelligence which, in "
                "the producer\u2019s assessment, <b>do</b> require disclosure "
                "under %s" % _art50_en)),
        ]

    t = Tabelle([[("" if a is None else _kaestchen(a)), Paragraph(b, S_WERT)]
               for a, b in kreuz], colWidths=[8 * mm, 166 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    e.append(t)
    if unentschieden:
        # If no item fits, NONE is ticked - not even the first. Open never
        # becomes a tick.
        e.append(Spacer(1, 2 * mm))
        _offen_de = ("Bei %d Position(en) wurde die Transparenzpflicht nicht "
                     "entschieden; daf\u00fcr wurde nichts angekreuzt."
                     % len(unentschieden))
        _offen_en = ("For %d item(s) the disclosure obligation was not "
                     "decided; nothing was ticked for those."
                     % len(unentschieden))
        if not degeto and len(unentschieden) == len(akten):
            _offen_de = ("Die Einstufung nach %s wurde f\u00fcr dieses Dokument "
                         "noch nicht getroffen. Es ist deshalb nichts "
                         "angekreuzt." % _art50_de)
            _offen_en = ("The classification under %s has not been made for "
                         "this document. Nothing is therefore ticked."
                         % _art50_en)
        e.append(Paragraph(zitat(_offen_de, _offen_en) if degeto
                           else sp(_offen_de, _offen_en), S_KLEIN))
    if not degeto:
        e.append(Spacer(1, 3 * mm))
        e.append(Paragraph(sp("Die einzelnen Eins\u00e4tze sind nachstehend "
                              "aufgef\u00fchrt.",
                              "The individual uses are listed below."), S_TXT))
    e.append(Spacer(1, 5 * mm))

    # The heading of the enumeration now hangs on its table - that
    # carries more precisely than an estimated remainder.
    # Inside the quotation the quotation language order applies, in our
    # own declaration the document's. The number column belongs to the
    # Degeto form; with exactly one clip in our rendition it is dropped -
    # there it counted a count that is none.
    beschriften = zitat if degeto else sp
    nummern = degeto or len(akten) > 1
    _auflistung_kopf = Paragraph(
        beschriften("Auflistung:", "List of items:", klein=False), S_H2_ZUSAMMEN)
    kopf = ([""] if nummern else []) + [
        beschriften("Konkreter Einsatz / Szene", "Item / scene"),
        beschriften("Name KI-System", "AI system"),
        beschriften("Zweck des Einsatzes", "Purpose"),
        beschriften("Transparenz-<br/>pflicht<br/>Art. 50 (4)",
                    "Disclosure<br/>Art. 50 (4)"),
        "TC"]
    daten = [[Paragraph(x, S_TH) for x in kopf]]
    for i, a in enumerate(akten, 1):
        eins = a.get("einsatz") or {}
        tp = _pflichtwert(a)
        daten.append(([Paragraph("#%d" % i, S_TD)] if nummern else []) + [
            Paragraph(eins.get("szene") or (a.get("ergebnis") or {}).get("datei")
                      or "<i>%s</i>" % _fehlt(beschriften), S_TD),
            Paragraph(_ki_system(a, 33 * mm - 6), S_TD),
            Paragraph(eins.get("zweck") or "<i>%s</i>" % _fehlt(beschriften), S_TD),
            # None is NOT no: reporting a never-decided duty as "nein" would
            # be a false statement. Noticed on the round trip Creator ->
            # bundling (Creator records carry no decision).
            # "ja"/"nein" belong to the quoted form. In our own declaration
            # they follow the language of the document - the English BBC sheet
            # otherwise said "ja".
            Paragraph(beschriften("<b>ja</b>", "<b>yes</b>") if tp is True else
                      beschriften("nein", "no") if tp is False else
                      beschriften("<i>nicht entschieden</i>",
                                  "<i>not decided</i>"), S_TD),
            Paragraph(eins.get("timecode_start")
                      or "<i>%s</i>" % _fehlt(beschriften), S_TD),
        ])
    # If the number column is dropped, its 8 mm go to the scene.
    _spalten = ([8 * mm] if nummern else []) + [
        38 * mm if nummern else 46 * mm, 33 * mm, 44 * mm, 26 * mm, 25 * mm]
    def _auflistung(zeilen):
        t = Tabelle(zeilen, colWidths=_spalten, repeatRows=1)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, LINIE),
                               ("BACKGROUND", (0, 0), (-1, 0), HELL),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                               ("LEFTPADDING", (0, 0), (-1, -1), 3)]))
        return t

    # Heading, column header and the first three rows stay together;
    # everything further may break and then repeats the column header
    # (repeatRows).
    e.append(_kopf_mit_inhalt(_auflistung_kopf, Spacer(1, 2 * mm),
                              _auflistung(daten[:4])))
    if len(daten) > 4:
        e.append(_auflistung([daten[0]] + daten[4:]))

    _signatur: List[Any] = []
    e = _signatur
    # ---------- Signature at the very end.
    # It stands at the end of the declaration and covers the whole
    # document. Lead-in sentence and line hold together: otherwise the
    # line slid alone onto an otherwise empty page (measured 02.08.).
    _linie = Tabelle([["", ""]], colWidths=[85 * mm, 89 * mm], rowHeights=[10 * mm])
    _linie.setStyle(TableStyle([("LINEBELOW", (0, 0), (0, 0), 0.5, TINTE)]))
    e.append(Spacer(1, 10 * mm))
    # KeepTogether around bar, sentence and line: the line otherwise slid
    # by a few millimetres onto its own, otherwise empty page - one whole
    # page for one line on the Degeto broadcast and the project document
    # (measured 02.08.).
    e.append(KeepTogether([
        bal("SIGNATURE", "Unterschrift"),
        Spacer(1, 4 * mm),
        # The sentence names the declaration above it - it is called
        # differently per broadcaster, hence two versions.
        Paragraph(
            sp("Mit der Unterschrift wird der vorstehende Erkl\u00e4rungsbogen "
               "abgegeben und die Richtigkeit der Angaben in diesem Dokument "
               "best\u00e4tigt.",
               "By signing, the declaration form above is submitted and the "
               "entries in this document are confirmed as correct.")
            if degeto else
            sp("Mit der Unterschrift wird die vorstehende Erkl\u00e4rung abgegeben "
               "und die Richtigkeit der Angaben in diesem Dokument best\u00e4tigt.",
               "By signing, the declaration above is given and the entries in "
               "this document are confirmed as correct."), S_TXT),
        Spacer(1, 14 * mm),
        _linie,
        Paragraph(sp("Ort, Datum, Unterschrift", "Place, date, signature",
                     klein=False), S_KLEIN),
    ]))

    e = _haupt

    # 1 evidence - in the project document with the overview in front.
    e += _uebersicht
    e += _nachweis
    # 2 model directory
    e += _modelle
    # 3 reach and limits, with the technical details at the end
    e += _grenzen
    e += _technik
    # 4 The declaration gets its own page (Pit's requirement) and carries
    #   the signature with it: what you sign should stand on the same
    #   page as what you declare.
    e.append(PageBreak())
    e += _erklaerung
    e += _signatur

    doc.build(e, canvasmaker=_SeitenKanvas)
    _zellen_schreiben(pfad)
    return pfad


def kennung_bauen(akte: Optional[Dict[str, Any]] = None,
                  akten: Optional[List[Dict[str, Any]]] = None) -> str:
    """
    Die Kennung des Dokuments - EINE Stelle fuer alle drei Knoten.

        VALYDA-P-<JJMMTT>-<4 Zeichen der Akten-ID, gross>

    Vorher baute jeder Knoten sie anders. Der Broadcast-Knoten schnitt mit
    `name[-6:]` mitten in die Sekundenzahl ("VALYDA-P-6_120f"), und der
    Project-Knoten nahm nur das Tagesdatum - zwei Produktionen am selben
    Tag bekamen damit DIESELBE Kennung. Beides erledigt (Pit, 02.08.).

    Der Tagesteil kommt aus der Akte, nicht aus der Uhr des Rechners: ein
    spaeter nachgebautes Dokument soll dieselbe Kennung tragen wie beim
    ersten Mal. Beim Buendeln zaehlt dafuer die AELTESTE Akte - sie ist
    der Anfang der Produktion.

    Beim Buendeln kommen die vier Zeichen NICHT aus einer der Akten,
    sondern aus einer Pruefsumme ueber alle Akten-IDs, sortiert (die
    Reihenfolge beim Einlesen darf nichts aendern). Sonst truege das
    Projektdokument dieselbe Kennung wie das Einzelblatt seiner aeltesten
    Akte - zwei verschiedene Dokumente mit einer Kennung.

    VERMERK, damit es spaeter niemand fuer einen Fehler haelt: aendert
    sich der Satz der Clips, aendert sich die Kennung. Das ist richtig -
    es ist dann ein anderes Dokument.
    """
    if akte is None and akten:
        gueltig = [a for a in akten if a]
        aelteste = min(gueltig, default=None,
                       key=lambda a: (a.get("erzeugt_am") or "￿"))
        ids = sorted((a.get("akte_id") or "") for a in gueltig)
        if len(gueltig) > 1:
            import hashlib
            kurz = hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()[:4].upper()
            return "%s-%s" % (_kennung_tag(aelteste), kurz)
        akte = aelteste
    akte = akte or {}
    return "%s-%s" % (_kennung_tag(akte),
                      ((akte.get("akte_id") or "")[:4] or "0000").upper())


def _kennung_tag(akte: Optional[Dict[str, Any]]) -> str:
    roh = ((akte or {}).get("erzeugt_am") or "").replace("-", "")
    tag = roh[2:8] if len(roh) >= 8 and roh[:8].isdigit() else time.strftime("%y%m%d")
    return "VALYDA-P-%s" % tag


def _kopf_mit_inhalt(*teile) -> KeepTogether:
    """
    Eine Ueberschrift und der Anfang dessen, was sie ueberschreibt.

    Ein Balken allein am Seitenfuss ist ein Satzfehler - die Ueberschrift
    verspricht etwas, das erst zwei Zentimeter weiter kommt. KeepTogether
    schiebt beides gemeinsam auf die naechste Seite (Pit, 02.08.).

    Gebunden wird der Balken mit so viel Inhalt, dass die Bindung traegt:
    bei einer Tabelle mit Kopfzeile und ersten Zeilen, bei einer
    Feldliste mit den ersten Zeilen. Reportlab bricht ein zu grosses
    Buendel notfalls doch auf - dann bleibt die Ueberschrift beim ersten
    Stueck, und genau darum geht es.
    """
    return KeepTogether([x for x in teile if x is not None])


def _tabelle_teilen(daten, erste: int):
    """
    Teilt die Zeilen einer Modelltabelle in Kopfstueck und Rest.

    Das Kopfstueck (Spaltenkopf plus die ersten Zeilen) wird an die
    Ueberschrift gebunden, der Rest laeuft frei weiter und darf umbrechen.
    Eine ganze lange Tabelle an die Ueberschrift zu binden wuerde sie
    festnageln und Seiten sprengen.
    """
    kopf = _tabelle_modelle(daten[:erste])
    rest = _tabelle_modelle([daten[0]] + daten[erste:]) if len(daten) > erste else None
    return kopf, rest


def _tabelle_modelle(daten) -> Table:
    """Die beiden Tabellen in Abschnitt 2 - gleiche Spalten, gleiche Gestalt."""
    t = Tabelle(daten, colWidths=[60 * mm, 26 * mm, 88 * mm], repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, LINIE),
                           ("BACKGROUND", (0, 0), (-1, 0), HELL),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _balken(text: str, englisch: str = "") -> Rubrikband:
    """
    Die Abschnitts-Rubrik - seit Entwurf-3 (08.08.) ein ruhiges Band statt
    des schwarzen Balkens: helle Fuellung, feine Kontur, Haupttitel links
    gesperrt, die Entsprechung klein rechts. Kein Gruen (Farbregel Pit).
    Der Name bleibt, damit jede Aufrufstelle das neue Band bekommt.
    """
    return Rubrikband(text, englisch)


def _modellname(m: Dict[str, Any]) -> str:
    """Wie das Modell heisst. Akten vor dem 02.08. kennen nur `datei`."""
    return m.get("bezeichnung") or m.get("datei") or _fehlt()


def _modellnachweis(m: Dict[str, Any]) -> str:
    """
    Woher der Modellname stammt.

    Fehlt der Schluessel, stammt die Akte aus einem Stand vor dem 02.08. -
    dann gilt NICHT "gemessen", sondern "unbekannt". Ein unentschiedener
    Wert darf nie zu einer Entscheidung werden.
    """
    n = m.get("nachweis")
    return n if n in (NACHWEIS_DATEI, NACHWEIS_ABLAUF) else NACHWEIS_UNBEKANNT


def _rolle_text(m: Dict[str, Any], sp) -> str:
    """
    Die Rolle in der Sprache des Dokuments.

    Die eingefuehrten Rollennamen sind Fachwoerter und bleiben, wie sie
    sind (lora, controlnet, vae ...). Uebersetzt wird allein der seit dem
    02.08. moegliche offene Wert - er ist deutsch geschrieben und stuende
    sonst mitten in einem englischen Blatt.
    """
    rolle = m.get("rolle") or ROLLE_OFFEN
    if rolle == ROLLE_OFFEN:
        return sp("nicht zugeordnet", "not assigned", klein=False)
    return rolle


def _nachweis_text(m: Dict[str, Any], sp, abschnitt2: bool = True) -> str:
    """
    Woher der Modellname stammt - der Satz, der im Dokument steht.

    Ein Eintrag "laut Ablauf" darf nie so aussehen wie eine gemessene
    Datei. Die volle Pruefsumme steht NICHT hier, sondern in Abschnitt 2:
    im Nachweis genuegt die Auskunft, dass es eine gibt (Pit, 02.08.).

    `abschnitt2=False` fuer das Creator-Blatt: es hat keinen Abschnitt 2,
    dort liegt die volle Pruefsumme in der Datendatei.
    """
    nachweis = _modellnachweis(m)
    if nachweis == NACHWEIS_ABLAUF:
        return sp("laut Ablauf, keine Datei — nicht prüfbar",
                  "per workflow, no file — not verifiable", klein=False)
    if nachweis == NACHWEIS_UNBEKANNT:
        return sp("Herkunft der Angabe unbekannt",
                  "origin of this entry unknown", klein=False)
    if m.get("sha256"):
        if not abschnitt2:
            return sp("gemessen, Prüfsumme in der Datendatei",
                      "measured, checksum in the data file", klein=False)
        return sp("gemessen, Prüfsumme in Abschnitt 2",
                  "measured, checksum in section 2", klein=False)
    return sp("Datei nicht auffindbar — nicht prüfbar",
              "file not found — not verifiable", klein=False)


def _modellangabe(modelle, breite: float, sp, gelesen: bool,
                  abschnitt2: bool = True) -> Any:
    """
    Die Modellangabe fuer JEDE Dokumentfassung (Pit, 02.08.: jedes
    erzeugte Dokument muss sagen, mit welchem Modell gerechnet wurde).

    Dieselbe abgenommene Form wie im Senderblatt: ein Modell ist eine
    Zeile "Bezeichnung (Rolle) · Nachweis", mehrere sind die kleine
    Tabelle. Kein Modell erhoben: das steht ausdruecklich da - nicht
    nichts, und kein Strich.
    """
    if not modelle:
        return _modelltabelle_b([], breite, sp, gelesen)
    if len(modelle) == 1:
        m = modelle[0]
        return "%s (%s) · %s" % (_schuetzen(_modellname(m)),
                                 _rolle_text(m, sp),
                                 _nachweis_text(m, sp, abschnitt2))
    return _modelltabelle_b(modelle, breite, sp, gelesen,
                            abschnitt2=abschnitt2)


#: A model name may break only at these places. Without this,
#: reportlab breaks a long identifier mid-word ("sdxl_base_1." /
#: "0.safetensors") - which reads like two files (Pit, 02.08.).
_TRENNSTELLEN = "_.-"


def _umbrechen(text: str, breite: float, grad: float = 7.7,
               schrift: str = "Helvetica") -> str:
    """
    Bricht einen Modellnamen NUR an seinen Trennstellen um.

    Selbst gemessen statt reportlab ueberlassen: ein Nullbreiten-Leerzeichen
    ist dort keine Umbruchgelegenheit (nachgemessen 02.08.), und
    `splitLongWords` bricht an beliebiger Stelle. Layout-Regel 1 verlangt
    ohnehin, vor der Ausgabe zu messen - also wird hier gemessen und
    zerlegt. Passt ein Stueck allein nicht mehr, bleibt es stehen und
    reportlab bricht es; das ist dann kein Zuschnitt, sondern ein zu enger
    Rahmen.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth
    if stringWidth(text, schrift, grad) <= breite:
        return text
    stuecke, aktuell = [], ""
    for zeichen in text:
        aktuell += zeichen
        if zeichen in _TRENNSTELLEN:
            stuecke.append(aktuell)
            aktuell = ""
    if aktuell:
        stuecke.append(aktuell)

    zeilen, zeile = [], ""
    for stueck in stuecke:
        if zeile and stringWidth(zeile + stueck, schrift, grad) > breite:
            zeilen.append(zeile)
            zeile = stueck
        else:
            zeile += stueck
    if zeile:
        zeilen.append(zeile)
    return "<br/>".join(zeilen)


def _modelltabelle_b(modelle, breite: float, sp, gelesen: bool = True,
                     abschnitt2: bool = True) -> Any:
    """
    Die Modelle im Nachweis - als kleine Tabelle, nicht als Fliesstext.

    Warum eine Tabelle und keine Bloecke: die drei Auskuenfte je Modell
    (Name, Rolle, Nachweis) sind bei mehreren Modellen nur in Spalten
    vergleichbar - untereinander gesetzt lesen sie sich als ein Absatz,
    und genau das war der Einwand. Die Spalten haben denselben Zuschnitt
    wie Abschnitt 2, wer das eine kennt, findet sich im anderen zurecht. Und
    der Name bekommt eine eigene Spalte, in der er nicht mit dem Rest um
    die Zeile kaempft. Jede Zelle traegt ihre Uebersetzung selbst - so
    bleibt die Kleinzeile bei ihrer Angabe.
    """
    if not modelle:
        # Measured absence - but only if the graph was read. If it was
        # unreadable, nothing was measured and thus nothing is absent.
        return Paragraph("<i>%s</i>" % _fehlt(sp, gemessen=gelesen), S_WERT)
    b_name = breite * 0.42
    b_rolle = breite * 0.20
    daten = [[Paragraph(sp("Modell", "Model"), S_TH),
              Paragraph(sp("Rolle", "Role"), S_TH),
              Paragraph(sp("Nachweis", "Evidence"), S_TH)]]
    for m in modelle:
        name = _umbrechen(_schuetzen(_modellname(m)), b_name - 6)
        daten.append([Paragraph(name, S_TD),
                      Paragraph(_rolle_text(m, sp), S_TD),
                      Paragraph(_nachweis_text(m, sp, abschnitt2), S_TD)])
    t = Tabelle(daten, colWidths=[b_name, b_rolle, breite - b_name - b_rolle])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, LINIE),
                           ("BACKGROUND", (0, 0), (-1, 0), HELL),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 2),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _ki_system(a: Dict[str, Any], breite: Optional[float] = None) -> str:
    """
    Die Spalte "Name KI-System" des Erklaerungsbogens.

    Genannt werden ALLE Modelle mit der Rolle `generator`, in
    Ablaufreihenfolge. Einen von zweien still auszuwaehlen verwuerfe genau
    die Auskunft, die der Sender fuer die Rechtefrage braucht: hat ein
    Checkpoint das Standbild erzeugt und ein Dienst daraus das Video, sind
    beide benutzt worden. Modelle mit offener Rolle erscheinen hier NIE -
    ein Freistellmodell ist kein erzeugendes System.

    `breite`: die Spaltenbreite. Ist sie bekannt, wird ein langer
    Modellname an seinen Trennstellen umbrochen statt mitten im Wort.
    """
    gen = [m for m in (a.get("modelle") or []) if m.get("rolle") == "generator"]
    wz = (a.get("werkzeug") or {}).get("name") or "ComfyUI"
    if gen:
        # Without a prefix: the question is the AI system, and that is the
        # model. Prepending "ComfyUI" names the workbench, not the system
        # (Pit, 02.08.); it stands under "Werkzeug" in the record anyway.
        namen = [_schuetzen(_modellname(m)) for m in gen]
        if breite:
            namen = [_umbrechen(n, breite) for n in namen]
        return " \u00b7 ".join(namen)
    # Both call sites are in the declaration sheet: German on top,
    # English small below. The suffix says that ComfyUI itself is not
    # the generating system here - simply none was surveyed.
    return _sp("beide", "%s \u00b7 kein Modell erhoben" % wz,
               "%s \u00b7 no model recorded" % wz)


def _pflichtwert(a: Dict[str, Any]) -> Optional[bool]:
    """
    Die Transparenzpflicht - DREIWERTIG.

    True ja · False nein · None noch nicht eingestuft. Wer den Wert als
    truthy liest, macht aus None ein Nein und damit aus einer offenen
    Frage eine Rechtsaussage. Genau dieser Griff ist in diesem Projekt
    schon mehrfach schiefgegangen; deshalb gibt es ihn nur noch hier.
    """
    wert = ((a.get("einsatz") or {}).get("transparenzpflicht") or {}).get("wert")
    return wert if isinstance(wert, bool) else None


def _zusammenfassung(akten: List[Dict[str, Any]], sprache: str) -> str:
    """
    Der Satz im hellblauen Kasten.

    ZWEI Textquellen, bewusst getrennt (Pit, 02.08.): Creator und
    Broadcast protokollieren immer genau einen Clip - dort steht ein Satz
    in der Einzahl, ohne Zahlen und ohne Klammer-Mehrzahl. Nur das
    Projektprotokoll zaehlt. Solange sich beide eine Funktion teilten,
    stand auf einem Einzelblatt "1 Position(en), davon 1 vollstaendig
    generiert, 0 veraenderte Realaufnahmen".
    """
    de = sprache == "de"
    return _zusammenfassung_einzeln(akten[0], de) if len(akten) == 1 \
        else _zusammenfassung_projekt(akten, de)


def _zusammenfassung_einzeln(a: Dict[str, Any], de: bool) -> str:
    """Ein Clip: was er ist, und ob er zu kennzeichnen ist."""
    status = (a.get("herkunft") or {}).get("status") or STATUS_UNBEKANNT
    hand = a.get("angabe_quelle") == "hand"
    ton = a.get("medium") == "ton"

    was_de = {STATUS_VOLL: "ist vollständig KI-generiert",
              "hybrid": "ist eine veränderte Realaufnahme",
              "retusche": "ist eine retuschierte Realaufnahme"}.get(
                  status, "hat eine nicht feststellbare Herkunft")
    was_en = {STATUS_VOLL: "is fully AI-generated",
              "hybrid": "is modified real footage",
              "retusche": "is retouched real footage"}.get(
                  status, "has an origin that could not be determined")
    gegenstand_de = "Diese Tonaufnahme" if ton else "Dieser Clip"
    gegenstand_en = "This audio item" if ton else "This clip"
    # The gender carries into the next sentence: "Diese Tonaufnahme ...
    # Er begruendet" stood on a built sheet.
    es_de = "Sie" if ton else "Er"

    # Three states, three outputs. "noch nicht eingestuft" is written
    # out and never becomes a no (C2, Pit 02.08.).
    pflicht = _pflichtwert(a)
    if pflicht is True:
        folge_de = ("%s begründet nach Einschätzung des Produzenten eine "
                    "Transparenzpflicht nach Artikel 50 (4)." % es_de)
        folge_en = ("In the producer’s assessment it requires disclosure "
                    "under Article 50 (4).")
    elif pflicht is False:
        folge_de = ("%s begründet nach Einschätzung des Produzenten keine "
                    "Transparenzpflicht nach Artikel 50 (4)." % es_de)
        folge_en = ("In the producer’s assessment it does not require "
                    "disclosure under Article 50 (4).")
    else:
        folge_de = ("Ob %s eine Transparenzpflicht nach Artikel 50 (4) "
                    "begründet, ist noch nicht eingestuft." % es_de.lower())
        folge_en = ("Whether it requires disclosure under Article 50 (4) has "
                    "not been classified yet.")

    herkunft_de = (" Die Angaben zu dieser Position stammen aus einem "
                   "Hand-Eintrag des Produzenten, nicht aus einem "
                   "protokollierten Ablauf." if hand else
                   " Die Angaben wurden aus dem ausgeführten Ablauf "
                   "mitgeschrieben.")
    herkunft_en = (" The entries for this item come from a manual entry by "
                   "the producer, not from a logged workflow." if hand else
                   " The entries were recorded from the executed workflow.")

    if de:
        return "<b>%s %s.</b> %s%s" % (gegenstand_de, was_de, folge_de, herkunft_de)
    return "<b>%s %s.</b> %s%s" % (gegenstand_en, was_en, folge_en, herkunft_en)


def _zusammenfassung_projekt(akten: List[Dict[str, Any]], de: bool) -> str:
    """Viele Clips: hier wird gezaehlt - und der offene Zustand mitgezaehlt."""
    voll = sum(1 for a in akten if (a.get("herkunft") or {}).get("status") == STATUS_VOLL)
    veraendert = sum(1 for a in akten
                     if (a.get("herkunft") or {}).get("status") in ("hybrid", "retusche"))
    unklar = len(akten) - voll - veraendert
    ton = sum(1 for a in akten if a.get("medium") == "ton")
    ja = sum(1 for a in akten if _pflichtwert(a) is True)
    nein = sum(1 for a in akten if _pflichtwert(a) is False)
    offen_pflicht = sum(1 for a in akten if _pflichtwert(a) is None)
    hand = sum(1 for a in akten if a.get("angabe_quelle") == "hand")

    def stueck(zahl, text_de, text_en):
        if not zahl:
            return None
        return "%d %s" % (zahl, text_de if de else text_en)

    art = [s for s in (stueck(voll, "vollständig generiert", "fully generated"),
                       stueck(veraendert, "veränderte Realaufnahmen",
                              "modified real footage"),
                       stueck(unklar, "ohne feststellbare Herkunft",
                              "without determinable origin"),
                       stueck(ton, "davon Tonpositionen", "of them audio")) if s]
    pflicht = [s for s in (stueck(ja, "mit Transparenzpflicht",
                                  "requiring disclosure"),
                           stueck(nein, "ohne Transparenzpflicht",
                                  "not requiring disclosure"),
                           stueck(offen_pflicht, "noch nicht eingestuft",
                                  "not classified yet")) if s]

    # Here too no bracket plural: "1 Position(en)" is exactly the
    # convenience Pit objected to on the single sheet.
    def zahlwort(n, ein_de, viele_de, ein_en, viele_en):
        return "%d %s" % (n, (ein_de if n == 1 else viele_de) if de
                          else (ein_en if n == 1 else viele_en))

    if de:
        satz = ("Die Produktion enthält <b>%s mit KI-Anteil</b>: %s."
                % (zahlwort(len(akten), "Position", "Positionen", "", ""),
                   ", ".join(art)))
        satz += " Nach Einschätzung des Produzenten: %s." % ", ".join(pflicht)
        if hand:
            satz += (" %s beruht auf Hand-Eintrag, %s aus dem ausgeführten "
                     "Ablauf mitgeschrieben."
                     % (zahlwort(hand, "Position", "Positionen", "", ""),
                        zahlwort(len(akten) - hand, "Position wurde",
                                 "Positionen wurden", "", "")))
        else:
            satz += " Alle Positionen wurden aus dem ausgeführten Ablauf mitgeschrieben."
        return satz
    satz = ("This production contains <b>%s with AI involvement</b>: %s."
            % (zahlwort(len(akten), "", "", "item", "items"), ", ".join(art)))
    satz += " In the producer’s assessment: %s." % ", ".join(pflicht)
    if hand:
        satz += (" %s a manual entry, %s recorded from the executed workflow."
                 % (zahlwort(hand, "", "", "item is", "items are"),
                    zahlwort(len(akten) - hand, "", "", "item was", "items were")))
    else:
        satz += " All items were recorded from the executed workflow."
    return satz


def _protokoll_umfang(akten: Any, sprache: str = "en") -> str:
    """
    Der Satz darüber, was in der Datenakte steht - abhängig davon, was wirklich
    drinsteht.

    Vorher stand hier fest: "A full production log with models, checksums and
    prompts exists and is available on request." Beim Creator-Knoten stimmt das
    nicht: der setzt den Prompt-Modus fest auf "nur_pruefsumme", der Prompt liegt
    also gar nicht im Klartext vor. Ein Dokument, das ein vollständiges
    Protokoll verspricht, das es nicht gibt, ist genau der Fehler, gegen den
    dieses Werkzeug gebaut ist.

    Der Satz muss in jedem Fall wahr sein, ohne dass jemand nachschauen muss.
    """
    if isinstance(akten, dict):
        akten = [akten]
    akten = [a for a in (akten or []) if a]

    maschinell = [a for a in akten if a.get("angabe_quelle") != "hand"]
    voll = [a for a in maschinell
            if (a.get("prompt") or {}).get("modus") == "vollstaendig"]

    if not maschinell:
        return ("Alle Positionen in diesem Dokument sind Hand-Einträge des "
                "Produzenten. Es wurde kein Ablauf maschinell mitgeschrieben."
                if sprache == "de" else
                "Every item in this document is a manual entry by the creator. "
                "No workflow data was recorded automatically.")
    if len(voll) == len(maschinell):
        return ("Ein vollständiges Herstellungsprotokoll mit Modellen, Prüfsummen "
                "und Prompts liegt bei diesem Dokument und ist auf Anfrage "
                "verfügbar."
                if sprache == "de" else
                "A full production log with models, checksums and prompts is stored "
                "with this record and available on request.")
    if not voll:
        return ("Die Datenakte zu diesem Dokument enthält Modelle, Prüfsummen und "
                "Parameter. Der Prompt ist nur als Prüfsumme festgehalten, nicht "
                "im Klartext."
                if sprache == "de" else
                "The data record stored with this document holds models, checksums "
                "and parameters. The prompt is kept as a checksum only, not in "
                "plain text.")
    return ("Die Datenakten zu diesem Dokument enthalten Modelle, Prüfsummen und "
            "Parameter. Bei einem Teil der Positionen ist der Prompt nur als "
            "Prüfsumme festgehalten, nicht im Klartext."
            if sprache == "de" else
            "The data records stored with this document hold models, checksums and "
            "parameters. For some items the prompt is kept as a checksum only, not "
            "in plain text.")


def _bindung_zeile(akten: Any, sprache: str = "de") -> str:
    """
    Der Satz darüber, was die Prüfsummen binden - abhängig vom Bestand (Z-1).

    Vorher stand in Abschnitt 3 fest: "Jede Ergebnisdatei ist über ihre
    an ihren Eintrag gebunden." Ohne übergebene Ergebnisdatei steht im
    Nachweis "nicht übergeben" - und Abschnitt 3 behauptete zwei Seiten
    später trotzdem "jede". Wortlaute: Pit, 31.07.
    """
    if isinstance(akten, dict):
        akten = [akten]
    akten = [a for a in (akten or []) if a]
    ohne = sum(1 for a in akten if not (a.get("ergebnis") or {}).get("sha256"))

    if not akten or ohne == len(akten):
        satz = ("Es wurde keine Ergebnisdatei übergeben; das Dokument ist an "
                "keine Datei gebunden."
                if sprache == "de" else
                "No result file was supplied; this document is not bound to any "
                "file.")
    elif ohne == 0:
        satz = ("Jede Ergebnisdatei ist über ihre Prüfsumme an ihren Eintrag "
                "gebunden."
                if sprache == "de" else
                "Every result file is bound to its entry by its checksum.")
    else:
        satz = ("Wo eine Ergebnisdatei übergeben wurde, ist sie über ihre "
                "Prüfsumme an ihren Eintrag gebunden. Bei %d Position(en) wurde "
                "keine übergeben." % ohne
                if sprache == "de" else
                "Where a result file was supplied, it is bound to its entry by "
                "its checksum. For %d item(s) none was supplied." % ohne)

    # The suffix qualifies WHAT the checksum binds. If no file is bound
    # at all there is nothing to qualify - then it is dropped entirely.
    # (Corrected 31.07.: the first rule "in all three cases" produced, in
    # the "no file" case, a sentence about a file that does not exist.)
    gebunden = ohne < len(akten)
    stapel = any(((a.get("ergebnis") or {}).get("bilder") or 0) > 1 for a in akten)
    if gebunden and stapel:
        satz += (" Bei mehreren Bildern eines Laufs bindet die Prüfsumme die "
                 "genannte Datei, nicht den gesamten Stapel."
                 if sprache == "de" else
                 " Where one run produced several images, the checksum binds the "
                 "named file, not the whole batch.")
    return satz


def _erfassung_satz(akten: Any) -> str:
    """
    Der erste Punkt im Scope-Block der Fassung K (Beobachtung 2, 31.07.).

    Ein Projektblatt kann automatisch erfasste Positionen UND Hand-Einträge
    mischen. Der bisherige Satz stand pauschal über allen - auch über den
    Hand-Einträgen, deren Ablauf nie mitgeschrieben wurde. Bei gemischter Lage
    sagt der Punkt das jetzt; bei rein automatischer bleibt der bisherige Satz,
    die reine Hand-Lage benennt der dritte Punkt (_protokoll_umfang).
    Wortlaut: Pit, 31.07.
    """
    if isinstance(akten, dict):
        akten = [akten]
    akten = [a for a in (akten or []) if a]
    hand = [a for a in akten if a.get("angabe_quelle") == "hand"]
    if hand and len(hand) < len(akten):
        return ("For the items recorded in ComfyUI, the workflow data above was "
                "recorded automatically at generation time, not entered "
                "afterwards. Items marked as manual entries were supplied by the "
                "creator. Classification, source origin and the labelling "
                "details are statements by the creator.")
    return ("The workflow data above was recorded automatically at generation "
            "time, not entered afterwards. Classification, source origin and "
            "the labelling details are statements by the creator.")


def _datenakte_satz(akten: Any, sprache: str = "de") -> str:
    """
    Was in der Datenakte maschinenlesbar liegt - abhängig vom Prompt-Modus (Z-4).

    "Enthaelt alle Angaben" stimmt bei nur_pruefsumme nicht: der Prompt liegt
    dort nur als Prüfsumme. Dieselbe Fehlerklasse wie der Satz in Fassung K.
    Wortlaute: Pit, 31.07.
    """
    if isinstance(akten, dict):
        akten = [akten]
    akten = [a for a in (akten or []) if a]
    maschinell = [a for a in akten if a.get("angabe_quelle") != "hand"]
    voll = [a for a in maschinell
            if (a.get("prompt") or {}).get("modus") == "vollstaendig"]

    if maschinell and len(voll) == len(maschinell):
        return ("Die Datenakte enthält alle Angaben dieses Dokuments "
                "maschinenlesbar."
                if sprache == "de" else
                "The data record holds every entry of this document in "
                "machine-readable form.")
    if not voll:
        return ("Die Datenakte enthält die Angaben dieses Dokuments "
                "maschinenlesbar; der Prompt liegt dort nur als Prüfsumme."
                if sprache == "de" else
                "The data record holds the entries of this document in "
                "machine-readable form; the prompt is kept there as a checksum "
                "only.")
    return ("Die Datenakten enthalten die Angaben dieses Dokuments "
            "maschinenlesbar; bei einem Teil der Positionen liegt der Prompt "
            "dort nur als Prüfsumme."
            if sprache == "de" else
            "The data records hold the entries of this document in "
            "machine-readable form; for some items the prompt is kept there as "
            "a checksum only.")


def _stapel_hinweis(a: Dict[str, Any], sprache: str = "de") -> Optional[str]:
    """
    Sagt, worauf sich das Blatt bezieht, wenn ein Lauf mehrere Bilder erzeugt hat.

    Ohne diesen Satz sieht ein Blatt über acht Bilder aus wie eines über eines -
    zumal die Prüfsumme nur eine einzige Datei binden kann.
    """
    anzahl = (a.get("ergebnis") or {}).get("bilder")
    try:
        anzahl = int(anzahl)
    except (TypeError, ValueError):
        return None
    if anzahl <= 1:
        return None

    gebunden = bool((a.get("ergebnis") or {}).get("sha256"))
    en = ("This record covers <b>%d images</b> produced in one run. Workflow, "
          "models, prompt and origin are identical for all of them. %s"
          % (anzahl, "The checksum binds one of these files."
             if gebunden else "No output file was supplied, so no checksum "
                              "binds this record to a specific image."))
    if sprache == "en":
        return en
    text = ("Dieses Blatt bezieht sich auf <b>%d Bilder</b> aus einem Lauf. Ablauf, "
            "Modelle, Prompt und Herkunft sind für alle gleich. %s"
            % (anzahl, "Die Prüfsumme bindet eine dieser Dateien."
               if gebunden else "Es wurde keine Ergebnisdatei übergeben, also "
                                "bindet keine Prüfsumme das Blatt an ein "
                                "bestimmtes Bild."))
    if sprache == "beide":
        text += ("<br/><font size=\"7\" color=\"#666666\">This record covers %d images "
                 "produced in one run.</font>" % anzahl)
    if sprache == "en+de":
        return ("%s<br/><font size=\"7\" color=\"#666666\">Dieses Blatt bezieht "
                "sich auf %d Bilder aus einem Lauf.</font>" % (en, anzahl))
    return text


def _stufen_zeile(a: Dict[str, Any], sp) -> Optional[str]:
    """
    Die Rechenschritte einzeln - nur wenn es mehr als einen gibt.

    Bei einem zweistufigen Aufbau gehoert der Seed nicht als ein Wert ins
    Dokument: er gehoert zu genau einem der beiden Schritte. Wer beide zu einer
    Zeile verruehrt, schreibt am Ende den Seed des falschen hinein.
    """
    stufen = a.get("sampler_stufen") or []
    if len(stufen) < 2:
        return None

    teile = []
    for i, s in enumerate(stufen, 1):
        erz = s.get("erzeugt")
        marke = (sp("erzeugend", "generating") if erz is True else
                 sp("ohne Rauschen", "no noise added") if erz is False else
                 sp("unbekannt", "undetermined"))
        werte = {k: v for k, v in (s.get("werte") or {}).items()
                 if k != "add_noise"}
        # A stage only stands here because it was found in the read graph -
        # here "keine" is always a genuine measured statement.
        text = (", ".join("%s %s" % (k, v) for k, v in werte.items())
                or sp("keine", "none", klein=False))
        offen = s.get("nicht_bestimmbar") or []
        if offen:
            text += " · %s: %s" % (sp("nicht feststellbar", "not determinable"),
                                        ", ".join(offen))
        teile.append("<b>%s %d</b> (%s): %s"
                     % (sp("Stufe", "Stage", klein=False), i, marke, text))
    return "<br/>".join(teile)


def _einzelnachweis(nr: Optional[int], a: Dict[str, Any], ordner: str,
                    zweisprachig: bool = True,
                    vorspann: Optional[List[Any]] = None) -> KeepTogether:
    """
    Der Nachweis zu EINER Position.

    `nr` ist die Positionsnummer im Projektdokument. Beim Einzelblatt ist
    sie None: dort gibt es nur einen Clip, und "#1" behauptet eine
    Zaehlung, die keine ist (Pit, 02.08.).

    `vorspann` kommt MIT IN dieselbe Bindung - der Abschnittsbalken hat
    dort seinen Platz. Ihn stattdessen um diese Bindung herum zu legen
    kostete eine ganze Seite: zwei ineinander geschachtelte
    KeepTogether rechnen ihren Platzbedarf grosszuegiger, und das
    englische Sender-Blatt wurde davon vier statt drei Seiten lang
    (gemessen 02.08.).
    """
    # Fixed language order of the document: English, German small below -
    # or English only if the client is not German-speaking.
    sp = lambda de, en, klein=True: _sp("en+de" if zweisprachig else "en",
                                        de, en, klein)
    herk = a.get("herkunft") or {}
    status = herk.get("status") or "unbekannt"
    eins = a.get("einsatz") or {}
    erg = a.get("ergebnis") or {}
    par = a.get("parameter") or {}
    pr = a.get("prompt") or {}

    # The preview image decides the width of the value column - and with
    # it the columns of the model table. Hence BEFORE the rows.
    #
    # The label column is 36 mm wide. Measured: below that,
    # "Disclosure type Art. 50 (4) / Art der Kennzeichnung Art. 50 (4)"
    # breaks into three to four lines; from 36 mm on EVERY label stays
    # at two at most (Pit, 02.08.). The 8 mm come off the preview image.
    bild = _bild((erg.get("vorschau") or {}).get("datei"), ordner, 34 * mm)
    labelbreite = 36 * mm
    wertbreite = (92 if bild else 138) * mm

    hand = a.get("angabe_quelle") == "hand"
    farbe = (colors.HexColor("#8A6D1F") if hand else
             colors.HexColor("#1F4E79") if status == STATUS_VOLL
             else colors.HexColor("#5A7A2E"))
    # The tick repeats here, where the classification stands anyway
    # (Pit, 02.08.): the coloured patch alone carries nothing in black
    # and white. Manual entries get none - nothing was measured there
    # that could be ticked.
    _bezeichner = (eins.get("szene") or erg.get("datei")
                   or "<i>%s</i>" % _fehlt(sp))
    titel = Tabelle([[Paragraph("<b>%s%s</b>"
                              % ("#%d &nbsp; " % nr if nr else "",
                                 _bezeichner), S_H2),
                    "" if hand else _kaestchen(True, 3.2 * mm, colors.white),
                    Paragraph((sp("HAND-EINTRAG", "MANUAL ENTRY", klein=False) if hand
                               else _status_text(status, englisch=not zweisprachig)),
                              ParagraphStyle("r", fontName="Helvetica-Bold", fontSize=8,
                                             leading=10, alignment=TA_RIGHT,
                                             textColor=colors.white))]],
                  colWidths=[118 * mm, 6 * mm, 50 * mm])
    titel.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), HELL),
                               ("BACKGROUND", (1, 0), (2, 0), farbe),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 5),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                               ("RIGHTPADDING", (1, 0), (1, 0), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))

    # Missing values: "nicht angegeben" = nobody said it,
    # "keine" = looked and found nothing. Classified per field.
    # "keine" only if the graph could be read at all - otherwise it
    # would be a measured statement without a measurement.
    gelesen = _ablauf_gelesen(a)
    offen = "<i>%s</i>" % _fehlt(sp)                    # statement missing
    keine = "<i>%s</i>" % _fehlt(sp, gemessen=gelesen)  # absence
    _wz = a.get("werkzeug") or {}
    _tc = " \u2013 ".join(t for t in (eins.get("timecode_start"),
                                 eins.get("timecode_ende")) if t)
    _quelle_wert = _schuetzen((a.get("quellen_herkunft") or {}).get("wert")) \
        if (a.get("quellen_herkunft") or {}).get("wert") else ""

    zeilen = [
        ("Timecode", _tc or offen),
        (sp("Grund f\u00fcr den KI-Einsatz", "Reason for AI use"),
         eins.get("zweck") or offen),
        # Only what exists gets joined - a missing ComfyUI version must not
        # tear a blank into the line.
        (sp("Werkzeug", "Tool"),
         " \u00b7 ".join(t for t in (" ".join(x for x in (_wz.get("name"),
                                                     _wz.get("version")) if x),
                                _wz.get("art")) if t) or offen),
        # The models as a small table - one row per model, each cell with
        # its own translation. Set one below the other they read as one
        # paragraph, and the small lines all stood at the end instead of
        # with their model (Pit, 02.08.).
        (sp("Modell", "Model"),
         _modelltabelle_b(a.get("modelle") or [], wertbreite, sp, gelesen)),
        # Measured absence: the graph was read, and there were no auxiliary
        # processes and no image sources in it.
        (sp("Modifikatoren", "Modifiers"),
         ", ".join(a.get("modifikatoren") or []) or keine),
        (sp("Referenzen", "References"),
         ", ".join(q.get("datei") or q.get("typ") or "?"
                   for q in (a.get("quellen") or [])) or keine),
        (sp("Art der Kennzeichnung Art. 50 (4)", "Disclosure type Art. 50 (4)"),
         {"deepfake": sp("realistischer Inhalt \u2013 sichtbarer Hinweis",
                         "realistic content \u2013 visible label"),
          "kuenstlerisch": sp("k\u00fcnstlerisches Werk \u2013 dezenter Hinweis",
                              "artistic work \u2013 discreet notice"),
          "ausserhalb": sp("offensichtlich fantastisch \u2013 keine Pflicht",
                           "clearly fantastical \u2013 no disclosure"),
          }.get((a.get("einstufung") or {}).get("wert"),
                sp("<i>nicht eingestuft</i>", "<i>not classified</i>"))),
        # Build BOTH language versions completely and only then stack them -
        # `sp(...)` inside the bracket let the line break and font change
        # fall right into it: "(stated by the producer / Angabe des
        # Produzenten)" stood there as one torn-apart bracket.
        (sp("Herkunft der Quelle", "Source origin"),
         sp("%s <i>(Angabe des Produzenten)</i>" % _quelle_wert,
            "%s <i>(stated by the producer)</i>" % _quelle_wert)
         if _quelle_wert else offen),
        # Measured absence: the graph had no settings.
        # Unresolvable single values stand separately under
        # "Rechenschritte" as "nicht feststellbar" - nothing is silently
        # lost here.
        (sp("Parameter", "Parameters"),
         ", ".join("%s %s" % (k, v) for k, v in par.items()) or keine),
        (sp("Ergebnisdatei", "Result file"),
         ("%s \u00b7 SHA-256 %s" % (erg.get("datei"), _kurz(erg.get("sha256"), 12)))
         if erg.get("sha256")
         else sp("<i>nicht \u00fcbergeben</i>", "<i>not supplied</i>",
                 klein=False)),
        *([(sp("Ver\u00f6ffentlicht auf", "Published on"),
            a.get("veroeffentlicht_auf"))]
          if (a.get("veroeffentlicht_auf") or "").strip() else []),
        (sp("Erstellt am", "Created"),
         (a.get("erzeugt_am") or "").replace("T", " ")[:19] or offen),
        (sp("Creator", "Creator"), a.get("ersteller") or offen),
        (sp("Status", "Status"),
         sp(" \u2013 ".join(t for t in (_status_text(status, englisch=False),
                                   herk.get("begruendung")) if t),
            " \u2013 ".join(t for t in (_status_text(status),
                                   herk.get("begruendung_en")
                                   or herk.get("begruendung")) if t))),
    ]

    # Several compute steps: then the seed stands not on top but here - per stage.
    stufen_text = _stufen_zeile(a, sp)
    if stufen_text:
        zeilen.insert(9, (sp("Rechenschritte", "Sampling stages"), stufen_text))

    stapel = _stapel_hinweis(a, "en+de" if zweisprachig else "en")
    if stapel:
        zeilen.insert(0, (sp("Umfang", "Scope"), stapel))

    if bild:
        block = Tabelle([[_felder(zeilen, breiten=(labelbreite, wertbreite)), bild]],
                      colWidths=[labelbreite + wertbreite,
                                 SATZBREITE - labelbreite - wertbreite])
        block.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("BOX", (1, 0), (1, 0), 0.5, LINIE),
                                   # Mittig im Kasten, nicht oben links
                                   # angeklebt (Pit, 09.08.).
                                   ("ALIGN", (1, 0), (1, 0), "CENTER"),
                                   ("VALIGN", (1, 0), (1, 0), "MIDDLE"),
                                   ("LEFTPADDING", (1, 0), (1, 0), 3),
                                   ("RIGHTPADDING", (1, 0), (1, 0), 3),
                                   ("TOPPADDING", (1, 0), (1, 0), 3),
                                   ("BOTTOMPADDING", (1, 0), (1, 0), 3)]))
    else:
        # The same label column even without a preview image - otherwise the
        # longest label would break into three lines again there.
        block = _felder(zeilen, breiten=(labelbreite, wertbreite))

    teile = [titel, Spacer(1, 2 * mm), block, Spacer(1, 2 * mm)]
    if hand:
        teile.append(_kasten([Paragraph(
            sp("Diese Position ist au\u00dferhalb von ComfyUI entstanden. Alle Angaben "
               "stammen vom Produzenten und wurden nicht maschinell gepr\u00fcft.",
               "This item was produced outside ComfyUI. All entries come from the producer "
               "and were not machine-verified."), S_TXT)],
            fuell=SAND, rand=SANDR, pad=5))
        teile.append(Spacer(1, 2 * mm))

    # references / keyframes as small images - recognition instead of file name
    ref = []
    for q in (a.get("quellen") or []):
        rb = _bild(q.get("vorschau"), ordner, 26 * mm)
        if rb is not None:
            _kachel = Tabelle([[rb], [Paragraph((q.get("datei") or "")[:34], S_KLEIN)]],
                              colWidths=[26 * mm])
            # Mittig in der 30-mm-Spalte (Pit, 09.08.).
            _kachel.hAlign = "CENTER"
            ref.append(_kachel)
    if ref:
        while len(ref) < 5:
            ref.append("")
        rt = Tabelle([ref[:5]], colWidths=[30 * mm] * 5)
        rt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("TOPPADDING", (0, 0), (-1, -1), 0)]))
        teile += [Paragraph(sp("Referenzen / Keyframes", "References / keyframes",
                       klein=False), S_LAB), Spacer(1, 1 * mm),
                  rt, Spacer(1, 2 * mm)]

    if pr.get("modus") == "nur_pruefsumme":
        # Without a prompt there is no checksum over it either. The sentence
        # then says what is, instead of claiming a checksum and putting a
        # dash behind it.
        if pr.get("sha256"):
            _prompt_satz = sp("Nicht offengelegt. Pr\u00fcfsumme SHA-256 %s \u2013 "
                              "belegt, dass der Text nachtr\u00e4glich nicht "
                              "ge\u00e4ndert wurde." % _kurz(pr.get("sha256"), 16),
                              "Not disclosed. Checksum SHA-256 %s \u2013 proves the "
                              "text was not changed afterwards."
                              % _kurz(pr.get("sha256"), 16))
        else:
            _prompt_satz = sp("Im Ablauf stand kein Prompt-Text. Es gibt "
                              "deshalb auch keine Pr\u00fcfsumme dar\u00fcber.",
                              "The workflow carried no prompt text. There is "
                              "therefore no checksum over one.")
        teile.append(_kasten([Paragraph("Prompt", S_LAB),
                              Paragraph(_prompt_satz, S_MONO)]))
    else:
        zusatz = ("" if pr.get("zuordnung") != "nutzer"
                  else sp(" \u2013 Zuordnung durch den Produzenten",
                          " \u2013 assigned by the producer", klein=False))
        # Measured absence: the graph had no text on this side. "nicht
        # angegeben" would be wrong here - nobody forgot it, there was
        # none. Only if reading really happened.
        _leer = "<i>%s</i>" % _fehlt(sp, gemessen=gelesen)
        inhalt = [Paragraph("Prompt" + zusatz, S_LAB),
                  Paragraph(_schuetzen(pr.get("positiv")) if pr.get("positiv")
                            else _leer, S_MONO),
                  Spacer(1, 3),
                  Paragraph(sp("Negativ-Prompt", "Negative prompt", klein=False), S_LAB),
                  Paragraph(_schuetzen(pr.get("negativ")) if pr.get("negativ")
                            else _leer, S_MONO)]
        ohne = pr.get("texte_ohne_rolle") or []
        if ohne:
            inhalt += [Spacer(1, 3),
                       Paragraph(sp("Texte aus dem Ablauf \u2013 Prompt und Negativ-Prompt "
                                    "waren nicht zu unterscheiden",
                                    "Texts from the workflow \u2013 prompt and negative "
                                    "prompt could not be told apart",
                                    klein=False), S_LAB)]
            for t in ohne[:4]:
                inhalt.append(Paragraph(_schuetzen(t), S_MONO))
        teile.append(_kasten(inhalt))

    return KeepTogether((vorspann or []) + teile)


def _schuetzen(text: Optional[str]) -> str:
    """
    Sonderzeichen fuer reportlab entschaerfen.

    Fehlt der Text, steht dort "nicht angegeben" statt eines
    Gedankenstrichs. Wer stattdessen die ZEILE weglassen will, prueft den
    Wert vorher selbst - das tun die Aufrufer, bei denen es darauf
    ankommt.
    """
    if not text:
        return "<i>%s</i>" % _fehlt()
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _fassung_k_projekt(akten: List[Dict[str, Any]], pfad: str, ordner: str,
                       projekt: Optional[str]) -> str:
    """Creator-Fassung für ein ganzes Projekt - Bildübersicht plus Tabelle."""
    kennung = kennung_bauen(akten=akten)
    _ZELLEN.clear()
    # A collection is recognisable AS a collection (Pit, 09.08.): the head
    # band says CREATOR \u00b7 PROJECT, like the file name says PROJECT_. The
    # single sheet stays untouched. Measured: the label is 37,7 mm wide
    # and leaves 99,3 mm to the wordmark in the 174-mm band.
    doc = _dok_neu(pfad, "VALYDA AI Protocol \u2013 Creator \u00b7 Project",
                   "CREATOR \u00b7 PROJECT", kennung, mit_kopfzeile=True)
    e: List[Any] = []

    e.append(Kopfband("Creator \u00b7 Project", kennung))
    e.append(Spacer(1, 6 * mm))
    # English ONLY, like the single sheet (language rule 01.08.).
    e.append(TitelNeu("Record of AI classification and labelling \u2013 project",
                      "Article 50 Regulation (EU) 2024/1689"))
    e.append(Spacer(1, 3 * mm))

    titel = projekt or next((a.get("projekt") for a in akten if a.get("projekt")),
                            "<i>%s</i>" % _fehlt())
    # Counted THREE-VALUED (same error class as C2): "deepfake" and
    # "kuenstlerisch" demand disclosure, "ausserhalb" is a decided no -
    # everything else is NOT classified and may appear in neither of the
    # first two numbers. Before, "0 item(s) require disclosure" stood
    # there while both items below carried "not classified": undecided
    # had become a zero.
    kz_ja = sum(1 for a in akten
                if (a.get("einstufung") or {}).get("wert") in ("deepfake", "kuenstlerisch"))
    kz_nein = sum(1 for a in akten
                  if (a.get("einstufung") or {}).get("wert") == "ausserhalb")
    kz_offen = len(akten) - kz_ja - kz_nein
    voll = sum(1 for a in akten if (a.get("herkunft") or {}).get("status") == STATUS_VOLL)
    veraendert = sum(1 for a in akten
                     if (a.get("herkunft") or {}).get("status") in ("hybrid", "retusche"))
    offen = len(akten) - voll - veraendert

    # Provenance three-valued as well: "modified real footage" used to
    # count len(akten) - voll, turning an undeterminable provenance into
    # modified real footage. The third share only appears if it exists -
    # as in the project summary of the broadcast sheet.
    _anteile = "%d fully generated, %d modified real footage" % (voll, veraendert)
    if offen:
        _anteile += ", %d without determinable origin" % offen

    e.append(_felder([
        ("Project", titel),
        ("Items with AI", "%d \u00b7 %s" % (len(akten), _anteile)),
        # Three states, three numbers - a never-classified item appears in
        # no count as a "no".
        ("Disclosure", "%d require disclosure under Article 50 (4), "
                       "%d do not, %d not classified yet"
                       % (kz_ja, kz_nein, kz_offen)),
        ("Created", time.strftime("%Y-%m-%d %H:%M")),
        # Id and storage: see fassung_k - the id is in the header line of
        # every page, the storage path does not belong in the document.
    ], breiten=(30 * mm, 144 * mm)))
    e.append(Spacer(1, 6 * mm))

    # The Creator project sheet is English WITHOUT EXCEPTION - including
    # the contact-sheet legend (found in the end-to-end run, case A/C).
    kontakt = _kontaktbogen(akten, ordner, zweisprachig=False)
    if kontakt:
        e += kontakt
        e.append(Spacer(1, 6 * mm))

    kopf = ["", "Item", "AI involvement", "Classification", "Disclosure applied", "Shown from"]
    daten = [[Paragraph(x, S_TH) for x in kopf]]
    sp_en = lambda de, en, klein=True: en
    for i, a in enumerate(akten, 1):
        herk = a.get("herkunft") or {}
        kz = a.get("kennzeichnung") or {}
        einst = (a.get("einstufung") or {}).get("wert") or "unbekannt"
        eins = a.get("einsatz") or {}
        # item line: timecode small under the label, only if set.
        posten = _schuetzen(eins.get("szene")
                            or (a.get("ergebnis") or {}).get("datei"))
        if eins.get("timecode_start"):
            posten = "%s<br/><font size='6.6' color='#666666'>TC %s</font>" % (
                posten, eins["timecode_start"])
        # Every produced document says which model was used (Pit, 02.08.) -
        # at ITS item, small under the name, not merged in the header
        # block: a project can mix Kling and a local model, and one shared
        # line would discard which clip was computed with what. Form as
        # everywhere: Bezeichnung (Rolle) · Nachweis; the checksum
        # reference points to the data file, for this sheet has no
        # section 2. An auxiliary model stands there too and carries its
        # open role.
        _ms = a.get("modelle") or []
        for m in _ms:
            posten += ("<br/><font size='6.6' color='#666666'>%s (%s) · %s</font>"
                       % (_umbrechen(_schuetzen(_modellname(m)), 44 * mm - 10,
                                     grad=6.6),
                          _rolle_text(m, sp_en),
                          _nachweis_text(m, sp_en, abschnitt2=False)))
        if not _ms:
            # No model surveyed: that is said explicitly - not nothing, no
            # dash. Without a readable graph it is not a measured statement,
            # and that is stated alongside.
            posten += ("<br/><font size='6.6' color='#666666'>%s</font>"
                       % ("no model recorded" if _ablauf_gelesen(a) else
                          "no model recorded — workflow was not readable"))
        daten.append([
            Paragraph("#%d" % i, S_TD),
            Paragraph(posten, S_TD),
            Paragraph(_status_text(herk.get("status") or STATUS_UNBEKANNT), S_TD),
            Paragraph({"deepfake": "<b>Realistic content</b>",
                       "kuenstlerisch": "Artistic work",
                       "ausserhalb": "Clearly fantastical"}.get(einst, "not classified"), S_TD),
            # Three states here too: without any disclosure statement it is
            # NOT decided that none would be needed (C2).
            Paragraph((kz.get("wortlaut") or "<i>%s</i>" % _fehlt())
                      if kz.get("erforderlich") is True else
                      "not required" if kz.get("erforderlich") is False else
                      "<i>not classified yet</i>", S_TD),
            Paragraph(kz.get("sichtbar_ab") or "<i>%s</i>" % _fehlt(), S_TD),
        ])
    t = Tabelle(daten, colWidths=[8 * mm, 44 * mm, 30 * mm, 28 * mm, 40 * mm, 24 * mm],
              repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, LINIE),
                           ("BACKGROUND", (0, 0), (-1, 0), HELL),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3)]))
    e.append(t)
    e.append(Spacer(1, 6 * mm))

    # Scope block AND signature as ONE unit - the same signed-off rule as
    # in fassung_k and fassung_s: the signature never stands alone on a
    # page (Pit, 02.08.).
    t = Tabelle([["", ""]], colWidths=[85 * mm, 89 * mm], rowHeights=[9 * mm])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (0, 0), 0.5, TINTE)]))
    e.append(KeepTogether([
        Paragraph("Scope of this record", S_H2),
        Paragraph(
            # Z-5, project version: automatically surveyed items and manual
            # entries can be mixed here - the first item then says what
            # applies to which.
            "\u2022&nbsp; %s<br/>"
            "\u2022&nbsp; Classification under Article 50 (4) is the creator\u2019s "
            "assessment, not legal advice.<br/>"
            "\u2022&nbsp; %s<br/>"
            "\u2022&nbsp; This is a self-declaration by the creator. It is not a "
            "proof of authenticity."
            % (_erfassung_satz(akten), _protokoll_umfang(akten, "en")), S_TXT),
        Spacer(1, 8 * mm),
        t,
        Paragraph("Place, date, signature", S_KLEIN),
    ]))

    doc.build(e, canvasmaker=_SeitenKanvas)
    _zellen_schreiben(pfad)
    return pfad


# ---------------------------------------------------------------- declaration sheet
class _BlattKanvas(Canvas):
    """
    Schreibt unten rechts "Blatt X von Y" - Y kennt man erst, wenn das letzte
    Blatt gebaut ist. Deshalb sammelt dieser Canvas die Seiten und traegt die
    Blattzahl beim Speichern nach (das uebliche reportlab-Verfahren).
    """

    def __init__(self, *args, **kwargs):
        Canvas.__init__(self, *args, **kwargs)
        self._blaetter = []

    def showPage(self):
        self._blaetter.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        gesamt = len(self._blaetter)
        for stand in self._blaetter:
            self.__dict__.update(stand)
            self.setFont("Helvetica", 6.8)
            self.setFillColor(GRAU)
            self.drawRightString(A4[0] - 18 * mm, 10.5 * mm,
                                 "Blatt %d von %d" % (self._pageNumber, gesamt))
            Canvas.showPage(self)
        Canvas.save(self)


def _bogen_rahmen(kennung: str, erstellt_am: str):
    """Kopf- und Fusszeile des Erklaerungsbogens. Die Blattzahl rechts unten
    schreibt _BlattKanvas beim Speichern - vorher ist sie nicht bekannt."""
    def zeichnen(c, d):
        c.saveState()
        b, h = A4
        c.setStrokeColor(LINIE)
        c.setLineWidth(0.4)
        c.line(18 * mm, h - 16 * mm, b - 18 * mm, h - 16 * mm)
        breite_marke = _gesperrt(c, 18 * mm, h - 14.2 * mm, "VALYDA AI PROTOCOL",
                                 "Helvetica-Bold", 6.8, GRAU, 0.9)
        c.setFillColor(GRAU)
        c.setFont("Helvetica", 6.8)
        # Layout rule 4: left and right blocks never touch.
        art = "ERKLAERUNGSBOGEN KI"
        links_x = 18 * mm + breite_marke + 8
        platz = (b - 18 * mm) - c.stringWidth(kennung, "Helvetica", 6.8) \
            - links_x - 8
        while art and c.stringWidth(art, "Helvetica", 6.8) > platz:
            art = art[:-1]
        c.drawString(links_x, h - 14.2 * mm, art)
        c.drawRightString(b - 18 * mm, h - 14.2 * mm, kennung)

        c.line(18 * mm, 14 * mm, b - 18 * mm, 14 * mm)
        # Footer: origin, proof, date - on the right, space remains for
        # "Blatt X von Y" (from _BlattKanvas). Measured, not estimated.
        fuss = ("Ausgefüllt aus dem VALYDA AI PROTOCOL · Angaben des "
                "Produzenten, kein Echtheitsnachweis · Beleg %s · %s"
                % (kennung, erstellt_am))
        platz = (b - 18 * mm) - c.stringWidth("Blatt 8 von 8", "Helvetica", 6.8) \
            - 18 * mm - 8
        while fuss and c.stringWidth(fuss, "Helvetica", 6.8) > platz:
            fuss = fuss[:-1]
        c.drawString(18 * mm, 10.5 * mm, fuss)
        c.setFont("Helvetica", 6.0)
        c.setFillColor(colors.HexColor("#999999"))
        c.drawString(18 * mm, 7.6 * mm,
                     "Completed from the VALYDA AI Protocol · statements by "
                     "the producer, not a proof of authenticity")
        c.restoreState()
    return zeichnen


def erklaerungsbogen(akten: List[Dict[str, Any]], pfad: str,
                     kopfdaten: Dict[str, Any],
                     ordner: Optional[str] = None) -> str:
    """
    Der Erklaerungsbogen KI als eigenes Blatt - inhaltsgleich mit Anlage 13
    der ARD Degeto Film GmbH (Stand 08.08.2025).

    ZITAT-REGELN (Pit, 01.08.):
    - Der Wortlaut der Erklaerung, der Verordnungsverweis und die fuenf
      Spaltenüberschriften stehen WORT FUER WORT wie im Original. Nichts
      glaetten, nichts modernisieren, keinen Tippfehler berichtigen.
    - Das Blatt ist UNSERES: kein Degeto-Briefkopf, keine Anschrift. Der Bezug
      steht in dem einen Satz unter dem Titel.
    - Deutsch ist Hauptsprache (Zitat), Englisch klein darunter.
    - Angekreuzt wird nur, was entschieden wurde. "not classified" bleibt
      unentschieden: beide Kaestchen leer, darunter der Hinweis mit der Zahl.
      Die Werte kommen aus der Akte - abgeleitet hat sie die EINE Stelle
      einstufung_aus_kennzeichnungsart() in nodes.py.
    """
    ordner = ordner or os.path.dirname(pfad) or "."
    _ZELLEN.clear()
    zitat = lambda de, en, klein=True: _sp("beide", de, en, klein)
    kennung = kopfdaten.get("kennung") or kennung_bauen(akten=akten)
    doc = BaseDocTemplate(pfad, pagesize=A4, leftMargin=18 * mm,
                          rightMargin=18 * mm, topMargin=22 * mm,
                          bottomMargin=18 * mm,
                          title="Erklärungsbogen KI", author=RECHTEINHABER,
                          creator="VALYDA AI Protocol")
    doc.addPageTemplates([PageTemplate(
        id="b", frames=[Frame(18 * mm, 18 * mm, A4[0] - 36 * mm, A4[1] - 40 * mm,
                              id="n", leftPadding=0, rightPadding=0,
                              topPadding=0, bottomPadding=0)],
        onPage=_bogen_rahmen(kennung, kopfdaten.get("erstellt_am") or ""))])
    e: List[Any] = []

    e.append(Kopfbalken("Erklärungsbogen KI", "AI declaration form"))
    e.append(Spacer(1, 7 * mm))
    e.append(Titelzeile("Erklärungsbogen KI", "AI declaration form"))
    e.append(Spacer(1, 2 * mm))
    e.append(Paragraph(zitat(
        "Inhaltsgleich mit Anlage 13 der ARD Degeto Film GmbH (Stand "
        "08.08.2025). Wortlaut der Erklärung unverändert "
        "übernommen.",
        "Identical in content to Annex 13 of ARD Degeto Film GmbH (as of "
        "08.08.2025). The wording of the declaration is quoted unchanged."),
        S_TXT))
    e.append(Spacer(1, 4 * mm))

    e.append(_felder([
        (zitat("Produktion", "Production"),
         "<b>%s</b>" % (kopfdaten.get("projekt") or "—")),
        (zitat("Produzent", "Producer"),
         kopfdaten.get("produzent")
         or zitat("<i>nicht angegeben</i>", "<i>not stated</i>")),
    ]))
    e.append(Spacer(1, 5 * mm))

    # Read three-valued - _pflichtwert() is the ONE place for that.
    pflichtig = [a for a in akten if _pflichtwert(a) is True]
    ohne_pflicht = [a for a in akten if _pflichtwert(a) is False]
    unentschieden = [a for a in akten if _pflichtwert(a) is None]

    e.append(Paragraph("In der Produktion <b>%s</b> ist/sind"
                       % (kopfdaten.get("projekt")
                          or "<i>nicht angegeben</i>"), S_TXT))
    e.append(Spacer(1, 3 * mm))
    # QUOTATION - the wording of Anlage 13, character for character.
    # Checked against the original PDF on 01.08.2026 (Pit). Three corrections:
    #
    #   1. The first tick line "keinerlei KI generierter Inhalt enthalten"
    #      stands HERE again. It had been removed on 30.07. - but that
    #      applied to section 4 of our own document, not to this sheet.
    #      It claims under its title that the wording of the declaration
    #      was adopted unchanged; a missing line made that sentence
    #      false. It is never ticked - the sheet only comes about when AI
    #      was involved - but it stands there as an empty box like in
    #      the original.
    #   2. "KI Verordnung" WITHOUT a hyphen in both tick sentences. The
    #      table header of the original writes "KI-Verordnung" WITH one -
    #      this inconsistency belongs to the original and is adopted.
    #   3. "Konkreter Einsatz/Szene" without spaces around the slash
    #      (table header further down).
    #
    # NOTHING is smoothed here and no typo is corrected.
    #   4. All four tick texts are UNDERLINED in the original.
    #   5. The two sub-items are indented: the box stands at the left
    #      margin as in the first two lines, the TEXT begins about 5 cm
    #      further right - and the following line sits on the same
    #      indent (hence leftIndent in the paragraph, not spaces).
    kreuz = [
        (False, "<u>keinerlei KI generierter Inhalt enthalten</u>", False),
        (None, "<u><b>KI generierte Inhalte enthalten</b>, wie unten stehend "
               "aufgelistet,</u>", False),
        (bool(ohne_pflicht),
         "<u>die <b>keine</b> Transparenzpflicht nach Artikel 50 (4) "
         "KI Verordnung (Verordnung (EU) 2024/1689) begründen</u>", True),
        (bool(pflichtig),
         "<u>die <b>eine</b> Transparenzpflicht nach Artikel 50 (4) "
         "KI Verordnung (Verordnung (EU) 2024/1689) begründen</u>", True),
    ]
    S_ZITAT_EIN = _st("zitat_ein", fontSize=8.5, leading=11, leftIndent=50 * mm)
    t = Tabelle([[("" if a is None else _kaestchen(a)),
                  Paragraph(b, S_ZITAT_EIN if eingerueckt else S_WERT)]
                 for a, b, eingerueckt in kreuz], colWidths=[8 * mm, 166 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    e.append(t)
    if unentschieden:
        e.append(Spacer(1, 2 * mm))
        e.append(Paragraph(zitat(
            "Bei %d Position(en) wurde die Transparenzpflicht nicht "
            "entschieden; dafür wurde nichts angekreuzt."
            % len(unentschieden),
            "For %d item(s) the disclosure obligation was not decided; "
            "nothing was ticked for those." % len(unentschieden)), S_KLEIN))
    e.append(Spacer(1, 5 * mm))

    e.append(CondPageBreak(55 * mm))
    e.append(Paragraph(zitat("Auflistung:", "List of items:", klein=False),
                       S_H2_ZUSAMMEN))
    e.append(Spacer(1, 2 * mm))
    # The five columns of the original, headings in full wording.
    # "Konkreter Einsatz/Szene" WITHOUT spaces around the slash - that is
    # how it stands there (checked 01.08.). The table header writes
    # "KI-Verordnung" WITH a hyphen, the tick sentences above without:
    # the inconsistency belongs to the original.
    kopf = [zitat("Konkreter Einsatz/Szene", "Item / scene"),
            zitat("Name KI-System", "AI system"),
            zitat("Zweck des Einsatzes", "Purpose of use"),
            zitat("Transparenzpflicht gemäß Artikel 50 (4) "
                  "KI-Verordnung", "Disclosure obligation under "
                  "Article 50 (4) AI Act"),
            "TC"]
    daten = [[Paragraph(x, S_TH) for x in kopf]]
    for a in akten:
        eins = a.get("einsatz") or {}
        tp = _pflichtwert(a)
        daten.append([
            Paragraph(eins.get("szene")
                      or (a.get("ergebnis") or {}).get("datei") or "—", S_TD),
            # The column is 30 mm wide here, 33 mm in the enumeration.
            Paragraph(_ki_system(a, 30 * mm - 6), S_TD),
            Paragraph(eins.get("zweck") or "—", S_TD),
            Paragraph("<b>ja</b>" if tp is True else
                      "nein" if tp is False else
                      zitat("<i>nicht entschieden</i>", "<i>not decided</i>"),
                      S_TD),
            Paragraph(eins.get("timecode_start") or "—", S_TD),
        ])
    # More than six items: the table continues, repeatRows repeats the
    # header row on the following sheet, _BlattKanvas writes the page
    # number. A broadcaster with twelve shots expects exactly that.
    t = Tabelle(daten, colWidths=[44 * mm, 30 * mm, 45 * mm, 30 * mm, 25 * mm],
                repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, LINIE),
                           ("BACKGROUND", (0, 0), (-1, 0), HELL),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3)]))
    e.append(t)

    e.append(Spacer(1, 12 * mm))
    t = Tabelle([["", ""]], colWidths=[85 * mm, 89 * mm], rowHeights=[10 * mm])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (0, 0), 0.5, TINTE)]))
    e.append(t)
    e.append(Paragraph(zitat("Ort, Datum, Unterschrift",
                             "Place, date, signature", klein=False), S_KLEIN))

    doc.build(e, canvasmaker=_BlattKanvas)
    _zellen_schreiben(pfad)
    return pfad
