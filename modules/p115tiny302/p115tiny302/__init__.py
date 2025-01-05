#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 8)
__license__ = "GPLv3 <https://www.gnu.org/licenses/gpl-3.0.txt>"

import logging

from collections.abc import Mapping
from errno import ENOENT
from hashlib import sha1 as calc_sha1
from http import HTTPStatus
from re import compile as re_compile
from string import digits, hexdigits
from time import time
from typing import Final
from urllib.parse import parse_qsl, quote, unquote, urlsplit

from blacksheep import json, text, Application, Request, Response, Router
from blacksheep.contents import Content
from blacksheep.server.remotes.forwarding import ForwardedHeadersMiddleware
from cachedict import LRUDict, TTLDict
from orjson import dumps
from p115client import check_response, P115Client, P115URL, P115OSError
from uvicorn.config import LOGGING_CONFIG


CRE_name_search: Final = re_compile("[^&=]+(?=&|$)").match

LOGGING_CONFIG["formatters"]["default"]["fmt"] = "[\x1b[1m%(asctime)s\x1b[0m] %(levelprefix)s %(message)s"
LOGGING_CONFIG["formatters"]["access"]["fmt"] = '[\x1b[1m%(asctime)s\x1b[0m] %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'


class ColoredLevelNameFormatter(logging.Formatter):

    def format(self, record):
        match record.levelno:
            case logging.DEBUG:
                # blue
                record.levelname = f"\x1b[34m{record.levelname}\x1b[0m:".ljust(18)
            case logging.INFO:
                # green
                record.levelname = f"\x1b[32m{record.levelname}\x1b[0m:".ljust(18)
            case logging.WARNING:
                # yellow
                record.levelname = f"\x1b[33m{record.levelname}\x1b[0m:".ljust(18)
            case logging.ERROR:
                # red
                record.levelname = f"\x1b[31m{record.levelname}\x1b[0m:".ljust(18)
            case logging.CRITICAL:
                # magenta
                record.levelname = f"\x1b[35m{record.levelname}\x1b[0m:".ljust(18)
            case _:
                # dark grey
                record.levelname = f"\x1b[2m{record.levelname}\x1b[0m: ".ljust(18)
        return super().format(record)


def get_first(m: Mapping, *keys, default=None):
    for k in keys:
        if k in m:
            return m[k]
    return default


