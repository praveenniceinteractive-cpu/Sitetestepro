import asyncio
import httpx
from playwright.async_api import async_playwright
import json

URL = "https://wilklawfirm.com/contact-wilk-law/"

async def test_httpx():
    result = {"method": "HTTPX"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
        "Referer": "https://www.google.com/"
    }
    
    try:
        async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
            resp = await client.get(URL, headers=headers, timeout=15.0)
            result["status"] = resp.status_code
            result["server"] = resp.headers.get('server', 'Unknown')
            result["content_sample"] = resp.text[:200]
    except Exception as e:
        result["error"] = str(e)
    return result

async def test_playwright():
    result = {"method": "Playwright"}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        try:
            response = await page.goto(URL, timeout=30000)
            result["status"] = response.status if response else "Unknown"
            result["content_sample"] = (await page.content())[:200]
        except Exception as e:
            result["error"] = str(e)
        finally:
            await browser.close()
    return result

async def main():
    r1 = await test_httpx()
    r2 = await test_playwright()
    
    with open("debug_results.json", "w") as f:
        json.dump([r1, r2], f, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
