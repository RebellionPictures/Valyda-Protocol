/**
 * VALYDA Protokoll - user interface extension
 * (c) Rebellion Pictures Berlin
 *
 * Draws the VALYDA emblem and the preview image into the node.
 *
 * Two ways on purpose:
 *   1. a DOM widget - works in the new ComfyUI node renderer
 *   2. canvas hooks - kept for older builds that still draw nodes themselves
 * Whichever one the running frontend supports will take effect. Purely cosmetic,
 * it never touches the logic.
 *
 * NOTE: plain ASCII on purpose. Some builds serve .js without a charset header.
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const VALYDA_NODES = new Set([
  "ValydaProtokollInternational",
  "ValydaProtokollSender",
  "ValydaProtokollBuendeln",
]);

const GRUEN = "#B5D93A";
const DUNKEL = "#14161A";
const MITTELPUNKT = "\u00b7";
// Zeigt in der Feldbeschriftung nach OBEN: die Zeile ist ohne die darueber
// unvollstaendig ("Veroeffentlicht auf Festival, und zwar Berlinale 2027").
const PFEIL_HOCH = "\u21b3";

// Optical centre of the emblem file, measured over the alpha channel
// (0.85 centre of mass + 0.15 centre of area): 0.4014 of the height from
// the top. A geometrically centred emblem shifts down by (0.5 - 0.4014)
// of its height - same correction as in the PDF (_logo_mitte).
const EMBLEM_VERSATZ = 0.0986;

const ZIELGRUPPE = {
  ValydaProtokollInternational: "web " + MITTELPUNKT + " social " + MITTELPUNKT + " festival",
  ValydaProtokollSender: "broadcast delivery " + MITTELPUNKT + " Sender-Anlieferung",
  ValydaProtokollBuendeln: "once at the end / einmal am Ende",
};

// Wofuer der Knoten da ist - muss auf den ersten Blick lesbar sein.
// Englisch oben, Deutsch klein darunter (Pit, 01.08.); der Creator ist
// AUSNAHMSLOS englisch und hat keine deutsche Zeile.
const RECHTSBEZUG = {
  ValydaProtokollInternational:
    { en: "Record under Article 50 EU AI Act", de: "" },
  ValydaProtokollSender:
    { en: "Record under Article 50 EU AI Act " + MITTELPUNKT + " broadcast delivery",
      de: "Nachweis nach Artikel 50 EU-KI-Verordnung " + MITTELPUNKT + " Sender-Anlieferung" },
  ValydaProtokollBuendeln:
    { en: "Project protocol under Article 50 EU AI Act",
      de: "Projektprotokoll nach Artikel 50 EU-KI-Verordnung" },
};

const PLATZIERUNG = {
  ValydaProtokollInternational:
    { en: "Place at the END of your workflow - it reads everything that leads into it",
      de: "" },
  ValydaProtokollSender:
    { en: "Always at the END of your workflow",
      de: "Immer ans ENDE des Workflows h\u00e4ngen" },
  ValydaProtokollBuendeln:
    { en: "Run once at the end of the production",
      de: "Einmal am Ende der Produktion ausf\u00fchren" },
};

// Die laufende Plugin-Fassung. Sie steht an genau EINER Stelle - in
// pyproject.toml; die kleine Route /valyda/fassung reicht sie herueber.
// Einmal geholt, dann gemerkt. Sie erscheint klein und grau im Banner-Kopf:
// damit laesst sich bei jeder Rueckfrage auf einen Blick sagen, welche
// Fassung laeuft. Zeigt ein Knoten KEINE Fassung, laeuft ein
// zwischengespeichertes altes JavaScript.
let fassungVersprechen = null;
function fassung_holen() {
  if (!fassungVersprechen) {
    fassungVersprechen = api.fetchApi("/valyda/fassung")
      .then((a) => a.json())
      .then((d) => (d && d.fassung ? String(d.fassung) : ""))
      .catch(() => "");
  }
  return fassungVersprechen;
}

const EMBLEM_DATEI = new URL("./valyda_logo_small.png", import.meta.url).href;

/**
 * Die Adresse des Emblems - MIT Versionsanhang.
 *
 * ComfyUI liefert die Web-Dateien einer Erweiterung ohne Versionsanhang aus.
 * Am 02.08. wurde das Emblem ausgetauscht, die Adresse blieb dieselbe - und
 * der Browser zeigte am Knoten weiter das alte Bild, waehrend das PDF (das
 * der Server aus derselben Quelle baut) laengst das neue trug. So ist es am
 * 03.08. aufgeschlagen.
 *
 * Der Grund ist gemessen, nicht vermutet: ComfyUIs eigenes
 * middleware/cache_middleware.py setzt fuer .js und .css "no-store", fuer
 * Bilder aber "public, max-age=86400". Das JavaScript ist also immer frisch -
 * ein Bild dagegen bleibt einen ganzen TAG im Zwischenspeicher des Browsers
 * und wird von dort genommen, ohne dass der Server je gefragt wird. Chrome
 * schliessen hilft nicht: die Frist laeuft nach der Uhr, nicht nach Sitzungen.
 *
 * Der Anhang aendert die Adresse mit jeder Fassung. Damit ist es ein anderer
 * Eintrag im Zwischenspeicher, das neue Bild kommt sofort - und weil das
 * JavaScript nie zwischengespeichert wird, greift es beim naechsten Laden der
 * Seite. Das gilt auch fuer jeden spaeteren Nutzer nach einer Aktualisierung,
 * ohne dass er etwas von Zwischenspeichern wissen muss.
 *
 * Die Nummer wird hier NICHT hingeschrieben - sie kommt aus fassung_holen()
 * und damit aus pyproject.toml. Eine Fassung, eine Stelle.
 */
