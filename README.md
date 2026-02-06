# Scraper

A simple and practical Python web scraper for real‑world websites. It supports normal HTTP scraping, JavaScript rendering via Playwright, rate limiting, pagination, form submission, file downloads, and structured data extraction.

Designed to be usable, reliable, and flexible.

---

## Features

* HTTP scraping with `httpx`
* Automatic fallback to browser mode (Playwright) when blocked
* JavaScript rendering support
* Rate limiting
* Parallel fetching
* Table extraction with `rowspan` / `colspan`
* Pagination (patterned pages + "Next" button)
* JSON endpoints
* Form submission
* Image and file downloading
* CSV / JSON export
* Logging system

---

## Install

```bash
pip install httpx beautifulsoup4 playwright
playwright install chromium
```

---

## Basic Usage

```python
from scraper import Scraper

s = Scraper(url="https://example.com", debug=True)
s.fetch()

print(s.get_text("h1"))
print(s.get_links())
```

---

## Common Examples

### Fetch a page

```python
s.fetch("https://example.com")
```

### Force JS rendering

```python
s.fetch("https://site.com", use_browser=True)
# or
s.render_js()
```

### Extract text

```python
s.get_text(".title")
s.get_text_clean(".content")
```

### Get links & images

```python
s.get_links()
s.get_images()
```

### Extract tables

```python
table = s.get_table()
```

### Scrape paginated pages

```python
s.scrape_pages("https://site.com/page/{}", 5, ".item")
```

### Auto "Next" pagination

```python
s.scrape_auto_next("https://site.com", ".post")
```

### Parallel fetch

```python
urls = ["https://a.com", "https://b.com"]
s.fetch_multiple(urls, workers=5)
```

### JSON API

```python
s.get_json("https://api.site.com/data")
```

### Submit form

```python
s.submit_form("https://site.com/login", {
    "user": "name",
    "pass": "password"
})
```

### Download files

```python
s.download_file(url, "file.pdf")
s.download_images("images/")
```

### Export

```python
s.export_csv(data, "data.csv")
s.export_json(data, "data.json")
```

---

## Close resources

```python
s.close()
```

---

## Notes

* Automatically switches to browser mode if blocked
* Thread‑safe request handling
* Suitable for large scraping jobs
