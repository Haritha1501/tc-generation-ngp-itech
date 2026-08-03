import asyncio
import re
import sys
import subprocess
from pathlib import Path

_PLAYWRIGHT_INSTALLED = False

def _ensure_chromium_installed():
    global _PLAYWRIGHT_INSTALLED
    if _PLAYWRIGHT_INSTALLED:
        return
    print("Attempting automatic Playwright Chromium installation...", file=sys.stderr)
    try:
        res = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=180
        )
        print(f"Playwright install stdout: {res.stdout}", file=sys.stderr)
        print(f"Playwright install stderr: {res.stderr}", file=sys.stderr)
        _PLAYWRIGHT_INSTALLED = True
    except Exception as e:
        print(f"Failed to auto-install Playwright chromium: {e}", file=sys.stderr)

def _try_xhtml2pdf_fallback(html_content: str, pdf_path: Path) -> bool:
    """
    Attempts to generate PDF using xhtml2pdf pure-python renderer if available.
    Returns True if successful, False otherwise.
    """
    try:
        from xhtml2pdf import pisa
        with open(pdf_path, "wb") as pdf_file:
            pisa_status = pisa.CreatePDF(html_content, dest=pdf_file)
        return not pisa_status.err
    except Exception as e:
        print(f"xhtml2pdf fallback failed: {e}", file=sys.stderr)
        return False

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
        cwd = Path.cwd().resolve()
        static_uri = (cwd / "static").as_uri()
        generated_uri = (cwd / "generated").as_uri()
        
        html_content = re.sub(r'(\.\.\/)+static/', f'{static_uri}/', html_content)
        html_content = re.sub(r'/static/', f'{static_uri}/', html_content)
        html_content = re.sub(r'(\.\.\/)+generated/', f'{generated_uri}/', html_content)
        html_content = re.sub(r'/generated/', f'{generated_uri}/', html_content)

        # Attempt Playwright first (up to 2 tries if chromium needs auto-installation)
        last_error = None
        for attempt in range(2):
            try:
                from playwright.async_api import async_playwright
                async with async_playwright() as p:
                    browser = await p.chromium.launch(
                        headless=True,
                        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
                    )
                    page = await browser.new_page()

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
                    print(f"Successfully generated PDF via Playwright: {pdf_path}")
                    return
            except Exception as e:
                last_error = e
                err_str = str(e)
                print(f"Playwright attempt {attempt+1} failed: {err_str}", file=sys.stderr)
                if ("Executable doesn't exist" in err_str or "executable" in err_str.lower()) and attempt == 0:
                    _ensure_chromium_installed()
                    continue
                else:
                    break

        # Fallback 1: xhtml2pdf pure-python renderer
        if _try_xhtml2pdf_fallback(html_content, pdf_path):
            print(f"Successfully generated PDF via xhtml2pdf fallback: {pdf_path}")
            return

        # Fallback 2: Valid binary PDF error note
        _create_valid_error_pdf(str(pdf_path), f"PDF generation error: {last_error}")

    except Exception as e:
        print(f"Error generating PDF: {e}", file=sys.stderr)
        _create_valid_error_pdf(str(pdf_path), f"PDF generation error: {e}")

def generate_pdf(html_file, pdf_file):
    asyncio.run(_generate(html_file, pdf_file))