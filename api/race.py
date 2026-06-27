"""API: 1レースをスクレイプし馬データ＋監査結果を返す"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import requests
from bs4 import BeautifulSoup
import re
import json

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
JRA_TRACKS = {"札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"}


def fetch_page(url):
    res = requests.get(url, headers={"User-Agent": UA}, timeout=15)
    return BeautifulSoup(res.content.decode("cp932", errors="replace"), "html.parser")


def normalize_class(c):
    c = re.sub(r"^[牝牡]", "", c.strip())
    c = re.sub(r"勝クラス|勝ク", "勝", c)
    return c


def scrape_race(url):
    soup = fetch_page(url)

    rn_el = soup.find("span", class_="race_name")
    race_name = rn_el.get_text().strip() if rn_el else ""
    if not race_name:
        return None

    venue = ""
    date_info = ""
    for div in soup.find_all("div", class_="cell"):
        t = div.get_text().strip()
        dm = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", t)
        if dm:
            date_info = f"{dm.group(1)}-{dm.group(2).zfill(2)}-{dm.group(3).zfill(2)}"
            vm = re.search(r"\d+回(\S+)\d+日", t)
            if vm:
                venue = vm.group(1)
            break

    race_num = ""
    rs = soup.find("div", class_="btn_race_select")
    if rs:
        nm = re.search(r"(\d+)R", rs.get_text())
        if nm:
            race_num = nm.group(1) + "R"

    course_info = ""
    cc = soup.find("div", class_="course")
    if not cc:
        for div in soup.find_all("div"):
            if "コース" in (div.get_text() or "") and "メートル" in (div.get_text() or ""):
                cc = div
                break
    if cc:
        ct = re.sub(r"\s+", " ", cc.get_text(separator=" ")).strip()
        ct = ct.replace("コース：", "").replace("コース ：", "").strip()
        dist_m = re.search(r"([\d,]+)\s*メートル", ct)
        detail_m = re.search(r"[（(]([^）)]+)[）)]", ct)
        if dist_m and detail_m:
            course_info = f"{dist_m.group(1).replace(',', '')}m {detail_m.group(1)}"
        elif dist_m:
            course_info = f"{dist_m.group(1).replace(',', '')}m"

    grade_info = ""
    grade_pattern = r"(GⅠ|GⅡ|GⅢ|G[1-3]|Jpn[1-3]|Jpn[ⅠⅡⅢ]|(?<![a-zA-Z])L(?![a-zA-Z])|OP|オープン|[1-3]勝クラス|[1-3]勝ク(?!ラス)|未勝利|新馬)"
    type_div = soup.find("div", class_="type")
    search_sources = [
        race_name,
        soup.find("h2").get_text() if soup.find("h2") else "",
        type_div.get_text() if type_div else "",
    ]
    for div in soup.find_all("div", class_="cell"):
        ct = div.get_text().strip()
        if re.search(r"(勝クラス|勝ク|OP|オープン|新馬|未勝利)", ct):
            search_sources.append(ct)
            break
    for st in search_sources:
        gm = re.search(grade_pattern, st, re.IGNORECASE)
        if gm:
            grade_info = gm.group(1)
            grade_info = grade_info.replace("Ⅰ", "1").replace("Ⅱ", "2").replace("Ⅲ", "3").replace("オープン", "OP")
            if grade_info.endswith("勝ク"):
                grade_info += "ラス"
            break
    if not grade_info:
        grade_info = "一般"

    horses = []
    seen = set()
    tbl = None
    for t in soup.find_all("table", class_="s_table"):
        if "narrow-xy" not in (t.get("class") or []):
            tbl = t
            break
    if tbl:
        for row in tbl.find_all("tr")[1:]:
            cols = row.find_all("td")
            if len(cols) < 2:
                continue
            try:
                num_div = cols[0].find("div", class_="num")
                horse_div = cols[0].find("div", class_="horse")
                odds_div = cols[1].find("div", class_="odds")
                if not num_div:
                    continue
                ut = re.sub(r"\D", "", num_div.get_text().strip())
                if not ut:
                    continue
                umaban = int(ut)
                name = horse_div.get_text().strip() if horse_div else "不明"
                odds = 0.0
                if odds_div:
                    try:
                        odds = float(odds_div.get_text().strip().replace(",", ""))
                    except ValueError:
                        pass
                if umaban not in seen:
                    seen.add(umaban)
                    horses.append({"umaban": umaban, "name": name, "odds": odds})
            except Exception:
                pass

    current_cls = normalize_class(grade_info)
    detail_tbl = None
    for t in soup.find_all("table", class_="s_table"):
        if "narrow-xy" in (t.get("class") or []):
            detail_tbl = t
            break

    if detail_tbl and current_cls:
        for row in detail_tbl.find_all("tr")[1:]:
            cols = row.find_all("td")
            if len(cols) < 6:
                continue
            try:
                umaban = int(re.sub(r"\D", "", cols[1].get_text().strip()))
            except (ValueError, IndexError):
                continue
            horse = next((h for h in horses if h["umaban"] == umaban), None)
            if not horse:
                continue

            qualifying_races = []
            for ci in range(6, min(11, len(cols))):
                col = cols[ci]
                time_span = col.find("span", class_="time")
                if not time_span:
                    continue

                rl_div = col.find("div", class_="race_line")
                rl_text = rl_div.get_text() if rl_div else ""

                if not any(t in rl_text for t in JRA_TRACKS):
                    continue

                past_cls_raw = ""
                r_class_div = col.find("div", class_="r_class")
                if r_class_div and r_class_div.get_text().strip():
                    past_cls_raw = r_class_div.get_text().strip()
                else:
                    if rl_div:
                        rl_m = re.search(
                            r"([1-3]勝ク(?:ラス)?|未勝利|新馬|OP|オープン|GⅠ|GⅡ|GⅢ|G[1-3])",
                            rl_text,
                        )
                        if rl_m:
                            past_cls_raw = rl_m.group(1)

                if not past_cls_raw or normalize_class(past_cls_raw) != current_cls:
                    continue

                margin_m = re.search(r"[(（]([\d.]+)[)）]", time_span.get_text())
                if not margin_m:
                    continue
                margin = float(margin_m.group(1))

                race_name_div = col.find("div", class_="name")
                place_div = col.find("div", class_="place")
                past_race_name = race_name_div.get_text().strip() if race_name_div else ""
                past_place = place_div.get_text().strip() if place_div else ""

                qualifying_races.append({
                    "race": past_race_name,
                    "cls": past_cls_raw,
                    "margin": margin,
                    "place": past_place,
                })

            horse["pastSameClass"] = qualifying_races
            horse["bestMargin"] = min((r["margin"] for r in qualifying_races), default=999)

    return {
        "venue": venue,
        "raceNum": race_num,
        "raceName": race_name,
        "grade": grade_info,
        "course": course_info,
        "date": date_info,
        "url": url,
        "horses": horses,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        url = params.get("url", [""])[0]

        if not url:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "url parameter required"}).encode())
            return

        try:
            data = scrape_race(url)
            if not data:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "レースデータが取得できませんでした"}).encode())
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
