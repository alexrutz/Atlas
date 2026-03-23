"""
VLM OCR Service - Vision-Language Model OCR mit Layout-as-thought.

Verwendet Qianfan-OCR (oder kompatible VLMs) über llama.cpp, um Dokument-
Seiten per Vision-Completion zu lesen, statt klassisches Tesseract-OCR.

Layout-as-thought: Das Modell analysiert zuerst die räumliche Struktur
der Seite (Spalten, Tabellen, Überschriften, Lesereihenfolge), bevor
es den Text extrahiert. Dies verbessert die Textqualität erheblich,
insbesondere bei komplexen Layouts.
"""

import base64
import io
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class VlmOcrService:
    """Extrahiert Text aus Bildern über ein Vision-Language Model."""

    def __init__(self):
        self.config = settings.vlm_ocr
        self.base_url = self.config.base_url

    def _build_system_prompt(self) -> str:
        """Baut den System-Prompt, mit oder ohne Layout-as-thought."""
        base = self.config.system_prompt
        if self.config.layout_as_thought:
            return (
                "IMPORTANT: Before extracting text, you MUST first perform "
                "Layout-as-thought analysis.\n"
                "Step 1 — LAYOUT ANALYSIS (internal, do not output):\n"
                "  • Identify the page structure: number of columns, header/footer "
                "regions, sidebars, margin notes.\n"
                "  • Detect tables (rows × columns), bulleted/numbered lists, "
                "captions, and figure references.\n"
                "  • Determine the logical reading order across all regions.\n"
                "Step 2 — TEXT EXTRACTION (output this):\n"
                "  • Using the layout analysis, extract all text in logical "
                "reading order.\n"
                "  • Preserve paragraph separation and structural hierarchy.\n\n"
                + base
            )
        return base

    @staticmethod
    def _image_to_data_uri(image_bytes: bytes, mime_type: str = "image/png") -> str:
        """Konvertiert Bilddaten in eine base64-Data-URI."""
        b64 = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{mime_type};base64,{b64}"

    @staticmethod
    def _pil_image_to_bytes(image, max_size: int = 2048) -> bytes:
        """Konvertiert ein PIL-Image zu PNG-Bytes, optional herunterskaliert."""
        w, h = image.size
        if max(w, h) > max_size:
            scale = max_size / max(w, h)
            image = image.resize(
                (int(w * scale), int(h * scale)),
                getattr(image, "Resampling", image).LANCZOS
                if hasattr(image, "Resampling")
                else 1,  # PIL.Image.LANCZOS
            )
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    async def ocr_image(self, image) -> str:
        """
        Extrahiert Text aus einem einzelnen PIL-Image.

        Args:
            image: PIL.Image.Image Objekt (z.B. eine PDF-Seite)

        Returns:
            Extrahierter Text als String
        """
        img_bytes = self._pil_image_to_bytes(
            image, max_size=self.config.max_image_size_px
        )
        data_uri = self._image_to_data_uri(img_bytes)
        system_prompt = self._build_system_prompt()

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": data_uri},
                        },
                        {
                            "type": "text",
                            "text": "Extract all text from this document page.",
                        },
                    ],
                },
            ],
            "max_tokens": self.config.max_tokens,
            "temperature": 0.1,
            "enable_thinking": False,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(
            connect=30.0,
            read=float(self.config.timeout),
            write=30.0,
            pool=30.0,
        )) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        message = data["choices"][0]["message"]
        text = message.get("content") or ""

        # With peg-native chat format, the model may put layout analysis
        # into reasoning_content (thinking tokens) and leave content empty
        # if it hits max_tokens before reaching the extraction phase.
        # Fall back to reasoning_content so we still capture the OCR text.
        if not text.strip():
            text = message.get("reasoning_content") or ""

        return text.strip()

    async def ocr_pdf_pages(self, file_path: str) -> tuple[list, list[str]]:
        """
        Führt VLM-OCR auf allen Seiten eines PDFs durch.

        Args:
            file_path: Pfad zur PDF-Datei

        Returns:
            Tuple von (ParsedSections-Liste, Volltexte-Liste)
        """
        from pdf2image import convert_from_path
        from app.utils.file_parsers import ParsedSection

        sections = []
        full_text = []

        try:
            images = convert_from_path(file_path, dpi=self.config.dpi)
            total = len(images)
            logger.info(
                f"VLM-OCR (Layout-as-thought={'ON' if self.config.layout_as_thought else 'OFF'}): "
                f"{total} Seiten in {file_path}"
            )

            for i, image in enumerate(images):
                try:
                    text = await self.ocr_image(image)
                    if text and len(text.strip()) >= 20:
                        sections.append(
                            ParsedSection(
                                header=None,
                                content=text.strip(),
                                page_number=i + 1,
                            )
                        )
                        full_text.append(text.strip())
                        logger.debug(
                            f"VLM-OCR Seite {i+1}/{total}: {len(text)} Zeichen"
                        )
                    elif text and text.strip():
                        logger.debug(
                            f"VLM-OCR Seite {i+1}/{total} übersprungen "
                            f"(zu wenig Text: {len(text.strip())} Zeichen)"
                        )
                except Exception as e:
                    logger.warning(f"VLM-OCR Seite {i+1}/{total} fehlgeschlagen: {e}")

        except Exception as e:
            logger.error(f"VLM-OCR Fehler für {file_path}: {e}")

        return sections, full_text
