import json, os, hashlib, asyncio, re
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
    "data bi", "bi engineer",
]
LOCATION_KEYWORDS = ["ירושלים", "jerusalem"]
MIN_EXP_YEARS    = 3
SEEN_JOBS_FILE   = "seen_jobs.json"

# ─── Experience detection ──────────────────────────────────
_EXP_RE = re.compile(
    r'(\d+)\+?\s*שנות?\s*ניסיון'
    r'|ניסיון\s*של\s*(\d+)\+?\s*שנ'
    r'|לפחות\s*(\d+)\s*שנ'
    r'|(\d+)\s*[-–]\s*\d+\s*שנות?\s*ניסיון'
    r'|(\d+)\+\s*years?\s*(?:of\s*)?(?:experience|exp\.?)'
    r'|(\d+)\s*[-–]\s*\d+\s*years?\s*(?:of\s*)?(?:experience|exp\.?)'
    r'|minimum\s+(\d+)\s+years?'
    r'|at\s+least\s+(\d+)\s+years?'
    r'|(\d+)\s*שנ[וי]?[מות]*\s*(?:ניסיון|לפחות)',
    re.IGNORECASE
)

def extract_max_years(text):
    """Return the maximum years-of-experience found in text, or None."""
    if not text:
        return None
    years = []
    for m in _EXP_RE.finditer(text):
        for g in m.groups():
            if g:
                try:
                    years.append(int(g))
                except ValueError:
                    pass
    return max(years) if years else None

def meets_experience(text):
    """
    True  → text explicitly states MIN_EXP_YEARS+ years of experience.
    False → text explicitly states < MIN_EXP_YEARS years.
    None  → not mentioned (let the job through – user decides).
    """
    yr = extract_max_years(text)
    if yr is None:
        return None
    return yr >= MIN_EXP_YEARS

# ─── Helpers ──────────────────────────────────────────────
def load_seen():
    return set(json.load(open(SEEN_JOBS_FILE, encoding="utf-8"))) if os.path.exists(SEEN_JOBS_FILE) else set()

def save_seen(seen):
    json.dump(list(seen), open(SEEN_JOBS_FILE, "w", encoding="utf-8"))

def jid(title, company, url):
    return hashlib.md5(f"{title}|{company}|{url}".lower().encode()).hexdigest()

def is_bi(text):
    t = text.lower()
    return any(k in t for k in KEYWORDS)

def is_jerusalem(text):
    t = text.lower()
    return any(l in t for l in LOCATION_KEYWORDS)

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

def fmt(title, company, location, url, source, exp_text=""):
    exp_line = f"⏳ {exp_text}\n" if exp_text else ""
    return (f"🔔 <b>משרה חדשה!</b>\n\n"
            f"💼 <b>{title}</b>\n"
            f"🏢 {company}\n"
            f"📍 {location}\n"
            f"{exp_line}"
            f"🌐 {source}\n\n"
            f"🔗 <a href='{url}'>לצפייה במשרה</a>")

def make_job(title, company, location, url, source, parent_text=""):
    yr = extract_max_years(parent_text)
    return {
        "title": title, "company": company,
        "location": location or "ירושלים",
        "url": url, "source": source,
        "exp_text": f"{yr}+ שנות ניסיון" if yr else "",
    }

# ─── AllJobs ──────────────────────────────────────────────
async def scrape_alljobs(page):
    jobs = []
    queries = ["BI Developer", "BI Team Lead", "Business Intelligence"]
    for q in queries:
        # cityid=3000 = ירושלים, fromedate=7 = שבוע אחרון
        url = (f"https://www.alljobs.co.il/SearchResults.aspx"
               f"?position={requests.utils.quote(q)}&cityid=3000&fromedate=7")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)
            html = await page.content()
            print(f"  [AllJobs/{q}] HTML: {len(html)}")

            cards = await page.query_selector_all(
                "a[href*='jobid'], a[href*='JobId'], a[href*='/job/'], "
                "[class*='job'][class*='item'], [class*='position']"
            )
            print(f"  [AllJobs/{q}] {len(cards)} קישורים")

            seen_titles = set()
            for card in cards:
                title = (await card.inner_text()).strip()
                href  = await card.get_attribute("href") or ""
                if not title or len(title) < 4 or title in seen_titles:
                    continue
                if not is_bi(title):
                    continue
                seen_titles.add(title)
                if href and not href.startswith("http"):
                    href = "https://www.alljobs.co.il" + href

                parent_text = await card.evaluate(
                    "el => el.closest('li, div, article')?.innerText || ''"
                )
                # URL already filters by Jerusalem city ID – still double-check
                exp = meets_experience(parent_text)
                if exp is False:
                    print(f"    ⏩ ניסיון נמוך, מדלג: {title}")
                    continue

                jobs.append(make_job(title, "ראה מודעה", "ירושלים", href, "AllJobs", parent_text))
        except Exception as e:
            print(f"  ⚠️ AllJobs [{q}]: {e}")
    return jobs

