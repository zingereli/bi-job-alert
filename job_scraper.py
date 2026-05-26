import requests
from bs4 import BeautifulSoup
import json, os, hashlib, re, time
from datetime import datetime
import xml.etree.ElementTree as ET

# ─── הגדרות ───────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

KEYWORDS = [
    "bi developer", "bi team lead", "ר\"צ bi", "ראש צוות bi",
    "business intelligence developer", "business intelligence team lead",
    "מפתח bi", "מפתחת bi", "bi analyst", "bi manager", "bi lead",
]
LOCATION_KEYWORDS = ["ירושלים", "jerusalem"]
SEEN_JOBS_FILE    = "seen_jobs.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ─── עזרים ────────────────────────────────────────────────
def load_seen_jobs():
    if os.path.exists(SEEN_JOBS_FILE):
        with open(SEEN_JOBS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen_jobs(seen):
    with open(SEEN_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f)

def job_id(title, company, url):
    return hashlib.md5(f"{title}|{company}|{url}".lower().encode()).hexdigest()

def is_relevant(title, location=""):
    kw = any(k in title.lower() for k in KEYWORDS)
    lc = any(l in location.lower() for l in LOCATION_KEYWORDS) or location.strip() == ""
    return kw and lc

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }, timeout=10)
        r.raise_for_status()
        print("  ✅ נשלחה הודעת טלגרם")
    except Exception as e:
        print(f"  ❌ שגיאת טלגרם: {e}")

def fmt(title, company, location, url, source):
    return (f"🔔 <b>משרה חדשה!</b>\n\n"
            f"💼 <b>{title}</b>\n"
            f"🏢 {company}\n📍 {location}\n🌐 {source}\n\n"
            f"🔗 <a href='{url}'>לצפייה במשרה</a>")

def get_soup(url, timeout=20):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.encoding = r.apparent_encoding
    return BeautifulSoup(r.text, "html.parser")

# ─── AllJobs ──────────────────────────────────────────────
def scrape_alljobs():
    """AllJobs – שימוש ב-API הפנימי שלהם (JSON)"""
    jobs = []
    queries = ["BI Developer", "BI Team Lead", "Business Intelligence"]
    for q in queries:
        # AllJobs API endpoint
        url = (f"https://www.alljobs.co.il/SearchResultsAjax.aspx"
               f"?position={requests.utils.quote(q)}&cityid=3000&fromedate=7")
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(r.text, "html.parser")
            
            # נסה לחלץ כל כרטיסיית משרה
            for item in soup.find_all(["div", "li", "article"]):
                text = item.get_text(separator=" ", strip=True)
                title_candidates = item.find_all(["h2", "h3", "strong", "b"])
                for tc in title_candidates:
                    title = tc.get_text(strip=True)
                    if len(title) > 5 and is_relevant(title):
                        link = item.find("a", href=True)
                        href = link["href"] if link else ""
                        if href and not href.startswith("http"):
                            href = "https://www.alljobs.co.il" + href
                        # חפש מיקום
                        loc_match = re.search(r"ירושלים|Jerusalem", text, re.IGNORECASE)
                        location = "ירושלים" if loc_match else ""
                        if location or True:  # שלח גם בלי מיקום מוגדר
                            jobs.append({
                                "title": title,
                                "company": "ראה מודעה",
                                "location": location or "ירושלים",
                                "url": href or f"https://www.alljobs.co.il/SearchResults.aspx?position={requests.utils.quote(q)}&cityid=3000",
                                "source": "AllJobs"
                            })
                        break
        except Exception as e:
            print(f"  ⚠️ AllJobs [{q}]: {e}")

        # גם נסה עם URL חיפוש רגיל
        try:
            url2 = f"https://www.alljobs.co.il/SearchResults.aspx?position={requests.utils.quote(q)}&cityid=3000&fromedate=7"
            soup2 = get_soup(url2)
            
            # AllJobs כרטיסיות – class אמיתי
            for card in soup2.find_all("div", class_=re.compile(r"job|position|result", re.I)):
                title_el = card.find(["h2", "h3", "a"], class_=re.compile(r"title|position|job", re.I))
                if not title_el:
                    title_el = card.find("a")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title or len(title) < 4:
                    continue
                if not is_relevant(title):
                    continue
                
                comp_el = card.find(class_=re.compile(r"company|employer", re.I))
                loc_el  = card.find(class_=re.compile(r"locat|city|place", re.I))
                link_el = card.find("a", href=True)
                
                company  = comp_el.get_text(strip=True) if comp_el else "לא צוין"
                location = loc_el.get_text(strip=True)  if loc_el  else "ירושלים"
                href     = link_el["href"] if link_el else ""
                if href and not href.startswith("http"):
                    href = "https://www.alljobs.co.il" + href
                
                if is_relevant(title, location):
                    jobs.append({
                        "title": title, "company": company,
                        "location": location, "url": href, "source": "AllJobs"
                    })
        except Exception as e:
            print(f"  ⚠️ AllJobs-v2 [{q}]: {e}")

    # הסר כפולים בתוך AllJobs
    seen_titles = set()
    unique = []
    for j in jobs:
        k = j["title"].lower()
        if k not in seen_titles:
            seen_titles.add(k)
            unique.append(j)
    return unique