let emblemAdresse = null;
function emblem_adresse() {
  if (!emblemAdresse) {
    emblemAdresse = fassung_holen().then(
      (f) => EMBLEM_DATEI + (f ? "?v=" + encodeURIComponent(f) : ""));
  }
  return emblemAdresse;
}

// for the canvas fallback
const emblem = new Image();
let emblemBereit = false;
emblem.onload = () => {
  emblemBereit = true;
  app.graph?.setDirtyCanvas(true, true);
};
emblem.onerror = () => console.warn("[VALYDA] emblem not reachable:", emblem.src);
// emblem_adresse() kann nicht scheitern - fassung_holen() faengt selbst ab und
// liefert im Zweifel die leere Fassung, dann eben die Adresse ohne Anhang.
emblem_adresse().then((u) => { emblem.src = u; });


/**
 * Removes the frontend's own video preview box from our nodes.
 *
 * Some ComfyUI builds attach a video preview to any node with a VIDEO input.
 * It cannot resolve an address here and shows "Video failed to load".
 * Our nodes never need it - the still image is the recognition value.
 * Only widgets that really carry a <video> element are touched; our own
 * banner is left alone.
 */
function videokasten_entfernen(node) {
  if (!node || !Array.isArray(node.widgets)) return 0;
  let weg = 0;
  for (let i = node.widgets.length - 1; i >= 0; i--) {
    const w = node.widgets[i];
    if (!w || w.name === "valyda_banner") continue;
    let istVideo = false;
    try {
      istVideo =
        /video/i.test(String(w.name || "")) ||
        (w.element && typeof w.element.querySelector === "function" &&
         !!w.element.querySelector("video"));
    } catch (e) { istVideo = false; }
    if (!istVideo) continue;
    try { w.element?.remove?.(); } catch (e) { /* ignore */ }
    node.widgets.splice(i, 1);
    weg++;
  }
  if (weg) node.setDirtyCanvas?.(true, true);
  return weg;
}

/**
 * Runs the server on the SAME machine as this browser?
 *
 * This decides whether "open folder" makes any sense: that button opens a
 * folder ON THE SERVER. Rented ComfyUI (RunPod, RunComfy, own server) would
 * open a window nobody can see.
 *
 * The check is the browser's own address. It is reliable in the direction
 * that matters: a remote address is NEVER the local machine, so the button
 * is correctly hidden there. The other direction can err on the safe side -
 * a tunnel (SSH, ngrok) shows up as 127.0.0.1 although the server is
 * elsewhere; then the button stays visible and does nothing visible. That is
 * why "open PDF" exists next to it: that one works everywhere.
 */
function server_ist_hier() {
  const h = window.location.hostname;
  return h === "127.0.0.1" || h === "localhost" || h === "[::1]" || h === "::1";
}

/**
 * Fetches a file through ComfyUI's own /view route - works everywhere,
 * local as well as rented: the file travels to the browser instead of a
 * window opening on the server.
 *
 * Verified against ComfyUI's server.py on 31.07.: /view serves arbitrary
 * files from the output directory, content type guessed from the name, so a
 * PDF arrives as application/pdf.
 */
function valyda_pdf_url(dok) {
  if (!dok || !dok.pfad) return null;
  const pfad = dok.pfad.replace(/\\/g, "/");
  const teile = pfad.split("/");
  const datei = teile.pop();
  // .../output/valyda/<Projekt>/datei.pdf  ->  subfolder "valyda/<Projekt>"
  const i = teile.lastIndexOf("output");
  if (i < 0) return null;
  const unterordner = teile.slice(i + 1).join("/");
  const p = new URLSearchParams({
    filename: datei,
    subfolder: unterordner,
    type: "output",
  });
  return api.apiURL("/view?" + p.toString());
}

/**
 * Asks the ComfyUI server to open a file or its folder.
 * A browser cannot do this itself - the small server behind ComfyUI can.
 */
async function valyda_oeffnen(pfad, ordner) {
  if (!pfad) return;
  try {
    const antwort = await api.fetchApi("/valyda/oeffnen", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pfad: pfad, ordner: !!ordner }),
    });
    const d = await antwort.json();
    if (!d.ok) console.warn("[VALYDA] not opened:", d.grund || "");
  } catch (e) {
    console.warn("[VALYDA] open request failed:", e);
  }
}

/**
 * Opens one result document the right way for where the server runs:
 * locally with the system viewer, remotely by fetching it into the browser.
 */
function dok_oeffnen(dok) {
  if (server_ist_hier()) {
    valyda_oeffnen(dok.pfad, false);
  } else {
    const url = valyda_pdf_url(dok);
    if (url) window.open(url, "_blank");
  }
}

/**
 * Live refresh for the production list on the bundle node.
 *
 * The usual order of work is: render clips, THEN bundle. So the project folder
 * is almost always created AFTER the page was loaded - and a list built only
 * at load time says "no project found" although the project exists.
 *
 * The list is fetched from the small server route /valyda/projekte (folder
 * names only, read-only) when the node is created and again whenever the node
 * is clicked. A value the user already picked is kept if it still exists.
 * The static list from INPUT_TYPES remains as the fallback if this script
 * does not run.
 */
