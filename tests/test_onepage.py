from playwright.sync_api import Page, expect

import os
import re
from urllib.parse import urlsplit

import pytest


# conftest.py 已載入共用 .env；多個網址可用逗號或換行分隔。
ONEPAGE_URLS = [
    url.strip() for url in re.split(r"[,\n]+", os.getenv("onepageURL", ""))
    if url.strip()
]
if not ONEPAGE_URLS:
    raise pytest.UsageError("請在 tests/.env 設定 onepageURL")
for url in ONEPAGE_URLS:
    if urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).netloc:
        raise pytest.UsageError(f"onepageURL 必須是完整的 http/https 網址：{url!r}")


def verify_cart_badges(page: Page, expected_count: int) -> None:
    # 徽章顯示商品種類數，同一商品增加 QTY 不會增加徽章數字。
    header = page.locator("button.header-cart")
    expect(header).to_be_visible()
    expect(header).to_have_accessible_name(
        re.compile(rf"購物車.*，\s*{expected_count}\s*件商品")
    )
    header_badge = header.locator(".cart_items_amount")
    if expected_count == 0:
        expect(header_badge).to_be_hidden()
    else:
        expect(header_badge).to_be_visible()
        expect(header_badge).to_have_text(str(expected_count))

    right_badge = page.locator(".fab-button-cart .fab-badge")
    expect(right_badge).to_be_visible()
    expect(right_badge).to_have_text(str(expected_count))
    print(f"PASS：頁首與右側購物車均為 {expected_count} 種商品")


@pytest.mark.parametrize("onepage_url", ONEPAGE_URLS)
def test_order_search(logged_in_page: Page, onepage_url: str) -> None:
    page = logged_in_page
    # 這裡已完成登入，接著寫自己的操作

    page.goto(onepage_url)
    expect(page.locator('[data-bv="page-loading"]')).to_be_hidden(timeout=30000)
    verify_cart_badges(page, 0)
    page.get_by_role("button", name="立即選購").nth(1).click()
    modal = page.locator('.modal-vue[role="dialog"]')
    first_name_field = modal.locator('[data-bv="product-info"] > p').first
    expect(first_name_field).to_be_visible()
    first_product_name = first_name_field.inner_text().strip()
    page.get_by_role("button", name="加入購物車").click()

    # 加入後應出現購物車動畫提示，並在提示結束後繼續操作。
    cart_hint = page.locator(".swal-cart-popup")
    expect(cart_hint.locator('[data-bv="cart-hint-icon"]')).to_be_visible()
    expect(cart_hint.get_by_text("已加入購物車", exact=True)).to_be_visible()
    print("PASS：出現加入購物車動畫提示")
    expect(cart_hint).to_be_hidden(timeout=15000)
    expect(modal).to_be_hidden()

    cart_rows = page.locator("#section1 div.grid").filter(
        has=page.locator('[data-bv="checkout-item-unit-price"]')
    )
    expect(cart_rows).to_have_count(1)
    expect(cart_rows.locator("p.product-text-wrap")).to_have_text(first_product_name)
    verify_cart_badges(page, 1)
    quantity_field = cart_rows.locator('input[id^="quantity-"]')
    expect(quantity_field).to_be_visible()
    initial_quantity = int(quantity_field.input_value())
    cart_rows.locator("button.rounded-r").click()
    expect(quantity_field).to_have_value(str(initial_quantity + 1))
    print(f"PASS：點擊一次 +，QTY {initial_quantity} → {initial_quantity + 1}")
    verify_cart_badges(page, 1)

    cart_rows.get_by_role("button", name="刪除購物車商品").click()
    expect(page.get_by_text("確定要移除此商品嗎?", exact=True)).to_be_visible()
    print("PASS：刪除前顯示「確定要移除此商品嗎?」")
    page.get_by_role("button", name="移除商品").click()
    expect(cart_rows).to_have_count(0)
    expect(page.get_by_text("購物車尚未加入商品，趕緊行動吧！", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="移除商品", exact=True)).to_be_hidden()
    print("PASS：移除後購物車為空")
    verify_cart_badges(page, 0)

    page.get_by_role("button", name="立即選購").nth(2).click()
    second_name_field = modal.locator('[data-bv="product-info"] > p').first
    expect(second_name_field).to_be_visible()
    second_product_name = second_name_field.inner_text().strip()
    assert second_product_name != first_product_name, "第二次必須選擇不同商品"
    page.get_by_role("button", name="直接購買").click()
    expect(modal).to_be_hidden(timeout=15000)
    expect(cart_rows).to_have_count(1)
    expect(cart_rows.locator("p.product-text-wrap")).to_have_text(second_product_name)
    expect(cart_rows.get_by_text(first_product_name, exact=True)).to_have_count(0)
    print(f"PASS：購物車僅顯示最新加入的商品 {second_product_name}")
    verify_cart_badges(page, 1)
