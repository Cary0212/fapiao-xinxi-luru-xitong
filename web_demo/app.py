"""Local-only FastAPI demo for PDF invoice extraction and DOCX export."""

from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from threading import RLock, Thread
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .exporter import build_docx
from .ocr import extract_pages
from .parser import parse_page


ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
DATA = Path(__file__).resolve().parent / "data" / "jobs"
TEMPLATE = ROOT / "reference" / "invoice_template.docx"
DATA.mkdir(parents=True, exist_ok=True)
LOCK = RLock()
MAX_FILE_BYTES = 30 * 1024 * 1024
MAX_FILES = 30

app = FastAPI(title="发票信息录入 Demo", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _job_path(job_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise HTTPException(status_code=404, detail="批次不存在")
    return DATA / job_id


def _load_job(job_id: str) -> dict:
    path = _job_path(job_id) / "job.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="批次不存在")
    with LOCK:
        return json.loads(path.read_text(encoding="utf-8"))


def _save_job(job: dict) -> None:
    path = _job_path(job["id"]) / "job.json"
    temporary = path.with_suffix(".tmp")
    with LOCK:
        temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


def _process_job(job_id: str) -> None:
    job = _load_job(job_id)
    for index, document in enumerate(job["documents"], start=1):
        try:
            pdf_path = _job_path(job_id) / document["stored_name"]
            preview_dir = _job_path(job_id) / f"preview-{index}"
            pages = extract_pages(pdf_path, preview_dir)
            if not pages:
                raise ValueError("PDF 没有可读取页面")
            for page in pages:
                if len(page.lines) < 3:
                    job["errors"].append(f"{document['name']} 第 {page.page_number} 页未识别到票据文字")
                    continue
                preview_url = f"/api/jobs/{job_id}/preview/{index}/{page.page_number}"
                job["receipts"].append(parse_page(page, document["name"], preview_url))
        except Exception as exc:  # One bad PDF must not discard other uploaded files.
            job["errors"].append(f"{document['name']}：{exc}")
        job["processed"] = index
        _save_job(job)
    job["status"] = "ready" if job["receipts"] else "failed"
    _save_job(job)


def _clean_money(value: object) -> str:
    if value is None or str(value).strip() == "":
        return ""
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError
        return f"{amount:.2f}"
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=422, detail="金额必须是非负数字")


def _validate_for_export(receipts: list[dict]) -> list[str]:
    errors = []
    if not receipts:
        return ["没有可导出的票据"]
    for index, receipt in enumerate(receipts, start=1):
        title = f"第 {index} 张票据（{receipt.get('source_name', '')}）"
        if receipt.get("kind") not in ("shopping", "taxi"):
            errors.append(f"{title}：请选择票据类型")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", receipt.get("date", "")):
            errors.append(f"{title}：请填写正确日期")
        if not _clean_money(receipt.get("final_amount", "")):
            errors.append(f"{title}：请填写最终金额")
        if receipt.get("kind") == "taxi" and not receipt.get("number", "").strip():
            errors.append(f"{title}：请填写发票号码")
        if receipt.get("kind") == "shopping" and not any(
            item.get("name", "").strip() for item in receipt.get("items", [])
        ):
            errors.append(f"{title}：请补充至少一行商品")
    return errors


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": TEMPLATE.is_file(), "template": TEMPLATE.name}


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)) -> dict:
    if not files or len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"一次最多上传 {MAX_FILES} 份 PDF")
    job_id = uuid4().hex
    job_dir = _job_path(job_id)
    job_dir.mkdir(parents=True)
    documents = []
    for index, file in enumerate(files, start=1):
        original_name = Path(file.filename or f"document-{index}.pdf").name
        payload = await file.read(MAX_FILE_BYTES + 1)
        if len(payload) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"{original_name} 超过 30 MB")
        if not original_name.lower().endswith(".pdf") or not payload.startswith(b"%PDF"):
            raise HTTPException(status_code=400, detail=f"{original_name} 不是有效的 PDF 文件")
        stored_name = f"document-{index}.pdf"
        (job_dir / stored_name).write_bytes(payload)
        documents.append({"name": original_name, "stored_name": stored_name})
    job = {
        "id": job_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "processing",
        "processed": 0,
        "total": len(documents),
        "documents": documents,
        "receipts": [],
        "errors": [],
    }
    _save_job(job)
    Thread(target=_process_job, args=(job_id,), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = _load_job(job_id)
    return {key: value for key, value in job.items() if key != "documents"}


@app.get("/api/jobs/{job_id}/preview/{document_index}/{page_number}")
def preview(job_id: str, document_index: int, page_number: int) -> FileResponse:
    job = _load_job(job_id)
    if document_index < 1 or document_index > len(job["documents"]) or page_number < 1:
        raise HTTPException(status_code=404, detail="预览不存在")
    path = _job_path(job_id) / f"preview-{document_index}" / f"page-{page_number}.png"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="预览不存在")
    return FileResponse(path, media_type="image/png")


@app.put("/api/jobs/{job_id}/receipts/{receipt_id}")
def update_receipt(job_id: str, receipt_id: str, changes: dict) -> dict:
    job = _load_job(job_id)
    receipt = next((item for item in job["receipts"] if item["id"] == receipt_id), None)
    if receipt is None:
        raise HTTPException(status_code=404, detail="票据不存在")
    editable = {
        "kind", "merchant", "address", "date", "time", "number", "number_type", "invoice_code",
        "gross_amount", "merchant_discount", "payment_discount", "final_amount", "payment_method", "items", "reviewed",
    }
    for key, value in changes.items():
        if key not in editable:
            continue
        if key == "kind":
            if value not in ("shopping", "taxi"):
                raise HTTPException(status_code=422, detail="票据类型无效")
            receipt[key] = value
        elif key == "items":
            if not isinstance(value, list) or len(value) > 100:
                raise HTTPException(status_code=422, detail="商品明细格式无效")
            receipt[key] = [
                {
                    "name": str(item.get("name", ""))[:200],
                    "unit_price": _clean_money(item.get("unit_price", "")),
                    "quantity": str(item.get("quantity", "1"))[:30],
                    "unit": str(item.get("unit", "件"))[:20],
                }
                for item in value if isinstance(item, dict)
            ]
        elif key in ("gross_amount", "merchant_discount", "payment_discount", "final_amount"):
            receipt[key] = _clean_money(value)
        elif key == "reviewed":
            receipt[key] = bool(value)
        else:
            receipt[key] = str(value or "")[:500]
    _save_job(job)
    return receipt


@app.post("/api/jobs/{job_id}/export")
def export(job_id: str) -> StreamingResponse:
    job = _load_job(job_id)
    if job["status"] != "ready":
        raise HTTPException(status_code=409, detail="请等待识别完成")
    errors = _validate_for_export(job["receipts"])
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    data = build_docx(job["receipts"], TEMPLATE)
    filename = f"发票信息汇总_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(
        BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )
