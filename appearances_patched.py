import json
import logging
from urllib.parse import urlparse

from crawlee import Request
from crawlee.crawlers import ParselCrawler, PlaywrightCrawler
from inflection import parameterize, underscore

from tfmkt.common import DEFAULT_BASE_URL, load_parents, build_initial_requests, check_failures

logger = logging.getLogger(__name__)


async def run(parents_arg=None, season=2024, base_url=None):
    base_url = base_url or DEFAULT_BASE_URL
    parents = load_parents(parents_arg)

    # Twee crawlers:
    # - parsel_crawler: snel, voor profielpagina's (plain HTML)
    # - pw_crawler: Playwright, voor stats-pagina's die JS vereisen
    parsel_failures = []
    pw_failures = []

    parsel_crawler = ParselCrawler()
    pw_crawler = PlaywrightCrawler(
        headless=True,
        browser_type='chromium',
    )

    @parsel_crawler.failed_request_handler
    async def on_parsel_failed(context, error):
        parsel_failures.append((context.request.url, error))

    @pw_crawler.failed_request_handler
    async def on_pw_failed(context, error):
        pw_failures.append((context.request.url, error))

    # ── Stap 1: profielpagina bezoeken via ParselCrawler ──────────────────────
    @parsel_crawler.router.default_handler
    async def parse_profile(context) -> None:
        """Bezoek speler-profielpagina en stuur door naar stats-URL."""
        parent = context.request.user_data['parent']
        sel = context.selector

        full_stats_href = sel.xpath('//a[contains(text(),"View full stats")]/@href').get()

        if full_stats_href is None:
            profile_path = context.request.url.split("transfermarkt.co.uk")[-1]
            if "/profil/spieler/" in profile_path:
                full_stats_href = profile_path.replace("/profil/spieler/", "/leistungsdaten/spieler/")
            else:
                logger.warning("appearances: geen stats-href voor %s", context.request.url)
                return

        stats_url = base_url + full_stats_href + f"/plus/0?saison={season}"

        # Voeg toe aan de Playwright-wachtrij
        await pw_crawler.add_requests([
            Request.from_url(
                url=stats_url,
                label='parse_stats',
                user_data={'parent': parent},
            )
        ])

    # ── Stap 2: stats-pagina met Playwright (JS-rendered) ────────────────────
    @pw_crawler.router.handler('parse_stats')
    async def parse_stats(context) -> None:
        """Parse de stats-pagina na JS-rendering."""
        parent = context.request.user_data['parent']
        page = context.page

        # Wacht tot de performance-tabel geladen is (of timeout na 15s)
        try:
            await page.wait_for_selector(
                'tm-player-performance-table-new [role="row"], div.responsive-table',
                timeout=15000
            )
        except Exception:
            logger.warning("appearances: timeout wachtend op stats voor %s", context.request.url)
            return

        # Haal de volledig gerenderde HTML op via Parsel
        from parsel import Selector
        html = await page.content()
        sel = Selector(text=html)

        url_path = urlparse(context.request.url).path

        # ── Nieuwe structuur: role="row" binnen tm-player-performance-table-new ──
        # Zoek de "matchPerformanceByCompetition" component
        match_tables = sel.css('tm-player-performance-table-new[data-type="matchPerformanceByCompetition"]')

        items_written = 0
        for match_table in match_tables:
            competition_code = match_table.attrib.get('competition', 'unknown')
            rows = match_table.css('[role="row"]')

            for row in rows:
                cells = row.css('[role="cell"], a.tm-grid__cell, div.tm-grid__cell')
                if len(cells) < 6:
                    continue

                cell_texts = []
                cell_hrefs = []
                for cell in cells:
                    text = ' '.join(cell.css('::text').getall()).strip()
                    href = cell.attrib.get('href', '')
                    cell_texts.append(text)
                    cell_hrefs.append(href)

                # Extraheer velden op basis van positie (TM-volgorde: datum, matchday, club, result, goals, assists, yellow, red, minuten)
                date = cell_texts[0] if cell_texts else ''
                result_href = next((h for h in cell_hrefs if 'spielbericht' in h), None)

                import re
                if not re.match(r'\d{2}/\d{2}/\d{2}', date):
                    continue

                goals = _safe_int(cell_texts[4]) if len(cell_texts) > 4 else 0
                assists = _safe_int(cell_texts[5]) if len(cell_texts) > 5 else 0
                yellow = _card(cell_texts[6]) if len(cell_texts) > 6 else 0
                red = _card(cell_texts[7]) if len(cell_texts) > 7 else 0
                minutes = _safe_int(cell_texts[-1].replace("'", "")) if cell_texts else 0

                item = {
                    'type': 'appearance',
                    'href': url_path,
                    'parent': parent,
                    'competition_code': competition_code,
                    'date': date,
                    'result': {'type': 'game', 'href': result_href} if result_href else None,
                    'goals': goals,
                    'assists': assists,
                    'yellow_cards': yellow,
                    'red_cards': red,
                    'minutes_played': minutes,
                }
                print(json.dumps(item), flush=True)
                items_written += 1

        if items_written == 0:
            # Fallback: probeer de oude responsive-table structuur
            competitions = (
                sel.css('div.content-box-headline > a::attr(name)').getall()
                or sel.css('div.table-header > a::attr(name)').getall()
            )
            stats_tables = sel.css('div.responsive-table')[1:]

            if len(competitions) == len(stats_tables) and len(competitions) > 0:
                for comp_name, table in zip(competitions, stats_tables):
                    for item in _parse_old_table(table, parent, comp_name, url_path):
                        print(json.dumps(item), flush=True)
                        items_written += 1

        if items_written == 0:
            logger.warning("appearances: 0 items voor %s (JS geladen of lege pagina)", context.request.url)

    def _safe_int(val):
        try:
            return int(str(val).strip()) if val and str(val).strip() not in ('', '-') else 0
        except:
            return 0

    def _card(val):
        if not val or str(val).strip() in ('', '-', '0'):
            return 0
        return 1

    def _parse_old_table(table, parent, competition_code, url_path):
        """Fallback: parse oude responsive-table structuur (v0.4.0)."""
        def parse_elem(elem):
            has_brackets = elem.xpath('*[@class = "tabellenplatz"]').get() is not None
            has_shield = elem.css('img::attr(src)').get() is not None
            club_href = elem.xpath('a[contains(@href, "spielplan/verein")]/@href').get()
            result_href = elem.css('a.ergebnis-link::attr(href)').get()
            if (has_brackets and not club_href) or (club_href and not has_shield):
                return None
            elif club_href:
                return {'type': 'club', 'href': club_href}
            elif result_href:
                return {'type': 'game', 'href': result_href}
            else:
                return elem.xpath('string(.)').get().strip()

        headers = [
            underscore(parameterize(h)) for h in
            table.css("th::text").getall() + table.css("th > span::attr(title)").getall()
        ]
        headers = [h if h != 'spieltag' else 'matchday' for h in headers]

        for row in table.css('tr'):
            if len(row.css('td').getall()) <= 9:
                continue
            values = [parse_elem(td) for td in row.xpath('td') if parse_elem(td) is not None]
            if len(headers) != len(values):
                continue
            appearance = dict(zip(headers, values))
            yield {
                'type': 'appearance',
                'href': url_path,
                'parent': parent,
                'competition_code': competition_code,
                **appearance,
            }

    # ── Uitvoeren ──────────────────────────────────────────────────────────────
    # Bouw initiële requests voor de profielpagina's
    initial_requests = build_initial_requests(parents, season, base_url, label=None, spider_name='appearances')

    # Start beide crawlers: eerst parsel (pikt stats-URLs op), dan playwright (haalt data op)
    await parsel_crawler.run(initial_requests)
    await pw_crawler.run()  # pw_crawler heeft zijn requests gekregen via add_requests()

    check_failures(parsel_failures + pw_failures)
