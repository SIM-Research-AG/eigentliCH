"""The navigation hub: one page from which every built surface can be reached.

**Generated rather than written, and that is the whole point.** A hand-written index would list things that no
longer exist and miss things that do — this repo has nine Master Control versions, eight Schulung pages, six
prototype app versions and five household cockpits, and every one of those counts has changed. So the hub is
built by looking at the disk at request time: `exists` is checked, the newest of a versioned family is picked by
number rather than by memory, and anything absent is shown as absent instead of linked into a 404.

**It also tells the truth about what is and is not running.** The cockpits are separate processes on their own
ports (8801 Macro_Model, 8802 PCP, 8804 andersCH), not part of this program. The hub probes each one and says
whether it is up, because a link that silently fails teaches the reader that the system is broken when in fact a
service simply was not started.

**Links carry their folder, and that is a correctness fix rather than a tidy-up (9 August 2026).** Until then a
link was a bare filename and the server resolved it by walking an allow-list of directories in order. Four
directories are on that list and two of them contain an `index.html`, so the card labelled *Blueprint ·
Architecture and data flow* served `andersCH-prototype/index.html` — a 239 KB prototype page — because that
folder is searched first. Nothing was broken in a way anything could detect: the link returned 200, with the
wrong document. Naming the folder makes the collision impossible rather than unlikely, which is the same
reasoning `_serve_known_file` already applied to path traversal.

**And it was missing whole surfaces.** Measured the same day: the client plan pages, the Curator workbench, the
book in both HTML and PDF, both blueprint PDFs, the prototype app versions and the questionnaire itself were all
unreachable from here. A hub that cannot reach a third of what is built is a table of contents for a different
repository.
"""

from __future__ import annotations

import html
import re
import socket
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Folders the hub may link into, and therefore the folders `server._serve_known_file` will serve from. A link
#: is `folder/name`, so two files may share a name without shadowing each other.
LINKABLE: tuple[str, ...] = ("architecture", "dashboard", "andersCH-prototype", "blueprint", "book",
                             "client", "curator")

#: Extensions the hub links to, with the content type the server should send. PDFs are here because the book and
#: the blueprint both build to PDF and neither was reachable.
SERVABLE: dict[str, str] = {".html": "text/html; charset=utf-8", ".pdf": "application/pdf"}


@dataclass
class Item:
    title: str
    detail: str
    #: Repo-relative `folder/name`. Empty means "exists but is not a page", e.g. a group heading.
    path: str = ""
    exists: bool = True
    note: str = ""
    #: A route this program serves, rather than a file it hands out. **Kept separate from `path` rather than
    #: overloading it**, because `path` is matched against a directory listing by `server._serve_known_file`
    #: and a route would never be found there -- it would render as a link and 404, which is the worst of the
    #: three possible outcomes.
    route: str = ""

    @property
    def href(self) -> str:
        if self.route:
            return self.route
        return f"/file/{self.path}" if self.path else ""


@dataclass
class Service:
    title: str
    detail: str
    port: int


#: Separate processes, each with its own venv and its own CLI. Started independently of this program.
SERVICES = (
    Service("Macro_Model Cockpit", "Regimes, scenario generation, the macro state space", 8801),
    Service("PCP Cockpit", "Portfolio Creation Program: allocation and instrument selection", 8802),
    Service("andersCH Cockpit", "Cross-engine view; writes nothing by design", 8804),
)


def _newest_versioned(folder: Path, stem: str) -> tuple[Path | None, int]:
    """The highest-numbered file in a `name_N.html` family, with its number.

    Nine Master Control versions exist and the current one is whichever has the largest number — read off the
    disk, because a hard-coded 9 becomes wrong the day a 10 is written. The number is returned rather than
    re-derived by the caller: doing that regex twice is how the first version of this got `r'_(\\d+)'` — a RAW
    string containing a literal backslash, which matches nothing and made `.group(1)` raise on every request.
    """
    best, best_n = None, -1
    for p in folder.glob(f"{stem}_*.html"):
        m = re.search(r"_(\d+)\.html$", p.name)
        if m and int(m.group(1)) > best_n:
            best, best_n = p, int(m.group(1))
    return best, best_n


def _version_of(p: Path) -> int:
    """The `-vN` suffix of a versioned prototype, or 0 for the unversioned original."""
    m = re.search(r"-v(\d+)$", p.stem)
    return int(m.group(1)) if m else 0


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def _item(folder: str, name: str, title: str, detail: str, note: str = "") -> Item:
    p = ROOT / folder / name
    if p.exists() and p.suffix == ".pdf":
        note = (note + " · " if note else "") + f"PDF, {p.stat().st_size // 1024} KB"
    return Item(title, detail, f"{folder}/{name}", p.exists(), note)


