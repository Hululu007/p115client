#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = ["iter_115_to_115"]
__doc__ = "这个模块提供了一些和上传有关的函数"

from collections.abc import AsyncIterator, Iterator
from itertools import dropwhile
from typing import overload, Literal

from concurrenttools import threadpool_map, taskgroup_map, Return
from iterutils import as_gen_step
from p115client import check_response, normalize_attr_simple, P115Client
from p115client.tool import iter_download_files, iter_files_with_path


@overload
def iter_115_to_115(
    from_client: P115Client, 
    to_client: P115Client, 
    from_cid: int = 0, 
    to_pid: int = 0, 
    max_workers: int = 8, 
    with_root: bool = True, 
    use_iter_files: bool = False, 
    *, 
    async_: Literal[False] = False, 
    **request_kwargs, 
) -> Iterator[dict]:
    ...
@overload
def iter_115_to_115(
    from_client: P115Client, 
    to_client: P115Client, 
    from_cid: int = 0, 
    to_pid: int = 0, 
    max_workers: int = 8, 
    with_root: bool = True, 
    use_iter_files: bool = False, 
    *, 
    async_: Literal[True], 
    **request_kwargs, 
) -> AsyncIterator[dict]:
    ...
def iter_115_to_115(
    from_client: P115Client, 
    to_client: P115Client, 
    from_cid: int = 0, 
    to_pid: int = 0, 
    max_workers: int = 8, 
    with_root: bool = True, 
    use_iter_files: bool = False, 
    async_: Literal[False, True] = False, 
    **request_kwargs, 
) -> Iterator[dict] | AsyncIterator[dict]:
    """从 115 传到 115

    :param from_client: 来源 115 客户端对象
    :param to_client: 去向 115 客户端对象
    :param from_cid: 来源 115 的目录 id
    :param to_pid: 去向 115 的父目录 id
    :param max_workers: 最大并发数
    :param with_root: 是否保留 `from_cid` 对应的目录名（如果为 False，则会少 1 级目录）
    :param use_iter_files: 如果为 True，则调用 iter_files_with_path，否则调用 iter_download_files
    :param async_: 是否异步
    :param request_kwargs: 其它请求参数

    :return: 迭代器，产生转移结果，有 3 种类型："good"、"fail" 和 "skip"
    """
    @as_gen_step(async_=async_)
    def upload(attr: dict, pid: int, /):
        @as_gen_step(async_=async_)
        def read_range_bytes_or_hash(sign_check: str, /):
            if attr["is_collect"]:
                url = yield from_client.download_url(
                    attr["pickcode"], 
                    use_web_api=True, 
                    async_=async_, 
                    **request_kwargs, 
                )
            else:
                url = yield from_client.download_url(
                    attr["pickcode"], 
                    app="android", 
                    async_=async_, 
                    **request_kwargs, 
                )
            return from_client.request(
                url, 
                headers=dict(url["headers"], Range="bytes="+sign_check), 
                parse=False, 
                async_=async_, 
                **request_kwargs, 
            )
        try:
            if not use_iter_files:
                resp = yield from_client.fs_supervision(
                    attr["pickcode"], 
                    async_=async_, 
                    **request_kwargs, 
                )
                check_response(resp)
                info = resp["data"]
                attr.update(
                    id=int(info["file_id"]), 
                    name=info["file_name"], 
                    sha1=info["file_sha1"], 
                    size=int(info["file_size"]), 
                    is_collect=int(info["is_collect"]), 
                    file_type=int(info["file_type"]), 
                )
                if attr["is_collect"] and attr["size"] >= 1024 * 1024 * 115:
                    return {"type": "skip", "attr": attr, "resp": None}
            resp = yield to_client.upload_file_init(
                filename=attr["name"], 
                filesize=attr["size"], 
                filesha1=attr["sha1"], 
                pid=pid, 
                read_range_bytes_or_hash=read_range_bytes_or_hash, 
                base_url=True, 
                async_=async_, 
                **request_kwargs, 
            )
            check_response(resp)
            if resp.get("statuscode"):
                return {"type": "fail", "attr": attr, "resp": resp}
            else:
                return {"type": "good", "attr": attr, "resp": resp}
        except BaseException as e:
            if isinstance(e, OSError) and len(e.args) == 2 and isinstance(e.args[1], dict):
                return {"type": "fail", "attr": attr, "resp": e.args[1], "exc": e}
            else:
                return {"type": "fail", "attr": attr, "resp": None, "exc": e}
    key_of_id = "id" if with_root else "parent_id"
    @as_gen_step(async_=async_)
    def get_pid(attr: dict, /):
        if use_iter_files:
            if attr["is_collect"] and attr["size"] >= 1024 * 1024 * 115:
                return Return({"type": "skip", "attr": attr, "resp": None})
            if from_cid:
                dir_ = "/".join(a["name"] for a in dropwhile(
                    lambda a: a[key_of_id] != from_cid, 
                    attr["ancestors"][1:-1], 
                ))
            else:
                dir_ = "/".join(a["name"] for a in attr["ancestors"][1:-1])
        else:
            if from_cid:
                dir_ = "/".join(a["name"] for a in dropwhile(
                    lambda a: a[key_of_id] != from_cid, 
                    attr["dir_ancestors"][1:], 
                ))
            else:
                dir_ = attr["dirname"][1:]
        if dir_ in dir_to_cid:
            return dir_to_cid[dir_]
        else:
            resp = yield to_client.fs_makedirs_app(
                dir_, 
                to_pid, 
                async_=async_, 
                **request_kwargs, 
            )
            check_response(resp)
            pid = dir_to_cid[dir_] = resp["cid"]
            return pid
    dir_to_cid = {"": 0}
    if use_iter_files:
        it = iter_files_with_path(
            from_client, 
            from_cid, 
            normalize_attr=normalize_attr_simple, 
            async_=async_, 
            **request_kwargs, 
        )
    else:
        it = iter_download_files(
            from_client, 
            from_cid, 
            async_=async_, 
            **request_kwargs, 
        )
    if async_:
        return taskgroup_map(upload, it, arg_func=get_pid, max_workers=max_workers)
    else:
        return threadpool_map(upload, it, arg_func=get_pid, max_workers=max_workers)

