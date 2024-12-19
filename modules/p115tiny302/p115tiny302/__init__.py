#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 3)
__all__ = ["make_application"]
__license__ = "GPLv3 <https://www.gnu.org/licenses/gpl-3.0.txt>"

from collections.abc import Mapping, MutableMapping
from itertools import cycle
from string import digits, hexdigits
from time import time
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit

from blacksheep import redirect, text, Application, Request, Router
from blacksheep.client import ClientSession
from blacksheep.contents import FormContent
from blacksheep.server.compression import use_gzip_compression
from blacksheep.server.remotes.forwarding import ForwardedHeadersMiddleware
from cachedict import LRUDict, TTLDict
from orjson import loads
from p115rsacipher import encrypt, decrypt


get_webapi_url: Final = cycle(("http://anxia.com/webapi", "http://v.anxia.com/webapi", "http://web.api.115.com")).__next__
get_proapi_url: Final = cycle(("http://pro.api.115.com", "http://pro.api.115.com", "http://pro.api.115.com", "http://pro.api.115.com", "https://proapi.115.com")).__next__


def get_first(m: Mapping, *keys, default=None):
    for k in keys:
        if k in m:
            return m[k]
    return default


def make_application(cookies: str, debug: bool = False) -> Application:
    ID_TO_PICKCODE: MutableMapping[int, str] = LRUDict(65536)
    SHA1_TO_PICKCODE: MutableMapping[str, str] = LRUDict(65536)
    NAME_TO_PICKCODE: MutableMapping[str, str] = LRUDict(65536)
    SHARE_NAME_TO_ID: MutableMapping[tuple[str, str], int] = LRUDict(65536)
    DOWNLOAD_URL_CACHE: MutableMapping[str | tuple[str, int], str] = TTLDict(65536, 3600)
    DOWNLOAD_URL_CACHE2: MutableMapping[tuple[str, str], tuple[str, int]] = LRUDict(1024)
    RECEIVE_CODE_MAP: dict[str, str] = {}

    app = Application(router=Router(), show_error_details=debug)
    use_gzip_compression(app)
    client: ClientSession

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

    @app.lifespan
    async def register_http_client():
        nonlocal client
        async with ClientSession(default_headers={"Cookie": cookies}) as client:
            app.services.register(ClientSession, instance=client)
            yield

    async def get_pickcode_to_id(id: int) -> str:
        pickcode = ID_TO_PICKCODE.get(id, "")
        if pickcode:
            return pickcode
        resp = await client.get(f"{get_webapi_url()}/files/file?file_id={id}")
        text = await resp.text()
        json = loads(text)
        if not (json and json["state"]):
            raise FileNotFoundError(text)
        info = json["data"][0]
        pickcode = ID_TO_PICKCODE[id] = info["pick_code"]
        return pickcode

    async def get_pickcode_for_sha1(sha1: str) -> str:
        pickcode = SHA1_TO_PICKCODE.get(sha1, "")
        if pickcode:
            return pickcode
        resp = await client.get(f"{get_webapi_url()}/files/shasearch?sha1={sha1}")
        text = await resp.text()
        json = loads(text)
        if not (json and json["state"]):
            raise FileNotFoundError(text)
        info = json["data"]
        pickcode = SHA1_TO_PICKCODE[sha1] = info["pick_code"]
        return pickcode

    async def get_pickcode_for_name(name: str, refresh: bool = False) -> str:
        if not refresh:
            pickcode = NAME_TO_PICKCODE.get(name, "")
            if pickcode:
                return pickcode
        api = f"{get_webapi_url()}/files/search"
        payload = {"search_value": name, "limit": 1, "type": 99}
        suffix = name.rpartition(".")[-1]
        if suffix.isalnum():
            payload["suffix"] = suffix
        resp = await client.get(f"{api}?{urlencode(payload)}")
        text = await resp.text()
        json = loads(text)
        if get_first(json, "errno", "errNo") == 20021:
            payload.pop("suffix")
            resp = await client.get(f"{api}?{urlencode(payload)}")
            text = await resp.text()
            json = loads(text)
        if not json["state"] or not json["count"]:
            raise FileNotFoundError(text)
        info = json["data"][0]
        if info["n"] != name:
            raise FileNotFoundError(f"name not found: {name!r}")
        pickcode = NAME_TO_PICKCODE[name] = info["pc"]
        return pickcode

    async def share_get_id_for_name(
        share_code: str, 
        receive_code: str, 
        name: str, 
        refresh: bool = False, 
    ) -> int:
        if not refresh:
            id = SHARE_NAME_TO_ID.get((share_code, name), 0)
            if id:
                return id
        api = f"{get_webapi_url()}/share/search"
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
        resp = await client.get(f"{api}?{urlencode(payload)}")
        text = await resp.text()
        json = loads(text)
        if get_first(json, "errno", "errNo") == 20021:
            payload.pop("suffix")
            resp = await client.get(f"{api}?{urlencode(payload)}")
            text = await resp.text()
            json = loads(text)
        if not json["state"] or not json["data"]["count"]:
            raise FileNotFoundError(text)
        info = json["data"]["list"][0]
        if info["n"] != name:
            raise FileNotFoundError(f"name not found: {name!r}")
        id = SHARE_NAME_TO_ID[(share_code, name)] = int(info["fid"])
        return id

    async def get_downurl(
        pickcode: str, 
        user_agent: str = "", 
    ) -> str:
        if url := DOWNLOAD_URL_CACHE.get(pickcode, ""):
            return url
        elif pairs := DOWNLOAD_URL_CACHE2.get((pickcode, user_agent)):
            url, expire_ts = pairs
            if expire_ts >= time():
                return url
            DOWNLOAD_URL_CACHE2.pop((pickcode, user_agent))
        resp = await client.post(
            f"{get_proapi_url()}/android/2.0/ufile/download", 
            content=FormContent([("data", encrypt(b'{"pick_code":"%s"}' % bytes(pickcode, "ascii")).decode("utf-8"))]), 
            headers={"User-Agent": user_agent}, 
        )
        text = await resp.text()
        json = loads(text)
        if not json["state"]:
            raise OSError(text)
        url = loads(decrypt(json["data"]))["url"]
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
    ):
        if url := DOWNLOAD_URL_CACHE.get((share_code, file_id), ""):
            return url
        payload = {"share_code": share_code, "receive_code": receive_code, "file_id": file_id}
        resp = await client.get(f"{get_proapi_url()}/android/2.0/share/downurl?{urlencode(payload)}")
        text = await resp.text()
        json = loads(text)
        if not json["state"]:
            if json.get("errno") == 4100008 and RECEIVE_CODE_MAP.pop(share_code, None):
                receive_code = await get_receive_code(share_code)
                return await get_share_downurl(share_code, receive_code, file_id)
            raise OSError(text)
        url_info = json["data"]["url"]
        if not url_info:
            raise FileNotFoundError(text)
        url = url_info["url"]
        if "&c=0&f=&" in url:
            DOWNLOAD_URL_CACHE[(share_code, file_id)] = url
        return url

    async def get_receive_code(share_code: str) -> str:
        receive_code = RECEIVE_CODE_MAP.get(share_code, "")
        if receive_code:
            return receive_code
        resp = await client.get(f"{get_webapi_url()}/share/shareinfo?share_code={share_code}")
        text = await resp.text()
        json = loads(text)
        if not json["state"]:
            raise FileNotFoundError(text)
        receive_code = RECEIVE_CODE_MAP[share_code] = json["data"]["receive_code"]
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
            url = await get_share_downurl(share_code, receive_code, id)
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
            else:
                query = request.url.query
                if query:
                    query_string = query.decode("latin-1")
                    if len(query_string) == 17 and query_string.isalnum():
                        pickcode = query_string
                    elif len(query_string) == 40 and not query_string.strip(hexdigits):
                        pickcode = await get_pickcode_for_sha1(query_string.upper())
                    elif not query_string.strip(digits):
                        pickcode = await get_pickcode_to_id(int(query_string))
                    else:
                        raise ValueError(f"bad query string: {query_string!r}")
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
            url = await get_downurl(pickcode.lower(), user_agent)

        return redirect(url)

    return app


if __name__ == "__main__":
    from uvicorn import run

    cookies = open("115-cookies.txt", encoding="latin-1").read().strip()
    app = make_application(cookies, debug=True)
    run(app, host="0.0.0.0", port=8000, proxy_headers=True, forwarded_allow_ips="*")

