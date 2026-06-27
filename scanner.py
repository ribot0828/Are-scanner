"""
D-Scanner: 全レースから穴馬候補を一括抽出
条件: オッズ100倍以上 × 同クラス近5走で着差≤1.0秒
"""

import requests
from bs4 import BeautifulSoup
import re
import sys
import time
from datetime import datetime

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
JRA_TRACKS = {"札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"}


def fetch_page(url):
    res = requests.get(url, headers={"User-Agent": UA}, timeout=15)
    return BeautifulSoup(res.content.decode("cp932", errors="replace"), "html.parser")


def normalize_class(c):
    c = re.sub(r"^[牝牡]", "", c.strip())
    c = re.sub(r"勝クラス|勝ク", "勝", c)
    return c


def collect_all_race_urls(seed_url):
    """1つのレースURLから、その日の全会場・全レースのURLリストを返す"""
    soup = fetch_page(seed_url)

    # 会場リンクを収集 (同一会場は全レース、他会場は1レースだけ)
    venue_links = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "accessD" in href and "CNAME" in href:
            if href.startswith("/"):
                href = "https://sp.jra.jp" + href
            venue_links.add(href)

    # 他会場リンクを特定 (venue code が異なるもの)
    seed_match = re.search(r"sw01ddd(\d{4})", seed_url)
    seed_venue = seed_match.group(1) if seed_match else ""
    other_venue_seeds = set()
    all_race_urls = set()

    for link in venue_links:
        m = re.search(r"sw01ddd(\d{4})", link)
        if m:
            vc = m.group(1)
            if vc == seed_venue:
                all_race_urls.add(link)
            else:
                other_venue_seeds.add(link)

    # 他会場のページからも全レースURLを収集
    for ov_url in other_venue_seeds:
        time.sleep(0.5)
        ov_soup = fetch_page(ov_url)
        for a in ov_soup.find_all("a", href=True):
            href = a.get("href", "")
            if "accessD" in href and "CNAME" in href:
                if href.startswith("/"):
                    href = "https://sp.jra.jp" + href
                all_race_urls.add(href)

    return sorted(all_race_urls)


def scrape_race(url):
    """1レースをスクレイプし、レース情報と全馬データを返す"""
    soup = fetch_page(url)

    # レース名
    rn_el = soup.find("span", class_="race_name")
    race_name = rn_el.get_text().strip() if rn_el else ""
    if not race_name:
        return None

    # 会場 + 日付
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

    # レース番号
    race_num = ""
    rs = soup.find("div", class_="btn_race_select")
    if rs:
        nm = re.search(r"(\d+)R", rs.get_text())
        if nm:
            race_num = nm.group(1) + "R"

    # コース
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

    # グレード
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

    # 馬リスト (Table 1: s_table without narrow-xy)
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

    # 近走監査 (Table 3: narrow-xy s_table)
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
            for ci in range(6, min(10, len(cols))):
                col = cols[ci]
                time_span = col.find("span", class_="time")
                if not time_span:
                    continue

                rc_div = col.find("div", class_="rc")
                rc_text = rc_div.get_text().strip() if rc_div else ""
                if not any(t in rc_text for t in JRA_TRACKS):
                    continue

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

                if not past_cls_raw or normalize_class(past_cls_raw) != current_cls:
                    continue

                margin_m = re.search(r"[(（]([\d.]+)[)）]", time_span.get_text())
                if not margin_m:
                    continue
                margin = float(margin_m.group(1))

                # レース名・着順も取得
                race_name_div = col.find("div", class_="name")
                place_div = col.find("div", class_="place")
                past_race_name = race_name_div.get_text().strip() if race_name_div else ""
                past_place = place_div.get_text().strip() if place_div else ""

                qualifying_races.append({
                    "race": past_race_name,
                    "class": past_cls_raw,
                    "margin": margin,
                    "place": past_place,
                })

            horse["past_same_class"] = qualifying_races
            horse["best_margin"] = min((r["margin"] for r in qualifying_races), default=999)

    return {
        "venue": venue,
        "race_num": race_num,
        "race_name": race_name,
        "grade": grade_info,
        "course": course_info,
        "date": date_info,
        "horses": horses,
    }


