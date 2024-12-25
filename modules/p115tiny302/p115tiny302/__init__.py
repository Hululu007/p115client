#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 5)
__license__ = "GPLv3 <https://www.gnu.org/licenses/gpl-3.0.txt>"

from collections.abc import Mapping
from errno import ENOENT
from string import digits, hexdigits
from time import time
from urllib.parse import parse_qsl, urlsplit

from blacksheep import redirect, text, Application, Request, Router
from blacksheep.server.compression import use_gzip_compression
from blacksheep.server.remotes.forwarding import ForwardedHeadersMiddleware
from cachedict import LRUDict, TTLDict
from p115client import check_response, P115Client, P115OSError


def get_first(m: Mapping, *keys, default=None):
    for k in keys:
        if k in m:
            return m[k]
    return default


def make_application(client: P115Client, debug: bool = False) -> Application:
    ID_TO_PICKCODE: LRUDict[int, str] = LRUDict(65536)
    SHA1_TO_PICKCODE: LRUDict[str, str] = LRUDict(65536)
    NAME_TO_PICKCODE: LRUDict[str, str] = LRUDict(65536)
    SHARE_NAME_TO_ID: LRUDict[tuple[str, str], int] = LRUDict(65536)
    DOWNLOAD_URL_CACHE: TTLDict[str | tuple[str, int], str] = TTLDict(65536, 3600)
    DOWNLOAD_URL_CACHE2: LRUDict[tuple[str, str], tuple[str, int]] = LRUDict(1024)
    RECEIVE_CODE_MAP: dict[str, str] = {}

    app = Application(router=Router(), show_error_details=debug)
    use_gzip_compression(app)

    if debug:
        getattr(app, "logger").level = 10
    else:
        @app.exception_handler(Exception)
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

    @app.on_middlewares_configuration
    def configure_forwarded_headers(app: Application):
        app.middlewares.insert(0, ForwardedHeadersMiddleware(accept_only_proxied_requests=False))

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
        if not refresh:
            if id := SHARE_NAME_TO_ID.get(key, 0):
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
    ) -> str:
        if url := DOWNLOAD_URL_CACHE.get(pickcode, ""):
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
        app: str = "android", 
    ):
        if url := DOWNLOAD_URL_CACHE.get((share_code, file_id), ""):
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
    @app.router.route("/<path:name>", methods=["GET", "HEAD", "POST"])
    async def index(
        request: Request, 
        name: str = "", 
        share_code: str = "", 
        receive_code: str = "", 
        pickcode: str = "", 
        id: int = 0, 
        sha1: str = "", 
        refresh: bool = False, 
        app: str = "", 
    ):
        if share_code:
            if not receive_code:
                receive_code = await get_receive_code(share_code)
            elif len(receive_code) != 4:
                raise ValueError(f"bad receive_code: {receive_code!r}")
            if not id:
                if name:
                    id = await share_get_id_for_name(share_code, receive_code, name, refresh=refresh)
            if not id:
                raise FileNotFoundError(f"please specify id or name: share_code={share_code!r}")
            url = await get_share_downurl(share_code, receive_code, id, app=app)
        else:
            if pickcode:
                if not (len(pickcode) == 17 and pickcode.isalnum()):
                    raise ValueError(f"bad pickcode: {pickcode!r}")
            elif id:
                pickcode = await get_pickcode_to_id(id)
            elif sha1:
                if len(sha1) != 40 or sha1.strip(hexdigits):
                    raise ValueError(f"bad sha1: {sha1!r}")
                pickcode = await get_pickcode_for_sha1(sha1.upper())
            elif (query_bytes := request.url.query):
                query = query_bytes.decode("latin-1").lstrip("?&=")
                if (idx := query.find("&")) > -1:
                    query = query[:idx]
                if query:
                    if len(query) == 17 and query.isalnum():
                        pickcode = query
                    elif len(query) == 40 and not query.strip(hexdigits):
                        pickcode = await get_pickcode_for_sha1(query.upper())
                    elif not query.strip(digits):
                        pickcode = await get_pickcode_to_id(int(query))
                    else:
                        raise ValueError(f"bad query string: {query!r}")
            elif name:
                if len(name) == 17 and name.isalnum():
                    pickcode = name
                elif len(name) == 40 and not name.strip(hexdigits):
                    pickcode = await get_pickcode_for_sha1(name.upper())
                elif not name.strip(digits):
                    pickcode = await get_pickcode_to_id(int(name))
                else:
                    pickcode = await get_pickcode_for_name(name, refresh=refresh)
            if not pickcode:
                raise FileNotFoundError(f"not found: {str(request.url)!r}")
            user_agent = (request.get_first_header(b"User-agent") or b"").decode("latin-1")
            url = await get_downurl(pickcode.lower(), user_agent, app=app)

        return redirect(url)

    return app


if __name__ == "__main__":
    from pathlib import Path
    from uvicorn import run

    client = P115Client(Path("115-cookies.txt"), ensure_cookies=True, check_for_relogin=True)
    app = make_application(client, debug=True)
    run(app, host="0.0.0.0", port=8000, proxy_headers=True, forwarded_allow_ips="*")

