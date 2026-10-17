"""Shared HTTP session with a polite, identifiable User-Agent."""
import requests

USER_AGENT = "vn-digest/1.0 (+https://github.com/; personal weekly digest)"

# A browser-ish UA used only as a fallback for sites (e.g. voz/Cloudflare) that
# reject unknown agents. Kept separate so default traffic stays honest.
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_session = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT})
        _session = s
    return _session


def get(url, *, timeout=25, browser=False, **kwargs):
    headers = kwargs.pop("headers", {})
    if browser:
        headers = {**headers, "User-Agent": BROWSER_UA}
    return session().get(url, timeout=timeout, headers=headers, **kwargs)


def post(url, *, timeout=25, **kwargs):
    return session().post(url, timeout=timeout, **kwargs)
