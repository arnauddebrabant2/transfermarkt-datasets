"""
patch_scraper.py - Patcht de appearances.py bug in de transfermarkt-scraper.
"""
from pathlib import Path

appearances_file = Path('/tmp/scraper/tfmkt/crawlers/appearances.py')

if not appearances_file.exists():
    print("FOUT: appearances.py niet gevonden")
    exit(1)

code = appearances_file.read_text()
print("Huidige inhoud appearances.py:")
for i, line in enumerate(code.split('\n')):
    if 'full_stats_href' in line or 'seasoned' in line:
        print(f"  Regel {i+1}: {repr(line)}")

# Probeer meerdere varianten van de buggy regel
targets = [
    'seasoned_full_stats_href = full_stats_href + f"/plus/0?saison={season}"',
    "seasoned_full_stats_href = full_stats_href + f'/plus/0?saison={season}'",
]

patched = False
for target in targets:
    if target in code:
        indent = '        '  # 8 spaties
        fixed = (f'{indent}if not full_stats_href:\n'
                 f'{indent}    return\n'
                 f'{indent}{target.strip()}')
        code = code.replace(indent + target.strip(), fixed)
        appearances_file.write_text(code)
        print(f"✅ appearances.py gepatcht (variant: {target[:40]}...)")
        patched = True
        break

if not patched:
    print("⚠️  Geen bekend patroon gevonden, forceer patch via line number...")
    lines = code.split('\n')
    for i, line in enumerate(lines):
        if 'full_stats_href +' in line and 'saison' in line:
            indent = len(line) - len(line.lstrip())
            spaces = ' ' * indent
            lines[i] = (f'{spaces}if not full_stats_href:\n'
                        f'{spaces}    return\n'
                        f'{line}')
            appearances_file.write_text('\n'.join(lines))
            print(f"✅ appearances.py gepatcht op regel {i+1}")
            patched = True
            break

if not patched:
    print("❌ Patch mislukt — volledige inhoud appearances.py:")
    print(code[:2000])
