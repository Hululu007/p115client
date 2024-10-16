#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = ["wish_make", "wish_answer", "wish_list", "wish_aid_list", "wish_adopt"]

from collections.abc import Iterable

from p115client import check_response, P115Client


def wish_make(
    client: str | P115Client, 
    content: str = "随便许个愿", 
    size: int = 5, 
) -> str:
    """许愿树活动：创建许愿（许愿创建后需要等审核）

    :param client: 115 客户端或 cookies
    :param content: 许愿内容
    :param size: 答谢空间大小，单位是 GB

    :return: 许愿 id
    """
    if not isinstance(client, P115Client):
        client = P115Client(client)
    return check_response(client.act_xys_wish(
        {"rewardSpace": size, "content": content}
    ))["data"]["xys_id"]


def wish_answer(
    client: str | P115Client, 
    wish_id: str, 
    content: str = "帮你助个愿", 
    file_ids: int | str | Iterable[int | str] = "", 
) -> str:
    """许愿树活动：创建助愿（助愿创建后需要等审核）

    :param client: 115 客户端或 cookies
    :param wish_id: 许愿 id
    :param content: 助愿内容
    :param file_ids: 文件在你的网盘的 id，多个用逗号 "," 隔开

    :return: 助愿 id
    """
    if not isinstance(client, P115Client):
        client = P115Client(client)
    if not isinstance(file_ids, (int, str)):
        file_ids = ",".join(map(str, file_ids))
    check_response(client.act_xys_get_desire_info(wish_id))
    return check_response(
        client.act_xys_aid_desire({"id": wish_id, "content": content, "file_ids": file_ids}
    ))["data"]["aid_id"]


def wish_list(
    client: str | P115Client, 
    type: int = 0, 
) -> list[dict]:
    """许愿树活动：我的许愿列表

    :param client: 115 客户端或 cookies
    :param type: 类型
        - 0: 全部
        - 1: 进行中
        - 2: 已实现

    :return: 许愿列表
    """
    if not isinstance(client, P115Client):
        client = P115Client(client)
    payload: dict = {"type": type, "limit": 1000, "page": 1}
    ls = adds = check_response(client.act_xys_my_desire(payload))["data"]["list"]
    while len(adds) == 1000:
        payload["page"] += 1
        adds = check_response(client.act_xys_my_desire(payload))["data"]["list"]
        ls.extend(adds)
    return ls


def wish_aid_list(
    client: str | P115Client, 
    wish_id: str, 
) -> list[dict]:
    """许愿树活动：许愿的助愿列表

    :param client: 115 客户端或 cookies
    :param wish_id: 许愿 id

    :return: 助愿列表
    """
    if not isinstance(client, P115Client):
        client = P115Client(client)
    payload: dict = {"id": wish_id, "limit": 1000, "page": 1}
    ls = adds = check_response(client.act_xys_desire_aid_list(payload))["data"]["list"]
    while len(adds) == 1000:
        payload["page"] += 1
        adds = check_response(client.act_xys_desire_aid_list(payload))["data"]["list"]
        ls.extend(adds)
    return ls


def wish_adopt(
    client: str | P115Client, 
    wish_id: str, 
    aid_id: int | str, 
    to_cid: int = 0, 
) -> dict:
    """许愿树活动：采纳助愿

    :param client: 115 客户端或 cookies
    :param wish_id: 许愿 id
    :param aid_id: 助愿 id
    :param to_cid: 助愿的分享文件保存到你的网盘中目录的 id

    :return: 返回信息
    """
    if not isinstance(client, P115Client):
        client = P115Client(client)
    return check_response(client.act_xys_adopt({"did": wish_id, "aid": aid_id, "to_cid": to_cid}))

