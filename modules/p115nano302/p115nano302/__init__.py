#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 7)
__all__ = ["make_application"]
__license__ = "GPLv3 <https://www.gnu.org/licenses/gpl-3.0.txt>"

from collections.abc import Mapping
from hashlib import sha1 as calc_sha1
from itertools import cycle
from re import compile as re_compile
from string import digits, hexdigits
from time import time
from typing import Final
from urllib.parse import parse_qsl, urlencode, unquote, urlsplit

from blacksheep import json, redirect, text, Application, FromJSON, Request, Router
from blacksheep.client import ClientSession
from blacksheep.contents import FormContent
from blacksheep.server.remotes.forwarding import ForwardedHeadersMiddleware
from cachedict import LRUDict, TTLDict
from orjson import dumps, loads
from p115rsacipher import encrypt, decrypt


CRE_COOKIES_UID_search: Final = re_compile(r"(?<=\bUID=)[^\s;]+").search
CRE_name_search: Final = re_compile(r"[^&=]+(?=&|$)").match
get_webapi_url: Final = cycle(("http://anxia.com/webapi", "http://v.anxia.com/webapi", "http://web.api.115.com", "http://webapi.115.com")).__next__


def get_first(m: Mapping, *keys, default=None):
    for k in keys:
        if k in m:
            return m[k]
    return default


def get_user_id_from_cookies(cookies: str, /) -> int:
    match = CRE_COOKIES_UID_search(cookies)
    if match is None:
        return 0
    return int(match[0].partition("_")[0])


