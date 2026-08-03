import asyncio
import re
import sys
from pathlib import Path

def _create_valid_error_pdf(pdf_path: str, message: str):
    """
    Generates a valid PDF 1.4 file containing an error message.
    Ensures Adobe Reader never throws a 'damaged file' error.
    """
    path = Path(pdf_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    clean_msg = message.replace("(", "[").replace(")", "]").replace("\\", "/")
    if len(clean_msg) > 80:
        clean_msg = clean_msg[:77] + "..."
        
    stream_content = f"BT /F1 12 Tf 50 700 Td (PDF Generation Note: {clean_msg}) Tj ET".encode("ascii", "ignore")
    stream_len = len(stream_content)
    
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
        b"5 0 obj << /Length " + str(stream_len).encode("ascii") + b" >>\nstream\n" +
        stream_content +
        b"\nendstream\nendobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000056 00000 n \n0000000111 00000 n \n0000000225 00000 n \n0000000294 00000 n \n"
        b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n380\n%%EOF\n"
    )
    with open(path, "wb") as f:
        f.write(pdf_bytes)

async def _generate(html_file, pdf_file):
    html_path = Path(html_file).resolve()
    pdf_path = Path(pdf_file).resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    if not html_path.exists():
        print(f"Error: HTML file does not exist: {html_file}", file=sys.stderr)
        _create_valid_error_pdf(str(pdf_path), f"HTML source file not found: {html_file}")
        return

    try:
        html_content = html_path.read_text(encoding="utf-8")
        
        # Convert relative asset links (/static/, ../static/, ../../static/) to absolute file URIs
        # so Playwright can locate CSS, images, seals, logos, and signatures from anywhere
        cwd = Path.cwd().resolve()
        static_uri = (cwd / "static").as_uri()
        generated_uri = (cwd / "generated").as_uri()
        
        html_content = re.sub(r'(\.\./)+static/', f'{static_uri}/', html_content)
        html_content = re.sub(r'/static/', f'{static_uri}/', html_content)
        html_content = re.sub(r'(\.\./)+generated/', f'{generated_uri}/', html_content)
        html_content = re.sub(r'/generated/', f'{generated_uri}/', html_content)

        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            page = await browser.new_page()

            # Load HTML content directly into Playwright
            await page.set_content(html_content, wait_until="load", timeout=15000)

            try:
                await page.evaluate("document.fonts.ready")
            except Exception:
                pass

            await page.pdf(
                path=str(pdf_path),
                width="210mm",
                height="297mm",
                print_background=True,
                prefer_css_page_size=True,
                margin={
                    "top": "0mm",
                    "bottom": "0mm",
                    "left": "0mm",
                    "right": "0mm"
                }
            )
            await browser.close()
            print(f"Successfully generated PDF: {pdf_path}")
    except Exception as e:
        print(f"Error generating PDF via Playwright: {e}", file=sys.stderr)
        _create_valid_error_pdf(str(pdf_path), f"PDF generation error: {e}")

def generate_pdf(html_file, pdf_file):
    asyncio.run(_generate(html_file, pdf_file))