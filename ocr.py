"""OCR extraction using Tesseract (open-source, no cloud dependency)."""

import io
import logging

import pytesseract
from PIL import Image, ImageFilter, ImageOps

logger = logging.getLogger(__name__)


def _preprocess(image: Image.Image) -> Image.Image:
    """Convert to greyscale and sharpen to improve Tesseract accuracy."""
    image = ImageOps.grayscale(image)
    image = image.filter(ImageFilter.SHARPEN)
    return image


def extract_text(image_bytes: bytes) -> str:
    """Run Tesseract OCR on raw image bytes. Returns extracted text."""
    image = Image.open(io.BytesIO(image_bytes))
    image = _preprocess(image)
    text = pytesseract.image_to_string(image, config="--psm 6")
    cleaned = text.strip()
    logger.debug("OCR extracted %d characters", len(cleaned))
    return cleaned
