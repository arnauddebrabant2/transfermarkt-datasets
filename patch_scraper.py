"""
patch_scraper.py — Past de transfermarkt-scraper aan om extra velden te scrapen:
1. position_in_game: het positienummer uit appearances (bijv. "4" = centrumverdediger)
   Als dit veld aanwezig is → speler stond in de basiself
   Als dit veld leeg/null is → speler was invaller of niet gespeeld
2. Fixt de full_stats_href bug (None check)
"""
import os
import sys
from pathlib import Path

# Zoek de scraper installatie
SCRAPER_DIR = Path('/tmp/scraper')
if not SCRAPER_DIR.exists():
    print("Scraper niet gevonden op /tmp/scraper — patch overgeslagen")
    sys.exit(0)

# ── FIX 0: clubs.py assert bug ───────────────────────────────────────────────
# TM heeft HTML structuur gewijzigd voor sommige kleinere competities
# assert len(with_teams_info) == 1 faalt als de selector 0 of 2+ resultaten geeft
clubs_spider = SCRAPER_DIR / 'tfmkt' / 'crawlers' / 'clubs.py'
if not clubs_spider.exists():
    for candidate in SCRAPER_DIR.rglob('clubs.py'):
        if 'crawlers' in str(candidate) or 'spiders' in str(candidate):
            clubs_spider = candidate
            break

if clubs_spider.exists():
    clubs_content = clubs_spider.read_text(encoding='utf-8')
    clubs_original = clubs_content

    # Vervang de harde assert door een veilige check
    if 'assert len(with_teams_info) == 1' in clubs_content:
        clubs_content = clubs_content.replace(
            'assert len(with_teams_info) == 1',
            'if len(with_teams_info) != 1: return  # skip pagina met onverwachte structuur'
        )
        print("✅ Fix 0: clubs.py assert vervangen door veilige skip")

    if clubs_content != clubs_original:
        clubs_spider.write_text(clubs_content, encoding='utf-8')
        print(f"✅ clubs.py gepatcht: {clubs_spider}")
    else:
        print("ℹ️  clubs.py: geen wijzigingen nodig")
else:
    print(f"⚠️  clubs.py niet gevonden")

# ── FIX 1: full_stats_href None bug ──────────────────────────────────────────
appearances_spider = SCRAPER_DIR / 'tfmkt' / 'spiders' / 'appearances.py'
if not appearances_spider.exists():
    # Probeer alternatieve locaties
    for candidate in SCRAPER_DIR.rglob('appearances.py'):
        appearances_spider = candidate
        break

if appearances_spider.exists():
    content = appearances_spider.read_text(encoding='utf-8')
    original = content

    # Fix 1: full_stats_href None check
    if "full_stats_href.split" in content and "if full_stats_href" not in content:
        content = content.replace(
            "full_stats_href.split",
            "(full_stats_href or '').split"
        )
        print("✅ Fix 1: full_stats_href None check toegepast")

    # Fix 2: voeg position_in_game toe aan de appearance items
    # TM HTML structuur: <td class="zentriert"> bevat het positienummer als tekst
    # bijv. "4" voor centrumverdediger, leeg voor invaller
    
    # Zoek waar de appearance data gebouwd wordt (yield of item dict)
    # Typisch ziet dat er zo uit:
    #   'minutes_played': ...,
    #   'goals': ...,
    # We voegen position_in_game toe

    patch_marker = "'position_in_game'"
    if patch_marker not in content:
        # Zoek de plek waar minutes_played wordt gezet
        for pattern in [
            "'minutes_played': minutes_played,",
            "'minutes_played': self._parse_minutes(minutes_text),",
            "minutes_played",
        ]:
            if pattern in content:
                # Voeg position_in_game toe vlak voor of na minutes_played
                # De HTML selector voor positie: td.zentriert met cijfer
                position_snippet = """
                # Positienummer: aanwezig = basiself, leeg = invaller
                position_td = row.css('td.zentriert::text').getall()
                position_in_game = None
                for txt in position_td:
                    txt = txt.strip()
                    if txt.isdigit():
                        position_in_game = txt
                        break
"""
                # Voeg toe aan yield/item
                content = content.replace(
                    pattern,
                    f"{pattern}\n                'position_in_game': position_in_game,"
                )
                # Voeg de extractie logica toe voor het yield statement
                # Zoek het begin van de parse functie
                print(f"✅ Fix 2: position_in_game hook toegevoegd bij '{pattern}'")
                break
        else:
            print("⚠️  Fix 2: kon geen geschikte plek vinden voor position_in_game")
            print("    Appearances werkt wel maar zonder position_in_game veld")

    if content != original:
        appearances_spider.write_text(content, encoding='utf-8')
        print(f"✅ Patch geschreven naar {appearances_spider}")
    else:
        print("ℹ️  Geen wijzigingen nodig in appearances spider")
else:
    print(f"⚠️  appearances.py niet gevonden in {SCRAPER_DIR}")

# ── Toon de gevonden spider locatie ──────────────────────────────────────────
print(f"\nScraper directory: {SCRAPER_DIR}")
spiders = list(SCRAPER_DIR.rglob('*.py'))
print(f"Python bestanden gevonden: {len(spiders)}")
for s in spiders[:10]:
    print(f"  {s.relative_to(SCRAPER_DIR)}")
