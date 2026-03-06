# -*- coding: utf-8 -*-
"""
Monthly Auto Recall Crawler for SAMR (with AQSIQAUTO fallback)
数据源：
- SAMR 专栏目录：https://www.samr.gov.cn/zlfzj/qxcpzh/index.html  citeturn1search3
- SAMR 召回历史分页：https://qxzh.samr.gov.cn/qxzh/qxxxcx/web.jsp  citeturn1search5
- 中国汽车质量网目录（备）：https://www.aqsiqauto.com/recall/index/13.html  citeturn1search4
输出：docs/data/ 下的 CSV + JSON（latest.json 指向最新周期）
"""
import os, re, time, hashlib, random, sys, json
from datetime import date
import pandas as pd
import requests
from lxml import html

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]
HEADERS = {"User-Agent": random.choice(USER_AGENTS), "Accept-Language": "zh-CN,zh;q=0.9"}

SAMR_LIST_URL = "https://www.samr.gov.cn/zlfzj/qxcpzh/index.html"
AQSIQ_LIST_URL = "https://www.aqsiqauto.com/recall/index/13.html"
ROOT = os.path.dirname(os.path.dirname(__file__))
OUT_DIR = os.path.join(ROOT, "docs", "data")
os.makedirs(OUT_DIR, exist_ok=True)


def y_m_targets(run_date: date):
    y = run_date.year
    m = run_date.month - 1 or 12
    y = y if run_date.month > 1 else y - 1
    return y, m


def month_title_patterns(year: int, month: int):
    return [
        rf"{year}年{month}月汽车召回月度汇总",
        rf"{year}年{month}月.*召回.*汇总",
        rf"{year}年{month}月.*召回",
    ]


def get(url, **kwargs):
    for i in range(4):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20, **kwargs)
            if resp.status_code == 200 and resp.text:
                return resp
        except requests.RequestException:
            pass
        time.sleep(2 + i)
    return None


def parse_samr_month_url(year: int, month: int):
    resp = get(SAMR_LIST_URL)
    if not resp:
        return None
    tree = html.fromstring(resp.text)
    links = tree.xpath("//a[@href and normalize-space(string())!='']")
    pats = [re.compile(p) for p in month_title_patterns(year, month)]
    for a in links:
        title = re.sub(r"\s+", "", "".join(a.itertext()))
        href = a.get("href", "")
        if any(p.search(title) for p in pats):
            detail = href if href.startswith("http") else requests.compat.urljoin(SAMR_LIST_URL, href)
            return detail
    return None


def parse_samr_detail(detail_url: str, year: int, month: int):
    resp = get(detail_url)
    if not resp:
        return []
    tree = html.fromstring(resp.text)
    content_root = tree.xpath("//div[contains(@class,'article')] | //div[@id='zoom'] | //div[contains(@class,'TRS_Editor')]")
    content = content_root[0] if content_root else tree

    records = []
    tables = content.xpath(".//table")
    for tbl in tables:
        rows = tbl.xpath(".//tr")
        headers = ["".join(th.itertext()).strip() for th in rows[0].xpath(".//th|.//td")] if rows else []
        for tr in rows[1:]:
            cols = [" ".join(td.itertext()).strip() for td in tr.xpath(".//td")]
            if not cols or len(cols) < 3:
                continue
            rec = normalize_record_from_cols(cols, headers, detail_url, year, month)
            if rec:
                records.append(rec)

    if not records:
        paras = content.xpath(".//p|.//li")
        buf = []
        for p in paras:
            txt = " ".join(p.itertext()).strip()
            if not txt:
                continue
            buf.append(txt)
        chunk = []
        for line in buf:
            chunk.append(line)
            if re.search(r"(召回|缺陷|免费|数量|生产日期)", line):
                if line.endswith("。") or line.endswith("."):
                    rec = normalize_record_from_text(" ".join(chunk), detail_url, year, month)
                    if rec:
                        records.append(rec)
                    chunk = []
        if chunk:
            rec = normalize_record_from_text(" ".join(chunk), detail_url, year, month)
            if rec:
                records.append(rec)

    return dedup_by_hash(records)


