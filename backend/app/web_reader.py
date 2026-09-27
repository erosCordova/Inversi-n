import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup


MAX_DOWNLOAD_BYTES = 1_000_000
MAX_TEXT_CHARACTERS = 5_000
MAX_LINKS = 8

DEADLINE_TERMS = (
    "fecha de cierre",
    "fecha límite",
    "fecha limite",
    "último día de registro",
    "ultimo dia de registro",
    "último día de inscripción",
    "ultimo dia de inscripcion",
    "plazo de inscripción",
    "plazo de inscripcion",
    "deadline",
)


def public_web_url(url: str) -> bool:
    """Acepta páginas web públicas y rechaza direcciones locales."""
    try:
        parsed = urlsplit(url)

        if parsed.scheme not in {"http", "https"}:
            return False

        if not parsed.hostname or parsed.username or parsed.password:
            return False

        if parsed.port not in {None, 80, 443}:
            return False

        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )

        return bool(addresses) and all(
            ipaddress.ip_address(item[4][0]).is_global
            for item in addresses
        )
    except (OSError, ValueError):
        return False


def deadline_excerpts(text: str) -> str:
    """Conserva fragmentos sobre plazos aunque estén al final de la página."""
    lower_text = text.lower()
    excerpts = []
    positions = set()

    for term in DEADLINE_TERMS:
        for match in re.finditer(re.escape(term), lower_text):
            start = max(0, match.start() - 35)
            end = min(len(text), match.end() + 120)

            if any(abs(start - previous) < 80 for previous in positions):
                continue

            positions.add(start)
            excerpts.append(text[start:end].strip())

            if len(excerpts) >= 6:
                break

        if len(excerpts) >= 6:
            break

    return " | ".join(excerpts)


def read_page(url: str) -> dict:
    """Lee una página HTML y devuelve texto, fecha y enlaces."""
    if not public_web_url(url):
        return {
            "url": url,
            "error": "Enlace no público o no válido.",
        }

    try:
        with httpx.stream(
            "GET",
            url,
            timeout=8.0,
            follow_redirects=False,
            trust_env=False,
            headers={
                "User-Agent": "ReplikersResearch/0.1",
                "Accept": "text/html",
            },
        ) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                return {
                    "url": url,
                    "error": "La página redirige; no se siguió el enlace.",
                }

            response.raise_for_status()

            content_type = response.headers.get(
                "content-type", ""
            ).lower()

            if "text/html" not in content_type:
                return {
                    "url": url,
                    "error": "El enlace no contiene una página HTML.",
                }

            chunks = []
            total = 0

            for chunk in response.iter_bytes():
                total += len(chunk)

                if total > MAX_DOWNLOAD_BYTES:
                    return {
                        "url": url,
                        "error": "La página supera el límite de 1 MB.",
                    }

                chunks.append(chunk)

            encoding = response.encoding or "utf-8"
            html = b"".join(chunks).decode(
                encoding,
                errors="replace",
            )

        soup = BeautifulSoup(html, "html.parser")

        title = (
            soup.title.get_text(" ", strip=True)
            if soup.title
            else "Sin título"
        )

        published = None

        for selector in (
            'meta[property="article:published_time"]',
            'meta[name="date"]',
            'meta[name="pubdate"]',
            "time[datetime]",
        ):
            element = soup.select_one(selector)

            if element:
                published = (
                    element.get("content")
                    or element.get("datetime")
                )
                if published:
                    break

        for element in soup(
            ["script", "style", "nav", "footer", "header"]
        ):
            element.decompose()

        candidates = [
            element
            for element in (
                soup.find("article"),
                soup.find("main"),
                soup.body,
            )
            if element is not None
        ]

        content = max(
            candidates,
            key=lambda element: len(
                element.get_text(" ", strip=True)
            ),
            default=soup,
        )

        full_text = re.sub(
            r"\s+",
            " ",
            content.get_text(" ", strip=True),
        )

        excerpts = deadline_excerpts(full_text)
        remaining = MAX_TEXT_CHARACTERS - len(excerpts) - 2

        if excerpts and remaining > 0:
            text = excerpts + "\n\n" + full_text[:remaining]
        else:
            text = full_text[:MAX_TEXT_CHARACTERS]

        links = []
        seen_urls = {url}

        for element in content.find_all("a", href=True, limit=30):
            link = urljoin(url, element["href"])
            label = element.get_text(" ", strip=True)

            if not label or link in seen_urls:
                continue

            if public_web_url(link):
                links.append(
                    {
                        "url": link,
                        "label": label[:120],
                    }
                )
                seen_urls.add(link)

            if len(links) >= MAX_LINKS:
                break

        return {
            "url": url,
            "title": title[:200],
            "published": str(published) if published else None,
            "text": text,
            "links": links,
        }

    except (httpx.HTTPError, UnicodeError, ValueError) as error:
        return {
            "url": url,
            "error": f"No se pudo leer la página: {type(error).__name__}",
        }