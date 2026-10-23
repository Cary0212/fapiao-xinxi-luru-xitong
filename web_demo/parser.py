"""Conservative receipt field extraction; the browser is the correction surface."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from .ocr import PageResult


MONEY = r"(\d+(?:\.\d{1,2})?)"
DATE = re.compile(r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})")
TIME = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?")
NUMBER = re.compile(r"(?:票号|流水号|发票号码)\s*[:：]?\s*(\d{8,20})")
ITEM_PRICE = re.compile(r"(?P<price>\d+\.\d{2})\s*[xX×]\s*(?P<qty>\d+(?:\.\d+)?)")


def _decimal(value: str | None) -> str:
    try:
        return format(Decimal(value or "0").quantize(Decimal("0.01")), ".2f")
    except InvalidOperation:
        return ""


def _value(lines: list[str], labels: tuple[str, ...], *, exclude: tuple[str, ...] = ()) -> str:
    for i, line in enumerate(lines):
        if any(x in line for x in exclude):
            continue
        for label in labels:
            match = re.search(re.escape(label) + r"\s*[:：]?\s*" + MONEY, line)
            if match:
                return _decimal(match.group(1))
            if re.fullmatch(rf"\s*{re.escape(label)}\s*[:：]?\s*", line) and i + 1 < len(lines):
                next_match = re.fullmatch(r"\s*¥?\s*" + MONEY + r"\s*元?\s*", lines[i + 1])
                if next_match:
                    return _decimal(next_match.group(1))
    return ""


def _number_after(lines: list[str], label: str) -> str:
    for i, line in enumerate(lines):
        match = re.search(re.escape(label) + r"\s*[:：]?\s*(\d{8,20})", line)
        if match:
            return match.group(1)
        if label in line and i + 1 < len(lines):
            match = re.fullmatch(r"\s*(\d{8,20})\s*", lines[i + 1])
            if match:
                return match.group(1)
    return ""


def _address(lines: list[str]) -> str:
    for i, line in enumerate(lines):
        if "地址" not in line:
            continue
        match = re.search(r"地址\s*[:：]\s*(.+)", line)
        if not match:
            continue
        address = match.group(1).strip()
        if i + 1 < len(lines) and re.match(r"^\d+[号-]", lines[i + 1]):
            address += lines[i + 1].strip()
        return address
    return ""


def _items_lawson(lines: list[str]) -> list[dict]:
    items: list[dict] = []
    previous_name = ""
    for line_index, line in enumerate(lines):
        if any(x in line for x in ("商品件数", "促销明细", "应收：", "应收:")):
            break
        price_match = ITEM_PRICE.search(line)
        if price_match:
            name = line[: price_match.start()].strip(" ：:") or previous_name
            raw_price = price_match.group("price")
            quantity = Decimal(price_match.group("qty"))
            unit_price = Decimal(raw_price)
            # OCR may join a package size and a price, e.g. "蓝莓4016.50x1".
            if line_index + 1 < len(lines) and quantity:
                subtotal_text = lines[line_index + 1].strip()
                if re.fullmatch(r"\d+\.\d{2}", subtotal_text):
                    subtotal = Decimal(subtotal_text)
                    inferred = (subtotal / quantity).quantize(Decimal("0.01"))
                    inferred_text = f"{inferred:.2f}"
                    if unit_price != inferred and raw_price.endswith(inferred_text):
                        name += raw_price[: -len(inferred_text)]
                        unit_price = inferred
            if name.count("（") > name.count("）"):
                name += "）"
            name = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]", "", name)
            if name and not any(x in name for x in ("地址", "票号", "店长")):
                items.append(
                    {
                        "name": name,
                        "unit_price": _decimal(str(unit_price)),
                        "quantity": price_match.group("qty"),
                        "unit": "件",
                    }
                )
            previous_name = ""
        elif re.search(r"[\u4e00-\u9fff]", line) and not any(
            x in line for x in ("地址", "票号", "店长", "太平洋", "商品件数", "合计", "日期", "促销", "会员")
        ):
            previous_name = line.strip()
    return items


def _items_peanut(lines: list[str], amount: str) -> list[dict]:
    header = next((i for i, line in enumerate(lines) if "品名" in line), -1)
    end = next((i for i, line in enumerate(lines) if "件数" in line), len(lines))
    section = lines[header + 1 : end] if header >= 0 else []
    name = next((line for line in section if re.search(r"[\u4e00-\u9fff]", line)), "")
    numbers = [line for line in section if re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", line)]
    if not name or not numbers:
        return []
    unit_price = _decimal(numbers[0])
    if not unit_price:
        return []
    quantity = "1"
    try:
        if amount:
            quantity = format((Decimal(amount) / Decimal(unit_price)).quantize(Decimal("0.001")), "f")
    except (InvalidOperation, ZeroDivisionError):
        pass
    return [{"name": name, "unit_price": unit_price, "quantity": quantity, "unit": "千克"}]


def parse_page(page: PageResult, source_name: str, preview_url: str) -> dict:
    lines = page.lines
    text = "\n".join(lines)
    is_taxi = any(x in text for x in ("车费发票", "TAXI", "上车", "下车"))
    kind = "taxi" if is_taxi else "shopping"
    date_match = DATE.search(text)
    date = ""
    if date_match:
        year, month, day = date_match.groups()
        date = f"{year}-{int(month):02d}-{int(day):02d}"
    time_match = TIME.search(text)
    time = time_match.group(0) if time_match else ""
    if is_taxi:
        number = _number_after(lines, "发票号码")
        code = _number_after(lines, "发票代码")
        amount = _value(lines, ("金额",))
        merchant = ""
        items: list[dict] = []
        gross = amount
        discount = "0.00"
        channel_discount = "0.00"
        address = ""
        payment = ""
        number_type = "发票号码"
    else:
        number_match = NUMBER.search(text)
        number = number_match.group(1) if number_match else ""
        number_type = "流水号" if "流水号" in text else "小票票号"
        code = ""
        amount = _value(lines, ("应收", "实收"))
        gross = _value(lines, ("合计",), exclude=("找零",)) or amount
        discount = _value(lines, ("优惠",), exclude=("支付优惠",)) or "0.00"
        channel_discount = _value(lines, ("支付宝支付优惠",)) or "0.00"
        address = _address(lines)
        if "欢囍花生" in text:
            merchant = "欢囍花生·上海太平洋新天地欢囍店"
            items = _items_peanut(lines, amount)
        elif "太平洋新天地店" in text:
            merchant = "罗森·太平洋新天地店"
            items = _items_lawson(lines)
        else:
            merchant = ""
            items = []
        payment = "支付宝" if "支付宝" in text else "微信支付" if "微信支付" in text else ""
    warnings = []
    for label, value in (("日期", date), ("金额", amount), ("号码", number)):
        if not value:
            warnings.append(f"未识别到{label}，请核对原票")
    if kind == "shopping" and not address:
        warnings.append("原票未识别到详细地址，请核对")
    if kind == "shopping" and not items:
        warnings.append("未识别到商品明细，请核对")
    if page.scores and sum(page.scores) / len(page.scores) < 0.75:
        warnings.append("OCR 识别质量偏低，建议逐项核对")
    return {
        "id": uuid4().hex,
        "source_name": source_name,
        "page_number": page.page_number,
        "preview_url": preview_url,
        "kind": kind,
        "merchant": merchant,
        "address": address,
        "date": date,
        "time": time,
        "number": number,
        "number_type": number_type,
        "invoice_code": code,
        "gross_amount": gross,
        "merchant_discount": discount,
        "payment_discount": channel_discount,
        "final_amount": amount,
        "payment_method": payment,
        "items": items,
        "raw_text": text,
        "warnings": warnings,
        "reviewed": False,
        "used_ocr": page.used_ocr,
    }
