import json, os, hashlib, asyncio
from datetime import datetime
import requests
from playwright.async_api import async_playwright

# ─── הגדרות ───────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

KEYWORDS = [
    "bi developer", "bi team lead", "ר\"צ bi", "ראש צוות bi",
    "business intelligence developer", "business intelligence team lead",
    "מפתח bi", "מפתחת bi", "bi analyst", "bi manager", "bi lead",
]
LOCATION_KEYWORDS = ["ירושלים", "jerusalem"]
SEEN_JOBS_FILE   = "seen_jobs.json"

# ─── עזרים ────────────────────────────────────────────────
def load_seen(): 
    return set(json.load(open(SEEN_JOBS_FILE, encoding="utf-8"))) if os.path.exists(SEEN_JOBS_FILE) else set()

def save_seen(seen): 
    json.dump(list(seen), open(SEEN_JOBS_FILE, "w", encoding="utf-8"))

def jid(title, company, url): 
    return hashlib.md5(f"{title}|{company}|{url}".lower().encode()).hexdigest()

def is_relevant(title, location=""):
    return (any(k in title.lower() for k in KEYWORDS) and
            (any(l in location.lower() for l in LOCATION_KEYWORDS) or not location.strip()))

def send_telegram(msg):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg,
                  "parse_mode": "HTML", "disable_web_page_preview": False},
            timeout=10)
        r.raise_for_status()
        print("  ✅ טלגרם נשלח")
    except Exception as e:
        print(f"  ❌ טלגרם: {e}")

def fmt(title, company, location, url, source):
    return (f"🔔 <b>משרה חדשה!</b>\n\n"
            f"💼 <b>{title}</b>\n🏢 {company}\n📍 {location}\n🌐 {source}\n\n"
            f"🔗 <a href='{url}'>לצפייה במשרה</a>")

# ─── Playwright scraper ───────────────────────────────────
async def scrape_site(page, site_name, search_url, job_selector, title_sel, company_sel, location_sel, link_sel, base_url=""):
    jobs = []
    try:
        print(f"  🌐 טוען {site_name}...")
        await page.goto(search_url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)  # המתן ל-JS
        
        cards = await page.query_selector_all(job_selector)
        print(f"  📋 נמצאו {len(cards)} כרטיסיות")
        
        for card in cards:
            try:
                t  = await card.query_selector(title_sel)
                c  = await card.query_selector(company_sel)
                lo = await card.query_selector(location_sel)
                lk = await card.query_selector(link_sel)
                
                title    = (await t.inner_text()).strip() if t else ""
                company  = (await c.inner_text()).strip() if c else "לא צוין"
                location = (await lo.inner_text()).strip() if lo else ""
                href     = await lk.get_attribute("href") if lk else ""
                
                if not title: continue
                if href and not href.startswith("http"):
                    href = base_url + href
                
                if is_relevant(title, location):
                    jobs.append({"title": title, "company": company,
                                 "location": location or "ירושלים",
                                 "url": href, "source": site_name})
            except:
                continue
    except Exception as e:
        print(f"  ⚠️ {site_name}: {e}")
    return jobs


async def scrape_alljobs(page):
    jobs = []
    queries = ["BI Developer", "BI Team Lead"]
    for q in queries:
        url = f"https://www.alljobs.co.il/SearchResults.aspx?position={requests.utils.quote(q)}&cityid=3000&fromedate=7"
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            
            # AllJobs – חכה לכרטיסיות
            await page.wait_for_selector(".single-job-content, .job-content, .JobContent", timeout=10000)
            cards = await page.query_selector_all(".single-job-content, .job-content, .JobContent, [class*='job-item'], [class*='JobItem']")
            
            for card in cards:
                title_el = await card.query_selector("h2, h3, a, [class*='title'], [class*='Title']")
                loc_el   = await card.query_selector("[class*='city'], [class*='location'], [class*='Location']")
                link_el  = await card.query_selector("a[href]")
                
                title    = (await title_el.inner_text()).strip() if title_el else ""
                location = (await loc_el.inner_text()).strip() if loc_el else ""
                href     = await link_el.get_attribute("href") if link_el else ""
                
                if not title or not is_relevant(title, location): continue
                if href and not href.startswith("http"):
                    href = "https://www.alljobs.co.il" + href
                
                comp_el = await card.query_selector("[class*='company'], [class*='Company'], [class*='employer']")
                company = (await comp_el.inner_text()).strip() if comp_el else "לא צוין"
                
                jobs.append({"title": title, "company": company,
                             "location": location or "ירושלים",
                             "url": href, "source": "AllJobs"})
        except Exception as e:
            print(f"  ⚠️ AllJobs [{q}]: {e}")
    return jobs


async def scrape_jobmaster(page):
    jobs = []
    queries = ["BI Developer", "BI Team Lead"]
    for q in queries:
        url = f"https://www.jobmaster.co.il/jobs/?q={requests.utils.quote(q)}&l=%D7%99%D7%A8%D7%95%D7%A9%D7%9C%D7%99%D7%9D"
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            
            cards = await page.query_selector_all("[class*='job'], [class*='Job'], article, li[class*='result']")
            
            for card in cards:
                title_el = await card.query_selector("h2, h3, [class*='title'], [class*='Title'], a")
                loc_el   = await card.query_selector("[class*='city'], [class*='location'], [class*='Location']")
                link_el  = await card.query_selector("a[href]")
                
                title    = (await title_el.inner_text()).strip() if title_el else ""
                location = (await loc_el.inner_text()).strip() if loc_el else ""
                href     = await link_el.get_attribute("href") if link_el else ""
                
                if not title or len(title) < 5: continue
                if not is_relevant(title, location): continue
                if href and not href.startswith("http"):
                    href = "https://www.jobmaster.co.il" + href
                
                comp_el = await card.query_selector("[class*='company'], [class*='Company']")
                company = (await comp_el.inner_text()).strip() if comp_el else "לא צוין"
                
                jobs.append({"title": title, "company": company,
                             "location": location or "ירושלים",
                             "url": href, "source": "JobMaster"})
        except Exception as e:
            print(f"  ⚠️ JobMaster [{q}]: {e}")
    return jobs


