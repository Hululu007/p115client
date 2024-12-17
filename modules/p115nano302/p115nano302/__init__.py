#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 1)
__license__ = "GPLv3 <https://www.gnu.org/licenses/gpl-3.0.txt>"

from blacksheep import redirect, text, Application, Request, Router
from blacksheep.server.remotes.forwarding import ForwardedHeadersMiddleware
from cachedict import TTLDict
from p115client import P115Client


def make_application(client: P115Client, debug: bool = False) -> Application:
    app = Application(router=Router(), show_error_details=debug)
    url_cache: TTLDict[str, str] = TTLDict(65536, 2900)

    @app.on_middlewares_configuration
    def configure_forwarded_headers(app: Application):
        app.middlewares.insert(0, ForwardedHeadersMiddleware(accept_only_proxied_requests=False))

    @app.router.route("/", methods=["GET", "HEAD", "POST"])
    @app.router.route("/<path:name>", methods=["GET", "HEAD", "POST"])
    async def index(request: Request, name: str = "", pickcode: str = ""):
        if not pickcode:
            if query := request.url.query:
                pickcode = query.decode("latin-1")
            else:
                pickcode = name
        if not (len(pickcode) == 17 and pickcode.isalnum()):
            return text("", 404)
        if url := url_cache.get(pickcode, ""):
            return url
        try:
            url = await client.download_url(
                pickcode, 
                headers={"User-Agent": (request.get_first_header(b"User-agent") or b"").decode("latin-1")}, 
                app="android", 
                async_=True, 
            )
        except Exception as e:
            if debug:
                raise
            return text(f"{type(e).__qualname__}: {e}", 500)
        if "&c=0&f=&" in url:
            url_cache[pickcode] = url
        return redirect(url)

    return app