def _sections() -> list[tuple[str, str, list[Item]]]:
    arch, dash, proto = ROOT / "architecture", ROOT / "dashboard", ROOT / "andersCH-prototype"
    bp, book, client_d, cur = ROOT / "blueprint", ROOT / "book", ROOT / "client", ROOT / "curator"

    # --- what a client touches -------------------------------------------------------------------
    # The book coach's readiness is two independent facts with two different remedies, so it is reported as
    # two: an index that was never built is one command, a daemon that is not running is another.
    idx_present = (ROOT / "desktop" / "bookindex" / "meta.json").exists()
    client: list[Item] = [
        Item("Onboarding (Chat)", "The client interview, then the real engine and the report. "
                                  "This program serves it at the root.", "", True, note="live"),
        Item("Wissenscoach", "Questions answered from the house's four documents, each claim shown against "
                             "the sentence it was verified against. Reads the corpus and nothing about any "
                             "household, so it carries no personal data at all. A question of law it "
                             "declines: none of the four is a legal source.",
             "", idx_present,
             note="im Fragebogen" if idx_present
                  else "index missing: python desktop/bookindex.py --build"),
        # The report path and the questionnaire handout are ROUTES, not files, and both are things somebody
        # goes looking for: "where do I get the report" and "which copy of the questionnaire is current".
        Item("Fragebogen herunterladen",
             "The interview file itself, served from this program so the copy handed out is by construction "
             "the one the engine will accept. Its schema version and hash are in the filename and the "
             "headers.", route="/questionnaire", note="eine Quelle der Wahrheit"),
        Item("Bericht aus einem fertigen Fragebogen",
             "An onboarding completed elsewhere produces a JSON file. Load it on the start screen of the "
             "interview and the full dossier is computed from it -- balance sheet, flows, gap, cash flow, "
             "bridge, levers, findings, allocation and schedule. No solve needed.",
             route="/", note="Startbildschirm, Datei laden"),
    ]
    # **Sorted by VERSION NUMBER, not by filename, and the difference is not cosmetic.** `anderschapp-v6.html`
    # and `anderschapp.html` both exist, and `-` sorts before `.`, so a plain name sort puts the UNVERSIONED
    # file last and picks the original as the newest. The unversioned one is v0 here, which is what it is.
    apps = sorted(proto.glob("anderschapp*.html"), key=_version_of)
    if apps:
        newest = apps[-1]
        client.append(_item("andersCH-prototype", newest.name, "Klienten-App",
                            "The client-facing app prototype: status, next steps, questions",
                            note=f"{newest.stem} · newest of {len(apps)}"))
    for p in sorted(client_d.glob("plan*.html")):
        client.append(_item("client", p.name, f"Plan · {p.stem.replace('plan-', '')}",
                            "A generated client plan page"))

    # --- worked dossiers -------------------------------------------------------------------------
    dossiers = [_item("andersCH-prototype", p.name,
                      f"Dossier · {p.stem.replace('gameplan-', '')}",
                      "A worked client dossier", note="test case")
                for p in sorted(proto.glob("gameplan-*.html"))]

    # --- the blueprint, both surfaces ------------------------------------------------------------
    blueprint = [
        _item("blueprint", "index.html", "Blueprint · Architecture and data flow",
              "The contract layer with its two boundaries, the client path, the engines, the ports",
              note="generated"),
        _item("blueprint", "modules.html", "Blueprint · Every module in its own words",
              "All modules outside the virtual environments, with their own docstrings, plus sequence "
              "diagrams and the five role paths", note="generated"),
        _item("blueprint", "index.pdf", "Blueprint · Architecture (print)", "The same page, paginated for A4"),
        _item("blueprint", "modules.pdf", "Blueprint · Modules (print)", "The same page, paginated for A4"),
    ]

    # --- the book --------------------------------------------------------------------------------
    books = [
        _item("book", "capital-saturation.html", "Capital Saturation · reading copy",
              "The set book as HTML, before pagination", note="generated"),
        _item("book", "capital-saturation.pdf", "Capital Saturation · the set book",
              "A5, 533 pages: 34 chapters, 7 parts, 4 appendices, bibliography, index"),
        _item("book", "capital-saturation-en.pdf", "Capital Saturation · published copy",
              "The copy published under the source's former name"),
        _item("book", "capital-saturation-en_OLD.pdf", "Capital Saturation · the source",
              "The original 604-page manuscript the set book was made from", note="source"),
    ]

    # --- programme status and per-household views -------------------------------------------------
    master, master_v = _newest_versioned(arch, "andersCH-Master-Control")
    cio: list[Item] = [
        Item("Master Control" + (f" (v{master_v})" if master else ""),
             "The programme's own status page: what exists, what is decided, what is open",
             f"architecture/{master.name}" if master else "", bool(master),
             note=f"newest of {len(list(arch.glob('andersCH-Master-Control_*.html')))}"),
    ]
    if (dash / "cockpit.html").exists():
        cio.append(_item("dashboard", "cockpit.html", "Cockpit overview", "The roll-up across households"))
    for p in sorted(dash.glob("cockpit-hh-*.html")):
        cio.append(_item("dashboard", p.name, f"Cockpit · {p.stem.replace('cockpit-hh-', 'hh-')}",
                         "One household, generated by dashboard/build.py"))
    if (cur / "workbench.html").exists():
        cio.append(_item("curator", "workbench.html", "Curator workbench",
                         "Where a Recommendation would be reviewed and recorded (G7)"))

    schulung = [
        _item("architecture", p.name, p.stem.replace("schulung-", "").replace("-", " ").title(),
              "How this engine works, with its live calibration")
        for p in sorted(arch.glob("schulung-*.html"))
    ]
    if (arch / "manual-gameplan.html").exists():
        schulung.insert(0, _item(
            "architecture", "manual-gameplan.html", "Handbuch · wie ein Gameplan gerechnet wird",
            "The working method: what to run, what to compute by hand, the recurring findings and the traps",
            note="method"))

    # --- everything else that is built and was previously unreachable from here -------------------
    #
    # These are the pages a reader looks for and could not get to: the questionnaire as a document rather than
    # as the live root, its earlier variants, the design reference the client surfaces are styled from, and
    # two decks. None of them is superseded — a superseded Master Control version is correctly not listed, but
    # a page nobody replaced is a gap.
    misc: list[Item] = []
    for folder, name, title, detail in (
        ("andersCH-prototype", "onboarding-chat.html", "Fragebogen (Quelle)",
         "The questionnaire as a file. This program serves the same file at the root."),
        ("andersCH-prototype", "onboarding-demo.html", "Fragebogen · Demo",
         "A walkthrough variant"),
        ("andersCH-prototype", "fragebogen-ceo-52.html", "Fragebogen · CEO 52",
         "An earlier questionnaire cut"),
        ("andersCH-prototype", "index.html", "Prototyp · Referenzseite",
         "The design reference the client surfaces take their palette from"),
        ("client", "index.html", "Client · Einstieg", "The client package's own entry page"),
        ("andersCH-prototype", "andersCH_sketches.pdf", "Skizzen", "Early design sketches"),
        ("andersCH-prototype", "different_intro_deck.pdf", "Intro-Deck", "An introduction deck"),
    ):
        it = _item(folder, name, title, detail)
        if it.exists:
            misc.append(it)

    return [
        ("Klient", "What a client sees and receives", client),
        ("Dossiers", "Worked cases. These contain real answers and are not in version control.", dossiers),
        ("Blueprint", "How the whole system fits together. Rebuilt from the repository by "
                      "tools/blueprint/build.py, so it cannot go stale in the way a written document does",
         blueprint),
        ("Buch", "Capital Saturation, set from book/manuscript/ by tools/book/press.py", books),
        ("CIO und Steuerung", "Programme status and per-household views", cio),
        ("Schulung", "One page per engine, built from the engines' own measured values", schulung),
        ("Weiteres", "Fragebogen-Varianten, Referenzseiten und Decks. Überholte Versionen einer "
                     "nummerierten Familie stehen bewusst nicht hier — die Übersicht verlinkt die neueste.",
         misc),
    ]


