import httpx
import asyncio

PROXY_URL = "http://127.0.0.1:8000/api/proxy"
TARGET_URL = "https://www.amazon.in/?&tag=googhydrabk1-21&ref=pd_sl_5szpgfto9i_e&adgrpid=155259813593&hvpone=&hvptwo=&hvadid=674893540034&hvpos=&hvnetw=g&hvrand=8777247946765633578&hvqmt=e&hvdev=c&hvdvcmdl=&hvlocint=&hvlocphy=9184631&hvtargid=kwd-64107830&hydadcr=14452_2316413&gad_source=1"

async def test_proxy():
    print(f"Testing Proxy with URL: {TARGET_URL[:50]}...")
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.get(PROXY_URL, params={"url": TARGET_URL})
            print(f"Status: {resp.status_code}")
            print(f"Headers: {resp.headers}")
            print(f"Body Length: {len(resp.content)}")
            print(f"Body Preview: {resp.text[:500]}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_proxy())
