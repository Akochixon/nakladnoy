from __future__ import annotations

import json
from dataclasses import dataclass, field

import google.generativeai as genai

from bot.config import settings

genai.configure(api_key=settings.gemini_api_key)

_MODEL_NAME = "gemini-2.0-flash"

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_invoice_document": {"type": "boolean"},
        "missing_or_unreadable_fields": {"type": "array", "items": {"type": "string"}},
        "invoice_number": {"type": "string"},
        "date": {"type": "string", "description": "DD.MM.YYYY formatida"},
        "supplier_name": {"type": "string"},
        "supplier_inn": {"type": "string"},
        "supplier_address": {"type": "string"},
        "supplier_phone": {"type": "string"},
        "customer_name": {"type": "string"},
        "customer_inn": {"type": "string"},
        "customer_address": {"type": "string"},
        "customer_client_code": {"type": "string"},
        "sales_agent_name": {"type": "string"},
        "expediter_name": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "name": {"type": "string"},
                    "unit": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit_price": {"type": "number"},
                    "line_total": {"type": "number"},
                },
                "required": ["code", "name", "quantity", "unit_price", "line_total"],
            },
        },
        "total_qty": {"type": "number"},
        "total_sum": {"type": "number"},
    },
    "required": [
        "is_invoice_document",
        "missing_or_unreadable_fields",
        "invoice_number",
        "date",
        "supplier_name",
        "customer_name",
        "items",
        "total_qty",
        "total_sum",
    ],
}

_PROMPT = """
Sen tovar-tashish nakladnoy (Товарная накладная) hujjatlarini o'qiydigan yordamchisan.
Rasmga qara va quyidagi maydonlarni to'liq va aniq chiqar:
- Hujjat raqami (No), sana (DD.MM.YYYY)
- Postavshik: nomi, INN, manzil, telefon
- Xaridor: nomi, INN, manzil, mijoz kodi
- Agent va Ekspeditor ismi (agar bo'lsa)
- Tovarlar jadvali: kod, nomi, o'lchov birligi, soni, narxi, summasi
- Jami soni va jami summa

Agar rasm umuman shunday hujjat bo'lmasa yoki muhim maydonlar o'qib bo'lmaydigan
darajada xira/kesilgan bo'lsa, is_invoice_document=false qil va
missing_or_unreadable_fields ro'yxatida qaysi maydonlar yo'qligini yoz.
Raqamlarni faqat son sifatida qaytar. Faqat berilgan JSON sxemasi bo'yicha javob ber.
"""


@dataclass
class OcrResult:
    raw: dict
    is_valid: bool
    missing_fields: list[str] = field(default_factory=list)


def extract_invoice(image_bytes: bytes, mime_type: str = "image/jpeg") -> OcrResult:
    model = genai.GenerativeModel(_MODEL_NAME)
    response = model.generate_content(
        [_PROMPT, {"mime_type": mime_type, "data": image_bytes}],
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": _RESPONSE_SCHEMA,
        },
    )
    data = json.loads(response.text)
    return OcrResult(
        raw=data,
        is_valid=bool(data.get("is_invoice_document")),
        missing_fields=data.get("missing_or_unreadable_fields") or [],
    )