#: The palette of `andersCH-prototype/index.html`, so the hub belongs to the same system as the pages it opens.
#: Copied rather than imported because that file is a 239 KB prototype and this is a 6 KB navigation page; what
#: is shared is the design language, not the stylesheet.
_CSS = """
:root{
  --ink:#1A1740; --ink-soft:#5d4591; --ink-mute:#7E7AA0;
  --line:#ECE8F4; --surface:#FFFFFF; --surface-off:#FAFAFA; --surface-tint:#F6F4FB;
  --g0:#62BFE6; --g1:#8890E7; --g2:#A059C1; --g3:#FEA479; --g4:#FFE8A1;
  --primary:var(--g2); --primary-deep:#3A3080;
  --grad-sunrise:linear-gradient(110deg,var(--g1),var(--g2) 40%,var(--g3) 80%,var(--g4));
  --ok:#12795B;
}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-off);color:var(--ink);
 font:15px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif}
.wrap{max-width:1060px;margin:0 auto;padding:44px 22px 72px}
header{padding-bottom:24px;margin-bottom:8px;border-bottom:1px solid var(--line)}
.rule{height:4px;border-radius:4px;background:var(--grad-sunrise);margin-bottom:20px}
h1{font-size:28px;margin:0 0 8px;letter-spacing:-.3px;color:var(--primary-deep)}
.lead{color:var(--ink-mute);margin:0;max-width:64ch}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.1em;color:var(--primary);margin:0 0 4px}
section{margin:34px 0}
.sub{color:var(--ink-mute);font-size:13.5px;margin:0 0 14px;max-width:72ch}
.grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(274px,1fr))}
.it{display:block;background:var(--surface);border:1px solid var(--line);border-radius:14px;
 padding:14px 16px;text-decoration:none;color:inherit;
 transition:border-color .12s,box-shadow .12s,transform .12s}
a.it:hover{border-color:var(--primary);box-shadow:0 4px 16px rgba(26,23,64,.07);transform:translateY(-1px)}
.it.off{opacity:.48;background:var(--surface-tint)}
.t{font-weight:600;font-size:14.5px;color:var(--primary-deep)}
.d{color:var(--ink-mute);font-size:12.5px;margin-top:4px}
.d a{color:var(--primary)}
.tag{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--ink-mute);
 background:var(--surface-tint);border:1px solid var(--line);border-radius:20px;
 padding:2px 8px;margin-left:6px;white-space:nowrap;font-weight:500}
.tag.up{color:var(--ok);border-color:var(--ok);background:transparent}
footer{margin-top:44px;border-top:1px solid var(--line);padding-top:18px;
 color:var(--ink-mute);font-size:12.5px;max-width:74ch}
"""


