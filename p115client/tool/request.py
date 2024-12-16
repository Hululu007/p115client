#!/usr/bin/env python3
# coding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = ["make_request"]
__doc__ = "自定义请求函数"

from collections.abc import Callable
from functools import partial
from http.cookiejar import CookieJar
from subprocess import run
from sys import executable, modules
from typing import Literal


def make_request(
    module: Literal["", "httpx", "httpx_async", "requests", "urllib3", "urlopen", "aiohttp", "blacksheep"] = "", 
    cookiejar: None | CookieJar = None, 
) -> None | Callable:
    """创建可更新 cookies 的请求函数

    :param module: 指定所用的模块
    :param cookiejar: cookies 罐，用来存储 cookies。如果为 None，则 "urllib3" 和 "urlopen" 并不会保存 cookies，其它 `module` 则有自己的 cookies 保存机制

    :return: 一个请求函数，可供 `P115Client.request` 使用，所以也可传给所有基于前者的 `P115Client` 的方法，作为 `request` 参数
    """
    match module:
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
                from urllib3_request import __version__
                if __version__ < (0, 0, 8):
                    modules.pop("urllib3_request", None)
                    raise ImportError
                from urllib3.poolmanager import PoolManager
                from urllib3_request import request as urllib3_request
            except ImportError:
                run([executable, "-m", "pip", "install", "-U", "urllib3", "urllib3_request>=0.0.8"], check=True)
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
            try:
                from aiohttp_client_request import __version__
                if __version__ < (0, 0, 4):
                    modules.pop("aiohttp_client_request", None)
                    raise ImportError
                from aiohttp import ClientSession as AiohttpClientSession
                from aiohttp_client_request import request as aiohttp_request
            except ImportError:
                run([executable, "-m", "pip", "install", "-U", "aiohttp", "aiohttp_client_request>=0.0.4"], check=True)
                from aiohttp import ClientSession as AiohttpClientSession
                from aiohttp_client_request import request as aiohttp_request
            return partial(aiohttp_request, session=AiohttpClientSession(), cookies=cookiejar)
        case "blacksheep":
            try:
                from blacksheep_client_request import __version__
                if __version__ < (0, 0, 4):
                    modules.pop("blacksheep_client_request", None)
                    raise ImportError
                from blacksheep.client import ClientSession as BlacksheepClientSession
                from blacksheep_client_request import request as blacksheep_request
            except ImportError:
                run([executable, "-m", "pip", "install", "-U", "blacksheep", "blacksheep_client_request>=0.0.4"], check=True)
                from blacksheep.client import ClientSession as BlacksheepClientSession
                from blacksheep_client_request import request as blacksheep_request
            return partial(blacksheep_request, session=BlacksheepClientSession(), cookies=cookiejar)
        case _:
            raise ValueError(f"can't make request for {module!r}")