def scan_day(seed_url, min_odds=100.0, max_margin=1.0):
    """1日の全レースをスキャンし、条件に合う馬をリストアップ"""
    print(f"全レースURLを収集中...", file=sys.stderr)
    all_urls = collect_all_race_urls(seed_url)
    print(f"  {len(all_urls)} レース検出", file=sys.stderr)

    results = []
    for i, url in enumerate(all_urls):
        print(f"  [{i+1}/{len(all_urls)}] スクレイプ中...", end="", file=sys.stderr)
        try:
            race = scrape_race(url)
            if not race:
                print(" スキップ (データなし)", file=sys.stderr)
                continue
            print(f" {race['venue']}{race['race_num']} {race['race_name']}", file=sys.stderr)

            for h in race["horses"]:
                if h["odds"] < min_odds:
                    continue
                if h.get("best_margin", 999) > max_margin:
                    continue
                results.append({
                    "venue": race["venue"],
                    "race_num": race["race_num"],
                    "race_name": race["race_name"],
                    "grade": race["grade"],
                    "course": race["course"],
                    **h,
                })
        except Exception as e:
            print(f" エラー: {e}", file=sys.stderr)
        time.sleep(0.3)

    return results


def generate_html(results, date_str):
    """結果をHTMLに変換"""
    rows = ""
    for r in results:
        past_detail = ""
        for pr in r.get("past_same_class", []):
            if pr["margin"] <= 1.0:
                past_detail += f'<div class="past-race">{pr["race"]} {pr["place"]} <span class="margin">{pr["margin"]}秒差</span></div>'

        rows += f"""
        <tr>
            <td class="venue">{r['venue']}{r['race_num']}</td>
            <td>{r['race_name']}<br><small class="meta">{r['grade']} / {r['course']}</small></td>
            <td class="umaban">{r['umaban']}</td>
            <td class="name">{r['name']}</td>
            <td class="odds">{r['odds']}倍</td>
            <td class="best">{r['best_margin']}秒</td>
            <td class="past">{past_detail}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>D-Scanner {date_str}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0f172a; color: #e2e8f0; font-family: 'Inter', 'Noto Sans JP', sans-serif; padding: 16px; }}
  h1 {{ font-size: 1.3rem; margin-bottom: 4px; color: #f97316; }}
  .subtitle {{ color: #94a3b8; font-size: 0.85rem; margin-bottom: 16px; }}
  .count {{ color: #38bdf8; font-weight: bold; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th {{ background: #1e293b; color: #94a3b8; padding: 8px; text-align: left; border-bottom: 2px solid #334155; position: sticky; top: 0; }}
  td {{ padding: 8px; border-bottom: 1px solid #1e293b; vertical-align: top; }}
  tr:hover {{ background: #1e293b; }}
  .venue {{ color: #38bdf8; font-weight: bold; white-space: nowrap; }}
  .meta {{ color: #64748b; }}
  .umaban {{ text-align: center; font-weight: bold; }}
  .name {{ font-weight: bold; white-space: nowrap; }}
  .odds {{ color: #f97316; font-weight: bold; text-align: right; white-space: nowrap; }}
  .best {{ color: #4ade80; font-weight: bold; text-align: center; }}
  .past-race {{ font-size: 0.8rem; color: #94a3b8; margin: 2px 0; }}
  .margin {{ color: #4ade80; }}
  .empty {{ text-align: center; padding: 40px; color: #64748b; font-size: 1.1rem; }}
</style>
</head>
<body>
<h1>D-Scanner</h1>
<div class="subtitle">{date_str} ｜ オッズ100倍以上 × 同クラス近走1.0秒以内 ｜ <span class="count">{len(results)}頭</span>該当</div>
<table>
<thead>
<tr><th>場/R</th><th>レース</th><th>馬番</th><th>馬名</th><th>オッズ</th><th>最小着差</th><th>該当レース</th></tr>
</thead>
<tbody>
{rows if rows else '<tr><td colspan="7" class="empty">該当馬なし</td></tr>'}
</tbody>
</table>
</body>
</html>"""


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python scanner.py <JRAレースURL>", file=sys.stderr)
        print("例: python scanner.py 'https://sp.jra.jp/JRADB/accessD.html?CNAME=sw01ddd0103202602010720260627/C4'", file=sys.stderr)
        sys.exit(1)

    seed = sys.argv[1]
    results = scan_day(seed)
    date_str = results[0]["venue"] + " " if results else ""

    # 日付はURLから推定
    dm = re.search(r"(\d{4})(\d{2})(\d{2})/", seed)
    if dm:
        date_str = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")

    html = generate_html(results, date_str)
    out_path = f"d_scan_{date_str}.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n結果: {out_path} ({len(results)}頭該当)", file=sys.stderr)
