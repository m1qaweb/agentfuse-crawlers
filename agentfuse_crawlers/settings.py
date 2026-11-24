BOT_NAME = "agentfuse_crawlers"
SPIDER_MODULES = ["agentfuse_crawlers.spiders"]
NEWSPIDER_MODULE = "agentfuse_crawlers.spiders"

# Respect publisher access controls; do not bypass login, CAPTCHAs, or robots.txt.
ROBOTSTXT_OBEY = True
USER_AGENT = "AgentFuseResearchBot/0.1 (+https://github.com/m1qaweb/agentfuse-crawlers)"
CONCURRENT_REQUESTS = 2
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 3
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 3
AUTOTHROTTLE_MAX_DELAY = 30
AUTOTHROTTLE_TARGET_CONCURRENCY = 1
DOWNLOAD_TIMEOUT = 35
DOWNLOAD_MAXSIZE = 8_000_000
RETRY_ENABLED = True
RETRY_TIMES = 1
RETRY_HTTP_CODES = [500, 502, 503, 504]
# Re-check exact-source access and short-lived plan expiry when a publisher
# source request reaches the downloader AFTER Scrapy's robots check (100).
# This prevents publisher page GETs after a long robots lookup; the robots
# fetch itself remains subject to separate per-source human policy review.
DOWNLOADER_MIDDLEWARES = {
    "scrapy.downloadermiddlewares.robotstxt.RobotsTxtMiddleware": None,
    "agentfuse_crawlers.validation_downloader.ValidationRobotsMiddleware": 100,
    "agentfuse_crawlers.validation_downloader.ValidationDownloadGate": 110,
}
REDIRECT_MAX_TIMES = 3
COOKIES_ENABLED = False
TELNETCONSOLE_ENABLED = False
LOG_LEVEL = "INFO"
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

# No Zyte API / headless browser add-on; no production database integrations.
FEED_EXPORT_ENCODING = "utf-8"
# Every periodic job makes real requests; never reuse an earlier crawl's HTML.
HTTPCACHE_ENABLED = False
# Keep RedirectMiddleware for legacy monitoring; validation robots and
# publisher requests explicitly disable automatic redirects and retries.
REDIRECT_ENABLED = True
METAREFRESH_ENABLED = False
DOWNLOAD_WARNSIZE = 4_000_000
EXTENSIONS = {
    "agentfuse_crawlers.extensions.coverage.SourceCoverageAudit": 100,
}
