
import json
import re
import pytest
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Page, expect

def parse_price(text: str) -> Decimal:
    match = re.search(r"NT\$\s*([\d,]+(?:\.\d+)?)", text)
    assert match, f"無法讀取金額：{text!r}"
    return Decimal(match.group(1).replace(",", ""))


def verify_cart(
    page: Page, product_path: str, unit_price: Decimal, quantity: int,
    variant: str | None = None,
) -> None:
    # 只讀取同一個商品列，避免匹配其他商品、運費或結帳總金額。
    row = page.locator("#section1 div.grid").filter(
        has=page.locator(f'a[href="{product_path}"]')
    ).filter(has=page.locator('[data-bv="checkout-item-unit-price"]'))
    if variant is not None:
        row = row.filter(has_text=variant)
    expect(row).to_have_count(1)
    price_field = row.locator('[data-bv="checkout-item-unit-price"]')
    quantity_field = row.locator('input[id^="quantity-"]')
    subtotal_field = row.locator('[data-bv="checkout-item-total-price"] > span').last
    expect(price_field).to_be_visible()
    expect(quantity_field).to_have_value(str(quantity))
    expect(subtotal_field).to_be_visible()

    cart_price = parse_price(price_field.inner_text())
    cart_quantity = int(quantity_field.input_value())
    cart_subtotal = parse_price(subtotal_field.inner_text())

    assert cart_price == unit_price, (
        f"單價不一致：商品頁 {unit_price}，購物車 {cart_price}"
    )
    assert cart_quantity == quantity, (
        f"數量不一致：商品頁 {quantity}，購物車 {cart_quantity}"
    )
    assert cart_subtotal == cart_price * cart_quantity, (
        f"購物車小計錯誤：{cart_subtotal}，"
        f"預期 {cart_price} × {cart_quantity} = {cart_price * cart_quantity}"
    )
    product_name = row.locator("p.product-text-wrap").inner_text().strip()
    print("\n========== 購物車驗證結果 ==========")
    print(
        f"PASS：商品 {product_name}、單價 {cart_price}、"
        f"數量 {cart_quantity}、小計 {cart_subtotal}"
    )


