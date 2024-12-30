#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = [
    "generate_cookies_factory", "generate_client_factory", "cookies_pool", "client_pool", 
    "call_wrap_with_cookies_pool", 
]
__doc__ = "这个模块提供了一些和 cookies 池有关的函数"

from asyncio import Lock as AsyncLock
from collections import deque
from collections.abc import Callable, Iterable
from functools import partial, update_wrapper
from threading import Lock
from time import time
from typing import Any

from iterutils import run_gen_step
from p115client import check_response, P115Client
from p115client.const import APP_TO_SSOENT
from p115client.exception import P115OSError, AuthenticationError


def get_status(e: BaseException, /) -> None | int:
    status = (
        getattr(e, "status", None) or 
        getattr(e, "code", None) or 
        getattr(e, "status_code", None)
    )
    if status is None and hasattr(e, "response"):
        response = e.response
        status = (
            getattr(response, "status", None) or 
            getattr(response, "code", None) or 
            getattr(response, "status_code", None)
        )
    return status


def is_timeouterror(exc: Exception) -> bool:
    exctype = type(exc)
    for exctype in exctype.mro():
        if exctype is Exception:
            break
        if "Timeout" in exctype.__name__:
            return True
    return False


def generate_cookies_factory(
    client: str | P115Client, 
    app: str = "", 
    **request_kwargs, 
) -> Callable:
    """利用一个已登录设备的 cookies，产生另一个设备的若干 cookies

    :param client: 115 客户端或 cookies
    :param app: 自动扫码后绑定的 app
    :param request_kwargs: 其它请求参数

    :return: 函数，调用以返回一个 cookies
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if app:
        if APP_TO_SSOENT.get(app) == client.login_ssoent:
            raise ValueError("same login device will cause conflicts")
    else:
        app = "tv" if client.login_ssoent == "R2" else "alipaymini"
    login = client.login_with_app
    def make_cookies(async_: bool = False):
        def call():
            while True:
                try:
                    resp = yield login(app, async_=async_, **request_kwargs) # type: ignore
                except Exception as e:
                    if not is_timeouterror(e):
                        raise
                check_response(resp)
                return "; ".join(f"{k}={v}" for k, v in resp["data"]["cookie"].items())
        return run_gen_step(call, async_=async_)
    return make_cookies


def generate_client_factory(
    client: str | P115Client, 
    app: str = "", 
    **request_kwargs, 
) -> Callable:
    """利用一个已登录设备的 client，产生另一个设备的若干 client

    :param client: 115 客户端或 cookies
    :param app: 自动扫码后绑定的 app
    :param request_kwargs: 其它请求参数

    :return: 函数，调用以返回一个 client
    """
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if app:
        if APP_TO_SSOENT.get(app) == client.login_ssoent:
            raise ValueError("same login device will cause conflicts")
    else:
        app = "tv" if client.login_ssoent == "R2" else "alipaymini"
    login = client.login_another_app
    def make_client(async_: bool = False):
        def call():
            while True:
                try:
                    return (yield login(app, async_=async_, **request_kwargs)) # type: ignore
                except Exception as e:
                    if not is_timeouterror(e):
                        raise
        return run_gen_step(call, async_=async_)
    return make_client


def make_pool(
    generate_factory: Callable, 
    initial_values: Iterable = (), 
    cooldown_time: int | float = 1, 
    lock: bool = True, 
    **request_kwargs, 
) -> Callable:
    """值の池

    :param generate_factory: 产生值的工厂函数
    :param initial_values: 一组初始值
    :param cooldown_time: cookies 的冷却时间
    :param lock: 是否需要锁
    :param request_kwargs: 其它请求参数

    :return: 返回一个函数，调用后返回一个元组，包含 值 和 一个调用以在完成后把 值 返还池中
    """
    generate = generate_factory(**request_kwargs)
    dq: deque[tuple[Any, float]] = deque(((a, time()) for a in initial_values))
    push, pop = dq.append, dq.popleft
    def get_value(async_: bool = False):
        def call():
            if dq and dq[0][1] + cooldown_time < time():
                value = pop()[0]
            elif async_:
                value = yield generate(async_=True)
            else:
                value = generate()
            return value, partial(push, (value, time()))
        return run_gen_step(call, async_=async_)
    if not lock:
        setattr(get_value, "deque", dq)
        return get_value
    lock_sync = Lock()
    lock_async = AsyncLock()
    def locked_get_value(async_: bool = False):
        if async_:
            async def async_locked_get_value():
                async with lock_async:
                    return await get_value(async_=True)
            return async_locked_get_value
        else:
            def locked_get_value():
                with lock_sync:
                    return get_value()
            return locked_get_value
    setattr(locked_get_value, "deque", dq)
    return locked_get_value


def cookies_pool(
    client: str | P115Client, 
    app: None | str = None, 
    initial_values: Iterable[str] = (), 
    cooldown_time: int | float = 1, 
    lock: bool = False, 
    **request_kwargs, 
) -> Callable:
    """cookies 池

    :param client: 115 客户端或 cookies
    :param app: 自动扫码后绑定的 app
    :param initial_values: 一组初始值
    :param cooldown_time: cookies 的冷却时间
    :param lock: 锁，如果不需要锁，传入 False
    :param request_kwargs: 其它请求参数

    :return: 返回一个函数，调用后返回一个元组，包含 cookies 和 一个调用以在完成后把 cookies 返还池中
    """
    return make_pool(
        generate_cookies_factory, 
        client=client, 
        app=app, 
        initial_values=initial_values, 
        cooldown_time=cooldown_time, 
        lock=lock, 
        **request_kwargs, 
    )


def client_pool(
    client: str | P115Client, 
    app: None | str = None, 
    initial_values: Iterable[P115Client] = (), 
    cooldown_time: int | float = 1, 
    lock: bool = False, 
    **request_kwargs, 
) -> Callable:
    """client 池

    :param client: 115 客户端或 cookies
    :param app: 自动扫码后绑定的 app
    :param initial_values: 一组初始值
    :param cooldown_time: cookies 的冷却时间
    :param lock: 锁，如果不需要锁，传入 False
    :param request_kwargs: 其它请求参数

    :return: 返回一个函数，调用后返回一个元组，包含 client 和 一个调用以在完成后把 client 返还池中
    """
    return make_pool(
        generate_client_factory, 
        client=client, 
        app=app, 
        initial_values=initial_values, 
        cooldown_time=cooldown_time, 
        lock=lock, 
        **request_kwargs, 
    )


def call_wrap_with_cookies_pool(
    get_cookies: Callable, 
    /, 
    func: Callable = P115Client("").fs_files, 
    check: bool | Callable = True, 
) -> Callable:
    """包装函数，使得用 cookies 池执行请求

    :param get_cookies: 获取 cookies 的函数
    :param func: 执行请求的函数
    """
    def wrapper(*args, headers=None, async_: bool = False, **kwds):
        def call():
            nonlocal headers
            if async_:
                cookies, revert = yield get_cookies(async_=True)
            else:
                cookies, revert = get_cookies()
            while True:
                if headers:
                    headers = dict(headers, Cookie=cookies)
                else:
                    headers = {"Cookie": cookies}
                try:
                    if async_:
                        resp = yield func(*args, headers=headers, async_=True, **kwds)
                    else:
                        resp = func(*args, headers=headers, **kwds)
                    if check:
                        if check is True:
                            check_response(resp)
                        else:
                            check(resp)
                    revert()
                    return resp
                except BaseException as e:
                    if isinstance(e, P115OSError) and e.args[0]["errno"] == 40101004:
                        raise
                    elif isinstance(e, AuthenticationError) or get_status(e) == 405:
                        if async_:
                            cookies, revert = yield get_cookies(async_=True)
                        else:
                            cookies, revert = get_cookies()
                        continue
                    revert()
                    raise
        return run_gen_step(call, async_=async_)
    return update_wrapper(wrapper, func)

# TODO: 需要完整的类型签名
# TODO: 池子可以被导出，下次继续使用
# TODO: 支持多个不同设备的 cookies 组成池，以及刷新（自己刷新自己，或者由另一个 cookies 辅助刷新）