def render(port: int) -> bytes:
    secs = _sections()
    live = [(s, _port_open(s.port)) for s in SERVICES]

    def card(i: Item) -> str:
        t = html.escape(i.title)
        d = html.escape(i.detail)
        note = f'<span class="tag">{html.escape(i.note)}</span>' if i.note else ""
        if not i.exists or not i.href:
            missing = "" if i.exists else " · nicht vorhanden"
            return (f'<div class="it off"><div class="t">{t} {note}</div>'
                    f'<div class="d">{d}{missing}</div></div>')
        return (f'<a class="it" href="{html.escape(i.href)}"><div class="t">{t} {note}</div>'
                f'<div class="d">{d}</div></a>')

    blocks = []
    for name, sub, items in secs:
        if not items:
            continue
        blocks.append(f'<section><h2>{html.escape(name)}</h2>'
                      f'<p class="sub">{html.escape(sub)}</p>'
                      f'<div class="grid">{"".join(card(i) for i in items)}</div></section>')

    svc = "".join(
        f'<div class="it {"" if up else "off"}">'
        f'<div class="t">{html.escape(s.title)} '
        f'<span class="tag {"up" if up else ""}">{"läuft" if up else "gestoppt"}</span></div>'
        f'<div class="d">{html.escape(s.detail)}<br>'
        + (f'<a href="http://127.0.0.1:{s.port}/">127.0.0.1:{s.port}</a>' if up
           else f'Port {s.port} — eigener Prozess, separat starten')
        + "</div></div>"
        for s, up in live
    )
    blocks.append('<section><h2>Eigene Dienste</h2>'
                  '<p class="sub">Separate Prozesse mit eigener Umgebung. Dieses Programm startet sie nicht — '
                  'es zeigt nur, ob sie erreichbar sind.</p>'
                  f'<div class="grid">{svc}</div></section>')

    n_links = sum(1 for _, _, items in secs for i in items if i.href and i.exists)
    doc = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>andersCH · Übersicht</title>
<style>{_CSS}</style></head><body><div class="wrap">
<header>
  <div class="rule"></div>
  <h1>andersCH · Übersicht</h1>
  <p class="lead">Alles, was gebaut ist, von einer Seite aus erreichbar. Diese Liste wird bei jedem Aufruf
  aus dem Dateisystem gelesen — was hier fehlt, existiert nicht, und was ausgegraut ist, wurde gesucht und
  nicht gefunden. Aktuell {n_links} erreichbare Seiten und Dokumente.</p>
</header>
{"".join(blocks)}
<footer>Lokales Programm auf 127.0.0.1:{port}. Es schreibt nichts auf die Festplatte und sendet nichts
ins Internet. Eine Standortbestimmung ist Bildung, keine Anlageberatung.</footer>
</div></body></html>"""
    return doc.encode("utf-8")
