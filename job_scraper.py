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

# ─── AllJobs ──────────────────────────────────────────────
async def scrape_alljobs(page):
    jobs = []
    queries = ["BI Developer", "BI Team Lead", "Business Intelligence"]
    for q in queries:
        url = (f"https://www.alljobs.co.il/SearchResults.aspx"
               f"?position={requests.utils.quote(q)}&cityid=3000&fromedate=7")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)  # המתן ל-JS

            # הדפס את ה-HTML לדיבוג
            html = await page.content()
            print(f"  [AllJobs debug] HTML length: {len(html)}")

            # נסה selectors גמישים מאוד
            cards = await page.query_selector_all("a[href*='jobid'], a[href*='JobId'], a[href*='/job/'], [class*='job'][class*='item'], [class*='position']")
            print(f"  [AllJobs] {len(cards)} קישורי משרה")

            seen_titles = set()
            for card in cards:
                title = (await card.inner_text()).strip()
                href  = await card.get_attribute("href") or ""

                if not title or len(title) < 4: continue
                if title in seen_titles: continue
                if not is_relevant(title): continue

                seen_titles.add(title)
                if href and not href.startswith("http"):
                    href = "https://www.alljobs.co.il" + href

                # נסה למצוא location בתוכן הסביבה
                parent = await card.evaluate("el => el.closest('li, div, article')?.innerText || ''")
                loc = "ירושלים" if any(l in parent.lower() for l in LOCATION_KEYWORDS) else ""

                if is_relevant(title, loc) or is_relevant(title):
                    jobs.append({"title": title, "company": "ראה מודעה",
                                 "location": loc or "ירושלים",
                                 "url": href, "source": "AllJobs"})
        except Exception as e:
            print(f"  ⚠️ AllJobs [{q}]: {e}")
    return jobs

# ─── JobMaster ────────────────────────────────────────────
async def scrape_jobmaster(page):
    jobs = []
    queries = ["BI Developer", "BI Team Lead"]
    for q in queries:
        url = (f"https://www.jobmaster.co.il/jobs/"
               f"?q={requests.utils.quote(q)}&l=%D7%99%D7%A8%D7%95%D7%A9%D7%9C%D7%99%D7%9D")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)

            html = await page.content()
            print(f"  [JobMaster debug] HTML length: {len(html)}")

            # חפש את כל הקישורים לדפי משרה
            links = await page.query_selector_all("a[href]")
            print(f"  [JobMaster] {len(links)} קישורים סה\"כ")

            seen_titles = set()
            for link in links:
                title = (await link.inner_text()).strip()
                href  = await link.get_attribute("href") or ""

                if not title or len(title) < 5: continue
                if title in seen_titles: continue
                if not is_relevant(title): continue

                seen_titles.add(title)
                if href and not href.startswith("http"):
                    href = "https://www.jobmaster.co.il" + href

                parent = await link.evaluate("el => el.closest('li, div, article')?.innerText || ''")
                loc = "ירושלים" if any(l in parent.lower() for l in LOCATION_KEYWORDS) else ""

                jobs.append({"title": title, "company": "JobMaster",
                             "location": loc or "ירושלים",
                             "url": href, "source": "JobMaster"})
        except Exception as e:
            print(f"  ⚠️ JobMaster [{q}]: {e}")
    return jobs

# ─── LinkedIn ─────────────────────────────────────────────
async def scrape_linkedin(page):
    jobs = []
    queries = [("BI Developer", "BI+Developer"),
               ("BI Team Lead", "BI+Team+Lead"),
               ("BI Analyst Jerusalem", "BI+Analyst")]
    for label, q in queries:
        url = (f"https://www.linkedin.com/jobs/search/?keywords={q}"
               f"&location=Jerusalem%2C+Israel&f_TPR=r604800")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)

            cards = await page.query_selector_all(
                "div.base-card, div.job-search-card, "
                "li.jobs-search-results__list-item, "
                "[data-entity-urn*='jobPosting']"
            )
            print(f"  [LinkedIn/{label}] {len(cards)} כרטיסיות")

            for card in cards:
                t  = await card.query_selector("h3, .base-search-card__title, [class*='title']")
                c  = await card.query_selector("h4, .base-search-card__subtitle, [class*='company']")
                lo = await card.query_selector(".job-search-card__location, [class*='location']")
                lk = await card.query_selector("a[href*='/jobs/view/']")

                title    = (await t.inner_text()).strip() if t else ""
                company  = (await c.inner_text()).strip() if c else "לא צוין"
                location = (await lo.inner_text()).strip() if lo else ""
                href     = (await lk.get_attribute("href") or "").split("?")[0] if lk else ""

                if title and is_relevant(title, location):
                    jobs.append({"title": title, "company": company,
                                 "location": location or "ירושלים",
                                 "url": href, "source": "LinkedIn"})
        except Exception as e:
            print(f"  ⚠️ LinkedIn [{label}]: {e}")
    return jobs

# ─── SecretHunter ─────────────────────────────────────────
async def scrape_secrethunter(page):
    jobs = []
    queries = ["BI Developer", "BI Team Lead"]
    for q in queries:
        url = f"https://secrethunter.io/jobs?query={requests.utils.quote(q)}&location=Jerusalem"
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(4000)

            html = await page.content()
            print(f"  [SecretHunter debug] HTML length: {len(html)}")

            links = await page.query_selector_all("a[href]")
            seen_titles = set()
            for link in links:
                title = (await link.inner_text()).strip()
                href  = await link.get_attribute("href") or ""

                if not title or len(title) < 5: continue
                if title in seen_titles: continue
                if not is_relevant(title): continue

                seen_titles.add(title)
                if href and not href.startswith("http"):
                    href = "https://secrethunter.io" + href

                parent = await link.evaluate("el => el.closest('li, div, article')?.innerText || ''")
                loc = "ירושלים" if any(l in parent.lower() for l in LOCATION_KEYWORDS) else ""

                jobs.append({"title": title, "company": "SecretHunter",
                             "location": loc or "ירושלים",
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
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="he-IL",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        # HireME הוסר – חוסם IPs של GitHub Actions
        scrapers = [
            ("AllJobs",      scrape_alljobs),
            ("JobMaster",    scrape_jobmaster),
            ("LinkedIn",     scrape_linkedin),
            ("SecretHunter", scrape_secrethunter),
        ]

        for name, fn in scrapers:
            print(f"\n📡 סורק {name}...")
            try:
                found = await fn(page)
                # הסר כפולים פנימיים
                unique = {j["title"].lower(): j for j in found}
                found  = list(unique.values())
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
