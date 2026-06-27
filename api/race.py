"""API: 1レースをスクレイプし馬データ＋監査結果を返す"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import requests
from bs4 import BeautifulSoup
import re
import json

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
JRA_TRACKS = {"札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"}
JRA_HOSTS = {"sp.jra.jp", "www.jra.go.jp"}
NETKEIBA_HOSTS = {"race.netkeiba.com", "race.sp.netkeiba.com"}


def classify_url(url):
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme not in ("http", "https"):
        return None, None
    if host in JRA_HOSTS:
        return "jra", url.replace("www.jra.go.jp", "sp.jra.jp")
    if host in NETKEIBA_HOSTS:
        nk = url.replace("race.sp.netkeiba.com", "race.netkeiba.com")
        nk = nk.replace("/shutuba.html", "/shutuba_past.html")
        if "shutuba_past" not in nk and "race_id=" in nk:
            nk = re.sub(r"/race/[^?]+", "/race/shutuba_past.html", nk)
        return "netkeiba", nk
    return None, None


def fetch_page(url):
    res = requests.get(url, headers={"User-Agent": UA}, timeout=15)
    return BeautifulSoup(res.content.decode("cp932", errors="replace"), "html.parser")


def fetch_page_utf8(url):
    res = requests.get(url, headers={"User-Agent": UA}, timeout=15)
    return BeautifulSoup(res.content.decode("utf-8", errors="replace"), "html.parser")


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

    cur_surface = "ダ" if "ダ" in course_info else ("芝" if "芝" in course_info else "")
    cur_dist_m = re.search(r"(\d+)m", course_info)
    cur_dist = int(cur_dist_m.group(1)) if cur_dist_m else 0

    if detail_tbl:
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
            all_past = []
            for ci in range(6, min(11, len(cols))):
                col = cols[ci]
                time_span = col.find("span", class_="time")
                if not time_span:
                    continue

                rc_div = col.find("div", class_="rc")
                rc_text = rc_div.get_text().strip() if rc_div else ""
                is_jra = any(t in rc_text for t in JRA_TRACKS)

                margin_m = re.search(r"[(（]([\d.]+)[)）]", time_span.get_text())
                margin = float(margin_m.group(1)) if margin_m else None

                race_name_div = col.find("div", class_="name")
                place_div = col.find("div", class_="place")
                past_race_name = race_name_div.get_text().strip() if race_name_div else ""
                past_place_str = place_div.get_text().strip() if place_div else ""
                past_place_m = re.search(r"(\d+)", past_place_str)
                past_place = int(past_place_m.group(1)) if past_place_m else 0

                past_dist = 0
                past_surface = ""
                info2 = col.find("div", class_="info_line2")
                if info2:
                    lines = info2.find_all("div", class_="line")
                    if lines:
                        cl = lines[0].find("div", class_=lambda c: c and "left" in str(c))
                        if cl:
                            dt = cl.get_text().strip()
                            dm2 = re.match(r"(\d+)(.*)", dt)
                            if dm2:
                                past_dist = int(dm2.group(1))
                                sf = dm2.group(2).strip()
                                if "ダ" in sf:
                                    past_surface = "ダ"
                                elif "芝" in sf:
                                    past_surface = "芝"

                corner_div = col.find("div", class_="corner_list")
                corners = []
                last_corner = 0
                if corner_div:
                    corners = re.findall(r"\d+", corner_div.get_text())
                    corners = [int(c) for c in corners]
                    last_corner = corners[-1] if corners else 0

                f3_val = 0.0
                f3_div = col.find("div", class_="f3")
                if f3_div:
                    f3_m = re.search(r"(\d{2,}\.\d)", f3_div.get_text())
                    f3_val = float(f3_m.group(1)) if f3_m else 0.0

                field_size = 0
                num_div = col.find("div", class_="num")
                if num_div:
                    fs_m = re.search(r"(\d+)頭", num_div.get_text())
                    field_size = int(fs_m.group(1)) if fs_m else 0

                past_cls_raw = ""
                r_class_div = col.find("div", class_="r_class")
                if r_class_div and r_class_div.get_text().strip():
                    past_cls_raw = r_class_div.get_text().strip()
                else:
                    rl_div = col.find("div", class_="race_line")
                    if rl_div:
                        rl_m = re.search(
                            r"([1-3]勝ク(?:ラス)?|未勝利|新馬|OP|オープン|GⅠ|GⅡ|GⅢ|G[1-3])",
                            rl_div.get_text(),
                        )
                        if rl_m:
                            past_cls_raw = rl_m.group(1)

                pr = {
                    "race": past_race_name,
                    "venue": rc_text,
                    "isJRA": is_jra,
                    "cls": past_cls_raw,
                    "margin": margin,
                    "place": past_place,
                    "placeStr": past_place_str,
                    "dist": past_dist,
                    "surface": past_surface,
                    "lastCorner": last_corner,
                    "f3": f3_val,
                    "fieldSize": field_size,
                }
                all_past.append(pr)

                if is_jra and current_cls and past_cls_raw and normalize_class(past_cls_raw) == current_cls and margin is not None:
                    qualifying_races.append({
                        "race": past_race_name,
                        "cls": past_cls_raw,
                        "margin": margin,
                        "place": past_place_str,
                    })

            horse["pastSameClass"] = qualifying_races
            horse["bestMargin"] = min((r["margin"] for r in qualifying_races), default=999)
            horse["pastRaces"] = all_past

    return {
        "venue": venue,
        "raceNum": race_num,
        "raceName": race_name,
        "grade": grade_info,
        "course": course_info,
        "surface": cur_surface,
        "distance": cur_dist,
        "date": date_info,
        "url": url,
        "horses": horses,
    }


def scrape_race_netkeiba(url):
    soup = fetch_page_utf8(url)

    rn_el = soup.find("h1", class_="RaceName")
    race_name = rn_el.get_text().strip() if rn_el else ""
    if not race_name:
        return None

    race_num = ""
    rn_span = soup.find("span", class_="RaceNum")
    if rn_span:
        nm = re.search(r"(\d+)\s*R", rn_span.get_text())
        if nm:
            race_num = nm.group(1) + "R"

    course_info = ""
    cur_surface = ""
    cur_dist = 0
    rd01 = soup.find("div", class_="RaceData01")
    if rd01:
        rd01_text = re.sub(r"\s+", " ", rd01.get_text()).strip()
        cm = re.search(r"(ダ|芝)(\d+)m", rd01_text)
        if cm:
            cur_surface = "ダ" if cm.group(1) == "ダ" else "芝"
            cur_dist = int(cm.group(2))
        dir_m = re.search(r"\(([^)]+)\)", rd01_text)
        if cm and dir_m:
            course_info = f"{cur_dist}m {cur_surface}・{dir_m.group(1)}"
        elif cm:
            course_info = f"{cur_dist}m {cur_surface}"

    venue = ""
    grade_info = ""
    date_info = ""
    rd02 = soup.find("div", class_="RaceData02")
    if rd02:
        for sp in rd02.find_all("span"):
            t = sp.get_text().strip()
            if t in JRA_TRACKS:
                venue = t
            gm = re.search(r"([１-３1-3]勝クラス|未勝利|新馬|OP|オープン)", t)
            if gm and not grade_info:
                grade_info = gm.group(1).translate(str.maketrans("１２３", "123"))

    if not grade_info:
        gp = r"(GⅠ|GⅡ|GⅢ|G[1-3]|Jpn[1-3]|OP|オープン|[1-3]勝クラス|未勝利|新馬)"
        for src in [race_name, rd02.get_text() if rd02 else ""]:
            gm = re.search(gp, src)
            if gm:
                grade_info = gm.group(1)
                grade_info = grade_info.replace("Ⅰ", "1").replace("Ⅱ", "2").replace("Ⅲ", "3").replace("オープン", "OP")
                break
    if not grade_info:
        grade_info = "一般"

    title_el = soup.find("title")
    if title_el:
        dm = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", title_el.get_text())
        if dm:
            date_info = f"{dm.group(1)}-{dm.group(2).zfill(2)}-{dm.group(3).zfill(2)}"

    current_cls = normalize_class(grade_info)

    horses = []
    seen = set()
    tbl = soup.find("table", id="sort_table")
    if not tbl:
        tbl = soup.find("table", class_="Shutuba_Past5_Table")
    if not tbl:
        return None

    for row in tbl.find_all("tr", class_="HorseList"):
        try:
            tr_id = row.get("id", "")
            um = re.search(r"tr_(\d+)", tr_id)
            if not um:
                continue
            umaban = int(um.group(1))

            horse_info = row.find("td", class_="Horse_Info")
            name = "不明"
            if horse_info:
                h02 = horse_info.find("div", class_="Horse02")
                if h02:
                    a = h02.find("a")
                    if a:
                        name = a.get_text().strip()

            odds = 0.0
            if horse_info:
                pop = horse_info.find("div", class_="Popular")
                if pop:
                    odds_span = pop.find("span", id=lambda x: x and x.startswith("odds-"))
                    if odds_span:
                        try:
                            odds = float(odds_span.get_text().strip().replace(",", ""))
                        except ValueError:
                            pass

            if umaban in seen:
                continue
            seen.add(umaban)
            horse = {"umaban": umaban, "name": name, "odds": odds}
            horses.append(horse)

            qualifying_races = []
            all_past = []
            for cell in row.find_all("td", class_="Past"):
                data_item = cell.find("div", class_="Data_Item")
                if not data_item:
                    continue

                data01 = data_item.find("div", class_="Data01")
                if not data01:
                    continue

                rc_text = ""
                first_span = data01.find("span", class_=lambda c: c != "Num" if c else True)
                if first_span:
                    parts = re.split(r"[\s\xa0]+", first_span.get_text().strip())
                    if len(parts) >= 2:
                        rc_text = parts[-1]

                past_place = 0
                num_span = data01.find("span", class_="Num")
                if num_span:
                    pm = re.search(r"(\d+)", num_span.get_text())
                    if pm:
                        past_place = int(pm.group(1))

                is_jra = any(t in rc_text for t in JRA_TRACKS)

                data02 = data_item.find("div", class_="Data02")
                past_race_name = ""
                past_cls_raw = ""
                if data02:
                    a = data02.find("a")
                    if a:
                        past_race_name = a.get_text().strip()
                    cls_m = re.search(
                        r"([1-3]勝ク(?:ラス)?|未勝利|新馬|OP|オープン|GⅠ|GⅡ|GⅢ|G[1-3]|Jpn[1-3])",
                        past_race_name,
                    )
                    if cls_m:
                        past_cls_raw = cls_m.group(1)

                data05 = data_item.find("div", class_="Data05")
                past_dist = 0
                past_surface = ""
                if data05:
                    dm5 = re.search(r"(ダ|芝)(\d+)", data05.get_text())
                    if dm5:
                        past_surface = "ダ" if dm5.group(1) == "ダ" else "芝"
                        past_dist = int(dm5.group(2))

                data03 = data_item.find("div", class_="Data03")
                field_size = 0
                if data03:
                    fs_m = re.search(r"(\d+)頭", data03.get_text())
                    if fs_m:
                        field_size = int(fs_m.group(1))

                data06 = data_item.find("div", class_="Data06")
                last_corner = 0
                f3_val = 0.0
                if data06:
                    d06 = data06.get_text().replace("\xa0", " ").strip()
                    cm6 = re.match(r"(\d+(?:-\d+)+)", d06)
                    if cm6:
                        corners = cm6.group(1).split("-")
                        last_corner = int(corners[-1])
                    f3m = re.search(r"\((\d{2}\.\d)\)", d06)
                    if f3m:
                        f3_val = float(f3m.group(1))

                data07 = data_item.find("div", class_="Data07")
                margin = None
                if data07:
                    d07 = data07.get_text().strip()
                    mm = re.search(r"\((-?[\d.]+)\)\s*$", d07)
                    if mm:
                        val = float(mm.group(1))
                        margin = 0.0 if val < 0 else val
                    elif past_place == 1:
                        margin = 0.0

                past_place_str = f"{past_place}着" if past_place > 0 else ""

                pr = {
                    "race": past_race_name,
                    "venue": rc_text,
                    "isJRA": is_jra,
                    "cls": past_cls_raw,
                    "margin": margin,
                    "place": past_place,
                    "placeStr": past_place_str,
                    "dist": past_dist,
                    "surface": past_surface,
                    "lastCorner": last_corner,
                    "f3": f3_val,
                    "fieldSize": field_size,
                }
                all_past.append(pr)

                if is_jra and current_cls and past_cls_raw and normalize_class(past_cls_raw) == current_cls and margin is not None:
                    qualifying_races.append({
                        "race": past_race_name,
                        "cls": past_cls_raw,
                        "margin": margin,
                        "place": past_place_str,
                    })

            horse["pastSameClass"] = qualifying_races
            horse["bestMargin"] = min((r["margin"] for r in qualifying_races), default=999)
            horse["pastRaces"] = all_past
        except Exception:
            pass

    return {
        "venue": venue,
        "raceNum": race_num,
        "raceName": race_name,
        "grade": grade_info,
        "course": course_info,
        "surface": cur_surface,
        "distance": cur_dist,
        "date": date_info,
        "url": url,
        "horses": horses,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        url = params.get("url", [""])[0]

        source, validated = classify_url(url) if url else (None, None)
        if not source:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "JRAまたはnetkeibaのレースURLを入力してください"}).encode())
            return

        try:
            data = scrape_race(validated) if source == "jra" else scrape_race_netkeiba(validated)
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
