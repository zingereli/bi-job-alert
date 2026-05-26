import requests
from bs4 import BeautifulSoup
import json, os, hashlib
from datetime import datetime

# ─── הגדרות ───────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

KEYWORDS = [
    "bi developer", "bi team lead", "ר\"צ bi", "ראש צוות bi",
    "business intelligence developer", "business intelligence team lead",
    "מפתח bi", "מפתחת bi", "bi analyst", "bi manager",
]
LOCATION_KEYWORDS = ["ירושלים", "jerusalem"]
SEEN_JOBS_FILE    = "seen_jobs.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
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
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message,
                                      "parse_mode": "HTML", "disable_web_page_preview": False}, timeout=10)
        r.raise_for_status()
        print("  ✅ נשלחה הודעה בטלגרם")
    except Exception as e:
        print(f"  ❌ שגיאת טלגרם: {e}")

def fmt(title, company, location, url, source):
    return (f"🔔 <b>משרה חדשה!</b>\n\n"
            f"💼 <b>{title}</b>\n"
            f"🏢 {company}\n📍 {location}\n🌐 {source}\n\n"
            f"🔗 <a href='{url}'>לצפייה במשרה</a>")

# ─── AllJobs ──────────────────────────────────────────────
def scrape_alljobs():
    jobs, base = [], "https://www.alljobs.co.il"
    for q in ["BI+Developer", "BI+Team+Lead", "Business+Intelligence"]:
        url = f"{base}/SearchResults.aspx?FromDate=1&position={q}&cityid=3000"
        try:
            soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=15).text, "html.parser")
            for card in soup.select(".job-content-top,.single-job-content,.job_box"):
                t  = card.select_one(".job-title a,h2 a,.position a")
                c  = card.select_one(".job-company,.company-name,.company")
                lo = card.select_one(".job-location,.location,.city")
                lk = card.select_one("a[href]")
                title = t.get_text(strip=True) if t else ""
                if not title: continue
                href = lk["href"] if lk else ""
                jobs.append({"title": title,
                              "company":  c.get_text(strip=True) if c else "לא צוין",
                              "location": lo.get_text(strip=True) if lo else "ירושלים",
                              "url": href if href.startswith("http") else base+href,
                              "source": "AllJobs"})
        except Exception as e:
            print(f"  ⚠️ AllJobs [{q}]: {e}")
    return [j for j in jobs if is_relevant(j["title"], j["location"])]

# ─── JobMaster ────────────────────────────────────────────
def scrape_jobmaster():
    jobs, base = [], "https://www.jobmaster.co.il"
    for q in ["BI Developer", "BI Team Lead", "Business Intelligence"]:
        url = f"{base}/jobs/?q={requests.utils.quote(q)}&l=%D7%99%D7%A8%D7%95%D7%A9%D7%9C%D7%99%D7%9D"
        try:
            soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=15).text, "html.parser")
            for card in soup.select(".job_list_item,.JobItem,article.job,.job-item"):
                t  = card.select_one("h2 a,.job-title a,.JobTitle a,.title a")
                c  = card.select_one(".company,.CompanyName,.employer")
                lo = card.select_one(".location,.JobLocation,.city")
                lk = card.select_one("a[href]")
                title = t.get_text(strip=True) if t else ""
                if not title: continue
                href = lk["href"] if lk else ""
                jobs.append({"title": title,
                              "company":  c.get_text(strip=True) if c else "לא צוין",
                              "location": lo.get_text(strip=True) if lo else "ירושלים",
                              "url": href if href.startswith("http") else base+href,
                              "source": "JobMaster"})
        except Exception as e:
            print(f"  ⚠️ JobMaster [{q}]: {e}")
    return [j for j in jobs if is_relevant(j["title"], j["location"])]