def make_application(
    cookies: str, 
    debug: bool = False, 
    cache_size: int = 65536, 
    password: str = "", 
    token: str = "", 
) -> Application:
    ID_TO_PICKCODE:   LRUDict[tuple[int, int], str] = LRUDict(cache_size)
    SHA1_TO_PICKCODE: LRUDict[tuple[int, str], str] = LRUDict(cache_size)
    NAME_TO_PICKCODE: LRUDict[tuple[int, str], str] = LRUDict(cache_size)
    SHARE_NAME_TO_ID: LRUDict[tuple[str, str], int] = LRUDict(cache_size)
    DOWNLOAD_URL_CACHE: TTLDict[tuple[int, str] | tuple[str, int], str] = TTLDict(cache_size, 3600)
    DOWNLOAD_URL_CACHE2: LRUDict[tuple[int, str, str], tuple[str, int]] = LRUDict(1024)
    RECEIVE_CODE_MAP: dict[str, str] = {}

    PASSWORD = password
    d_cookies = {ick: ck for ck in cookies.split("\n") if (ick := get_user_id_from_cookies(ck))}
    app = Application(router=Router(), show_error_details=debug)
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
            msg = f"{type(exc).__qualname__}: {exc}"
            if isinstance(exc, (KeyError, ValueError)):
                return text(msg, 400)
            elif isinstance(exc, FileNotFoundError):
                return text(msg, 404)
            elif isinstance(exc, OSError):
                return text(msg, 503)
            else:
                return text(msg, 500)

    @app.on_middlewares_configuration
    def configure_forwarded_headers(app: Application):
        app.middlewares.insert(0, ForwardedHeadersMiddleware(accept_only_proxied_requests=False))

    @app.lifespan
    async def register_http_client():
        nonlocal client
        async with ClientSession(default_headers={"Cookie": next(iter(d_cookies.values()))}) as client:
            app.services.register(ClientSession, instance=client)
            yield

    async def get_pickcode_to_id(id: int, user_id: int = 0) -> str:
        if user_id:
            cookies = d_cookies[user_id]
        else:
            user_id, cookies = next(iter(d_cookies.items()))
        if pickcode := ID_TO_PICKCODE.get((user_id, id), ""):
            return pickcode
        resp = await client.get(f"{get_webapi_url()}/files/file?file_id={id}", headers={"Cookie": cookies})
        text = await resp.text()
        json = loads(text)
        if not (json and json["state"]):
            raise FileNotFoundError(text)
        pickcode = ID_TO_PICKCODE[(user_id, id)] = json["data"][0]["pick_code"]
        return pickcode

    async def get_pickcode_for_sha1(sha1: str, user_id: int = 0) -> str:
        if user_id:
            cookies = d_cookies[user_id]
        else:
            user_id, cookies = next(iter(d_cookies.items()))
        if pickcode := SHA1_TO_PICKCODE.get((user_id, sha1), ""):
            return pickcode
        resp = await client.get(f"{get_webapi_url()}/files/shasearch?sha1={sha1}", headers={"Cookie": cookies})
        text = await resp.text()
        json = loads(text)
        if not (json and json["state"]):
            raise FileNotFoundError(text)
        pickcode = SHA1_TO_PICKCODE[(user_id, sha1)] = json["data"]["pick_code"]
        return pickcode

    async def get_pickcode_for_name(name: str, user_id: int = 0, refresh: bool = False) -> str:
        if user_id:
            cookies = d_cookies[user_id]
        else:
            user_id, cookies = next(iter(d_cookies.items()))
        if not refresh:
            if pickcode := NAME_TO_PICKCODE.get((user_id, name), ""):
                return pickcode
        api = f"{get_webapi_url()}/files/search"
        payload = {"search_value": name, "limit": 1, "type": 99}
        suffix = name.rpartition(".")[-1]
        if suffix.isalnum():
            payload["suffix"] = suffix
        resp = await client.get(f"{api}?{urlencode(payload)}", headers={"Cookie": cookies})
        text = await resp.text()
        json = loads(text)
        if get_first(json, "errno", "errNo") == 20021:
            payload.pop("suffix")
            resp = await client.get(f"{api}?{urlencode(payload)}", headers={"Cookie": cookies})
            text = await resp.text()
            json = loads(text)
        if not json["state"] or not json["count"]:
            raise FileNotFoundError(text)
        info = json["data"][0]
        if info["n"] != name:
            raise FileNotFoundError(f"name not found: {name!r}")
        pickcode = NAME_TO_PICKCODE[(user_id, name)] = info["pc"]
        return pickcode

    async def share_get_id_for_name(
        share_code: str, 
        receive_code: str, 
        name: str, 
        user_id: int = 0, 
        refresh: bool = False, 
    ) -> int:
        if user_id:
            cookies = d_cookies[user_id]
        else:
            user_id, cookies = next(iter(d_cookies.items()))
        if not refresh and (id := SHARE_NAME_TO_ID.get((share_code, name), 0)):
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
        resp = await client.get(f"{api}?{urlencode(payload)}", headers={"Cookie": cookies})
        text = await resp.text()
        json = loads(text)
        if get_first(json, "errno", "errNo") == 20021:
            payload.pop("suffix")
            resp = await client.get(f"{api}?{urlencode(payload)}", headers={"Cookie": cookies})
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
        app: str = "android", 
        user_id: int = 0, 
    ) -> str:
        if user_id:
            cookies = d_cookies[user_id]
        else:
            user_id, cookies = next(iter(d_cookies.items()))
        if url := DOWNLOAD_URL_CACHE.get((user_id, pickcode), ""):
            return url
        elif pairs := DOWNLOAD_URL_CACHE2.get((user_id, pickcode, user_agent)):
            url, expire_ts = pairs
            if expire_ts >= time():
                return url
            DOWNLOAD_URL_CACHE2.pop((user_id, pickcode, user_agent))
        if app == "chrome":
            resp = await client.post(
                "http://pro.api.115.com/app/chrome/downurl", 
                content=FormContent([("data", encrypt(f'{{"pickcode":"{pickcode}"}}').decode("utf-8"))]), 
                headers={"User-Agent": user_agent, "Cookie": cookies}, 
            )
        else:
            resp = await client.post(
                f"http://pro.api.115.com/{app or 'android'}/2.0/ufile/download", 
                content=FormContent([("data", encrypt(f'{{"pick_code":"{pickcode}"}}').decode("utf-8"))]), 
                headers={"User-Agent": user_agent, "Cookie": cookies}, 
            )
        text = await resp.text()
        json = loads(text)
        if not json["state"]:
            raise OSError(text)
        if app == "chrome":
            data = json["data"] = loads(decrypt(json["data"]))
            url_info = next(iter(data.values()))["url"]
            if not url_info:
                raise FileNotFoundError(dumps(json).decode("utf-8"))
            url = url_info["url"]
        else:
            url = loads(decrypt(json["data"]))["url"]
        if "&c=0&f=&" in url:
            DOWNLOAD_URL_CACHE[(user_id, pickcode)] = url
        elif "&c=0&f=1&" in url:
            expire_ts = int(next(v for k, v in parse_qsl(urlsplit(url).query) if k == "t"))
            DOWNLOAD_URL_CACHE2[(user_id, pickcode, user_agent)] = (url, expire_ts - 60)
        return url

    async def get_share_downurl(
        share_code: str, 
        receive_code: str, 
        file_id: int, 
        app: str = "android", 
        user_id: int = 0, 
    ):
        if user_id:
            cookies = d_cookies[user_id]
        else:
            user_id, cookies = next(iter(d_cookies.items()))
        if url := DOWNLOAD_URL_CACHE.get((share_code, file_id), ""):
            return url
        payload = {"share_code": share_code, "receive_code": receive_code, "file_id": file_id}
        if app:
            resp = await client.get(
                f"http://pro.api.115.com/{app}/2.0/share/downurl?{urlencode(payload)}", 
                headers={"Cookie": cookies}, 
            )
        else:
            resp = await client.post(
                "http://pro.api.115.com/app/share/downurl", 
                content=FormContent([("data", encrypt(dumps(payload)).decode("utf-8"))]), 
                headers={"Cookie": cookies}, 
            )
        text = await resp.text()
        json = loads(text)
        if not json["state"]:
            if json.get("errno") == 4100008 and RECEIVE_CODE_MAP.pop(share_code, None):
                receive_code = await get_receive_code(share_code, user_id=user_id)
                return await get_share_downurl(share_code, receive_code, file_id, app=app, user_id=user_id)
            raise OSError(text)
        if app:
            data = json["data"]
        else:
            data = loads(decrypt(json["data"]))
        if not (data and (url_info := data["url"])):
            raise FileNotFoundError(text)
        url = url_info["url"]
        if "&c=0&f=&" in url:
            DOWNLOAD_URL_CACHE[(share_code, file_id)] = url
        return url

    async def get_receive_code(share_code: str, user_id: int = 0) -> str:
        if user_id:
            cookies = d_cookies[user_id]
        else:
            user_id, cookies = next(iter(d_cookies.items()))
        if receive_code := RECEIVE_CODE_MAP.get(share_code, ""):
            return receive_code
        resp = await client.get(
            f"{get_webapi_url()}/share/shareinfo?share_code={share_code}", 
            headers={"Cookie": cookies}, 
        )
        text = await resp.text()
        json = loads(text)
        if not json["state"]:
            raise FileNotFoundError(text)
        receive_code = RECEIVE_CODE_MAP[share_code] = json["data"]["receive_code"]
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
        user_id: int = 0, 
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
        name = name or name2
        if str(request.url) == "/service-worker.js":
            raise FileNotFoundError
        if share_code:
            if resp := check_sign(id if id else name):
                return resp
            if not receive_code:
                receive_code = await get_receive_code(share_code, user_id=user_id)
            elif len(receive_code) != 4:
                raise ValueError(f"bad receive_code: {receive_code!r}")
            if not id:
                if name:
                    id = await share_get_id_for_name(share_code, receive_code, name, user_id=user_id, refresh=refresh)
            if not id:
                raise FileNotFoundError(f"please specify id or name: share_code={share_code!r}")
            url = await get_share_downurl(share_code, receive_code, id, app=app, user_id=user_id)
        else:
            if pickcode:
                if resp := check_sign(pickcode):
                    return resp
                if not (len(pickcode) == 17 and pickcode.isalnum()):
                    raise ValueError(f"bad pickcode: {pickcode!r}")
            elif id:
                if resp := check_sign(id):
                    return resp
                pickcode = await get_pickcode_to_id(id, user_id=user_id)
            elif sha1:
                if resp := check_sign(sha1):
                    return resp
                if len(sha1) != 40 or sha1.strip(hexdigits):
                    raise ValueError(f"bad sha1: {sha1!r}")
                pickcode = await get_pickcode_for_sha1(sha1.upper(), user_id=user_id)
            else:
                if match := CRE_name_search(unquote(request.url.query or b"")):
                    name = match[0]
                if name:
                    if resp := check_sign(name):
                        return resp
                    if len(name) == 17 and name.isalnum():
                        pickcode = name.lower()
                    elif not name.strip(digits):
                        pickcode = await get_pickcode_to_id(int(name), user_id=user_id)
                    elif len(name) == 40 and not name.strip(hexdigits):
                        pickcode = await get_pickcode_for_sha1(name.upper(), user_id=user_id)
                    else:
                        pickcode = await get_pickcode_for_name(name, user_id=user_id, refresh=refresh)
            if not pickcode:
                raise FileNotFoundError(f"not found: {str(request.url)!r}")
            user_agent = (request.get_first_header(b"User-agent") or b"").decode("latin-1")
            url = await get_downurl(pickcode.lower(), user_agent, app=app, user_id=user_id)

        return redirect(url)

    if PASSWORD:
        @app.router.route("/%3Ccookies", methods=["POST"])
        async def set_cookies(request: Request, password: str = "", body: None | FromJSON[dict] = None):
            """更新 cookies

            :param password: 口令
            :param body: 请求体为 json 格式 <code>{"cookies"&colon; "新的 cookies"}</code>
            """
            if PASSWORD != password:
                return json({"state": False, "message": "password does not match"}, 401)
            if body and (cookies := body.value.get("cookies")):
                try:
                    d_cookies.update((ick, ck) for ck in cookies.split("\n") if (ick := get_user_id_from_cookies(ck)))
                    return json({"state": True, "message": "ok"})
                except Exception as e:
                    return json({"state": False, "message": f"{type(e).__qualname__}: {e}"})
            return json({"state": True, "message": "skip"})

    return app


if __name__ == "__main__":
    from uvicorn import run

    cookies = open("115-cookies.txt", encoding="latin-1").read().strip()
    app = make_application(cookies, debug=True)
    run(app, host="0.0.0.0", port=8000, proxy_headers=True, forwarded_allow_ips="*")

