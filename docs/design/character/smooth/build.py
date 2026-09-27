import re, json, os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sheet
from sheet import *
HERE = os.path.dirname(os.path.abspath(__file__))
tiles = build_tiles()
open(os.path.join(HERE, "preview.html"), "w").write(preview(tiles))

def close_tags(x):
    return re.sub(r'<(\w+)([^<>]*?)/>', r'<\1\2></\1>', x)

boards, order = {}, []
for i, (name, title, sv) in enumerate(tiles):
    fn = ("Main" if i == 0 else f"T{name}") + ".dc.html"
    extra = STATUS if name.startswith("12") else ""
    font = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@500&amp;display=swap">'
            if extra else "")
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Dex {title}</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
{font}
<style>
body{{margin:0;background:#000}}
</style>
</helmet>
<div style="width: 368px; height: 448px; position: relative; overflow: hidden; background: #000000">
{close_tags(sv)}
{extra}
</div>
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{{"$preview":{{"width":368,"height":448}}}}'>
class Component extends DCLogic {{
renderVals() {{
return {{}};
}}
}}
</script>
</body>
</html>
"""
    open(os.path.join(HERE, "project", fn), "w").write(html)
    c, r = i % 4, i // 4
    boards[fn] = {"x": c * (368 + 80), "y": r * (448 + 120), "w": 368, "h": 448, "title": title}
    order.append(fn)
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
canvas = {"v": 3, "createdOnFiles": {"v": 1, "at": now}, "title": "Dex Charm r2 · SM-SHEET",
          "launch": {"view": "canvas"}, "pages": [], "boards": boards, "order": order, "notes": {}, "designSystems": []}
json.dump(canvas, open(os.path.join(HERE, "project", "canvas.json"), "w"), ensure_ascii=False, indent=1)
print(order)
