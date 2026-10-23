"""PDF page rendering and local Chinese OCR for the demo."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import numpy as np
import pymupdf
from PIL import Image
from rapidocr import RapidOCR


_engine: RapidOCR | None = None
_engine_lock = Lock()


@dataclass
class PageResult:
    lines: list[str]
    scores: list[float]
    preview_path: Path
    page_number: int
    used_ocr: bool


def _get_engine() -> RapidOCR:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = RapidOCR()
        return _engine


def _crop_content(image: Image.Image) -> Image.Image:
    """Trim the large white margins common in scanned A3 ticket PDFs."""
    gray = np.asarray(image.convert("L"))
    dark = gray < 185
    rows = np.where(dark.sum(axis=1) > 8)[0]
    cols = np.where(dark.sum(axis=0) > 8)[0]
    if len(rows) == 0 or len(cols) == 0:
        return image
    pad = 32
    box = (
        max(0, int(cols.min()) - pad),
        max(0, int(rows.min()) - pad),
        min(image.width, int(cols.max()) + pad),
        min(image.height, int(rows.max()) + pad),
    )
    return image.crop(box)


def _orientation_score(lines: list[str], scores: list[float]) -> float:
    if not lines:
        return -1000
    first = max(1, len(lines) // 3)
    start = " ".join(lines[:first])
    end = " ".join(lines[-first:])
    header_terms = ("地址", "票号", "流水号", "发票代码", "销售时间", "2026/")
    total_terms = ("应收", "实收", "合计", "金额")
    header_pos = next((i for i, t in enumerate(lines) if any(x in t for x in header_terms)), None)
    total_pos = next((i for i, t in enumerate(lines) if any(x in t for x in total_terms)), None)
    result = sum(scores) / max(len(scores), 1)
    if header_pos is not None and total_pos is not None:
        result += 7 if header_pos < total_pos else -7
    if any(x in start for x in ("店", "TAXI", "欢囍", "发票")):
        result += 2
    if any(x in end for x in ("投诉", "扫码", "谢谢", "退换")):
        result += 2
    return result


def _run_ocr(image: Image.Image) -> tuple[list[str], list[float]]:
    result = _get_engine()(np.asarray(image))
    return list(result.txts or []), [float(score) for score in (result.scores or [])]


def extract_pages(pdf_path: Path, preview_dir: Path) -> list[PageResult]:
    preview_dir.mkdir(parents=True, exist_ok=True)
    pages: list[PageResult] = []
    with pymupdf.open(pdf_path) as pdf:
        if len(pdf) > 30:
            raise ValueError("单个 PDF 最多支持 30 页")
        for index, page in enumerate(pdf):
            pix = page.get_pixmap(dpi=200, alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            direct_text = page.get_text("text", sort=True).strip()
            if len(direct_text) >= 40:
                lines = [line.strip() for line in direct_text.splitlines() if line.strip()]
                scores = [1.0] * len(lines)
                preview = image
                used_ocr = False
            else:
                image = _crop_content(image)
                angles = (90, 270) if image.width > image.height * 1.2 else (0, 180)
                candidates = []
                for angle in angles:
                    oriented = image.rotate(angle, expand=True)
                    lines, scores = _run_ocr(oriented)
                    candidates.append((_orientation_score(lines, scores), oriented, lines, scores))
                _, preview, lines, scores = max(candidates, key=lambda item: item[0])
                used_ocr = True
            preview_path = preview_dir / f"page-{index + 1}.png"
            preview.save(preview_path, optimize=True)
            pages.append(PageResult(lines, scores, preview_path, index + 1, used_ocr))
    return pages