# ─── Drushim ──────────────────────────────────────────────
async def scrape_drushim(page):
    jobs = []
    queries = ["BI Developer", "BI Team Lead", "Business Intelligence"]
    for q in queries:
        url = (f"https://www.drushim.co.il/jobs/search/"
               f"?q={requests.utils.quote(q)}"
               f"&city=%D7%99%D7%A8%D7%95%D7%A9%D7%9C%D7%99%D7%9D")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)
            html = await page.content()
            print(f"  [Drushim/{q}] HTML: {len(html)}")

            cards = await page.query_selector_all(
                "a[href*='/job/'], [class*='job-card'], "
                "[class*='jobCard'], [class*='job_item'], article"
            )
            print(f"  [Drushim/{q}] {len(cards)} כרטיסיות")

            seen_titles = set()
            for card in cards:
                title = (await card.inner_text()).strip().splitlines()[0].strip()
                href  = await card.get_attribute("href") or ""
                if not title or len(title) < 4 or title in seen_titles:
                    continue
                if not is_bi(title):
                    continue
                seen_titles.add(title)
                if href and not href.startswith("http"):
                    href = "https://www.drushim.co.il" + href

                parent_text = await card.evaluate(
                    "el => el.closest('li, div, article, section')?.innerText || el.innerText || ''"
                )
                # Drushim results may include non-Jerusalem if city filter didn't apply
                if not is_jerusalem(parent_text) and not is_jerusalem(url):
                    continue

                exp = meets_experience(parent_text)
                if exp is False:
                    print(f"    ⏩ ניסיון נמוך, מדלג: {title}")
                    continue

                jobs.append(make_job(title, "דרושים", "ירושלים", href, "דרושים", parent_text))
        except Exception as e:
            print(f"  ⚠️ Drushim [{q}]: {e}")
    return jobs

# ─── JobMaster ────────────────────────────────────────────
async def scrape_jobmaster(page):
    jobs = []
    queries = ["BI Developer", "BI Team Lead"]
    for q in queries:
        # %D7%99%D7%A8%D7%95%D7%A9%D7%9C%D7%99%D7%9D = ירושלים
        url = (f"https://www.jobmaster.co.il/jobs/"
               f"?q={requests.utils.quote(q)}&l=%D7%99%D7%A8%D7%95%D7%A9%D7%9C%D7%99%D7%9D")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)
            html = await page.content()
            print(f"  [JobMaster/{q}] HTML: {len(html)}")

            links = await page.query_selector_all("a[href]")
            seen_titles = set()
            for link in links:
                title = (await link.inner_text()).strip()
                href  = await link.get_attribute("href") or ""
                if not title or len(title) < 5 or title in seen_titles:
                    continue
                if not is_bi(title):
                    continue
                seen_titles.add(title)
                if href and not href.startswith("http"):
                    href = "https://www.jobmaster.co.il" + href

                parent_text = await link.evaluate(
                    "el => el.closest('li, div, article')?.innerText || ''"
                )
                if not is_jerusalem(parent_text) and not is_jerusalem(url):
                    continue

                exp = meets_experience(parent_text)
                if exp is False:
                    print(f"    ⏩ ניסיון נמוך, מדלג: {title}")
                    continue

                jobs.append(make_job(title, "JobMaster", "ירושלים", href, "JobMaster", parent_text))
        except Exception as e:
            print(f"  ⚠️ JobMaster [{q}]: {e}")
    return jobs

# ─── LinkedIn ─────────────────────────────────────────────
async def scrape_linkedin(page):
    jobs = []
    queries = [
        ("BI Developer",  "BI+Developer"),
        ("BI Team Lead",  "BI+Team+Lead"),
        ("BI Analyst",    "BI+Analyst"),
    ]
    for label, q in queries:
        # f_TPR=r604800 = last 7 days, f_E=3,4 = Mid-Senior + Director
        url = (f"https://www.linkedin.com/jobs/search/?keywords={q}"
               f"&location=Jerusalem%2C+Israel"
               f"&f_TPR=r604800&f_E=3,4")
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

                if not title or not is_bi(title):
                    continue
                if not is_jerusalem(location):
                    continue

                card_text = await card.inner_text()
                exp = meets_experience(card_text)
                if exp is False:
                    print(f"    ⏩ ניסיון נמוך, מדלג: {title}")
                    continue

                jobs.append(make_job(title, company, location, href, "LinkedIn", card_text))
        except Exception as e:
            print(f"  ⚠️ LinkedIn [{label}]: {e}")
    return jobs

