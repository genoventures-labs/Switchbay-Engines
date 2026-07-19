# Web to Markdown Engine

Use this engine when a model needs durable, local, RAG-friendly source text from a website.

- Use `fetch_page` for a single article, documentation page, landing page, or known URL.
- Use `crawl_site` only when multiple same-origin pages are needed. Start with conservative limits (`max_pages` 20-50, `max_depth` 1-2).
- Use `inspect_corpus` before loading documents so the model can select relevant pages by title, URL, depth, and word count.
- The crawler respects `robots.txt` by default, strips tracking query parameters, rejects private-network targets by default, and does not execute JavaScript.
- Dynamic client-rendered pages may produce thin Markdown. Prefer a static page, sitemap-backed documentation route, or a browser-rendering engine for those sites.