const KEIN_PROJEKT = "kein Projekt gefunden";

async function projekte_holen() {
  try {
    const antwort = await api.fetchApi("/valyda/projekte");
    const d = await antwort.json();
    // "auswahl" ist die fertige Liste mit dem "neuestes Projekt"-Eintrag vorn -
    // der Wortlaut des Eintrags lebt auf dem Server, nicht hier. Der "hinweis"
    // (nur solange es noch keinen Projektordner gibt) ebenso: es ist derselbe
    // Wortlaut wie in der Laufzeit-Meldung des Buendeln-Knotens.
    if (Array.isArray(d.auswahl) && d.auswahl.length)
      return { liste: d.auswahl, hinweis: d.hinweis || "" };
    if (Array.isArray(d.projekte))
      return { liste: d.projekte, hinweis: d.hinweis || "" };
    return null;
  } catch (e) {
    return null;   // Route nicht da (alte Installation): statische Liste bleibt
  }
}

function produktion_aktualisieren(node) {
  if ((node?.comfyClass || node?.type) !== "ValydaProtokollBuendeln") return;
  const w = (node.widgets || []).find((x) => x && x.name === "Production");
  if (!w) return;
  projekte_holen().then((geholt) => {
    if (!geholt) return;
    const liste = geholt.liste;
    if (liste && liste.length) {
      w.options = w.options || {};
      w.options.values = liste;
      // Ein gewaehlter Wert bleibt erhalten, wenn es ihn noch gibt. Nur der alte
      // Platzhalter springt auf den "neuestes Projekt"-Eintrag (immer vorn).
      if (w.value === KEIN_PROJEKT || liste.indexOf(w.value) < 0) {
        w.value = liste[0];
      }
    }
    // C (Pit, 08.08.): solange es noch keinen Projektordner gibt, steht die
    // Auskunft, die sonst erst der Ausfuehren-Fehler gab, sichtbar am Knoten.
    const kasten = node.__valyda && node.__valyda.hinweis;
    if (kasten) {
      kasten.textContent = geholt.hinweis || "";
      kasten.style.display = geholt.hinweis ? "block" : "none";
    }
    node.setDirtyCanvas?.(true, true);
  });
}

/**
 * Die Akten-Auskunft am Buendeln-Knoten (Pit, 08.08.): zeigt, was die Akten
 * des gewaehlten Projekts fuer Producer / Co-Producer / Rights-Holder
 * liefern WUERDEN. Der Wortlaut kommt vom Server (/valyda/akten_auskunft) -
 * englische Zeile mit dem Wert, deutsche Kleinzeile ohne Wert.
 *
 * NUR ANZEIGE: kein Widget wird beschrieben. Der Einstimmigkeits-Abgleich
 * beim Ausfuehren rechnet weiter auf dem leeren Feld - probelauf.py wacht
 * darueber, mit Gegenprobe. Der "neuestes Projekt"-Eintrag wird bewusst
 * dem SERVER zum Aufloesen gegeben, dort ist der Ordnerstand aktuell.
 */
async function auskunft_aktualisieren(node) {
  if ((node?.comfyClass || node?.type) !== "ValydaProtokollBuendeln") return;
  const teile = node.__valyda;
  if (!teile || !teile.auskunft) return;
  const w = (node.widgets || []).find((x) => x && x.name === "Production");
  const projekt = w && w.value != null ? String(w.value) : "";
  let d = null;
  try {
    const antwort = await api.fetchApi(
      "/valyda/akten_auskunft?projekt=" + encodeURIComponent(projekt));
    d = await antwort.json();
  } catch (e) {
    d = null;   // Route nicht da (aeltere Installation): Kasten bleibt leer
  }
  const kasten = teile.auskunft;
  kasten.innerHTML = "";
  if (!d || !d.anzahl || !d.felder) {
    kasten.style.display = "none";
    node.setDirtyCanvas?.(true, true);
    return;
  }
  const FELDER = [["Producer", "Producer"], ["Co_Producer", "Co-Producer"],
                  ["Rights_Holder", "Rights-Holder"]];
  for (const [schluessel, name] of FELDER) {
    const f = d.felder[schluessel];
    if (!f) continue;
    const block = document.createElement("div");
    block.style.cssText = "margin-top:3px;";
    const feld = document.createElement("div");
    feld.textContent = name;
    feld.style.cssText = "color:#8b9098;font:600 8.5px sans-serif;";
    const en = document.createElement("div");
    en.textContent = f.en || "";
    en.style.cssText = "color:#D7DBD2;font:400 9.5px sans-serif;";
    const de = document.createElement("div");
    de.textContent = f.de || "";
    de.style.cssText = "color:#5c6169;font:400 8px sans-serif;";
    block.appendChild(feld);
    block.appendChild(en);
    block.appendChild(de);
    kasten.appendChild(block);
  }
  kasten.style.display = "block";
  node.setDirtyCanvas?.(true, true);
}

/**
 * Input mask for the Timecode fields of both per-clip nodes.
 *
 * The user types digits, the field inserts the colons itself:
 * 1 -> 1, 10 -> 10, 100 -> 10:0, 1000 -> 10:00, 10000000 -> 10:00:00:00.
 * After eight digits the field accepts nothing more.
 *
 * The mask is convenience only - the truth is made in Python, which cleans
 * the value again on the server. Both paths yield the same result.
 *
 * Safety rules:
 *  - it only touches an INPUT whose aria-label starts with "Timecode"
 *    (covers Timecode_In and Timecode_Out, with or without the German
 *    sublabel) AND whose node card belongs to one of our two per-clip
 *    nodes (data-node-id lookup)
 *  - it only reformats while the caret sits at the END of the field; editing
 *    in the middle is left completely alone - a jumping caret is worse than
 *    a missing colon
 *  - in the classic canvas renderer there is no persistent input element, so
 *    the mask simply stays inactive there
 */
