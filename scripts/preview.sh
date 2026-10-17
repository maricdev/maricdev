#!/usr/bin/env bash
# Renders every card in its final state (reduced motion) as PNGs in .preview/, plus a sheet that
# shows the README column on GitHub's light (#fff) and dark (#0d1117) backgrounds side by side.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
out="$root/.preview"
chrome="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
cards=(hero flow work work-01 work-02 work-03 cta)
mkdir -p "$out"

shot() { # url width height file
  "$chrome" --headless=new --disable-gpu --hide-scrollbars --force-prefers-reduced-motion \
    --allow-file-access-from-files --window-size="$2,$3" --virtual-time-budget=3000 \
    --screenshot="$4" "$1" 2>/dev/null
}

for theme in light dark; do
  for card in "${cards[@]}"; do
    height=$(sed -E -n 's/.*viewBox="0 0 [0-9]+ ([0-9]+)".*/\1/p' "$root/assets/$card-$theme.svg" | head -1)
    shot "file://$root/assets/$card-$theme.svg" 1280 "$height" "$out/$card-$theme.png"
  done
done

{
  echo '<!doctype html><meta charset="utf-8"><style>body{margin:0;display:flex}'
  echo '.c{width:860px;padding:24px 20px}.c img{width:100%;display:block;margin:0 0 16px}</style>'
  for theme in light dark; do
    [[ $theme == light ]] && bg="#ffffff" || bg="#0d1117"
    echo "<div class=c style=background:$bg>"
    for card in "${cards[@]}"; do echo "<img src=\"file://$root/assets/$card-$theme.svg\">"; done
    echo "<p style=text-align:center>"
    for link in "$root"/assets/link-*-"$theme".svg; do echo "<img src=\"file://$link\" style=\"display:inline;height:44px;width:auto;margin:0 3px\">"; done
    echo "</p></div>"
  done
} > "$out/sheet.html"
shot "file://$out/sheet.html" 1800 2000 "$out/sheet.png"

echo "Final-state PNGs and sheet.png in $out"
