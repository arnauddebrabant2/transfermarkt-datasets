import json
import logging
from urllib.parse import urlparse

from crawlee import Request
from inflection import parameterize, underscore

from tfmkt.common import DEFAULT_BASE_URL, load_parents, build_initial_requests, safe_strip, create_crawler, check_failures

logger = logging.getLogger(__name__)


async def run(parents_arg=None, season=2024, base_url=None):
    base_url = base_url or DEFAULT_BASE_URL
    parents = load_parents(parents_arg)
    requests = build_initial_requests(parents, season, base_url, label='parse', spider_name='appearances')

    crawler, failures = create_crawler()
    debug_counter = {'n': 0}

    @crawler.router.handler('parse')
    async def parse(context) -> None:
        parent = context.request.user_data['parent']
        sel = context.selector

        full_stats_href = sel.xpath('//a[contains(text(),"View full stats")]/@href').get()

        # PATCH: fallback als "View full stats" link niet gevonden
        if full_stats_href is None:
            profile_path = context.request.url.split("transfermarkt.co.uk")[-1]
            if "/profil/spieler/" in profile_path:
                full_stats_href = profile_path.replace("/profil/spieler/", "/leistungsdaten/spieler/")
            else:
                logger.warning("appearances: geen full_stats_href voor %s - overslaan", context.request.url)
                return

        seasoned_full_stats_href = full_stats_href + f"/plus/0?saison={season}"

        await context.add_requests([
            Request.from_url(
                url=base_url + seasoned_full_stats_href,
                label='parse_stats',
                user_data={'parent': parent},
            )
        ])

    @crawler.router.handler('parse_stats')
    async def parse_stats(context) -> None:
        parent = context.request.user_data['parent']
        sel = context.selector

        # DEBUG: log HTML-structuur voor eerste 3 stats-pagina's
        debug_counter['n'] += 1
        if debug_counter['n'] <= 3:
            html = sel.get()
            # Log welke selectors iets teruggeven
            c1 = sel.css('div.content-box-headline > a::attr(name)').getall()
            c2 = sel.css('div.table-header > a::attr(name)').getall()
            c3 = sel.css('.content-box-headline a::attr(name)').getall()
            tables = sel.css('div.responsive-table')
            logger.warning(
                "DEBUG stats #%d url=%s | content-box-headline>a: %s | table-header>a: %s | .content-box-headline a: %s | responsive-tables: %d | html-len: %d",
                debug_counter['n'], context.request.url, c1[:3], c2[:3], c3[:3], len(tables), len(html)
            )

        def parse_stats_elem(elem):
            has_classification_in_brackets = elem.xpath('*[@class = "tabellenplatz"]').get() is not None
            has_shield_class = elem.css('img::attr(src)').get() is not None
            club_href = elem.xpath('a[contains(@href, "spielplan/verein")]/@href').get()
            result_href = elem.css('a.ergebnis-link::attr(href)').get()

            if (
                (has_classification_in_brackets and club_href is None)
                or (club_href is not None and not has_shield_class)
            ):
                return None
            elif club_href is not None:
                return {'type': 'club', 'href': club_href}
            elif result_href is not None:
                return {'type': 'game', 'href': result_href}
            else:
                extracted_element = elem.xpath('string(.)').get().strip()
                return extracted_element

        def parse_stats_table(table):
            header_elements = [
                underscore(parameterize(header)) for header in
                table.css("th::text").getall() + table.css("th > span::attr(title)").getall()
            ]
            header_elements = [
                header if header != 'spieltag' else 'matchday'
                for header in header_elements
            ]

            value_elements_matrix = [
                [parse_stats_elem(element) for element in row.xpath('td') if parse_stats_elem(element) is not None]
                for row in table.css('tr') if len(row.css('td').getall()) > 9
            ]

            results = []
            for value_elements in value_elements_matrix:
                if len(header_elements) != len(value_elements):
                    logger.warning("appearances: header/cell mismatch (%d vs %d) - rij overgeslagen", len(header_elements), len(value_elements))
                    continue
                results.append(dict(zip(header_elements, value_elements)))
            return results

        # Probeer meerdere selectors
        competitions = (
            sel.css('div.content-box-headline > a::attr(name)').getall()
            or sel.css('div.table-header > a::attr(name)').getall()
            or sel.css('.content-box-headline a::attr(name)').getall()
        )
        stats_tables = sel.css('div.responsive-table')[1:]

        if len(competitions) != len(stats_tables):
            logger.warning(
                "appearances: %d competitions vs %d tables op %s - overgeslagen",
                len(competitions), len(stats_tables), context.request.url
            )
            return

        url = urlparse(context.request.url).path
        for competition_name, table in zip(competitions, stats_tables):
            stats = parse_stats_table(table)
            for appearance in stats:
                item = {
                    'type': 'appearance',
                    'href': url,
                    'parent': parent,
                    'competition_code': competition_name,
                    **appearance,
                }
                print(json.dumps(item), flush=True)

    await crawler.run(requests)
    check_failures(failures)
