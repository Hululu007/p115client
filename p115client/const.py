#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all = ["AVAILABLE_APPS", "APP_TO_SSOENT", "SSOENT_TO_APP", "CLIENT_API_MAP"]

from typing import Final

#: 目前可用的登录设备
AVAILABLE_APPS: Final[tuple[str, ...]] = (
    "web", "ios", "115ios", "android", "115android", "115ipad", "tv", "qandroid", 
    "windows", "mac", "linux", "wechatmini", "alipaymini", "harmony", 
)
#: 目前已知的登录设备和对应的 ssoent
APP_TO_SSOENT: Final[dict[str, str]] = {
    "web": "A1", 
    "desktop": "A1", # 临时
    "ios": "D1", 
    "bios": "D1", # 临时
    "115ios": "D3", 
    "android": "F1", 
    "bandroid": "F1", # 临时
    "115android": "F3", 
    "ipad": "H1", 
    "115ipad": "H3", 
    "tv": "I1", 
    "qandroid": "M1", 
    "qios": "N1", 
    "windows": "P1", 
    "mac": "P2", 
    "linux": "P3", 
    "wechatmini": "R1", 
    "alipaymini": "R2", 
    "harmony": "S1", 
}
#: 目前已知的 ssoent 和对应的登录设备，一部分因为不知道具体的设备名，所以使用目前可用的设备名，作为临时代替
SSOENT_TO_APP: Final[dict[str, str]] = {
    "A1": "web", 
    "A2": "android", # 临时代替
    "A3": "ios",     # 临时代替
    "A4": "115ipad", # 临时代替
    "B1": "android", # 临时代替
    "D1": "ios", 
    "D2": "ios",     # 临时代替
    "D3": "115ios",  
    "F1": "android", 
    "F2": "android", # 临时代替
    "F3": "115android", 
    "H1": "115ipad", # 临时代替
    "H2": "115ipad", # 临时代替
    "H3": "115ipad", 
    "I1": "tv", 
    "M1": "qandroid", 
    "N1": "ios",     # 临时代替
    "P1": "windows", 
    "P2": "mac", 
    "P3": "linux", 
    "R1": "wechatmini", 
    "R2": "alipaymini", 
    "S1": "harmony", 
}
#: 所有已封装的 115 接口以及对应的方法名
CLIENT_API_MAP: Final[dict[str, str]] = {}
#: 文件的 class 属性对应的所属类型的整数代码
CLASS_TO_TYPE: Final[dict[str, int]] = {
    "JG_DOC": 1, 
    "DOC": 1, 
    "JG_PIC": 2, 
    "PIC": 2, 
    "JG_MUS": 3, 
    "MUS": 3, 
    "JG_AVI": 4, 
    "AVI": 4, 
    "JG_RAR": 5, 
    "RAR": 5, 
    "RAR_EXTRACT": 5, 
    "JG_EXE": 6, 
    "EXE": 6, 
    "JG_BOOK": 7, 
    "BOOK": 7
}
#: 文件后缀对应的所属类型的整数代码（尚需补充）
SUFFIX_TO_TYPE: Final[dict[str, int]] = {
    ".chm": 1, 
    ".doc": 1, 
    ".docx": 1, 
    ".dwg": 1, 
    ".htm": 1, 
    ".html": 1, 
    ".idx": 1, 
    ".jar": 1, 
    ".lrc": 1, 
    ".mdb": 1, 
    ".mdf": 1, 
    ".ods": 1, 
    ".odt": 1, 
    ".pdf": 1, 
    ".pot": 1, 
    ".pps": 1, 
    ".ppt": 1, 
    ".pptx": 1, 
    ".rtf": 1, 
    ".sub": 1, 
    ".txt": 1, 
    ".wps": 1, 
    ".wri": 1, 
    ".xls": 1, 
    ".xlsx": 1, 
    ".vtt": 1, 
    ".bmp": 2, 
    ".gif": 2, 
    ".heic": 2, 
    ".heif": 2, 
    ".jpeg": 2, 
    ".jpg": 2, 
    ".png": 2, 
    ".raw": 2, 
    ".svg": 2, 
    ".tif": 2, 
    ".tiff": 2, 
    ".webp": 2, 
    ".aiff": 3, 
    ".au": 3, 
    ".flac": 3, 
    ".m4a": 3, 
    ".mid": 3, 
    ".mp3": 3, 
    ".wav": 3, 
    ".wma": 3, 
    ".avi": 4, 
    ".dat": 4, 
    ".divx": 4, 
    ".f4v": 4, 
    ".flv": 4, 
    ".iso": 4, 
    ".m2ts": 4, 
    ".m4v": 4, 
    ".mkv": 4, 
    ".mov": 4, 
    ".mp4": 4, 
    ".mpeg": 4, 
    ".mpg": 4, 
    ".rm": 4, 
    ".rmvb": 4, 
    ".ts": 4, 
    ".vob": 4, 
    ".webm": 4, 
    ".wmv": 4, 
    ".7z": 5, 
    ".cab": 5, 
    ".dmg": 5, 
    ".msi": 5, 
    ".rar": 5, 
    ".tar": 5, 
    ".xz": 5, 
    ".z": 5, 
    ".zip": 5, 
    ".apk": 6, 
    ".bat": 6, 
    ".deb": 6, 
    ".exe": 6, 
    ".pkg": 6, 
    ".azw": 7, 
    ".azw3": 7, 
    ".epub": 7, 
    ".fb2": 7, 
    ".lit": 7, 
    ".lrf": 7, 
    ".mobi": 7, 
    ".prc": 7, 
}
