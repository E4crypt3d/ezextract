import time
import os
import httpx
import threading
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from .utils import clean_text, save_csv, save_json


class Scraper:
    def __init__(
        self,
        url=None,
        delay=0.0,
        headers=None,
        max_requests_per_minute=None,
        debug=False,
        strict=False,
    ):
        self._playwright = None
        self._browser = None
        self._context = None

        self.base_url = url
        self.delay = delay
        self.debug = debug
        self.strict = strict

        self._state = threading.local()
        self._lock = threading.Lock()

        # Setup logging
        self.logger = logging.getLogger(__name__)
        if debug:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.WARNING)

        # headers
        head = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        if headers:
            head.update({k.lower(): v for k, v in headers.items()})

        self.client = httpx.Client(headers=head, follow_redirects=True, timeout=15.0)

        self.last_req = 0

        if max_requests_per_minute and max_requests_per_minute > 0:
            self.delay = max(self.delay, 60.0 / max_requests_per_minute)

    @property
    def soup(self):
        """Get the current BeautifulSoup object from thread-local state."""
        return getattr(self._state, "soup", None)

    @property
    def response(self):
        """Get the current response object from thread-local state."""
        return getattr(self._state, "res", None)

    def _init_browser(self):
        """Initialize browser if not already initialized."""
        if self._browser:
            return

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36",
            locale="en-US",
        )

    def _close_browser(self):
        """Close browser and cleanup resources."""
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

        self._context = None
        self._browser = None
        self._playwright = None

    def _wait(self):
        """Enforce rate limiting between requests."""
        with self._lock:
            passed = time.time() - self.last_req
            if passed < self.delay:
                time.sleep(self.delay - passed)
            self.last_req = time.time()

    def fetch(self, url=None, retries=0, use_browser=False):
        """
        Fetch a URL and parse its content.

        Args:
            url: URL to fetch (uses base_url if not provided)
            retries: Number of retries on failure
            use_browser: Force using Playwright browser instead of httpx

        Returns:
            self if successful, None if failed
        """
        target = url or self.base_url
        if not target:
            self.logger.warning("No URL provided to fetch")
            return self

        if use_browser:
            return self._fetch_browser(target)

        for i in range(retries + 1):
            try:
                self._wait()
                self.logger.debug(f"Fetching: {target}")

                res = self.client.get(target)

                text_low = res.text.lower()
                # Check for common blocking indicators
                blocking_indicators = (
                    res.status_code in (403, 429),
                    "captcha" in text_low,
                    "cloudflare" in text_low,
                    "verify you are human" in text_low,
                    "access denied" in text_low,
                )

                if any(blocking_indicators):
                    self.logger.warning(
                        "Access blocked or soft-blocked -> switching to browser mode"
                    )
                    return self._fetch_browser(target)

                if self.strict:
                    res.raise_for_status()

                self._state.res = res
                self._state.soup = BeautifulSoup(res.text, "html.parser")
                return self

            except httpx.HTTPError as e:
                self.logger.error(f"HTTP error on {target}: {e}")
                if self.strict and i == retries:
                    raise
                if i < retries:
                    time.sleep(1)
            except Exception as e:
                self.logger.error(f"Error on {target}: {e}")
                if self.strict and i == retries:
                    raise
                if i < retries:
                    time.sleep(1)

        return None

    def _fetch_browser(self, target, wait=1.5):
        """
        Fetch URL using Playwright browser for JavaScript-heavy pages.

        Args:
            target: URL to fetch
            wait: Time to wait after page load (seconds)

        Returns:
            self if successful
        """
        self.logger.debug(f"[browser] fetching: {target}")

        self._init_browser()

        page = self._context.new_page()
        try:
            try:
                page.goto(target, wait_until="networkidle", timeout=15000)
            except PlaywrightTimeout:
                self.logger.warning(
                    f"Playwright timeout for {target}, continuing anyway"
                )

            time.sleep(wait)
            html = page.content()
        except Exception as e:
            self.logger.error(f"Browser error fetching {target}: {e}")
            return None
        finally:
            page.close()

        # Create mock response object
        mock_response = type(
            "Response", (), {"url": target, "text": html, "status_code": 200}
        )()
        self._state.res = mock_response
        self._state.soup = BeautifulSoup(html, "html.parser")
        return self

    def render_js(self, wait=2):
        """
        Re-fetch current page with JavaScript rendering enabled.

        Args:
            wait: Time to wait after page load (seconds)

        Returns:
            self if successful
        """
        if not self.response:
            self.logger.warning("No current response to render")
            return self
        return self._fetch_browser(str(self.response.url), wait=wait)

    def get_text(self, selector):
        """
        Extract text from first element matching selector.

        Args:
            selector: CSS selector

        Returns:
            Text content or empty string
        """
        if not self.soup:
            self.logger.warning("No soup object available")
            return ""
        el = self.soup.select_one(selector)
        return el.get_text(strip=True) if el else ""

    def get_text_clean(self, selector):
        """Extract and clean text from element."""
        return clean_text(self.get_text(selector))

    def get_links(self):
        """Extract all unique links from current page."""
        if not self.soup:
            self.logger.warning("No soup object available")
            return []

        links = set()
        for a in self.soup.find_all("a", href=True):
            try:
                href = a.get("href", "").strip()
                if href:  # Skip empty hrefs
                    full_url = urljoin(str(self.response.url), href)
                    links.add(full_url)
            except Exception as e:
                self.logger.debug(f"Error processing link: {e}")
                continue

        return list(links)

    def get_images(self):
        """Extract all unique image URLs from current page."""
        if not self.soup:
            self.logger.warning("No soup object available")
            return []

        images = set()
        for img in self.soup.find_all("img", src=True):
            try:
                src = img.get("src", "").strip()
                if src:  # Skip empty src attributes
                    full_url = urljoin(str(self.response.url), src)
                    images.add(full_url)
            except Exception as e:
                self.logger.debug(f"Error processing image: {e}")
                continue

        return list(images)

    def get_json(self, url=None):
        """
        Fetch and parse JSON from URL.

        Args:
            url: URL to fetch (uses base_url if not provided)

        Returns:
            Parsed JSON data
        """
        target = url or self.base_url
        if not target:
            raise ValueError("No URL provided for JSON fetch")

        self._wait()
        try:
            r = self.client.get(target)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            self.logger.error(f"HTTP error fetching JSON from {target}: {e}")
            raise
        except ValueError as e:
            self.logger.error(f"Invalid JSON from {target}: {e}")
            raise
        finally:
            self.last_req = time.time()

    def get_table(self, selector=None):
        """
        Extract table data with support for colspan/rowspan.

        Args:
            selector: CSS selector for table(s), defaults to ".wikitable"

        Returns:
            List of lists representing table rows
        """
        if not self.soup:
            self.logger.warning("No soup object available")
            return []

        tables = (
            self.soup.select(selector)
            if selector
            else self.soup.select("table.wikitable")
        )

        if not tables:
            self.logger.debug(f"No tables found with selector: {selector}")
            return []

        # Find table with most rows
        table = max(tables, key=lambda t: len(t.find_all("tr"))) if tables else None
        if not table:
            return []

        rows = table.find_all("tr")
        matrix = []
        active_spans = {}
        max_cols = 0

        for tr in rows:
            cells = tr.find_all(["td", "th"])
            row = []
            col = 0
            cell_i = 0

            while cell_i < len(cells) or col in active_spans:
                if col in active_spans:
                    val, remaining = active_spans[col]
                    row.append(val)
                    if remaining > 1:
                        active_spans[col][1] -= 1
                    else:
                        del active_spans[col]
                    col += 1
                    continue

                if cell_i >= len(cells):
                    break

                cell = cells[cell_i]
                cell_i += 1

                try:
                    rowspan = int(cell.get("rowspan", 1))
                    colspan = int(cell.get("colspan", 1))
                except (ValueError, TypeError):
                    rowspan, colspan = 1, 1

                value = cell.get_text(" ", strip=True)

                if rowspan > 1:
                    for c in range(colspan):
                        active_spans[col + c] = [value, rowspan - 1]

                for _ in range(colspan):
                    row.append(value)
                    col += 1

            max_cols = max(max_cols, len(row))
            matrix.append(row)

        # Pad rows with empty strings
        for r in matrix:
            if len(r) < max_cols:
                r.extend([""] * (max_cols - len(r)))

        return matrix

    def scrape_pages(self, url_pattern, pages, selector):
        """
        Scrape multiple pages with numbered URL pattern.

        Args:
            url_pattern: URL pattern with {}, e.g., "https://example.com/page/{}"
            pages: Number of pages to scrape
            selector: CSS selector for elements to extract

        Returns:
            List of extracted text values
        """
        if pages < 1:
            raise ValueError("pages must be >= 1")

        results = []
        for i in range(1, pages + 1):
            self.logger.debug(f"Scraping page {i}/{pages}")
            try:
                formatted_url = url_pattern.format(i)
                if self.fetch(formatted_url):
                    results.extend(
                        [el.get_text(strip=True) for el in self.soup.select(selector)]
                    )
            except Exception as e:
                self.logger.error(f"Error scraping page {i}: {e}")
                if self.strict:
                    raise
        return results

    def scrape_auto_next(self, url, selector, max_pages=10):
        """
        Scrape pages by following "Next" button.

        Args:
            url: Starting URL
            selector: CSS selector for elements to extract
            max_pages: Maximum pages to scrape

        Returns:
            List of extracted text values
        """
        if max_pages < 1:
            raise ValueError("max_pages must be >= 1")

        data, curr = [], url
        for page_num in range(max_pages):
            self.logger.debug(f"Scraping auto-next page {page_num + 1}/{max_pages}")

            if not self.fetch(curr):
                break

            data.extend([el.get_text(strip=True) for el in self.soup.select(selector)])

            # IMPROVED: More resilient "Next" button detection
            nxt = (
                self.soup.find("a", string=lambda t: t and "next" in t.lower().strip())
                or self.soup.find("a", attrs={"rel": "next"})
                or self.soup.select_one("li.next a")
                or self.soup.select_one("a.next")
            )

            if nxt and nxt.get("href"):
                curr = urljoin(str(self.response.url), nxt["href"])
            else:
                self.logger.debug("No 'Next' button found, stopping pagination")
                break

        return data

    def fetch_multiple(self, urls, workers=5):
        """
        Fetch multiple URLs in parallel.

        Args:
            urls: List of URLs to fetch
            workers: Number of worker threads

        Returns:
            List of tuples (url, success_status)
        """
        if not urls:
            self.logger.warning("No URLs provided for parallel fetch")
            return []

        if workers < 1:
            raise ValueError("workers must be >= 1")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(lambda u: (u, self.fetch(u) is not None), urls))

    def submit_form(self, url, data):
        """
        Submit form data via POST.

        Args:
            url: Form endpoint URL
            data: Dictionary of form data

        Returns:
            self
        """
        if not url or not data:
            raise ValueError("url and data are required")

        self._wait()
        try:
            res = self.client.post(url, data=data)
            res.raise_for_status()
            self._state.res = res
            self._state.soup = BeautifulSoup(res.text, "html.parser")
        except httpx.HTTPError as e:
            self.logger.error(f"HTTP error submitting form to {url}: {e}")
            if self.strict:
                raise
        return self

    def download_file(self, url, dest):
        """
        Download file from URL.

        Args:
            url: File URL
            dest: Destination file path
        """
        if not url or not dest:
            raise ValueError("url and dest are required")

        try:
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            with self.client.stream("GET", url) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
            self.logger.debug(f"Downloaded: {dest}")
        except httpx.HTTPError as e:
            self.logger.error(f"HTTP error downloading {url}: {e}")
            raise
        except IOError as e:
            self.logger.error(f"Error writing to {dest}: {e}")
            raise

    def download_images(self, folder="images/"):
        """
        Download all images from current page.

        Args:
            folder: Destination folder for images
        """
        if not folder:
            raise ValueError("folder is required")

        images = self.get_images()
        if not images:
            self.logger.warning("No images found to download")
            return

        for i, url in enumerate(images):
            try:
                ext = url.split(".")[-1].split("?")[0][:3]
                if len(ext) > 3 or not ext:
                    ext = "jpg"
                dest = os.path.join(folder, f"img_{i}.{ext}")
                self.download_file(url, dest)
            except Exception as e:
                self.logger.error(f"Error downloading image {i} from {url}: {e}")
                if self.strict:
                    raise

    def list_selectors(self):
        """List available HTML tags, IDs, and classes for debugging."""
        if not self.soup:
            self.logger.warning("No soup object available")
            return

        tags = list(set(el.name for el in self.soup.find_all()))[:15]
        ids = list(set(el["id"] for el in self.soup.find_all(id=True)))[:15]
        classes = list(
            set(c for el in self.soup.find_all(class_=True) for c in el["class"])
        )[:15]

        print(f"tags: {tags}\nids: {ids}\nclasses: {classes}")

    def export_csv(self, data, path):
        """Export data to CSV file."""
        if not path:
            raise ValueError("path is required")
        save_csv(data, path)
        self.logger.debug(f"Exported CSV: {path}")

    def export_json(self, data, path):
        """Export data to JSON file."""
        if not path:
            raise ValueError("path is required")
        save_json(data, path)
        self.logger.debug(f"Exported JSON: {path}")

    def close(self):
        """Close client and cleanup resources."""
        self.client.close()
        self._close_browser()
        self.logger.debug("Scraper closed")