# ─── LinkedIn ─────────────────────────────────────────────
def scrape_linkedin():
    """סריקת דפי משרות ציבוריים של לינקדין (ללא התחברות)."""
    jobs, base = [], "https://www.linkedin.com"
    for q in ["BI+Developer", "BI+Team+Lead", "Business+Intelligence+Developer"]:
        url = (f"{base}/jobs/search/?keywords={q}"
               f"&location=Jerusalem%2C+Israel&f_TPR=r86400")
        try:
            soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=20).text, "html.parser")
            for card in soup.select("div.base-card,.job-search-card,.base-search-card"):
                t  = card.select_one("h3.base-search-card__title,h3,.job-title")
                c  = card.select_one("h4.base-search-card__subtitle,.company-name,h4")
                lo = card.select_one(".job-search-card__location,.location")
                lk = card.select_one("a.base-card__full-link,a[href*='/jobs/view/']")
                title = t.get_text(strip=True) if t else ""
                if not title: continue
                href = lk["href"].split("?")[0] if lk else ""
                jobs.append({"title": title,
                              "company":  c.get_text(strip=True) if c else "לא צוין",
                              "location": lo.get_text(strip=True) if lo else "ירושלים",
                              "url": href,
                              "source": "LinkedIn"})
        except Exception as e:
            print(f"  ⚠️ LinkedIn [{q}]: {e}")
    return [j for j in jobs if is_relevant(j["title"], j["location"])]

# ─── HireME ───────────────────────────────────────────────
def scrape_hireme():
    jobs, base = [], "https://hireme.co.il"
    for q in ["BI Developer", "BI Team Lead", "Business Intelligence"]:
        url = f"{base}/job-search/?s={requests.utils.quote(q)}&location=%D7%99%D7%A8%D7%95%D7%A9%D7%9C%D7%99%D7%9D"
        try:
            soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=15).text, "html.parser")
            for card in soup.select(".job-listing,.job_listing,article.job_listing,.job-card,.wpjb-job-row"):
                t  = card.select_one("h3 a,h2 a,.job-title a,.position a")
                c  = card.select_one(".company,.company-name,strong.company")
                lo = card.select_one(".location,.job-location,.city")
                lk = card.select_one("a[href]")
                title = t.get_text(strip=True) if t else ""
                if not title: continue
                href = lk["href"] if lk else ""
                jobs.append({"title": title,
                              "company":  c.get_text(strip=True) if c else "לא צוין",
                              "location": lo.get_text(strip=True) if lo else "ירושלים",
                              "url": href if href.startswith("http") else base+href,
                              "source": "HireME"})
        except Exception as e:
            print(f"  ⚠️ HireME [{q}]: {e}")
    return [j for j in jobs if is_relevant(j["title"], j["location"])]

# ─── SecretHunter ─────────────────────────────────────────
def scrape_secrethunter():
    jobs, base = [], "https://secrethunter.io"
    for q in ["BI Developer", "BI Team Lead", "Business Intelligence"]:
        url = f"{base}/jobs?query={requests.utils.quote(q)}&location=Jerusalem"
        try:
            soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=15).text, "html.parser")
            # נסה selectors שונים – האתר עשוי להשתמש ב-React/Next.js
            for card in soup.select("[class*='job'],[class*='position'],[class*='card'],article"):
                t  = card.select_one("h2,h3,[class*='title'],[class*='name']")
                c  = card.select_one("[class*='company'],[class*='employer']")
                lo = card.select_one("[class*='location'],[class*='city']")
                lk = card.select_one("a[href]")
                title = t.get_text(strip=True) if t else ""
                if not title or len(title) < 3: continue
                href = lk["href"] if lk else ""
                jobs.append({"title": title,
                              "company":  c.get_text(strip=True) if c else "לא צוין",
                              "location": lo.get_text(strip=True) if lo else "ירושלים",
                              "url": href if href.startswith("http") else base+href,
                              "source": "SecretHunter"})
        except Exception as e:
            print(f"  ⚠️ SecretHunter [{q}]: {e}")
    return [j for j in jobs if is_relevant(j["title"], j["location"])]

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
        found = fn()
        print(f"   נמצאו {len(found)} משרות")
        all_jobs.extend(found)

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