def verify_checkout_summary(
    page: Page, coupon_discount: Decimal = Decimal("0"),
    full_discount_applies: bool = True,
) -> None:
    summary = page.locator('[data-bv="checkout-summary"]')
    expect(summary).to_be_visible()
    # 等待結帳明細的遮罩消失，確保促銷與運費已完成計算。
    expect(summary.locator(":scope > div.absolute.inset-0")).to_be_hidden(
        timeout=30000
    )

    def amount_field(label: str):
        return summary.locator(":scope > div").filter(
            has=page.get_by_text(label, exact=True)
        ).locator("p").last

    # 累加所有商品列的小計，不包含運費與折扣。
    subtotals = page.locator(
        '#section1 [data-bv="checkout-item-total-price"] > span:last-child'
    )
    assert subtotals.count() > 0, "購物車沒有可驗證的商品小計"
    expected_total = sum(
        (parse_price(text) for text in subtotals.all_inner_texts()), Decimal("0")
    )
    total_field = amount_field("商品合計")
    expect(total_field).to_be_visible()
    actual_total = parse_price(total_field.inner_text())
    assert actual_total == expected_total, (
        f"商品合計錯誤：顯示 {actual_total}，所有商品小計加總 {expected_total}"
    )
    print("\n========== 購物車合計價格驗證結果 ==========")
    print(f"PASS：商品合計 {actual_total}，等於所有商品小計加總")

    # 可累加：未滿 800 折 0、滿 800 折 10、滿 1600 折 20，以此類推。
    discount_times = int(expected_total // Decimal("800"))
    expected_discount = Decimal("10") * discount_times
    discount_field = amount_field("滿800扣10")
    if not full_discount_applies:
        # 此優惠碼取代滿額優惠，確認沒有重複折抵。
        expect(discount_field).to_have_count(0)
        expected_discount = Decimal("0")
        discount_times = 0
    if expected_discount > 0:
        expect(discount_field).to_be_visible()
        expect(discount_field).to_have_text(re.compile(r"^\s*[-−]\s*NT\$\s*[\d,.]+\s*$"))
        actual_discount = parse_price(discount_field.inner_text())
    elif discount_field.count():
        actual_discount = parse_price(discount_field.inner_text())
    else:
        actual_discount = Decimal("0")
    assert actual_discount == expected_discount, (
        f"滿800扣10折扣錯誤：顯示折抵 {actual_discount}，"
        f"預期 {discount_times} 次 × 10 = {expected_discount}"
    )
    if full_discount_applies:
        print(f"PASS：滿800扣10，符合 {discount_times} 次，折抵 {actual_discount}")
    else:
        print("PASS：優惠碼已取代滿800扣10，未重複折抵")

    shipping_field = amount_field("運費")
    expect(shipping_field).to_be_visible()
    shipping = parse_price(shipping_field.inner_text())
    expected_checkout = expected_total - expected_discount - coupon_discount + shipping
    checkout_field = amount_field("結帳總金額")
    expect(checkout_field).to_be_visible()
    actual_checkout = parse_price(checkout_field.inner_text())
    assert actual_checkout == expected_checkout, (
        f"結帳總金額錯誤：顯示 {actual_checkout}，"
        f"預期 商品合計 {expected_total} - 折扣 {expected_discount}"
        f" - 優惠碼折扣 {coupon_discount} + 運費 {shipping} = {expected_checkout}"
    )
    print(
        f"PASS：結帳總金額 {actual_checkout}"
        f" = 商品合計 {expected_total} - 折扣 {expected_discount}"
        f" - 優惠碼折扣 {coupon_discount} + 運費 {shipping}"
    )


def verify_coupon_codes(
    page: Page, invalid_code: str, valid_code: str,
    discount_name: str, discount_rate: Decimal,
) -> None:
    coupon = page.locator('[data-bv="checkout-coupon"]')
    summary = page.locator('[data-bv="checkout-summary"]')
    expect(summary.locator(":scope > div.absolute.inset-0")).to_be_hidden(timeout=30000)
    total_field = summary.locator(":scope > div").filter(
        has=page.get_by_text("商品合計", exact=True)
    ).locator("p").last
    expect(total_field).to_be_visible()
    product_total = parse_price(total_field.inner_text())
    # 以折扣前商品合計為基準，不含運費，四捨五入至整數元。
    expected_coupon_discount = (product_total * discount_rate).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    # 錯誤提示會加入 label 文字，使用固定 id 避免第二次輸入時定位失效。
    code_field = coupon.locator("#coupon-code-input")
    apply_button = code_field.locator("..").get_by_role(
        "button", name="套用", exact=True
    )

    code_field.fill(invalid_code)
    expect(apply_button).to_be_enabled()
    apply_button.click()
    invalid_message = page.get_by_text("無效的優惠券/碼", exact=True)
    expect(invalid_message).to_be_visible(timeout=15000)
    print(f"PASS：無效優惠碼 {invalid_code}，顯示「無效的優惠券/碼」")

    code_field.fill(valid_code)
    expect(apply_button).to_be_enabled()
    apply_button.click()
    expect(coupon.get_by_text("已套用折扣", exact=True)).to_be_visible(timeout=15000)
    discount_row = summary.locator(":scope > div").filter(
        has=page.get_by_text(f"{discount_name} ({valid_code})", exact=True)
    )
    expect(discount_row).to_have_count(1)
    discount_field = discount_row.locator("p").last
    expect(discount_field).to_have_text(
        re.compile(r"^\s*[-−]\s*NT\$\s*" + format(expected_coupon_discount, ",.0f") + r"\s*$"),
        timeout=15000,
    )
    coupon_discount = parse_price(discount_field.inner_text())
    assert coupon_discount == expected_coupon_discount, (
        f"優惠碼折扣錯誤：顯示 {coupon_discount}，"
        f"預期商品合計 {product_total} × {discount_rate:.0%} 四捨五入 = {expected_coupon_discount}"
    )
    print(
        f"PASS：已套用折扣 {discount_name} ({valid_code})，"
        f"商品合計 {product_total} × {discount_rate:.0%}，折抵 NT$ {coupon_discount}"
    )
    verify_checkout_summary(
        page, coupon_discount=coupon_discount, full_discount_applies=False
    )


# 測試資料獨立存放；使用本檔路徑定位，不受執行指令的目錄影響。
COUPON_CASES = json.loads(
    (Path(__file__).parent / "data" / "coupon_cases.json").read_text(encoding="utf-8")
)


# JSON 中每組資料會獨立執行一次完整測試。
@pytest.mark.parametrize(
    "invalid_code, valid_code, discount_name, discount_rate",
    [
        pytest.param(
            case["invalid_code"], case["valid_code"], case["discount_name"],
            Decimal(case["discount_rate"]), id=case["id"],
        )
        for case in COUPON_CASES
    ],
)
def test_example(
    logged_in_page: Page, invalid_code: str, valid_code: str,
    discount_name: str, discount_rate: Decimal,
) -> None:
    page = logged_in_page

    menu_names = [
        "開店步驟",
        "商店概況",
        "商店設定",
        "樣式設定",
        "店員管理",
        "商品管理",
        "促銷管理",
        "訂單管理",
        "行銷推廣",
        "顧客管理",
        "狙擊追單",
        "數據分析",
        "文章管理",
        "網站工具",
    ]

    failed_items = []
    passed_items = []

    print("\n========== 開始驗證側邊欄 ==========")

    for name in menu_names:
        try:
            expect(
                page.get_by_text(name, exact=True).first
            ).to_be_visible(timeout=5000)

            passed_items.append(name)
            print(f"PASS：{name}")

        except AssertionError:
            failed_items.append(name)
            print(f"FAIL：{name}")

    print("\n========== 驗證結果統計 ==========")
    print(f"總項目：{len(menu_names)}")
    print(f"成功：{len(passed_items)}")
    print(f"失敗：{len(failed_items)}")

    if failed_items:
        print("\n未通過的項目：")
        for name in failed_items:
            print(f"- {name}")

    assert not failed_items, (
        f"側邊欄有 {len(failed_items)} 個項目未通過："
        f"{', '.join(failed_items)}"
    )


    # 點擊前往商店
    with page.expect_popup() as page1_info:
        page.get_by_role("link", name="前往商店").click()

    page1 = page1_info.value


    # 確認商店頁面已載入
    expect(page1).to_have_url(re.compile(r"https://develop\.bv-shop\.tw/.*"))
    expect(page1.locator("body")).to_be_visible()

    page1.locator("div:nth-child(3) > div > .productBoxStyle > .relative.col-span-12 > .group.relative > .group-hover\\:opacity-100 > div > .auto-size-product > .absolute").first.click()
    page1.goto("https://develop.bv-shop.tw/")
    page1.get_by_role("link").filter(has_text=re.compile(r"^$")).nth(4).click()


    # 從 1 開始，每點擊一次加號，預期數量加 1。
    expected_quantity = 1
    plus_clicks = 3  # 調整這裡即可改變加號點擊次數。
    product_quantity_field = page1.locator('[data-bv="product-quantity-input"]')
    expect(product_quantity_field).to_have_value(str(expected_quantity))
    plus_button = page1.get_by_role("button", name="＋").nth(0)
    expect(plus_button).to_be_visible()
    for _ in range(plus_clicks):
        plus_button.click()
        expected_quantity += 1
        expect(product_quantity_field).to_have_value(str(expected_quantity))

    # 記錄實際商品頁的售價與選購數量，不使用寫死的預期金額。
    product_path = urlsplit(page1.url).path
    product_price = page1.locator(
        '[data-bv="product-price"] .productInfoSpecialPrice:visible'
    )
    expect(product_price).to_be_visible()
    product_unit_price = parse_price(product_price.inner_text())
    expect(product_quantity_field).to_have_value(str(expected_quantity))
    product_quantity = int(product_quantity_field.input_value())


    # 加入購物車
    add_button = page1.get_by_role("button", name="加入購物車")
    expect(add_button).to_be_enabled()
    add_button.click()


    # 以「購物車」開頭，避免同時匹配「加入購物車」按鈕
    page1.get_by_role("button", name=re.compile(r"^購物車")).click()
    page1.get_by_role("button", name="開始結帳").click()


    # 驗證商品頁與購物車的單價、數量一致，小計等於單價乘以數量。
    verify_cart(page1, product_path, product_unit_price, product_quantity)

    # 再次回到商店，點擊商品列表中的第一個商品。
    page1.goto("https://develop.bv-shop.tw/")
    expect(page1.locator('[data-bv="page-loading"]')).to_be_hidden(timeout=30000)
    first_product = page1.locator('.productBoxStyle a[href^="/item/"]').first
    expect(first_product).to_be_visible()
    first_product.click()
    expect(page1.locator('[data-bv="page-loading"]')).to_be_hidden(timeout=30000)

    # 品種選擇藝妓，確認選取成功後才讀取該規格的價格。
    variety_field = page1.get_by_label("品種", exact=True)
    variety_field.select_option(label="藝妓")
    expect(variety_field).to_have_value("藝妓")

    expected_quantity = 1
    plus_clicks = 1
    product_quantity_field = page1.locator('[data-bv="product-quantity-input"]')
    expect(product_quantity_field).to_have_value(str(expected_quantity))
    plus_button = page1.locator('[data-bv="product-quantity"]').get_by_role(
        "button", name="＋", exact=True
    )
    for _ in range(plus_clicks):
        plus_button.click()
        expected_quantity += 1
        expect(product_quantity_field).to_have_value(str(expected_quantity))

    product_path = urlsplit(page1.url).path
    product_price = page1.locator(
        '[data-bv="product-price"] .productInfoSpecialPrice:visible'
    )
    expect(product_price).to_be_visible()
    product_unit_price = parse_price(product_price.inner_text())
    product_quantity = int(product_quantity_field.input_value())

    add_button = page1.get_by_role("button", name="加入購物車", exact=True)
    expect(add_button).to_be_enabled()
    add_button.click()
    page1.get_by_role("button", name=re.compile(r"^購物車")).click()
    page1.get_by_role("button", name="開始結帳").click()

    # 以商品路徑及藝妓規格定位，驗證第二次加入的商品。
    verify_cart(
        page1, product_path, product_unit_price, product_quantity, variant="藝妓"
    )

    # 驗證所有商品小計加總、累加滿額折扣，以及含運費的結帳總金額。
    verify_checkout_summary(page1)

    # 先驗證無效優惠碼，再套用有效優惠碼並重新核對結帳總金額。
    verify_coupon_codes(page1, invalid_code, valid_code, discount_name, discount_rate)


    # 暫停，方便觀察登入後的畫面
    page.pause()
