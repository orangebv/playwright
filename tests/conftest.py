import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from dotenv import load_dotenv
from playwright.sync_api import Page, expect

# 明確讀取 tests/.env，不受啟動目錄影響，外部環境變數優先。
load_dotenv(Path(__file__).parent / ".env")


@pytest.fixture
def logged_in_page(page: Page) -> Page:
    """每個使用此 fixture 的測試，都取得獨立且已登入的頁面。"""
    email = os.getenv("BVSHOP_EMAIL")
    password = os.getenv("BVSHOP_PASSWORD")

    # 確認環境變數都有設定，避免填入空值
    if not email or not password:
        message = "FAIL：無法登入，請在 .env 設定 BVSHOP_EMAIL 與 BVSHOP_PASSWORD"
        print(message)
        raise AssertionError(message)

    page.goto("https://bvshop-manage.bv-shop.tw/login")

    page.get_by_role(
        "textbox", name="請輸入您的註冊信箱"
    ).fill(email)

    page.get_by_role(
        "textbox", name="請輸入您的密碼"
    ).fill(password)

    page.get_by_role("button", name="登入").click()

    # 以登入後才會出現的「前往商店」連結判斷登入成功。
    print("\n========== 登入結果 ==========")
    try:
        expect(page.get_by_role("link", name="前往商店", exact=True)).to_be_visible(
            timeout=15000
        )
    except AssertionError as error:
        if urlsplit(page.url).path.rstrip("/") == "/login":
            message = "FAIL：登入未成功，15 秒後仍停留在登入頁，請確認帳號密碼或頁面錯誤提示"
        else:
            message = "FAIL：無法確認登入成功，15 秒內未出現「前往商店」連結，請確認頁面或網路狀態"
        print(message)
        raise AssertionError(message) from error
    print("PASS：登入成功，已顯示「前往商店」連結")

    return page