const MASKE_KNOTEN = new Set(["ValydaProtokollSender", "ValydaProtokollInternational"]);
let maskeLaeuft = false;

function timecode_gruppieren(ziffern) {
  let raus = "";
  for (let i = 0; i < ziffern.length && i < 8; i++) {
    if (i > 0 && i % 2 === 0) raus += ":";
    raus += ziffern[i];
  }
  return raus;
}

document.addEventListener("input", function (ev) {
  if (maskeLaeuft) return;
  const el = ev.target;
  if (!el || el.tagName !== "INPUT") return;
  if (!/^Timecode/.test(el.getAttribute("aria-label") || "")) return;
  const karte = el.closest ? el.closest("[data-node-id]") : null;
  if (!karte) return;
  const knoten = app.graph?.getNodeById?.(Number(karte.getAttribute("data-node-id")));
  const art = knoten?.comfyClass || knoten?.type;
  if (!MASKE_KNOTEN.has(art)) return;

  const alt = el.value || "";
  const amEnde = el.selectionStart === alt.length && el.selectionEnd === alt.length;
  if (!amEnde) return;                    // mitten im Feld: nichts anfassen
  const neu = timecode_gruppieren(alt.replace(/\D/g, ""));
  if (neu === alt) return;
  maskeLaeuft = true;
  try {
    el.value = neu;
    el.setSelectionRange(neu.length, neu.length);
    // das Modell der Oberflaeche nachziehen (v-model haengt am input-Ereignis)
    el.dispatchEvent(new Event("input", { bubbles: true }));
  } finally {
    maskeLaeuft = false;
  }
}, true);

/**
 * Field labels (decision of 01.08., stage 1/2).
 *
 * ComfyUI widgets have ONE label baseline - a second line under the field
 * name does not exist (frontend 1.47.11, NODE_WIDGET_HEIGHT=20). So the
 * German term goes into the SAME line: "Production [middle dot] Produktion".
 * Implemented via widget.label, which the frontend demonstrably respects
 * (".label||this.name" in the bundle): DISPLAY ONLY - the serialized name
 * stays English, saved workflows are untouched.
 *
 * Creator stays monolingual English; Broadcast and Project carry the German
 * term. Umlaut-free by design, the middle dot is written as an escape -
 * this file stays plain ASCII.
 */
const FELD_DEUTSCH = {
  Production: "Produktion",
  Scene: "Szene / Sequenz",
  Reason_for_AI_Use: "Grund f\u00fcr den KI-Einsatz",
  Disclosure_Type: "Art der Kennzeichnung",
  Timecode_In: "Start-Timecode",
  Timecode_Out: "End-Timecode",
  Source_Footage: "Ausgangsmaterial",
  Creator: "Urheber",
  Producer: "Produzent",
  Co_Producer: "Co-Produzent",
  Broadcaster: "Sender / Auftraggeber",
  // Die Beschriftung zeigt nach OBEN: der Pfeil und "und zwar" machen
  // unmissverstaendlich, dass die Zeile ohne die darueber unvollstaendig
  // ist - man liest es als einen Satz (Pit, 01.08.). Als Escape, damit
  // diese Datei reines ASCII bleibt.
  Broadcaster_Name: PFEIL_HOCH + " genau " + MITTELPUNKT + " und zwar",
  Published_On: "Ver\u00f6ffentlicht auf",
  Published_On_Name: PFEIL_HOCH + " genau " + MITTELPUNKT + " und zwar",
  Rights_Holder: "Rechteinhaber",
  Output_File: "Name der Ausgabedatei",
  Reference_File: "Name der Bezugsdatei",
  Store_Prompt: "Prompt speichern",
  Prompt_Assignment: "Prompt-Zuordnung",
  Preview_In_Node: "Vorschau im Knoten",
  Version: "Fassung",
  Multiple_Runs: "Mehrfachl\u00e4ufe",
  Output: "Ausgabe",
  External_1: "Extern 1",
  External_2: "Extern 2",
  External_3: "Extern 3",
  External_4: "Extern 4",
  External_5: "Extern 5",
  Records_Folder: "Aktenordner",
};

function feldbeschriftung(node) {
  const art = node?.comfyClass || node?.type;
  if (!VALYDA_NODES.has(art)) return;
  const zweisprachig = art !== "ValydaProtokollInternational";
  for (const w of node.widgets || []) {
    if (!w || !w.name || w.name === "valyda_banner") continue;
    const en = w.name.replace(/_/g, " ");
    const de = FELD_DEUTSCH[w.name];
    w.label = zweisprachig && de && de !== en
      ? en + " " + MITTELPUNKT + " " + de
      : en;
  }
}