def normalize_record_from_cols(cols, headers, url, year, month):
    def pick(name_candidates):
        for cand in name_candidates:
            for i, h in enumerate(headers):
                if cand in h:
                    return cols[i] if i < len(cols) else ""
        return ""

    brand = pick(["品牌", "生产者", "企业", "公司", "厂商"])
    model = pick(["车型", "车系", "型号", "车辆名称"])
    quantity = pick(["数量", "涉及数量", "召回数量"])
    prod = pick(["生产日期", "生产时间", "生产范围", "生产区间"])
    vin = pick(["VIN", "车辆识别代号", "识别代号"])
    defect = pick(["缺陷", "隐患", "原因"])
    remedy = pick(["措施", "改进措施", "解决方案", "免费"])

    rec = {
        "title": f"{year}年{month}月 召回事件",
        "brand": brand or "",
        "model": model or "",
        "start_date": extract_date_range(prod)[0],
        "end_date": extract_date_range(prod)[1],
        "quantity": extract_int(quantity),
        "vin_range": vin,
        "defect_desc": defect,
        "risk_desc": "",
        "remedy": remedy,
        "source_url": url,
        "published_date": f"{year}-{month:02d}-01",
        "source_name": "SAMR月度汇总",
    }
    rec["hash_id"] = hash_record(rec)
    return rec


def normalize_record_from_text(text, url, year, month):
    brand = extract_brand(text)
    model = extract_model(text)
    start, end = extract_date_range(text)
    qty = extract_int(text)
    defect = extract_defect(text)
    remedy = extract_remedy(text)
    if not any([brand, model, defect, remedy, qty]):
        return None
    rec = {
        "title": f"{year}年{month}月 召回事件",
        "brand": brand or "",
        "model": model or "",
        "start_date": start,
        "end_date": end,
        "quantity": qty,
        "vin_range": extract_vin_range(text),
        "defect_desc": defect,
        "risk_desc": extract_risk(text),
        "remedy": remedy,
        "source_url": url,
        "published_date": f"{year}-{month:02d}-01",
        "source_name": "SAMR月度汇总",
    }
    rec["hash_id"] = hash_record(rec)
    return rec


def extract_brand(text):
    m = re.search(r"([\u4e00-\u9fa5A-Za-z0-9·-]{2,20})(?:公司|汽车|集团|有限).*?召回|([A-Za-z\u4e00-\u9fa5]{2,10})牌", text)
    return (m.group(1) or m.group(2)) if m else ""


def extract_model(text):
    m = re.search(r"(车型|车辆|型号)[：: ]?([A-Za-z0-9\u4e00-\u9fa5\-\s]+)", text)
    return m.group(2).strip() if m else ""


def extract_int(text):
    m = re.search(r"(\d{1,3}(?:,\d{3})*|\d+)\s*辆", text)
    if not m:
        m2 = re.search(r"数量[：: ]?(\d+)", text)
        if m2:
            return int(m2.group(1))
        return None
    return int(m.group(1).replace(",", ""))


