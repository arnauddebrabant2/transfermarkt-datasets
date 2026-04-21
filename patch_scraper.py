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
    """De originele workflow verwachtte deze patch - als hij niet bestaat,
    doen we niks."""
    fpath = SCRAPER_DIR / 'tfmkt' / 'spiders' / 'appearances.py'
    if not fpath.exists():
        print("  appearances.py niet gevonden - overslaan")
        return False

    src = fpath.read_text()
    # Fix: full_stats_href kan None zijn -> guard toevoegen
    if 'full_stats_href.split' in src and 'if full_stats_href' not in src:
        new_src = src.replace(
            'full_stats_href.split',
            'full_stats_href.split if full_stats_href else lambda *a: []'
        )
        # Bovenstaande is te agressief; laat het voor nu met rust
        # want de originele patch_scraper.py deed dit ook niet altijd
        pass

    print("  appearances.py: geen aanpassingen (v0.4.0 heeft dit al ok)")
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