# ─── Indeed Israel ────────────────────────────────────────
async def scrape_indeed(page):
    jobs = []
    queries = ["BI Developer", "BI Team Lead", "Business Intelligence"]
    for q in queries:
        # explvl=senior_level, fromage=7 = last 7 days
        url = (f"https://il.indeed.com/jobs?q={requests.utils.quote(q)}"
               f"&l=%D7%99%D7%A8%D7%95%D7%A9%D7%9C%D7%99%D7%9D"
               f"&fromage=7&explvl=senior_level")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)
            html = await page.content()
            print(f"  [Indeed/{q}] HTML: {len(html)}")

            cards = await page.query_selector_all(
                "[class*='job_seen_beacon'], "
                "[data-testid='jobsearch-ResultsList'] li, "
                ".jobsearch-SerpJobCard, [class*='tapItem']"
            )
            print(f"  [Indeed/{q}] {len(cards)} כרטיסיות")

            for card in cards:
                t  = await card.query_selector("h2 a span, [class*='jobTitle'] span, h2[class*='title']")
                c  = await card.query_selector("[class*='companyName'], [data-testid='company-name']")
                lo = await card.query_selector("[class*='companyLocation'], [data-testid='text-location']")
                lk = await card.query_selector("a[id*='job_'], a[href*='/rc/clk'], a[href*='/pagead/']")

                title    = (await t.inner_text()).strip() if t else ""
                company  = (await c.inner_text()).strip() if c else "לא צוין"
                location = (await lo.inner_text()).strip() if lo else ""
                href     = await lk.get_attribute("href") or "" if lk else ""

                if not title or not is_bi(title):
                    continue
                if not is_jerusalem(location) and not is_jerusalem(url):
                    continue
                if href and not href.startswith("http"):
                    href = "https://il.indeed.com" + href

                card_text = await card.inner_text()
                exp = meets_experience(card_text)
                if exp is False:
                    print(f"    ⏩ ניסיון נמוך, מדלג: {title}")
                    continue

                jobs.append(make_job(title, company, location or "ירושלים", href, "Indeed", card_text))
        except Exception as e:
            print(f"  ⚠️ Indeed [{q}]: {e}")
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
            print(f"  [SecretHunter/{q}] HTML: {len(html)}")

            links = await page.query_selector_all("a[href]")
            seen_titles = set()
            for link in links:
                title = (await link.inner_text()).strip()
                href  = await link.get_attribute("href") or ""
                if not title or len(title) < 5 or title in seen_titles:
                    continue
                if not is_bi(title):
                    continue
                seen_titles.add(title)
                if href and not href.startswith("http"):
                    href = "https://secrethunter.io" + href

                parent_text = await link.evaluate(
                    "el => el.closest('li, div, article')?.innerText || ''"
                )
                if not is_jerusalem(parent_text) and not is_jerusalem(url):
                    continue

                exp = meets_experience(parent_text)
                if exp is False:
                    print(f"    ⏩ ניסיון נמוך, מדלג: {title}")
                    continue

                jobs.append(make_job(title, "SecretHunter", "ירושלים", href, "SecretHunter", parent_text))
        except Exception as e:
            print(f"  ⚠️ SecretHunter [{q}]: {e}")
    return jobs

# ─── Main ──────────────────────────────────────────────────
async def main_async():
    print(f"\n🔍 סריקה החלה – {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"   מחפש: BI Developer / BI Team Lead | ירושלים | {MIN_EXP_YEARS}+ שנות ניסיון")
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

        scrapers = [
            ("AllJobs",      scrape_alljobs),
            ("Drushim",      scrape_drushim),
            ("JobMaster",    scrape_jobmaster),
            ("LinkedIn",     scrape_linkedin),
            ("Indeed",       scrape_indeed),
            ("SecretHunter", scrape_secrethunter),
        ]

        for name, fn in scrapers:
            print(f"\n📡 סורק {name}...")
            try:
                found = await fn(page)
                unique = {j["title"].lower(): j for j in found}
                found  = list(unique.values())
                print(f"   נמצאו {len(found)} משרות רלוונטיות")
                all_jobs.extend(found)
            except Exception as e:
                print(f"   ❌ {name}: {e}")

        await browser.close()

    print(f"\n📋 סה\"כ לפני ניקוי כפולים: {len(all_jobs)}")

    for job in all_jobs:
        jid_ = jid(job["title"], job["company"], job["url"])
        if jid_ not in seen:
            seen.add(jid_)
            send_telegram(fmt(
                job["title"], job["company"], job["location"],
                job["url"], job["source"], job.get("exp_text", "")
            ))
            new_count += 1
            print(f"  ➕ {job['source']}: {job['title']} @ {job['company']}")

    save_seen(seen)
    print("\n" + "=" * 50)
    print("✅ אין משרות חדשות" if new_count == 0 else f"🎉 נשלחו {new_count} התראות!")


def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
