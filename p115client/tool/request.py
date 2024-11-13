#!/usr/bin/env python3
# coding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = ["make_request"]
__doc__ = "自定义请求方法"

from collections.abc import Callable
from functools import partial
from http.cookiejar import CookieJar
from subprocess import run
from sys import executable


def make_request(
    package: str = "", 
    cookiejar: None | CookieJar = None, 
) -> None | Callable:
    match package:
        case "":
            return None
        case "httpx":
            from httpx import Client, Cookies, Limits
            from httpx_request import request_sync
            if cookiejar is None:
                cookies = None
            else:
                cookies = Cookies()
                cookies.jar = cookiejar
            return partial(request_sync, session=Client(cookies=cookies, limits=Limits(max_connections=128)))
        case "httpx_async":
            from httpx import AsyncClient, Cookies, Limits
            from httpx_request import request_async
            if cookiejar is None:
                cookies = None
            else:
                cookies = Cookies()
                cookies.jar = cookiejar
            return partial(request_async, session=AsyncClient(cookies=cookies, limits=Limits(max_connections=128)))
        case "requests":
            try:
                from requests import Session
                from requests_request import request as requests_request
            except ImportError:
                run([executable, "-m", "pip", "install", "-U", "requests", "requests_request"], check=True)
                from requests import Session
                from requests_request import request as requests_request
            session = Session()
            if cookiejar is not None:
                session.cookies.__dict__ = cookiejar.__dict__
            return partial(requests_request, session=session)
        case "urllib3":
            try:
                from urllib3.poolmanager import PoolManager
                from urllib3_request import request as urllib3_request
            except ImportError:
                run([executable, "-m", "pip", "install", "-U", "urllib3", "urllib3_request"], check=True)
                from urllib3.poolmanager import PoolManager
                from urllib3_request import request as urllib3_request
            return partial(urllib3_request, pool=PoolManager(128), cookies=cookiejar)
        case "urlopen":
            # TODO: 需要实现连接池，扩展 urllib.request.AbstractHTTPHandler
            try:
                from urlopen import request as urlopen_request
            except ImportError:
                run([executable, "-m", "pip", "install", "-U", "python-urlopen"], check=True)
                from urlopen import request as urlopen_request
            return partial(urlopen_request, cookies=cookiejar)
        case "aiohttp":
            # TODO: 需要实现 cookiejar 的包装类，扩展 aiohttp.cookiejar.CookieJar
            try:
                from aiohttp import ClientSession as AiohttpClientSession
                from aiohttp_client_request import request as aiohttp_request
            except ImportError:
                run([executable, "-m", "pip", "install", "-U", "aiohttp", "aiohttp_client_request"], check=True)
                from aiohttp import ClientSession as AiohttpClientSession
                from aiohttp_client_request import request as aiohttp_request
            return partial(aiohttp_request, session=AiohttpClientSession())
        case "blacksheep":
            # TODO: 需要实现 cookiejar 的包装类，扩展 blacksheep.client.cookies.CookieJar
            try:
                from blacksheep.client import ClientSession as BlacksheepClientSession
                from blacksheep_client_request import request as blacksheep_request
            except ImportError:
                run([executable, "-m", "pip", "install", "-U", "blacksheep", "blacksheep_client_request"], check=True)
                from blacksheep.client import ClientSession as BlacksheepClientSession
                from blacksheep_client_request import request as blacksheep_request
            return partial(blacksheep_request, session=BlacksheepClientSession())
        case _:
            raise ValueError(f"can't make request for {package!r}")

# TODO: 这个模块还未完成，所以不要使用

