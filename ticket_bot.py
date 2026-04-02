import asyncio
from playwright.async_api import async_playwright

URL = "https://ticket-training.onrender.com/"
TARGET_TEXT = "立即購票"

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        await page.goto(URL)
        await page.wait_for_load_state("domcontentloaded")
        print("頁面載入完成")

        # 1️⃣ 點「開始」
        try:
            await page.click("text=開始")
            print("已點開始")
        except:
            print("找不到開始按鈕")

        # 2️⃣ 等「立即購票」按鈕 enable
        await page.wait_for_function(f"""
            () => {{
                const btn = [...document.querySelectorAll('button')]
                    .find(el => el.innerText.includes('{TARGET_TEXT}'));
                return btn && !btn.disabled;
            }}
        """)
        print("立即購票已啟用")

        # 3️⃣ 點擊購票
        await page.click(f"text={TARGET_TEXT}")
        print("已點擊購票")

        # 4️⃣ 自動選區（選第一個有「區」的按鈕）
        areas = page.locator("button")
        for i in range(await areas.count()):
            text = await areas.nth(i).inner_text()
            if "區" in text:
                await areas.nth(i).click()
                print(f"已選區: {text}")
                break

        # 5️⃣ 選票數（選 2 張示例）
        try:
            await page.select_option("select", "2")
            print("已選 2 張票")
        except:
            print("找不到票數下拉選單")

        # 6️⃣ 點下一步
        try:
            await page.click("text=下一步")
            print("已點下一步")
        except:
            print("找不到下一步按鈕")

        # 停留在頁面，不關閉
        while True:
            await asyncio.sleep(1)

asyncio.run(run())