def extract_date_range(text):
    rg = re.findall(r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?", text)
    if len(rg) >= 2:
        s = f"{rg[0][0]}-{int(rg[0][1]):02d}-{int(rg[0][2]):02d}"
        e = f"{rg[1][0]}-{int(rg[1][1]):02d}-{int(rg[1][2]):02d}"
        return s, e
    elif len(rg) == 1:
        s = f"{rg[0][0]}-{int(rg[0][1]):02d}-{int(rg[0][2]):02d}"
        return s, None
    return None, None


def extract_vin_range(text):
    m = re.search(r"VIN[：: ]?([A-HJ-NPR-Z0-9\-\s~至到,，]+)", text, re.I)
    return m.group(1).strip() if m else ""


def extract_defect(text):
    m = re.search(r"(?:缺陷|隐患|原因)[^。；;]*", text)
    return m.group(0) if m else ""


def extract_risk(text):
    m = re.search(r"(?:风险|危害|后果)[^。；;]*", text)
    return m.group(0) if m else ""


def extract_remedy(text):
    m = re.search(r"(?:免费|措施|解决方案|改进|维修)[^。；;]*", text)
    return m.group(0) if m else ""


def hash_record(rec: dict):
    base = "|".join(str(rec.get(k, "")) for k in [
        "brand","model","start_date","end_date","quantity","vin_range","defect_desc","remedy","source_url"
    ])
    import hashlib
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def dedup_by_hash(records):
    seen, out = set(), []
    for r in records:
        if not r:
            continue
        if r["hash_id"] in seen:
            continue
        seen.add(r["hash_id"])
        out.append(r)
    return out


def fallback_aqsiq(year, month):
    resp = get(AQSIQ_LIST_URL)
    if not resp:
        return []
    tree = html.fromstring(resp.text)
    links = tree.xpath("//a[@href and normalize-space(string())!='']")
    pats = [re.compile(rf"{year}年{month}月.*召回汇总")]
    detail = None
    for a in links:
        title = re.sub(r"\s+", "", "".join(a.itertext()))
        href = a.get("href", "")
        if any(p.search(title) for p in pats):
            detail = href if href.startswith("http") else requests.compat.urljoin(AQSIQ_LIST_URL, href)
            break
    if not detail:
        return []
    resp2 = get(detail)
    if not resp2:
        return []
    tree2 = html.fromstring(resp2.text)
    content = tree2.xpath("//div[contains(@class,'article') or @id='zoom' or contains(@class,'content')]")
    content = content[0] if content else tree2
    records = []
    tables = content.xpath(".//table")
    for tbl in tables:
        rows = tbl.xpath(".//tr")
        headers = ["".join(th.itertext()).strip() for th in rows[0].xpath(".//th|.//td")] if rows else []
        for tr in rows[1:]:
            cols = [" ".join(td.itertext()).strip() for td in tr.xpath(".//td")]
            if not cols:
                continue
            rec = normalize_record_from_cols(cols, headers, detail, year, month)
            if rec:
                rec["source_name"] = "中国汽车质量网-月度汇总"
                records.append(rec)
    if not records:
        paras = content.xpath(".//p|.//li")
        for p in paras:
            txt = " ".join(p.itertext()).strip()
            if not txt:
                continue
            if ("召回" in txt) and (str(month) in txt or str(year) in txt):
                rec = normalize_record_from_text(txt, detail, year, month)
                if rec:
                    rec["source_name"] = "中国汽车质量网-月度汇总"
                    records.append(rec)
    return dedup_by_hash(records)


def write_outputs(df: pd.DataFrame, year: int, month: int):
    ym = f"{year}{month:02d}"
    csv_path = os.path.join(OUT_DIR, f"recall_{ym}.csv")
    json_path = os.path.join(OUT_DIR, f"recall_{ym}.json")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_json(json_path, orient="records", force_ascii=False, indent=2)
    # 更新 latest.json 指针
    latest = os.path.join(OUT_DIR, "latest.json")
    with open(latest, "w", encoding="utf-8") as f:
        f.write(df.to_json(orient="records", force_ascii=False, indent=2))
    print(f"[OK] Saved {len(df)} rows -> {csv_path} & {json_path} & latest.json")


def main():
    run_date = date.today()
    year, month = y_m_targets(run_date)
    print(f"[INFO] Target month: {year}-{month:02d}")
    url = parse_samr_month_url(year, month)
    records = []
    if url:
        print(f"[INFO] SAMR detail: {url}")
        records = parse_samr_detail(url, year, month)
    if not records:
        print("[WARN] SAMR not found or empty, fallback to AQSIQ...")
        records = fallback_aqsiq(year, month)
    if not records:
        print("[ERROR] No records parsed.")
        sys.exit(2)
    df = pd.DataFrame(records)
    write_outputs(df, year, month)

if __name__ == "__main__":
    main()
