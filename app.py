import asyncio
import random
import logging
from aiohttp import web
from urllib.parse import urlparse
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import gzip
import brotli
from aiohttp.web_middlewares import middleware
import sys
import subprocess
from dotenv import load_dotenv
import os

load_dotenv()

# 配置
USER_DATA_DIR = './user_data'
EXECUTABLE_PATH = None
BROWSER_HEADLESS = True
REMOTE_DEBUGGING_PORT = int(os.getenv("REMOTE_DEBUGGING_PORT", 9222))
REMOTE_DEBUGGING_ADDRESS = os.getenv("REMOTE_DEBUGGING_ADDRESS", "127.0.0.1")
MAX_CONCURRENT_PAGES = int(os.getenv("MAX_CONCURRENT_PAGES", 8))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", 8))
PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", 30000))  # 30秒超时（注意 Playwright 内部最大限制）
# REQUEST_TIMEOUT = 120  # 整体接口请求超时时间（aiohttp层）
TOKEN = os.getenv("TOKEN", "")
APP_PATH = os.getenv("APP_PATH", "/")
PORT = int(os.getenv("PORT", 8000))
HOST = os.getenv("HOST", "127.0.0.1")

# 初始化日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

browser_context = None
playwright_instance = None
semaphore = asyncio.Semaphore(MAX_CONCURRENT_PAGES)

# 关闭浏览器
async def close_browser(app):
    if browser_context:
        await browser_context.close()
    if playwright_instance:
        await playwright_instance.stop()

async def close_page_later(page, delay=2):
    try:
        await asyncio.sleep(delay)
        await page.close()
    except Exception as e:
        logging.error(f"Error closing page: {e}")
        
async def wait_for_cloudflare(page, timeout=15):
    try:
        # 检查常见的Cloudflare盾页面特征
        await page.wait_for_selector('div#challenge-running, form#challenge-form', timeout=timeout * 1000)
        logging.info("Detected Cloudflare challenge, waiting for bypass...")
        await page.wait_for_load_state('networkidle', timeout=timeout * 1000)
    except PlaywrightTimeoutError:
        pass  # 没找到挑战页面或者已经正常加载了

async def fetch_page_content(url, retries=MAX_RETRIES):
    async with semaphore:
        
        page = await browser_context.new_page()
        
        for attempt in range(1, retries + 2):  # 尝试1 + MAX_RETRIES次
            try:
                start = asyncio.get_event_loop().time()

                await page.goto(url, timeout=PAGE_TIMEOUT, wait_until='domcontentloaded')
                # await wait_for_cloudflare(page)

                # 等到页面完全空闲
                # await page.wait_for_load_state('networkidle', timeout=PAGE_TIMEOUT)

                content = await page.content()
                elapsed = asyncio.get_event_loop().time() - start

                logging.info(f"Success [{url}] in {elapsed:.2f}s")
                
                # 后台延迟关闭
                asyncio.create_task(close_page_later(page, delay= 1 + 6 * random.random()))
                return content

            except PlaywrightTimeoutError:
                logging.warning(f"Timeout on attempt {attempt} for {url}")
                if attempt >= retries + 1:
                    await page.close()
                    raise web.HTTPGatewayTimeout(text="Page load timeout.")
            except Exception as e:
                logging.error(f"Error on attempt {attempt} for {url}: {e}")
                if attempt >= retries + 1:
                    await page.close()
                    raise web.HTTPInternalServerError(text=f"Error loading page: {e}")

async def handle_request(request):
    token = request.query.get('token')
    if token != TOKEN:
        await asyncio.sleep(random.randrange(1,5))
        raise web.HTTPUnauthorized(text="Invalid or missing token.")

    url = request.query.get('url')
    if not url:
        raise web.HTTPBadRequest(text="Missing 'url' parameter.")

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise web.HTTPBadRequest(text="Invalid URL.")

    content = await fetch_page_content(url)
    return web.Response(text=content, content_type='text/html')

def _random_user_agent():
    agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    ]
    return random.choice(agents)

# 初始化浏览器
async def init_browser():
    global browser_context, playwright_instance
    playwright_instance = await async_playwright().start()
    browser_context = await playwright_instance.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        headless=BROWSER_HEADLESS,
        executable_path=EXECUTABLE_PATH,
        user_agent=_random_user_agent(),
        args=[
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-gpu',
            '--disable-dev-shm-usage',
            '--disable-blink-features=AutomationControlled',
            '--window-size=820,750',
            '--lang=zh-CN,zh',  # 加一个中文偏好，减少触发反爬
            f'--remote-debugging-port={REMOTE_DEBUGGING_PORT}',
            f'--remote-debugging-address={REMOTE_DEBUGGING_ADDRESS}',
        ]
    )
    
    # 统一修改 User-Agent，看起来像正常浏览器
    await browser_context.set_extra_http_headers({
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "gzip, deflate, br" # aiohttp客户端只支持这三个
    })

    page = await browser_context.new_page()
    await page.set_content("""
        <html>
            <head>
                <title>🚫 DON'T CLOSE THE LAST TAB</title>
            </head>
            <body style="color: darkred; padding: 30px;">
                <h1><br/>请勿手动关闭最后一个标签页，否则浏览器将退出，服务会中断</h1>
                <h2>Do not close the last tab manually, otherwise the browser will exit and the service will be interrupted</h2>
            </body>
        </html>
    """)
@middleware
async def compression_middleware(request, handler):
    response = await handler(request)

    # 如果已经有Content-Encoding，就不压了
    if response.headers.get('Content-Encoding'):
        return response

    # 只压缩文本类型
    if response.content_type not in ("text/html", "application/xml", "application/json"):
        return response

    # 检查客户端支持什么压缩
    accept_encoding = request.headers.get('Accept-Encoding', '').lower()
    if 'br' in accept_encoding:
        encoding = 'br'
    elif 'gzip' in accept_encoding:
        encoding = 'gzip'
    else:
        return response  # 客户端不支持压缩

    # 压缩body
    body = response.body
    if body:
        if encoding == 'br':
            compressed_body = brotli.compress(body)
            response.headers['Content-Encoding'] = 'br'
        else:
            compressed_body = gzip.compress(body)
            response.headers['Content-Encoding'] = 'gzip'

        response.body = compressed_body
        response.headers['Content-Length'] = str(len(compressed_body))
        response.headers['Vary'] = 'Accept-Encoding'

    return response

# def ensure_chromium_installed():
# 	try:
# 		result = subprocess.run(
# 			[sys.executable, "-m", "playwright", "install", "chromium-headless-shell"],
# 			check=True,
# 			capture_output=True,
# 			text=True
# 		)
# 	except subprocess.CalledProcessError as e:
# 		with open("playwright_install_error.log", "w", encoding="utf-8") as f:
# 			f.write("Playwright 安装失败！\n")
# 			f.write(f"退出码: {e.returncode}\n")
# 			f.write("标准输出:\n" + (e.stdout or '') + "\n")
# 			f.write("标准错误:\n" + (e.stderr or '') + "\n")
# 		raise

async def create_app():
    # ensure_chromium_installed()
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium-headless-shell"], check=True)
    subprocess.run([sys.executable, "-m", "playwright", "install-deps"], check=True)
    # playwright install-deps
    await init_browser()
    app = web.Application(middlewares=[compression_middleware])
    app.router.add_get(APP_PATH, handle_request)
    app.on_shutdown.append(close_browser)
    return app

if __name__ == "__main__":
    web.run_app(create_app(), host=HOST, port=PORT)