/** Builds the banner element: emblem on the left, wordmark, audience on the right. */
function banner(nodeName) {
  const wrap = document.createElement("div");
  wrap.style.cssText =
    "display:flex;flex-direction:column;gap:6px;width:100%;box-sizing:border-box;";

  const kopf = document.createElement("div");
  kopf.style.cssText =
    "display:flex;align-items:center;gap:10px;background:" + DUNKEL +
    ";" +
    ";border-radius:5px 5px 0 0;padding:9px 10px 6px 10px;box-sizing:border-box;" +
    "min-height:34px;";

  const bild = document.createElement("img");
  bild.alt = "VALYDA";
  emblem_adresse().then((u) => { bild.src = u; });
  // Optischer Versatz des Emblems: EMBLEM_VERSATZ der Bildhoehe nach unten
  // (18 px x 0.0986 = rund 2 px), dieselbe Korrektur wie im PDF.
  bild.style.cssText =
    "height:18px;display:block;flex:0 0 auto;position:relative;top:2px;";
  bild.onerror = () => { bild.style.display = "none"; };

  // Der Name (Pit, 01.08.): AI PROTOCOL, darunter klein KI-Protokoll -
  // ausser im Creator, der AUSNAHMSLOS englisch ist.
  const wort = document.createElement("span");
  wort.style.cssText = "display:flex;flex-direction:column;flex:1 1 auto;";
  const wortEn = document.createElement("span");
  wortEn.textContent = "AI PROTOCOL";
  wortEn.style.cssText =
    "color:#F2F4F0;font:600 11px sans-serif;letter-spacing:1.4px;";
  wort.appendChild(wortEn);
  if (nodeName !== "ValydaProtokollInternational") {
    const wortDe = document.createElement("span");
    wortDe.textContent = "KI-Protokoll";
    wortDe.style.cssText =
      "color:#7E868E;font:400 8px sans-serif;letter-spacing:.4px;margin-top:1px;";
    wort.appendChild(wortDe);
  }

  const ziel = document.createElement("span");
  ziel.textContent = ZIELGRUPPE[nodeName] || "";
  ziel.style.cssText = "color:#7E868E;font:400 9.5px sans-serif;white-space:nowrap;";

  // die laufende Plugin-Fassung, klein und grau neben der Zielgruppe
  const fassung = document.createElement("span");
  fassung.style.cssText =
    "color:#5c6169;font:400 8.5px sans-serif;white-space:nowrap;margin-left:6px;";
  fassung_holen().then((f) => { fassung.textContent = f ? "v" + f : ""; });

  kopf.appendChild(bild);
  kopf.appendChild(wort);
  kopf.appendChild(ziel);
  kopf.appendChild(fassung);

  // Zweite Zeile: wofuer das Ganze da ist - englisch, darunter klein deutsch.
  const bezug = RECHTSBEZUG[nodeName] || { en: "", de: "" };
  const zweck = document.createElement("div");
  zweck.style.cssText =
    "background:" + DUNKEL + ";color:#D7DBD2;font:600 10px sans-serif;" +
    "padding:6px 10px 3px 10px;box-sizing:border-box;";
  zweck.textContent = bezug.en;
  if (bezug.de) {
    const zweckDe = document.createElement("div");
    zweckDe.textContent = bezug.de;
    zweckDe.style.cssText = "color:#7E868E;font:400 8.5px sans-serif;";
    zweck.appendChild(zweckDe);
  }

  // Dritte Zeile: wohin der Knoten gehoert - englisch, darunter klein deutsch.
  const platz = PLATZIERUNG[nodeName] || { en: "", de: "" };
  const ort = document.createElement("div");
  ort.style.cssText =
    "background:" + DUNKEL + ";color:#8b9098;font:400 9px sans-serif;" +
    "padding:0 10px 7px 10px;border-radius:0 0 5px 5px;box-sizing:border-box;";
  ort.textContent = platz.en;
  if (platz.de) {
    const ortDe = document.createElement("div");
    ortDe.textContent = platz.de;
    ortDe.style.cssText = "color:#5c6169;font:400 8px sans-serif;";
    ort.appendChild(ortDe);
  }

  // gruene Trennlinie erst unter dem ganzen Kopfblock
  const linie = document.createElement("div");
  linie.style.cssText = "height:2px;background:" + GRUEN + ";";

  const vorschau = document.createElement("img");
  // Bewusst klein gehalten: es geht um Wiedererkennung, nicht um Bildbeurteilung.
  vorschau.style.cssText =
    "display:none;width:100%;max-height:150px;object-fit:contain;" +
    "border:1px solid #43484f;border-radius:4px;background:#111;box-sizing:border-box;";

  const zeile = document.createElement("div");
  zeile.style.cssText = "color:" + GRUEN + ";font:400 9.5px sans-serif;text-align:center;";

  // Wo das Dokument liegt - die wichtigste Zeile fuer den Nutzer.
  const ablage = document.createElement("div");
  ablage.style.cssText =
    "display:none;margin-top:5px;padding:5px 7px;border-radius:4px;" +
    "background:#1A1D21;border:1px solid #3c4149;box-sizing:border-box;";

  // Die Akten-Auskunft (nur Buendeln-Knoten, Pit 08.08.): was die Akten des
  // gewaehlten Projekts liefern wuerden. Gefuellt von
  // auskunft_aktualisieren() - die Felder selbst bleiben unberuehrt.
  const auskunft = document.createElement("div");
  auskunft.style.cssText =
    "display:none;margin-top:5px;padding:5px 7px;border-radius:4px;" +
    "background:#1A1D21;border:1px solid #3c4149;box-sizing:border-box;";

  // C (Pit, 08.08.): der Hinweis, solange es noch keinen Projektordner gibt.
  // Der Wortlaut kommt vom Server und ist derselbe wie in der
  // Laufzeit-Meldung - hier steht er schon VOR dem Ausfuehren.
  const hinweis = document.createElement("div");
  hinweis.style.cssText =
    "display:none;margin-top:5px;padding:5px 7px;border-radius:4px;" +
    "background:#1A1D21;border:1px solid #3c4149;color:#D7DBD2;" +
    "font:400 9.5px sans-serif;box-sizing:border-box;";

  wrap.appendChild(kopf);
  wrap.appendChild(zweck);
  wrap.appendChild(ort);
  wrap.appendChild(linie);
  wrap.appendChild(hinweis);
  wrap.appendChild(auskunft);
  wrap.appendChild(vorschau);
  wrap.appendChild(zeile);
  wrap.appendChild(ablage);
  wrap.__valyda = { vorschau: vorschau, zeile: zeile, ablage: ablage,
                    auskunft: auskunft, hinweis: hinweis };
  return wrap;
}