def make_application(
    client: P115Client, 
    debug: bool = False, 
    token: str = "", 
    cache_size: int = 65536, 
) -> Application:
    ID_TO_PICKCODE: LRUDict[int, str] = LRUDict(cache_size)
    SHA1_TO_PICKCODE: LRUDict[str, str] = LRUDict(cache_size)
    NAME_TO_PICKCODE: LRUDict[str, str] = LRUDict(cache_size)
    SHARE_NAME_TO_ID: LRUDict[tuple[str, str], int] = LRUDict(cache_size)
    DOWNLOAD_URL_CACHE: TTLDict[str | tuple[str, int], P115URL] = TTLDict(cache_size, 3600)
    DOWNLOAD_URL_CACHE2: LRUDict[tuple[str, str], tuple[P115URL, int]] = LRUDict(1024)
    RECEIVE_CODE_MAP: dict[str, str] = {}

    app = Application(router=Router(), show_error_details=debug)
    logger = getattr(app, "logger")
    handler = logging.StreamHandler()
    handler.setFormatter(ColoredLevelNameFormatter("[\x1b[1m%(asctime)s\x1b[0m] %(levelname)s %(message)s"))
    logger.addHandler(handler)

    async def redirect_exception_response(
        self, 
        request: Request, 
        exc: Exception, 
    ):
        if isinstance(exc, ValueError):
            return text(str(exc), 400)
        elif isinstance(exc, FileNotFoundError):
            return text(str(exc), 404)
        elif isinstance(exc, OSError):
            return text(str(exc), 503)
        else:
            return text(str(exc), 500)

    if debug:
        logger.level = logging.DEBUG

    @app.on_middlewares_configuration
    def configure_forwarded_headers(app: Application):
        app.middlewares.insert(0, ForwardedHeadersMiddleware(accept_only_proxied_requests=False))

    @app.middlewares.append
    async def access_log(request: Request, handler) -> Response:
        start_t = time()
        def log(log, response):
            remote_attr = request.scope["client"]
            status = response.status
            if status < 300:
                status_color = 32
            elif status < 400:
                status_color = 33
            else:
                status_color = 31
            log(f'\x1b[5;35m{remote_attr[0]}:{remote_attr[1]}\x1b[0m - "\x1b[1;36m{request.method}\x1b[0m \x1b[1;4;34m{request.url}\x1b[0m \x1b[1mHTTP/{request.scope["http_version"]}\x1b[0m" - \x1b[{status_color}m{status} {HTTPStatus(status).phrase}\x1b[0m - \x1b[32m{(time() - start_t) * 1000:.3f}\x1b[0m \x1b[3mms\x1b[0m')
        try:
            response = await handler(request)
            log(logger.info, response)
        except Exception as e:
            response = await redirect_exception_response(app, request, e)
            if debug:
                log(logger.exception, response)
            else:
                log(logger.error, response)
        return response

    async def get_pickcode_to_id(id: int) -> str:
        if pickcode := ID_TO_PICKCODE.get(id, ""):
            return pickcode
        resp = await client.fs_file_skim(id, async_=True)
        check_response(resp)
        pickcode = ID_TO_PICKCODE[id] = resp["data"][0]["pick_code"]
        return pickcode 

    async def get_pickcode_for_sha1(sha1: str) -> str:
        if pickcode := SHA1_TO_PICKCODE.get(sha1, ""):
            return pickcode
        resp = await client.fs_shasearch(sha1, async_=True)
        check_response(resp)
        pickcode = SHA1_TO_PICKCODE[sha1] = resp["data"]["pick_code"]
        return pickcode

    async def get_pickcode_for_name(name: str, refresh: bool = False) -> str:
        if not refresh:
            if pickcode := NAME_TO_PICKCODE.get(name, ""):
                return pickcode
        payload = {"search_value": name, "limit": 1, "type": 99}
        suffix = name.rpartition(".")[-1]
        if suffix.isalnum():
            payload["suffix"] = suffix
        resp = await client.fs_search(payload, async_=True)
        if get_first(resp, "errno", "errNo") == 20021:
            payload.pop("suffix")
            resp = await client.fs_search(payload, async_=True)
        check_response(resp)
        data = resp["data"]
        if not data or (info := data[0])["n"] != name:
            raise FileNotFoundError(ENOENT, name)
        pickcode = NAME_TO_PICKCODE[name] = info["pc"]
        return pickcode

    async def share_get_id_for_name(
        share_code: str, 
        receive_code: str, 
        name: str, 
        refresh: bool = False, 
    ) -> int:
        key = (share_code, name)
        if not refresh and (id := SHARE_NAME_TO_ID.get(key, 0)):
            return id
        payload = {
            "share_code": share_code, 
            "receive_code": receive_code, 
            "search_value": name, 
            "limit": 1, 
            "type": 99, 
        }
        suffix = name.rpartition(".")[-1]
        if suffix.isalnum():
            payload["suffix"] = suffix
        resp = await client.share_search(payload, async_=True)
        if get_first(resp, "errno", "errNo") == 20021:
            payload.pop("suffix")
            resp = await client.share_search(payload, async_=True)
        check_response(resp)
        data = resp["data"]["list"]
        if not data or (info := data[0])["n"] != name:
            raise FileNotFoundError(ENOENT, key)
        id = SHARE_NAME_TO_ID[key] = int(info["fid"])
        return id

    async def get_downurl(
        pickcode: str, 
        user_agent: str = "", 
        app: str = "android", 
    ) -> P115URL:
        if url := DOWNLOAD_URL_CACHE.get(pickcode):
            return url
        elif pairs := DOWNLOAD_URL_CACHE2.get((pickcode, user_agent)):
            url, expire_ts = pairs
            if expire_ts >= time():
                return url
            DOWNLOAD_URL_CACHE2.pop((pickcode, user_agent))
        url = await client.download_url(pickcode, headers={"User-Agent": user_agent}, app=app or "android", async_=True)
        if "&c=0&f=&" in url:
            DOWNLOAD_URL_CACHE[pickcode] = url
        elif "&c=0&f=1&" in url:
            expire_ts = int(next(v for k, v in parse_qsl(urlsplit(url).query) if k == "t"))
            DOWNLOAD_URL_CACHE2[(pickcode, user_agent)] = (url, expire_ts - 60)
        return url

    async def get_share_downurl(
        share_code: str, 
        receive_code: str, 
        file_id: int, 
        app: str = "", 
    ) -> P115URL:
        if url := DOWNLOAD_URL_CACHE.get((share_code, file_id)):
            return url
        payload = {"share_code": share_code, "receive_code": receive_code, "file_id": file_id}
        try:
            url = await client.share_download_url(payload, app=app, async_=True)
        except P115OSError as e:
            if not (e.args[1].get("errno") == 4100008 and RECEIVE_CODE_MAP.pop(share_code, None)):
                raise
            receive_code = await get_receive_code(share_code)
            return await get_share_downurl(share_code, receive_code, file_id)
        if "&c=0&f=&" in url:
            DOWNLOAD_URL_CACHE[(share_code, file_id)] = url
        return url

    async def get_receive_code(share_code: str) -> str:
        if receive_code := RECEIVE_CODE_MAP.get(share_code, ""):
            return receive_code
        resp = await client.share_info(share_code, async_=True)
        check_response(resp)
        receive_code = RECEIVE_CODE_MAP[share_code] = resp["data"]["receive_code"]
        return receive_code

    @app.router.route("/", methods=["GET", "HEAD", "POST"])
    @app.router.route("/<path:name2>", methods=["GET", "HEAD", "POST"])
    async def index(
        request: Request, 
        share_code: str = "", 
        receive_code: str = "", 
        pickcode: str = "", 
        id: int = 0, 
        sha1: str = "", 
        name: str = "", 
        name2: str = "", 
        refresh: bool = False, 
        app: str = "", 
        sign: str = "", 
        t: int = 0, 
    ):
        def check_sign(value, /):
            if not token:
                return None
            if sign != calc_sha1(bytes(f"302@115-{token}-{t}-{value}", "utf-8")).hexdigest():
                return json({"state": False, "message": "invalid sign"}, 403)
            elif t > 0 and t <= time():
                return json({"state": False, "message": "url was expired"}, 401)
        file_name = name or name2
        if str(request.url) in ("/service-worker.js", "/favicon.ico"):
            raise FileNotFoundError
        if share_code:
            if resp := check_sign(id if id else file_name):
                return resp
            if not receive_code:
                receive_code = await get_receive_code(share_code)
            elif len(receive_code) != 4:
                raise ValueError(f"bad receive_code: {receive_code!r}")
            if not id:
                if file_name:
                    id = await share_get_id_for_name(share_code, receive_code, file_name, refresh=refresh)
            if not id:
                raise FileNotFoundError(f"please specify id or name: share_code={share_code!r}")
            url = await get_share_downurl(share_code, receive_code, id, app=app)
        else:
            if pickcode:
                if resp := check_sign(pickcode):
                    return resp
                if not (len(pickcode) == 17 and pickcode.isalnum()):
                    raise ValueError(f"bad pickcode: {pickcode!r}")
            elif id:
                if resp := check_sign(id):
                    return resp
                pickcode = await get_pickcode_to_id(id)
            elif sha1:
                if resp := check_sign(sha1):
                    return resp
                if len(sha1) != 40 or sha1.strip(hexdigits):
                    raise ValueError(f"bad sha1: {sha1!r}")
                pickcode = await get_pickcode_for_sha1(sha1.upper())
            else:
                remains = ""
                if match := CRE_name_search(unquote(request.url.query or b"")):
                    file_name = match[0]
                elif not name and (idx := file_name.find("/")) > 0:
                    file_name, remains = file_name[:idx], file_name[idx:]
                if file_name:
                    if resp := check_sign(file_name + remains):
                        return resp
                    if len(file_name) == 17 and file_name.isalnum():
                        pickcode = file_name.lower()
                    elif not file_name.strip(digits):
                        pickcode = await get_pickcode_to_id(int(file_name))
                    elif len(file_name) == 40 and not file_name.strip(hexdigits):
                        pickcode = await get_pickcode_for_sha1(file_name.upper())
                    else:
                        pickcode = await get_pickcode_for_name(file_name + remains, refresh=refresh)
            if not pickcode:
                raise FileNotFoundError(f"not found: {str(request.url)!r}")
            user_agent = (request.get_first_header(b"User-agent") or b"").decode("latin-1")
            url = await get_downurl(pickcode.lower(), user_agent, app=app)

        return Response(302, [
            (b"Location", bytes(url, "utf-8")), 
            (b"Content-Disposition", b'attachment; filename="%s"' % bytes(quote(url["name"], safe=""), "latin-1")), 
        ], Content(b"application/json; charset=utf-8", dumps(url.__dict__)))

    return app


if __name__ == "__main__":
    from pathlib import Path
    from uvicorn import run

    client = P115Client(Path("115-cookies.txt"), ensure_cookies=True, check_for_relogin=True)
    run(
        make_application(client, debug=True), 
        host="0.0.0.0", 
        port=8000, 
        proxy_headers=True, 
        server_header=False, 
        forwarded_allow_ips="*", 
        timeout_graceful_shutdown=1, 
        access_log=False, 
    )