# ─── JobMaster ────────────────────────────────────────────
def scrape_jobmaster():
    jobs = []
    queries = ["BI Developer", "BI Team Lead", "Business Intelligence"]
    base = "https://www.jobmaster.co.il"
    
    for q in queries:
        # נסה כמה URL formats
        urls = [
            f"{base}/jobs/?q={requests.utils.quote(q)}&l=%D7%99%D7%A8%D7%95%D7%A9%D7%9C%D7%99%D7%9D",
            f"{base}/jobs/search/?query={requests.utils.quote(q)}&city=ירושלים",
            f"{base}/?q={requests.utils.quote(q)}&city=ירושלים",
        ]
        for url in urls:
            try:
                soup = get_soup(url)
                
                # חפש בכל ה-divs שמכילים את מילת החיפוש
                all_links = soup.find_all("a", href=True)
                for link in all_links:
                    title = link.get_text(strip=True)
                    if not title or len(title) < 4:
                        continue
                    if not is_relevant(title):
                        continue
                    
                    href = link["href"]
                    if href and not href.startswith("http"):
                        href = base + href
                    
                    # בדוק parent לחברה ומיקום
                    parent = link.parent
                    if parent:
                        full_text = parent.get_text(separator=" ", strip=True)
                        loc_match = re.search(r"ירושלים|Jerusalem", full_text, re.IGNORECASE)
                        location = "ירושלים" if loc_match else ""
                        
                        if location or "ירושלים" in url:
                            jobs.append({
                                "title": title,
                                "company": "JobMaster",
                                "location": location or "ירושלים",
                                "url": href,
                                "source": "JobMaster"
                            })
                            break
            except Exception as e:
                print(f"  ⚠️ JobMaster [{q}/{url[:50]}]: {e}")
                continue
            time.sleep(0.5)

    seen_titles = set()
    unique = []
    for j in jobs:
        k = j["title"].lower()
        if k not in seen_titles:
            seen_titles.add(k)
            unique.append(j)
    return unique

# ─── LinkedIn RSS ──────────────────────────────────────────
def scrape_linkedin():
    """LinkedIn דרך גישה לדף ציבורי"""
    jobs = []
    queries = [
        ("BI Developer", "BI+Developer"),
        ("BI Team Lead", "BI+Team+Lead"),
        ("Business Intelligence", "Business+Intelligence+Developer"),
    ]
    for label, q in queries:
        url = (f"https://www.linkedin.com/jobs/search/?keywords={q}"
               f"&location=Jerusalem%2C+Israel&f_TPR=r604800&position=1&pageNum=0")
        try:
            r = requests.get(url, headers={
                **HEADERS,
                "Accept": "text/html,application/xhtml+xml",
                "Referer": "https://www.linkedin.com/",
            }, timeout=20)
            soup = BeautifulSoup(r.text, "html.parser")
            
            # LinkedIn job cards
            selectors = [
                "div.base-card",
                "li.jobs-search-results__list-item",
                "div.job-search-card",
                "[data-entity-urn]",
            ]
            cards = []
            for sel in selectors:
                cards = soup.select(sel)
                if cards:
                    break

            for card in cards:
                t  = card.select_one("h3, .base-search-card__title, [class*='title']")
                c  = card.select_one("h4, .base-search-card__subtitle, [class*='company']")
                lo = card.select_one(".job-search-card__location, [class*='location']")
                lk = card.select_one("a[href*='/jobs/view/'], a.base-card__full-link")
                
                title    = t.get_text(strip=True) if t else ""
                company  = c.get_text(strip=True) if c else "לא צוין"
                location = lo.get_text(strip=True) if lo else "ירושלים"
                href     = lk["href"].split("?")[0] if lk else ""
                
                if title and is_relevant(title, location):
                    jobs.append({
                        "title": title, "company": company,
                        "location": location, "url": href, "source": "LinkedIn"
                    })
        except Exception as e:
            print(f"  ⚠️ LinkedIn [{label}]: {e}")
        time.sleep(1)
    return jobs