async def scrape_linkedin(page):
    jobs = []
    queries = [("BI Developer", "BI+Developer"), ("BI Team Lead", "BI+Team+Lead")]
    for label, q in queries:
        url = (f"https://www.linkedin.com/jobs/search/?keywords={q}"
               f"&location=Jerusalem%2C+Israel&f_TPR=r604800")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)
            
            cards = await page.query_selector_all("div.base-card, div.job-search-card, li.jobs-search-results__list-item")
            
            for card in cards:
                t  = await card.query_selector("h3, .base-search-card__title")
                c  = await card.query_selector("h4, .base-search-card__subtitle")
                lo = await card.query_selector(".job-search-card__location, [class*='location']")
                lk = await card.query_selector("a[href*='/jobs/view/']")
                
                title    = (await t.inner_text()).strip() if t else ""
                company  = (await c.inner_text()).strip() if c else "לא צוין"
                location = (await lo.inner_text()).strip() if lo else ""
                href     = await lk.get_attribute("href") if lk else ""
                if href: href = href.split("?")[0]
                
                if title and is_relevant(title, location):
                    jobs.append({"title": title, "company": company,
                                 "location": location or "ירושלים",
                                 "url": href, "source": "LinkedIn"})
        except Exception as e:
            print(f"  ⚠️ LinkedIn [{label}]: {e}")
    return jobs


async def scrape_hireme(page):
    jobs = []
    queries = ["BI Developer", "BI Team Lead"]
    for q in queries:
        url = f"https://hireme.co.il/?s={requests.utils.quote(q)}&location=ירושלים"
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            
            cards = await page.query_selector_all("[class*='job'], [class*='Job'], article, .listing")
            
            for card in cards:
                title_el = await card.query_selector("h2, h3, [class*='title'], a")
                loc_el   = await card.query_selector("[class*='location'], [class*='city']")
                link_el  = await card.query_selector("a[href]")
                
                title    = (await title_el.inner_text()).strip() if title_el else ""
                location = (await loc_el.inner_text()).strip() if loc_el else ""
                href     = await link_el.get_attribute("href") if link_el else ""
                
                if not title or not is_relevant(title, location): continue
                
                jobs.append({"title": title, "company": "HireME",
                             "location": location or "ירושלים",
                             "url": href, "source": "HireME"})
        except Exception as e:
            print(f"  ⚠️ HireME [{q}]: {e}")
    return jobs


async def scrape_secrethunter(page):
    jobs = []
    queries = ["BI Developer", "BI Team Lead"]
    for q in queries:
        url = f"https://secrethunter.io/jobs?query={requests.utils.quote(q)}&location=Jerusalem"
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)
            
            cards = await page.query_selector_all("[class*='job'], [class*='Job'], [class*='card'], [class*='Card'], article")
            
            for card in cards:
                title_el = await card.query_selector("h2, h3, [class*='title'], [class*='Title']")
                loc_el   = await card.query_selector("[class*='location'], [class*='city']")
                link_el  = await card.query_selector("a[href]")
                
                title    = (await title_el.inner_text()).strip() if title_el else ""
                location = (await loc_el.inner_text()).strip() if loc_el else ""
                href     = await link_el.get_attribute("href") if link_el else ""
                
                if not title or not is_relevant(title, location): continue
                if href and not href.startswith("http"):
                    href = "https://secrethunter.io" + href
                
                jobs.append({"title": title, "company": "SecretHunter",
                             "location": location or "ירושלים",
                             "url": href, "source": "SecretHunter"})
        except Exception as e:
            print(f"  ⚠️ SecretHunter [{q}]: {e}")
    return jobs


# ─── Main ──────────────────────────────────────────────────
async def main_async():
    print(f"\n🔍 סריקה החלה – {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    seen      = load_seen()
    new_count = 0
    all_jobs  = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-dev-shm-usage", "--disable-gpu"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            locale="he-IL",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        scrapers = [
            ("AllJobs",      scrape_alljobs),
            ("JobMaster",    scrape_jobmaster),
            ("LinkedIn",     scrape_linkedin),
            ("HireME",       scrape_hireme),
            ("SecretHunter", scrape_secrethunter),
        ]

        for name, fn in scrapers:
            print(f"\n📡 סורק {name}...")
            try:
                found = await fn(page)
                print(f"   נמצאו {len(found)} משרות רלוונטיות")
                all_jobs.extend(found)
            except Exception as e:
                print(f"   ❌ {name}: {e}")

        await browser.close()

    print(f"\n📋 סה\"כ: {len(all_jobs)}")

    for job in all_jobs:
        jid_ = jid(job["title"], job["company"], job["url"])
        if jid_ not in seen:
            seen.add(jid_)
            send_telegram(fmt(job["title"], job["company"],
                              job["location"], job["url"], job["source"]))
            new_count += 1
            print(f"  ➕ {job['source']}: {job['title']} @ {job['company']}")

    save_seen(seen)
    print("\n" + "=" * 50)
    print("✅ אין משרות חדשות" if new_count == 0 else f"🎉 נשלחו {new_count} התראות!")


def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