app.registerExtension({
  name: "valyda.protokoll.branding",

  async setup() {
    console.log("[VALYDA] branding extension active");
  },

  /** New renderer: put emblem and preview into the node as a DOM element. */
  async nodeCreated(node) {
    const art = node?.comfyClass || node?.type;
    if (!VALYDA_NODES.has(art)) return;
    if (typeof node.addDOMWidget !== "function") return;   // old build, canvas path takes over

    try {
      // Der Oberflaeche sagen, dass unsere Vorschau ein BILD ist. Ohne das haelt
      // sie den Knoten wegen des VIDEO-Eingangs fuer einen Video-Knoten und
      // versucht, das Vorschaubild als Film zu laden ("Video failed to load").
      try { node.previewMediaType = "image"; } catch (e) { /* ignore */ }

      feldbeschriftung(node);
      const el = banner(art);
      node.addDOMWidget("valyda_banner", "valyda", el, {
        serialize: false,
        hideOnZoom: false,
      });
      node.__valyda = el.__valyda;
      if (node.size && node.size[0] < 300) node.size[0] = 300;
      console.log("[VALYDA] banner attached:", art);
      // the frontend may add its own video box - remove it now and shortly after
      videokasten_entfernen(node);
      setTimeout(() => videokasten_entfernen(node), 400);
      setTimeout(() => videokasten_entfernen(node), 1500);

      // bundle node: keep the production list fresh. Refreshed when the node
      // is created and on every click on the node - the fetch is local and
      // lands before the dropdown opens.
      if (art === "ValydaProtokollBuendeln") {
        produktion_aktualisieren(node);
        auskunft_aktualisieren(node);
        const mausAlt = node.onMouseDown;
        node.onMouseDown = function () {
          produktion_aktualisieren(this);
          auskunft_aktualisieren(this);
          return mausAlt ? mausAlt.apply(this, arguments) : undefined;
        };
        // Die Auskunft folgt der Projekt-Auswahl: der Rueckruf des Feldes
        // wird umwickelt, nicht ersetzt.
        const wProd = (node.widgets || []).find((x) => x && x.name === "Production");
        if (wProd) {
          const rueckrufAlt = wProd.callback;
          wProd.callback = function () {
            const raus = rueckrufAlt ? rueckrufAlt.apply(this, arguments) : undefined;
            auskunft_aktualisieren(node);
            return raus;
          };
        }
      }
    } catch (e) {
      console.warn("[VALYDA] banner could not be attached:", e);
    }
  },

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!VALYDA_NODES.has(nodeData?.name)) return;
    const art = nodeData.name;
    const zielgruppe = ZIELGRUPPE[nodeData.name] || "";
    console.log("[VALYDA] node registered:", nodeData.name);

    // ---- show the preview once the run is finished
    const ausgefuehrtAlt = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      if (ausgefuehrtAlt) ausgefuehrtAlt.apply(this, arguments);
      try { this.previewMediaType = "image"; } catch (e) { /* ignore */ }
      videokasten_entfernen(this);
      setTimeout(() => videokasten_entfernen(this), 300);
      setTimeout(() => videokasten_entfernen(this), 1200);
      const teile = this.__valyda;
      if (!teile) return;

      // Der PDF-Kasten (Pit, 01.08., Etappe 4): hier bekommt der Nutzer sein
      // Ergebnis in die Hand. Bei mehreren Dokumenten (Protokoll,
      // Erklaerungsbogen, bei Output=both zwei Fassungen) sagt eine
      // BESCHRIFTUNG je Zeile, welches was ist - Beschriftung vor Gestaltung.
      // Jedes Dokument hat sein eigenes Knopfpaar; der Ordner steht einmal
      // unten, denn alle Dokumente eines Laufs liegen im selben Ordner.
      const doks = message?.valyda_pdf;
      if (doks && doks.length && teile.ablage) {
        teile.ablage.innerHTML = "";

        // Kopfzeile mit der UHRZEIT des Laufs. Sie beantwortet die Frage,
        // die Pit am 02.08. hatte: ist das, was ich hier sehe, von eben -
        // oder sehe ich noch das Ergebnis des vorigen Laufs? Die Zeit
        // kommt aus nodes._ui_dokument(); fehlt sie (aeltere Fassung),
        // bleibt die Zeile wie bisher.
        const kopfk = document.createElement("div");
        kopfk.style.cssText = "display:flex;align-items:baseline;gap:6px;" +
                              "margin-bottom:1px;";
        const kopftext = document.createElement("span");
        kopftext.textContent = "PROTOCOL SAVED";
        kopftext.style.cssText = "color:#c8e08a;font:700 10px sans-serif;" +
                                 "letter-spacing:.08em;";
        kopfk.appendChild(kopftext);
        if (doks[0].zeit) {
          const uhr = document.createElement("span");
          uhr.textContent = doks[0].zeit;
          uhr.style.cssText = "color:#c8e08a;font:400 9px monospace;" +
                              "opacity:.75;";
          kopfk.appendChild(uhr);
        }
        teile.ablage.appendChild(kopfk);
        if (art !== "ValydaProtokollInternational") {
          const kopfd = document.createElement("div");
          kopfd.textContent = "Protokoll gespeichert";
          kopfd.style.cssText = "color:#8b9098;font:400 8.5px sans-serif;" +
                                "margin-bottom:3px;";
          teile.ablage.appendChild(kopfd);
        }

        doks.forEach((dok, i) => {
          const datei = dok.datei || "";
          const englisch = art === "ValydaProtokollInternational";
          // Welches Dokument ist das? Aus dem Dateinamen abgelesen
          // (VALYDA-AI-PROTOCOL_Creator/_Broadcast, ..._Erklaerungsbogen-KI;
          // der PROJECT_-Vorsatz des Project-Knotens stoert die Teilstring-
          // Suche nicht, geprueft 09.08.).
          let beschriftung = "Broadcast Protocol " + MITTELPUNKT + " Sender-Protokoll";
          if (/Erklaerungsbogen-KI/i.test(datei)) {
            beschriftung = "Erkl\u00e4rungsbogen KI";
          } else if (/Creator/i.test(datei)) {
            beschriftung = "Creator Protocol";
          }

          const zeile = document.createElement("div");
          zeile.style.cssText = (i > 0 ? "margin-top:7px;" : "margin-top:3px;") +
            "padding-top:" + (i > 0 ? "6px;border-top:1px solid #33383f;" : "0;");

          const b = document.createElement("div");
          b.textContent = beschriftung;
          b.style.cssText = "color:#F2F4F0;font:600 10px sans-serif;";
          zeile.appendChild(b);

          // Der Dateiname ist die AUSKUNFT dieses Kastens, nicht sein
          // Kleingedrucktes: er sagt, welche der Dateien im Ordner gerade
          // entstanden ist. Vorher stand er in 8,5 px Grau unter der
          // Beschriftung und war neben dem gruenen Knopf nicht zu sehen
          // (Pit, 02.08. abends).
          const d = document.createElement("div");
          d.textContent = datei;
          d.style.cssText = "color:#E4E9E0;font:600 9.5px monospace;" +
                            "word-break:break-all;margin-top:2px;cursor:pointer;";
          d.title = englisch
            ? (server_ist_hier() ? "Click to open the document"
                                 : "Click to open the document in the browser")
            : (server_ist_hier()
               ? "Click to open " + MITTELPUNKT + " Dokument \u00f6ffnen"
               : "Click to open in the browser " + MITTELPUNKT
                 + " im Browser \u00f6ffnen");
          d.onclick = () => dok_oeffnen(dok);
          zeile.appendChild(d);

          const knopfzeile = document.createElement("div");
          knopfzeile.style.cssText = "display:flex;gap:5px;margin-top:4px;";

          // OPEN PDF: gruen und breit. Laeuft der Server hier, oeffnet das
          // System-Programm; laeuft er woanders, kommt die Datei in den
          // Browser (dort ist sie damit auch heruntergeladen).
          const oeffnen = document.createElement("div");
          oeffnen.textContent = "OPEN PDF";
          oeffnen.style.cssText =
            "flex:1 1 auto;padding:5px 8px;border-radius:4px;cursor:pointer;" +
            "background:" + GRUEN + ";color:" + DUNKEL + ";" +
            "font:700 10px sans-serif;text-align:center;letter-spacing:.05em;";
          oeffnen.title = englisch
            ? (server_ist_hier() ? "Opens the document"
                                 : "Fetches the document into the browser")
            : (server_ist_hier()
               ? "Opens the document " + MITTELPUNKT + " \u00d6ffnet das Dokument"
               : "Fetches the document into the browser " + MITTELPUNKT
                 + " holt es \u00fcber ComfyUI in den Browser");
          oeffnen.onclick = () => dok_oeffnen(dok);
          knopfzeile.appendChild(oeffnen);

          // "Folder" oeffnet ein Fenster AUF DEM SERVER - nur sinnvoll, wenn
          // der Server hier laeuft; sonst bleibt der Knopf weg.
          if (server_ist_hier()) {
            const ordner = document.createElement("div");
            ordner.textContent = "Folder";
            ordner.style.cssText =
              "flex:0 0 auto;padding:5px 9px;border:1px solid #4a5058;" +
              "border-radius:4px;color:#c8e08a;font:600 9.5px sans-serif;" +
              "text-align:center;cursor:pointer;background:#22262b;";
            ordner.title = englisch
              ? "Open the folder"
              : "Open the folder " + MITTELPUNKT + " Ordner \u00f6ffnen";
            ordner.onclick = () => valyda_oeffnen(dok.pfad, true);
            knopfzeile.appendChild(ordner);
          }
          zeile.appendChild(knopfzeile);
          teile.ablage.appendChild(zeile);
        });

        const o = document.createElement("div");
        o.textContent = (doks[0].ordner || "");
        o.style.cssText = "color:#7d838b;font:400 8.5px sans-serif;" +
                          "word-break:break-all;margin-top:6px;";
        teile.ablage.appendChild(o);

        // Der Satz, der Pits Frage beantwortet: jeder Lauf schreibt eine
        // NEUE Datei. Wer nach einer Aenderung in der Maske die zuvor
        // geoeffnete Datei ansieht, sieht den alten Stand - nicht, weil
        // etwas dauert, sondern weil daneben eine zweite Datei liegt.
        // Reine Anzeige, kein Bedienelement.
        const merk = document.createElement("div");
        merk.textContent = (art === "ValydaProtokollInternational")
          ? "Every run writes a NEW file - open the one named above."
          : "Every run writes a NEW file " + MITTELPUNKT
            + " jeder Lauf schreibt eine NEUE Datei";
        merk.style.cssText = "color:#8b9098;font:400 8px sans-serif;" +
                             "margin-top:3px;font-style:italic;";
        teile.ablage.appendChild(merk);
        teile.ablage.title = doks.map((x) => x.pfad || "").join("\n");
        teile.ablage.style.display = "block";

        // Klick auf das Vorschaubild oeffnet das Hauptdokument.
        if (teile.vorschau) {
          teile.vorschau.style.cursor = "pointer";
          teile.vorschau.title = (art === "ValydaProtokollInternational")
            ? "Click to open the protocol"
            : "Click to open the protocol " + MITTELPUNKT
              + " Protokoll \u00f6ffnen";
          teile.vorschau.onclick = () => dok_oeffnen(doks[0]);
        }
      }

      const bilder = message?.valyda_vorschau || message?.images;
      if (!bilder || !bilder.length) return;
      const b = bilder[0];
      try {
        const p = new URLSearchParams({
          filename: b.filename,
          subfolder: b.subfolder || "",
          type: b.type || "output",
          rand: String(Math.random()),
        });
        teile.vorschau.src = api.apiURL("/view?" + p.toString());
        teile.vorschau.style.display = "block";
        teile.zeile.textContent = b.filename;
        this.setDirtyCanvas?.(true, true);
      } catch (e) {
        console.warn("[VALYDA] preview could not be shown:", e);
      }
    };

    // ---- canvas path for older builds
    const titelAlt = nodeType.prototype.onDrawTitleText;
    nodeType.prototype.onDrawTitleText = function (ctx, titleHeight, size, scale, font) {
      if (this.flags?.collapsed) {
        if (titelAlt) titelAlt.apply(this, arguments);
        return;
      }
      let x = 10;
      const h = Math.round(titleHeight * 0.52);
      if (emblemBereit && emblem.naturalWidth) {
        const w = Math.round(h * (emblem.naturalWidth / emblem.naturalHeight));
        const y = -titleHeight + (titleHeight - h) / 2 + h * EMBLEM_VERSATZ;
        try {
          ctx.drawImage(emblem, x, y, w, h);
          x += w + 9;
        } catch (e) { /* draw on without the image */ }
      } else {
        ctx.save();
        ctx.font = "bold " + Math.round(titleHeight * 0.42) + "px sans-serif";
        ctx.fillStyle = GRUEN;
        ctx.fillText("VALYDA", x, -titleHeight * 0.3);
        x += ctx.measureText("VALYDA").width + 9;
        ctx.restore();
      }
      const roh = (this.title || "")
        .replace(/^VALYDA\s*(AI\s*PROTOCOL|PROTOKOLL)\s*[\u00b7\-|]?\s*/i, "")
        .replace(/\s*[\u2013-]\s*.*$/, "");
      ctx.save();
      ctx.font = "600 " + Math.round(titleHeight * 0.42) + "px sans-serif";
      ctx.fillStyle = "#F2F4F0";
      ctx.letterSpacing = "1.4px";
      ctx.fillText("AI PROTOCOL", x, -titleHeight * 0.3);
      x += ctx.measureText("AI PROTOCOL").width + 8;
      ctx.letterSpacing = "0px";
      // darunter ist im Titelband kein Platz - klein daneben, gemessen
      // angesetzt; der Creator ist AUSNAHMSLOS englisch
      if (art !== "ValydaProtokollInternational") {
        ctx.font = Math.round(titleHeight * 0.3) + "px sans-serif";
        ctx.fillStyle = "#7E868E";
        ctx.fillText("KI-Protokoll", x, -titleHeight * 0.3);
        x += ctx.measureText("KI-Protokoll").width + 12;
      } else {
        x += 4;
      }
      if (roh) {
        ctx.font = Math.round(titleHeight * 0.36) + "px sans-serif";
        ctx.fillStyle = "#98A0A8";
        ctx.fillText(roh, x, -titleHeight * 0.3);
      }
      if (zielgruppe && this.size && this.size[0] > 240) {
        ctx.font = Math.round(titleHeight * 0.32) + "px sans-serif";
        ctx.fillStyle = "#7E868E";
        ctx.textAlign = "right";
        ctx.fillText(zielgruppe, this.size[0] - 10, -titleHeight * 0.3);
        ctx.textAlign = "left";
      }
      ctx.restore();
    };

    const erstelltAlt = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = erstelltAlt ? erstelltAlt.apply(this, arguments) : undefined;
      this.color = "#1E2126";
      this.bgcolor = "#2B2F35";
      try { this.previewMediaType = "image"; } catch (e) { /* ignore */ }
      // also on the canvas path of older builds - litegraph draws
      // w.label || w.name, so the same mechanism works there
      try { feldbeschriftung(this); } catch (e) { /* ignore */ }
      return r;
    };
    try { nodeType.prototype.previewMediaType = "image"; } catch (e) { /* ignore */ }
  },
});