# ─── HireME ───────────────────────────────────────────────
def scrape_hireme():
    """HireME.co.il"""
    jobs = []
    base = "https://hireme.co.il"
    queries = ["BI Developer", "BI Team Lead", "Business Intelligence"]
    
    for q in queries:
        urls_to_try = [
            f"{base}/jobs/?search={requests.utils.quote(q)}&location=jerusalem",
            f"{base}/?s={requests.utils.quote(q)}",
            f"{base}/search/?q={requests.utils.quote(q)}&city=jerusalem",
        ]
        for url in urls_to_try:
            try:
                soup = get_soup(url)
                
                # חפש כל קישור לדף משרה
                for link in soup.find_all("a", href=re.compile(r"/jobs?/|/position/|/career/", re.I)):
                    title = link.get_text(strip=True)
                    if not title or len(title) < 4:
                        continue
                    if not is_relevant(title):
                        continue
                    
                    href = link["href"]
                    if not href.startswith("http"):
                        href = base + href
                    
                    parent_text = link.parent.get_text(separator=" ", strip=True) if link.parent else ""
                    loc_match   = re.search(r"ירושלים|Jerusalem", parent_text, re.I)
                    location    = "ירושלים" if loc_match else ""
                    
                    if location or True:
                        jobs.append({
                            "title": title,
                            "company": "HireME",
                            "location": location or "ירושלים",
                            "url": href,
                            "source": "HireME"
                        })
                if jobs:
                    break
            except requests.exceptions.ConnectionError:
                print(f"  ⚠️ HireME [{q}]: חסום – דלג")
                break
            except Exception as e:
                print(f"  ⚠️ HireME [{q}]: {e}")
        time.sleep(0.5)

    seen_titles = set()
    unique = []
    for j in jobs:
        k = j["title"].lower()
        if k not in seen_titles:
            seen_titles.add(k)
            unique.append(j)
    return unique

# ─── SecretHunter ─────────────────────────────────────────
def scrape_secrethunter():
    """secrethunter.io"""
    jobs = []
    base = "https://secrethunter.io"
    queries = ["BI Developer", "BI Team Lead", "Business Intelligence"]
    
    for q in queries:
        urls_to_try = [
            f"{base}/jobs?query={requests.utils.quote(q)}&location=Jerusalem",
            f"{base}/jobs?q={requests.utils.quote(q)}&city=Jerusalem",
            f"{base}/search?term={requests.utils.quote(q)}",
        ]
        for url in urls_to_try:
            try:
                r = requests.get(url, headers=HEADERS, timeout=15)
                if r.status_code != 200:
                    continue
                soup = BeautifulSoup(r.text, "html.parser")
                
                # SecretHunter – React/Next.js – חפש data ב-script tags
                scripts = soup.find_all("script", type="application/json")
                for script in scripts:
                    try:
                        data = json.loads(script.string or "")
                        # חפש משרות ב-JSON
                        text = json.dumps(data, ensure_ascii=False).lower()
                        if any(k in text for k in KEYWORDS):
                            # מצאנו נתוני משרות ב-JSON
                            print(f"  📦 SecretHunter: נמצא JSON עם משרות")
                    except:
                        pass
                
                # נסה גם HTML רגיל
                for link in soup.find_all("a", href=True):
                    title = link.get_text(strip=True)
                    if not title or len(title) < 4:
                        continue
                    if not is_relevant(title):
                        continue
                    
                    href = link["href"]
                    if not href.startswith("http"):
                        href = base + href
                    
                    parent_text = link.parent.get_text(separator=" ", strip=True) if link.parent else ""
                    loc_match   = re.search(r"ירושלים|Jerusalem", parent_text, re.I)
                    location    = "ירושלים" if loc_match else ""
                    
                    jobs.append({
                        "title": title,
                        "company": "SecretHunter",
                        "location": location or "ירושלים",
                        "url": href,
                        "source": "SecretHunter"
                    })
                if jobs:
                    break
            except requests.exceptions.ConnectionError:
                print(f"  ⚠️ SecretHunter [{q}]: חסום")
                break
            except Exception as e:
                print(f"  ⚠️ SecretHunter [{q}]: {e}")
        time.sleep(0.5)
    
    seen_titles = set()
    unique = []
    for j in jobs:
        k = j["title"].lower()
        if k not in seen_titles:
            seen_titles.add(k)
            unique.append(j)
    return unique

# ─── Main ──────────────────────────────────────────────────
def main():
    print(f"\n🔍 סריקה החלה – {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    seen      = load_seen_jobs()
    new_count = 0

    scrapers = [
        ("AllJobs",      scrape_alljobs),
        ("JobMaster",    scrape_jobmaster),
        ("LinkedIn",     scrape_linkedin),
        ("HireME",       scrape_hireme),
        ("SecretHunter", scrape_secrethunter),
    ]

    all_jobs = []
    for name, fn in scrapers:
        print(f"\n📡 סורק {name}...")
        try:
            found = fn()
            print(f"   נמצאו {len(found)} משרות")
            all_jobs.extend(found)
        except Exception as e:
            print(f"   ❌ שגיאה כללית ב-{name}: {e}")

    print(f"\n📋 סה\"כ: {len(all_jobs)} (לפני הסרת כפולים)")

    for job in all_jobs:
        jid = job_id(job["title"], job["company"], job["url"])
        if jid not in seen:
            seen.add(jid)
            send_telegram(fmt(job["title"], job["company"],
                              job["location"], job["url"], job["source"]))
            new_count += 1
            print(f"  ➕ {job['source']}: {job['title']} @ {job['company']}")

    save_seen_jobs(seen)
    print("\n" + "=" * 50)
    print("✅ אין משרות חדשות" if new_count == 0 else f"🎉 נשלחו {new_count} התראות!")

if __name__ == "__main__":
    main()
