import asyncio
import sys
from pathlib import Path

async def _generate(html_file, pdf_file):
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            # Add headless args suitable for Linux containers (Render, etc.)
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            page = await browser.new_page()

            try:
                await page.goto(Path(html_file).absolute().as_uri(), wait_until="domcontentloaded", timeout=10000)
            except Exception as e:
                print(f"Warning: page.goto warning: {e}")

            try:
                await page.evaluate("document.fonts.ready")
            except Exception:
                pass

            await page.pdf(
                path=pdf_file,
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
    except Exception as e:
        print(f"Error generating PDF via Playwright: {e}", file=sys.stderr)
        # Create destination folder if needed and write a fallback note if Playwright is unavailable
        Path(pdf_file).parent.mkdir(parents=True, exist_ok=True)
        if not Path(pdf_file).exists():
            with open(pdf_file, "w", encoding="utf-8") as f:
                f.write(f"PDF generation error: {e}")

def generate_pdf(html_file, pdf_file):
    asyncio.run(_generate(html_file, pdf_file))