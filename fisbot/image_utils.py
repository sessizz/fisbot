import io
import logging

from PIL import Image, ImageEnhance

from fisbot.config import MAX_IMAGE_DIMENSION

logger = logging.getLogger(__name__)


def preprocess_image(image_bytes: bytes) -> bytes:
    """Resize and enhance a receipt image for better OCR results."""
    img = Image.open(io.BytesIO(image_bytes))

    # Resize if too large (keep aspect ratio)
    w, h = img.size
    if max(w, h) > MAX_IMAGE_DIMENSION:
        ratio = MAX_IMAGE_DIMENSION / max(w, h)
        new_size = (int(w * ratio), int(h * ratio))
        img = img.resize(new_size, Image.LANCZOS)
        logger.info("Resized image from %dx%d to %dx%d", w, h, *new_size)

    # Enhance contrast (helps with faded thermal paper)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.3)

    # Enhance sharpness
    enhancer = ImageEnhance.Sharpness(img)
    img = enhancer.enhance(1.5)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()
