"""draw.io diagrams for `study draw` (standard library only).

A diagram is one file, <Subject>/diagrams/<name>.drawio. The editor saves straight into it, so the
tutor reads what was drawn without any download / upload. Editors, in order of preference:
  draw.io desktop app  ->  VS Code + "Draw.io Integration" (hediet.vscode-drawio)  ->  app.diagrams.net
"""

import base64
import html
import platform
import re
import shutil
import subprocess
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

BLANK = ('<mxfile><diagram name="Page-1"><mxGraphModel><root>'
         '<mxCell id="0"/><mxCell id="1" parent="0"/>'
         '</root></mxGraphModel></diagram></mxfile>\n')
VSCODE_EXT = "hediet.vscode-drawio"


def diagram_path(sd, name):
    return sd / "diagrams" / (name if name.endswith(".drawio") else name + ".drawio")


def desktop_app():
    if platform.system() == "Darwin":
        for app in (Path("/Applications/draw.io.app"), Path.home() / "Applications/draw.io.app"):
            if app.exists():
                return ["open", "-a", str(app)]
        return None
    return [shutil.which("drawio")] if shutil.which("drawio") else None


def vscode():
    code = shutil.which("code")
    if not code:
        return None
    try:
        exts = subprocess.run([code, "--list-extensions"], capture_output=True, text=True,
                              timeout=15).stdout.lower()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return [code] if VSCODE_EXT in exts else None


def editor():
    """(label, command prefix) of the best installed editor, or (None, None) for the browser."""
    if cmd := desktop_app():
        return "draw.io desktop", cmd
    if cmd := vscode():
        return "VS Code (Draw.io Integration)", cmd
    return None, None


def browser_link(xml):
    """app.diagrams.net link that opens this diagram (a copy: edits there don't reach the file)."""
    data = urllib.parse.quote(xml, safe="~()*!.'").encode()
    deflate = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = base64.b64encode(deflate.compress(data) + deflate.flush()).decode()
    return "https://app.diagrams.net/#R" + urllib.parse.quote(packed, safe="")


def open_url(url):
    opener = "open" if platform.system() == "Darwin" else "xdg-open"
    if shutil.which(opener):
        subprocess.run([opener, url], check=False)


def cmd_draw(sd, name, browser=False):
    path = diagram_path(sd, name)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(BLANK, encoding="utf-8")
        print(f"Created {path}")
    label, cmd = (None, None) if browser else editor()
    if cmd:
        subprocess.run(cmd + [str(path)], check=False)
        print(f"Opened in {label}. Draw, press Cmd/Ctrl+S, then tell the tutor you're done.")
        return
    url = browser_link(path.read_text(encoding="utf-8"))
    open_url(url)
    print("Opened in the browser (app.diagrams.net). That tab is a copy, so to hand your drawing back:\n"
          f"  File > Open from > Device > {path}\n"
          "  then Cmd/Ctrl+S saves straight into that file (Chrome / Edge).\n"
          "For no extra steps, install an editor once:  brew install --cask drawio\n"
          f"  or the VS Code extension:  code --install-extension {VSCODE_EXT}\n"
          f"Link: {url}")


# --- reading a diagram back -------------------------------------------------------------------

def _pages(path):
    root = ET.parse(path).getroot()
    if root.tag == "mxGraphModel":
        return [("Page-1", root)]
    pages = []
    for d in root.iter("diagram"):
        model = d.find("mxGraphModel")
        if model is None and (d.text or "").strip():  # compressed page (older default)
            raw = zlib.decompress(base64.b64decode(d.text.strip()), -15).decode()
            model = ET.fromstring(urllib.parse.unquote(raw))
        if model is not None:
            pages.append((d.get("name", "page"), model))
    return pages


def _text(value):
    value = re.sub(r"<(br|hr|div|p)\b[^>]*>", " | ", value or "", flags=re.I)
    value = html.unescape(re.sub(r"<[^>]+>", "", value))
    return re.sub(r"(\s*\|\s*)+", " | ", re.sub(r"[ \t\r\n]+", " ", value)).strip(" |")


def _style(s):
    out = {}
    for part in (s or "").split(";"):
        k, _, v = part.partition("=")
        if k:
            out[k] = v if _ else True
    return out


def _arrow(st, end):
    a = st.get(end + "Arrow", "classic" if end == "end" else "none")
    if a in ("none", "0", ""):
        return None
    hollow = st.get(end + "Fill") == "0"
    return f"{a}{' (hollow)' if hollow else ''}"


def _kind(st):
    ends = " ".join(filter(None, (_arrow(st, "end"), _arrow(st, "start"))))
    dashed = st.get("dashed") == "1"
    if "block" in ends and "hollow" in ends:
        return "realization" if dashed else "inheritance"
    if "diamond" in ends:
        return "aggregation" if "hollow" in ends else "composition"
    if dashed:
        return "dependency"
    return "association" if ends else "line"


def cmd_show(sd, name):
    path = diagram_path(sd, name)
    if not path.exists():
        sys.exit(f"No diagram {path}")
    for page, model in _pages(path):
        cells = {c.get("id"): c for c in model.iter("mxCell")}
        kids = {}
        for c in cells.values():
            kids.setdefault(c.get("parent"), []).append(c)
        label = lambda i: (_text(cells[i].get("value")) or f"#{i}") if i in cells else "?"
        edges = [c for c in cells.values() if c.get("edge") == "1"]
        shapes = [c for c in cells.values() if c.get("vertex") == "1"
                  and not _style(c.get("style")).get("edgeLabel")]
        print(f"{path.name} / {page}: {len(shapes)} shapes, {len(edges)} links")

        def walk(parent, depth):
            for c in kids.get(parent, []):
                st = _style(c.get("style"))
                if c.get("vertex") != "1" or st.get("edgeLabel"):
                    continue
                shape = next(iter(st)) if st else "rect"
                print(f"{'  ' * depth}- {_text(c.get('value')) or '(empty)'}  [{shape}]")
                walk(c.get("id"), depth + 1)

        print("Shapes")
        for layer in kids.get("0", []):  # cell 0 holds the layers, the layers hold the shapes
            walk(layer.get("id"), 1)
        if edges:
            print("Links")
        for e in edges:
            st = _style(e.get("style"))
            words = [_text(e.get("value"))] + [_text(k.get("value")) for k in kids.get(e.get("id"), [])]
            words = [w for w in words if w]
            arrows = ", ".join(f"{end}={a}" for end in ("start", "end") if (a := _arrow(st, end)))
            print(f"  - {label(e.get('source'))} -> {label(e.get('target'))}  {_kind(st)}"
                  f"{'  [' + arrows + (', dashed' if st.get('dashed') == '1' else '') + ']' if arrows else ''}"
                  f"{'  labels: ' + ' / '.join(words) if words else ''}")
