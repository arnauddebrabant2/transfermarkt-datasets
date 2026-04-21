#!/usr/bin/env python3
"""
Patch voor transfermarkt-scraper v0.4.0

Repareert twee bekende fragiele plekken:
1. players.py - de strikte xpath + assert faalt wanneer Transfermarkt
   zijn HTML-structuur aanpast. We vervangen de parse() door een robuustere
   versie die alle /spieler/ links op de pagina vindt.
2. appearances.py - full_stats_href kan None zijn (bekende bug).

Wordt uitgevoerd door de workflow NA het clonen van de scraper.
"""
import re
from pathlib import Path
import sys

SCRAPER_DIR = Path('/tmp/scraper')

def patch_players():
    """Vervang de fragile parse() in players.py door een robuuste versie."""
    fpath = SCRAPER_DIR / 'tfmkt' / 'spiders' / 'players.py'
    if not fpath.exists():
        print(f"  players.py niet gevonden op {fpath}")
        return False

    src = fpath.read_text()

    # Zoek de originele parse() method en vervang hem
    new_parse = '''  def parse(self, response, parent):
      """Parse club's page to collect player URLs. Robuuste versie.
      Vindt alle unieke /spieler/<id>/ links op de pagina, ongeacht
      exacte tabel-structuur. Transfermarkt past HTML regelmatig aan,
      dus we zoeken breed en deduplicaten op player-ID.
      """
      import re as _re
      # Vind alle hrefs die naar /spieler/ wijzen (spelerprofiel)
      all_hrefs = response.xpath('//a/@href').getall()
      seen = set()
      player_hrefs = []
      for h in all_hrefs:
          if not h:
              continue
          # Match /<naam>/profil/spieler/<id>
          m = _re.search(r'(/[^/]+/profil/spieler/\\d+)', h)
          if m:
              canonical = m.group(1)
              if canonical not in seen:
                  seen.add(canonical)
                  player_hrefs.append(canonical)

      self.logger.info(
          "players.parse: %d unieke spelers gevonden op %s",
          len(player_hrefs), response.url
      )

      if not player_hrefs:
          self.logger.warning("GEEN spelers gevonden op %s", response.url)
          return

      for href in player_hrefs:
          cb_kwargs = {
              'base': {
                  'type': 'player',
                  'href': href,
                  'parent': parent
              }
          }
          yield response.follow(href, self.parse_details, cb_kwargs=cb_kwargs)

'''

    # Vervang van 'def parse(self, response, parent):' t/m de eerste 'def parse_details'
    pattern = re.compile(
        r'  def parse\(self, response, parent\):.*?(?=  def parse_details)',
        re.DOTALL
    )
    if not pattern.search(src):
        print("  players.py: kon originele parse() niet vinden - overslaan")
        return False

    new_src = pattern.sub(lambda m: new_parse, src, count=1)
    fpath.write_text(new_src)
    print("  ✅ players.py: parse() vervangen door robuuste versie")
    return True


def patch_appearances():
    """Fix appearances.py waar full_stats_href None kan zijn.

    De originele parse() methode gebruikt een xpath om de 'full stats' link
    te vinden op de speler-profielpagina. In 2025 is die xpath niet meer
    betrouwbaar - hij matcht soms niets, waarna de spider crasht met:
        TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'

    Fix: als full_stats_href None is, probeer een fallback op basis van de
    speler-URL (die heeft een deterministische relatie met de stats-URL).
    Als dat ook niet lukt: skip deze speler netjes.
    """
    fpath = SCRAPER_DIR / 'tfmkt' / 'spiders' / 'appearances.py'
    if not fpath.exists():
        print("  appearances.py niet gevonden - overslaan")
        return False

    src = fpath.read_text()

    # Vind de crashende regel en behoud de bestaande indentatie
    # Regex: optionele whitespace + "seasoned_full_stats_href = full_stats_href..."
    pattern = re.compile(
        r'^([ \t]*)seasoned_full_stats_href = full_stats_href \+ f"/plus/0\?saison=\{season\}"',
        re.MULTILINE
    )
    m = pattern.search(src)
    if not m:
        print("  appearances.py: crashende regel niet gevonden (versie mismatch?) - overslaan")
        return False

    indent = m.group(1)  # behoud exacte indentatie (spaties of tabs)

    # Bouw vervangende block met dezelfde indentatie
    new_block = (
        f'{indent}# PATCH: fallback als full_stats_href None is (TM HTML aanpassing)\n'
        f'{indent}if full_stats_href is None:\n'
        f'{indent}    profile_path = response.url.split("transfermarkt.co.uk")[-1].split("transfermarkt.com")[-1]\n'
        f'{indent}    if "/profil/spieler/" in profile_path:\n'
        f'{indent}        full_stats_href = profile_path.replace("/profil/spieler/", "/leistungsdatendetails/spieler/")\n'
        f'{indent}        self.logger.info("appearances: fallback URL gebruikt voor %s", response.url)\n'
        f'{indent}    else:\n'
        f'{indent}        self.logger.warning("appearances: geen full_stats_href en geen fallback voor %s - overslaan", response.url)\n'
        f'{indent}        return\n'
        f'{indent}seasoned_full_stats_href = full_stats_href + f"/plus/0?saison={{season}}"'
    )

    new_src = pattern.sub(lambda _m: new_block, src, count=1)
    if new_src == src:
        print("  appearances.py: vervanging mislukt - overslaan")
        return False

    # Extra fix uit dcaribou main-branch: TM heeft 'div.table-header' vervangen
    # door 'div.content-box-headline' voor de competitie-namen bij stats-tabellen.
    # Issue #34 in dcaribou/transfermarkt-scraper.
    old_css = "response.css(\n        'div.table-header > a::attr(name)'\n    ).getall()"
    new_css = "response.css('div.content-box-headline > a::attr(name)').getall()"
    if old_css in new_src:
        new_src = new_src.replace(old_css, new_css)
        print("  ✅ appearances.py: CSS-selector bijgewerkt (table-header -> content-box-headline)")
    else:
        # Probeer een minder specifieke match (een-regelige variant)
        alt_old = "response.css('div.table-header > a::attr(name)').getall()"
        if alt_old in new_src:
            new_src = new_src.replace(alt_old, new_css)
            print("  ✅ appearances.py: CSS-selector bijgewerkt (table-header -> content-box-headline)")
        else:
            print("  ⚠ appearances.py: oude CSS-selector niet gevonden (al bijgewerkt?)")

    fpath.write_text(new_src)
    print(f"  ✅ appearances.py: None-guard + fallback toegevoegd (indent={len(indent)} chars)")
    return True


def main():
    print("=== Scraper patch script ===")
    print(f"Scraper directory: {SCRAPER_DIR}")
    if not SCRAPER_DIR.exists():
        print("FOUT: scraper directory bestaat niet!")
        sys.exit(1)

    patch_players()
    patch_appearances()
    print("=== Patches klaar ===")


if __name__ == '__main__':
    main()
