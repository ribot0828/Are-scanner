"""API: その日の全レースURLリストを返す"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import requests
from bs4 import BeautifulSoup
import re
import json

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
ALLOWED_HOST = "sp.jra.jp"


def validate_jra_url(url):
    parsed = urlparse(url)
    if parsed.hostname != ALLOWED_HOST:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if "accessD" not in parsed.path and "CNAME" not in (parsed.query or ""):
        return None
    return url


def fetch_page(url):
    res = requests.get(url, headers={"User-Agent": UA}, timeout=15)
    return BeautifulSoup(res.content.decode("cp932", errors="replace"), "html.parser")


def collect_all_race_urls(seed_url):
    soup = fetch_page(seed_url)
    venue_links = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "accessD" in href and "CNAME" in href:
            if href.startswith("/"):
                href = "https://sp.jra.jp" + href
            venue_links.add(href)

    seed_match = re.search(r"sw01ddd(\d{4})", seed_url)
    seed_venue = seed_match.group(1) if seed_match else ""
    other_venue_seeds = set()
    all_race_urls = set()

    for link in venue_links:
        if not validate_jra_url(link):
            continue
        m = re.search(r"sw01ddd(\d{4})", link)
        if m:
            vc = m.group(1)
            if vc == seed_venue:
                all_race_urls.add(link)
            else:
                other_venue_seeds.add(link)

    for ov_url in other_venue_seeds:
        ov_soup = fetch_page(ov_url)
        for a in ov_soup.find_all("a", href=True):
            href = a.get("href", "")
            if "accessD" in href and "CNAME" in href:
                if href.startswith("/"):
                    href = "https://sp.jra.jp" + href
                all_race_urls.add(href)

    return sorted(all_race_urls)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        url = params.get("url", [""])[0]

        if not url or not validate_jra_url(url):
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "sp.jra.jp のレースURLのみ対応しています"}).encode())
            return

        try:
            urls = collect_all_race_urls(url)
            dm = re.search(r"(\d{4})(\d{2})(\d{2})/", url)
            date_str = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}" if dm else ""

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"urls": urls, "date": date_str, "count": len(urls)}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
