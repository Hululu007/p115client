#!/usr/bin/env python3
# encoding: utf-8

from __future__ import annotations

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 3, 8, 1)
__requirements__ = ["cachetools", "flask", "Flask-Compress", "httpagentparser", "orjson", "path_predicate", "pysubs2", "python-115", "python-encode_uri", "urllib3_request", "werkzeug", "wsgidav"]
__doc__ = """\
    🕸️ 获取你的 115 网盘账号上文件信息和下载链接 🕷️

🚫 注意事项：请求头需要携带 User-Agent。
如果使用 web 的下载接口，则有如下限制：
    - 大于等于 115 MB 时不能下载
    - 不能直接请求直链，因为需要携带特定的 Cookie 和 User-Agent，所以文件由服务器代理转发，不走 302
"""

from argparse import ArgumentParser, RawTextHelpFormatter

parser = ArgumentParser(
    formatter_class=RawTextHelpFormatter, 
    description=__doc__, 
    epilog="""
---------- 使用说明 ----------

你可以打开浏览器进行直接访问。

1. 如果想要访问某个路径，可以通过查询接口

    GET {path}

或者

    GET ?path={path}

也可以通过 pickcode 查询（对于分享无效）

    GET ?pickcode={pickcode}

也可以通过 id 查询

    GET ?id={id}

也可以通过 sha1 查询（必是文件）（对于分享无效）

    GET ?sha1={sha1}

2. 查询文件或文件夹的信息，返回 json

    GET ?method=attr

3. 查询文件夹内所有文件和文件夹的信息，返回 json

    GET ?method=list

4. 获取文件的下载链接

    GET ?method=url

5. 强制视为文件下载（而不进行多余的检测）

    GET ?method=file

6. 支持的查询参数

💡 如果是分享 （路由路径以 /<share 开始），则只有 id 和 method 有效，其它参数自动忽略

 参数      | 类型    | 必填 | 说明
---------  | ------- | ---- | ----------
pickcode   | string  | 否   | 文件或文件夹的 pickcode，优先级高于 id
id         | integer | 否   | 文件或文件夹的 id，优先级高于 sha1
sha1       | string  | 否   | 文件或文件夹的 id，优先级高于 path
path       | string  | 否   | 文件或文件夹的路径，优先级高于 url 中的路径部分
method     | string  | 否   | 0. '':     缺省值，下载文件或显示目录列表
           |         |      | 2. 'url':  这个文件的下载链接和请求头，JSON 格式
           |         |      | 2. 'attr': 这个文件或文件夹的信息，JSON 格式
           |         |      | 3. 'list': 这个文件夹内所有文件和文件夹的信息，JSON 格式
           |         |      | 4. 'file': 下载文件

当文件被下载时，可以有其它查询参数

 参数      | 类型    | 必填 | 说明
---------  | ------- | ---- | ----------
web        | string  | 否   | 使用 web 接口获取下载链接（文件由服务器代理转发，不走 302）
image      | string  | 否   | 文件作为图片打开

7. 支持 webdav

在浏览器或 webdav 挂载软件 中输入
    http://localhost:8000/<dav
目前没有用户名和密码就可以浏览，支持 302

8. 支持分享列表

在浏览器中输入
    http://localhost:8000/<share
在浏览器或 webdav 挂载软件 中输入
    http://localhost:8000/<dav/<share
""")

parser.add_argument("-c", "--cookies", help="115 登录 cookies，优先级高于 -cp/--cookies-path")
parser.add_argument("-cp", "--cookies-path", default="", help="cookies 文件保存路径，默认为当前工作目录下的 115-cookies.txt")
parser.add_argument("-pcs", "--path-cache-size", type=int, default=1048576, help="路径缓存的容量大小，默认值 1048576，等于 0 时关闭，小于等于 0 时不限")
parser.add_argument("-r", "--root", default="0", help="选择一个根 路径 或 id，默认值 0")
parser.add_argument("-o", "--origin", help="[webdav] origin 或者说 base_url，用来拼接路径，获取完整链接，默认行为是自行确定")
parser.add_argument("-p1", "--predicate", help="[webdav] 断言，当断言的结果为 True 时，文件或目录会被显示")
parser.add_argument(
    "-t1", "--predicate-type", default="ignore", 
    choices=("ignore", "ignore-file", "expr", "lambda", "stmt", "module", "file", "re"), 
    help="""[webdav] 断言类型，默认值为 'ignore'
    - ignore       （默认值）gitignore 配置文本（有多个时用空格隔开），在文件路径上执行模式匹配，匹配成功则断言为 False
                   NOTE: https://git-scm.com/docs/gitignore#_pattern_format
    - ignore-file  接受一个文件路径，包含 gitignore 的配置文本（一行一个），在文件路径上执行模式匹配，匹配成功则断言为 False
                   NOTE: https://git-scm.com/docs/gitignore#_pattern_format
    - expr         表达式，会注入一个名为 path 的 p115.P115PathBase 对象
    - lambda       lambda 函数，接受一个 p115.P115PathBase 对象作为参数
    - stmt         语句，当且仅当不抛出异常，则视为 True，会注入一个名为 path 的 p115.P115PathBase 对象
    - module       模块，运行后需要在它的全局命名空间中生成一个 check 或 predicate 函数用于断言，接受一个 p115.P115PathBase 对象作为参数
    - file         文件路径，运行后需要在它的全局命名空间中生成一个 check 或 predicate 函数用于断言，接受一个 p115.P115PathBase 对象作为参数
    - re           正则表达式，模式匹配，如果文件的名字匹配此模式，则断言为 True
""")
parser.add_argument("-p2", "--strm-predicate", help="[webdav] strm 断言（优先级高于 -p1/--predicate），当断言的结果为 True 时，文件会被显示为带有 .strm 后缀的文本文件，打开后是链接")
parser.add_argument(
    "-t2", "--strm-predicate-type", default="filter", 
    choices=("filter", "filter-file", "expr", "lambda", "stmt", "module", "file", "re"), 
    help="""[webdav] 断言类型，默认值为 'filter'
    - filter       （默认值）gitignore 配置文本（有多个时用空格隔开），在文件路径上执行模式匹配，匹配成功则断言为 True
                   请参考：https://git-scm.com/docs/gitignore#_pattern_format
    - filter-file  接受一个文件路径，包含 gitignore 的配置文本（一行一个），在文件路径上执行模式匹配，匹配成功则断言为 True
                   请参考：https://git-scm.com/docs/gitignore#_pattern_format
    - expr         表达式，会注入一个名为 path 的 p115.P115PathBase 对象
    - lambda       lambda 函数，接受一个 p115.P115PathBase 对象作为参数
    - stmt         语句，当且仅当不抛出异常，则视为 True，会注入一个名为 path 的 p115.P115PathBase 对象
    - module       模块，运行后需要在它的全局命名空间中生成一个 check 或 predicate 函数用于断言，接受一个 p115.P115PathBase 对象作为参数
    - file         文件路径，运行后需要在它的全局命名空间中生成一个 check 或 predicate 函数用于断言，接受一个 p115.P115PathBase 对象作为参数
    - re           正则表达式，模式匹配，如果文件的名字匹配此模式，则断言为 True
""")
parser.add_argument("-fs", "--fast-strm", action="store_true", help="""快速实现 媒体筛选 和 虚拟 strm，此命令优先级较高，相当于命令行指定

    --strm-predicate-type expr \\
    --strm-predicate '(
        path.media_type.startswith(("video/", "audio/")) and
        path.suffix.lower() != ".ass"
    )' \\
    --predicate-type expr \\
    --predicate '(
        path.is_dir() or
        path.media_type.startswith("image/") or
        path.suffix.lower() in (".nfo", ".ass", ".ssa", ".srt", ".idx", ".sub", ".txt", ".vtt", ".smi")
    )'
""")
parser.add_argument("-ass", "--load-libass", action="store_true", help="加载 libass.js，实现 ass/ssa 字幕特效")

if __name__ == "__main__":
    parser.add_argument("-H", "--host", default="0.0.0.0", help="ip 或 hostname，默认值：'0.0.0.0'")
    parser.add_argument("-P", "--port", default=8000, type=int, help="端口号，默认值：8000")
    parser.add_argument("-d", "--debug", action="store_true", help="启用 debug 模式，当文件变动时自动重启 + 输出详细的错误信息")
    parser.add_argument("-v", "--version", action="store_true", help="输出版本号")

    args = parser.parse_args()
    if args.version:
        print(".".join(map(str, __version__)))
        raise SystemExit(0)
else:
    from sys import argv

    try:
        args_start = argv.index("--")
        args, unknown = parser.parse_known_args(argv[args_start+1:])
        if unknown:
            from warnings import warn
            warn(f"unknown args passed: {unknown}")
    except ValueError:
        args = parser.parse_args([])

try:
    from cachetools import LRUCache, TTLCache
    from encode_uri import encode_uri, encode_uri_component_loose
    from flask import request, redirect, render_template_string, send_file, Flask, Response
    from flask_compress import Compress # type: ignore
    # NOTE: 其它可用模块
    # - https://pypi.org/project/user-agents/
    # - https://github.com/faisalman/ua-parser-js
    from httpagentparser import detect as detect_ua
    from jinja2 import Environment, DictLoader
    from orjson import dumps
    from p115 import check_response, AuthenticationError, P115URL
    from p115.component import P115Client, P115FileSystem, P115ShareFileSystem
    from p115.tool import type_of_attr
    from path_predicate import make_predicate
    from posixpatht import escape as escape_name, path_is_dir_form
    from pysubs2 import SSAFile
    from urllib3.poolmanager import PoolManager
    from urllib3_request import request as urllib3_request
    from werkzeug.middleware.dispatcher import DispatcherMiddleware
    from wsgidav.wsgidav_app import WsgiDAVApp # type: ignore
    from wsgidav.dav_error import DAVError # type: ignore
    from wsgidav.dav_provider import DAVCollection, DAVNonCollection, DAVProvider # type: ignore
except ImportError:
    from sys import executable
    from subprocess import run
    run([executable, "-m", "pip", "install", "-U", *__requirements__], check=True)
    from cachetools import LRUCache, TTLCache
    from encode_uri import encode_uri, encode_uri_component_loose
    from flask import request, redirect, render_template_string, send_file, Flask, Response
    from flask_compress import Compress # type: ignore
    from httpagentparser import detect as detect_ua # type: ignore
    from jinja2 import Environment, DictLoader
    from orjson import dumps
    from p115 import check_response, AuthenticationError, P115URL
    from p115.component import P115Client, P115FileSystem, P115ShareFileSystem
    from p115.tool import type_of_attr
    from path_predicate import make_predicate
    from posixpatht import escape as escape_name, path_is_dir_form
    from pysubs2 import SSAFile # type: ignore
    from urllib3.poolmanager import PoolManager
    from urllib3_request import request as urllib3_request
    from werkzeug.middleware.dispatcher import DispatcherMiddleware
    from wsgidav.wsgidav_app import WsgiDAVApp # type: ignore
    from wsgidav.dav_error import DAVError # type: ignore
    from wsgidav.dav_provider import DAVCollection, DAVNonCollection, DAVProvider # type: ignore

from collections.abc import Callable, Mapping, MutableMapping
from datetime import datetime
from functools import cached_property, partial, update_wrapper
from html import escape
from io import BytesIO
from pathlib import Path
from posixpath import split as splitpath, splitext
from string import digits, hexdigits
from time import time
from typing import cast
from urllib.parse import unquote, urlsplit


urlopen = partial(urllib3_request, pool=PoolManager(num_pools=256))

origin = args.origin
root = args.root

if args.fast_strm:
    predicate = make_predicate("""(
    path.is_dir() or
    path.media_type.startswith("image/") or
    path.suffix.lower() in (".nfo", ".ass", ".ssa", ".srt", ".idx", ".sub", ".txt", ".vtt", ".smi")
)""", type="expr")
elif predicate := args.predicate or None:
    predicate = make_predicate(predicate, {"re": __import__("re")}, type=args.predicate_type)

if args.fast_strm:
    strm_predicate = make_predicate("""(
    path.media_type.startswith(("video/", "audio/")) and
    path.suffix.lower() != ".ass"
)""", type="expr")
elif strm_predicate := args.strm_predicate or None:
    strm_predicate = make_predicate(strm_predicate, {"re": __import__("re")}, type=args.strm_predicate_type)

if not (cookies := args.cookies):
    if cookies_path := args.cookies_path:
        cookies = Path(cookies_path)
    else:
        cookies = Path("115-cookies.txt")
client = P115Client(cookies, check_for_relogin=True, ensure_cookies=True, app="harmony")
fs = client.get_fs(cache_id_to_readdir=65536, cache_path_to_id=args.path_cache_size, request=urlopen)

# NOTE: id 到 pickcode 的映射
ID_TO_PICKCODE: MutableMapping[int, str] = LRUCache(65536)
# NOTE: sha1 到 pickcode 到映射
SHA1_TO_PICKCODE: MutableMapping[str, str] = LRUCache(65536)
# NOTE: 缓存图片的 CDN 直链 1 小时
IMAGE_URL_CACHE: MutableMapping[str | tuple[str, int], None | P115URL] = TTLCache(65536, ttl=3600)
# NOTE: 缓存 115 分享的文件系统对象
SHARE_FS_MAP: dict[str, P115ShareFileSystem] = {}
# NOTE: 限制请求频率，以一组请求信息为 key，0.5 秒内相同的 key 只放行一个
URL_COOLDOWN: MutableMapping[tuple, None] = TTLCache(1024, ttl=0.5)
# NOTE: 下载链接缓存，以减少接口调用频率，只需缓存很短时间
URL_CACHE: MutableMapping[tuple, P115URL] = TTLCache(64, ttl=1)
# NOTE: webdav 的文件对象缓存
if strm_predicate:
    DAV_FILE_CACHE: MutableMapping[str, DAVNonCollection] = LRUCache(65536)

root_dir: str = ""
if root in ("0", "", "/") or fs.abspath(root) == "/":
    root = 0
    root_dir = "/"
else:
    if not (root.startswith("0") or root.strip(digits)):
        root = int(root)
    try:
        fs.chdir(root)
    except NotADirectoryError:
        root_attr = fs.attr(root)
        root = root_attr["id"]
        root_pickcode = root_attr["pickcode"]
    else:
        root = fs.id
        if root == 0:
            root_dir = "/"
        else:
            root_dir = str(fs.path) + "/"

flask_app = Flask(__name__)
Compress(flask_app)
setattr(flask_app.json, "ensure_ascii", False)
env = Environment(loader=DictLoader({
    "base_template": """\
<!DOCTYPE html>
<html>
<head>
  <title>dav 115 302</title>
  <link rel="shortcut icon" href="/?pic=favicon" type="image/x-icon">
  <link href="//cdnres.115.com/site/static/style_v10.0/file/css/file_type.css?_vh=bf604a2_70" rel="stylesheet" type="text/css">
  <style>
    body {
      margin: 0;
      padding: 0;
    }

    a:hover {
      color: red;
    }

    .file-type {
      flex: 1;
      min-width: 0;
      position: relative;
      height: 32px;
      padding-left: 47px;
      flex-direction: column;
      justify-content: center;
    }

    td {
      vertical-align: middle;
    }

    img {
      height: 32px;
      width: 32px; 
    }

    table {
      border-collapse: collapse;
      margin: 25px 0;
      font-size: 0.9em;
      font-family: sans-serif;
      min-width: 800px;
      box-shadow: 0 0 20px rgba(0, 0, 0, 0.15);
    }

    thead tr {
      font-family: Lato-Bold;
      font-size: 18px;
      color: #3636f0;
      line-height: 1.4;
      background-color: #f0f0f0;
      position: sticky;
      top: 0;
      z-index: 100;
    }

    th, td:not(:first-child) {
      padding: 12px 15px;
    }

    tbody tr {
      border-bottom: 1px solid #dddddd;
      background-color: #fff;
      transition: background-color 0.3s, transform 0.3s;
    }

    tbody tr:last-of-type {
      border-bottom: 2px solid #009879;
    }

    tbody tr:hover {
      color: #009879;
      font-weight: bold;
      background-color: rgba(230, 230, 230, 0.5);
      transform: scale(1.02);
    }

    .icon {
      border-radius: 10px;
      display: inline-block;
      padding: 8px;
      transition: background-color 0.5s;
    }
    .icon:hover {
        background-color: #d2d2d2;
    }

    .popup {
      position: relative;
      display: inline-block;
      cursor: pointer;
      -webkit-user-select: none;
      -moz-user-select: none;
      -ms-user-select: none;
      user-select: none;
    }
  
    .popup .popuptext {
      visibility: hidden;
      width: 160px;
      background-color: #555;
      color: #fff;
      text-align: center;
      border-radius: 6px;
      padding: 8px 0;
      position: absolute;
      z-index: 1;
      bottom: 125%;
      left: 50%;
      margin-left: -80px;
    }
  
    .popup .popuptext::after {
      content: "";
      position: absolute;
      top: 100%;
      left: 50%;
      margin-left: -5px;
      border-width: 5px;
      border-style: solid;
      border-color: #555 transparent transparent transparent;
    }
  
    .popup:hover .popuptext {
      visibility: visible;
      -webkit-animation: fadeIn 1s;
      animation: fadeIn 1s;
    }
  
    @-webkit-keyframes fadeIn {
      from {opacity: 0;} 
      to {opacity: 1;}
    }
  
    @keyframes fadeIn {
      from {opacity: 0;}
      to {opacity:1 ;}
    }

    .draggable-resizable-window {
      width: 900px;
      height: 520px;
      position: absolute;
      overflow: hidden;
      resize: both;
      cursor: move;
      display: none;
      z-index: 999;
    }

    .player-container {
      width: 100%;
      height: 100%;
      display: flex;
      justify-content: center;
      align-items: center;
      cursor: pointer;
      position: absolute;
    }

    .art-icon > svg {
      padding: 0px;
    }
  </style>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/particles.js/2.0.0/particles.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/progressbar.js/1.1.1/progressbar.min.js"></script>
  <script src="https://cdn.jsdmirror.com/npm/@fancyapps/ui@latest/dist/fancybox/fancybox.umd.js"></script>
  <link href="https://cdn.jsdmirror.com/npm/@fancyapps/ui@latest/dist/fancybox/fancybox.css" rel="stylesheet"/>
  <script src="https://cdn.jsdmirror.com/npm/@fancyapps/ui@latest/dist/carousel/carousel.umd.js"></script>
  <link href="https://cdn.jsdmirror.com/npm/@fancyapps/ui@latest/dist/carousel/carousel.css" rel="stylesheet"/>
  <script src="https://cdn.jsdmirror.com/npm/@fancyapps/ui@latest/dist/carousel/carousel.thumbs.umd.js"></script>
  <link href="https://cdn.jsdmirror.com/npm/@fancyapps/ui@latest/dist/carousel/carousel.thumbs.css" rel="stylesheet"/>
  <script src="https://cdn.jsdmirror.com/npm/artplayer@latest/dist/artplayer.min.js"></script>
  <script src="https://cdn.jsdmirror.com/npm/hls.js@latest/dist/hls.min.js"></script>
  <script src="https://cdn.jsdmirror.com/npm/plyr@latest/dist/plyr.min.js"></script>
  <link href="https://cdn.jsdmirror.com/npm/plyr@latest/dist/plyr.min.css" rel="stylesheet"/>
  {%- if args.load_libass %}
  <script src="https://artplayer.org/uncompiled/artplayer-plugin-libass/index.js"></script>
  {%- endif %}
</head>
<body>
  <div class="draggable-resizable-window">
    <div class="player-container"></div>
  </div>
  {%- block content %}{% endblock %}
  <script>
document.addEventListener('DOMContentLoaded', function () {
  let player;
  const draggableWindow = document.querySelector(".draggable-resizable-window");
  var playerContainer = draggableWindow.querySelector('.player-container');
  let isDragging = false;
  let initialOffsetX, initialOffsetY, startX, startY;

  playerContainer.addEventListener("mousedown", (e) => {
    isDragging = true;
    initialOffsetX = draggableWindow.offsetLeft;
    initialOffsetY = draggableWindow.offsetTop;
    startX = e.clientX;
    startY = e.clientY;
  });

  playerContainer.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    const newOffsetX = initialOffsetX + dx;
    const newOffsetY = initialOffsetY + dy;
    const maxWidth = window.pageXOffset + window.innerWidth - draggableWindow.offsetWidth;
    const maxHeight = window.pageYOffset + window.innerHeight - draggableWindow.offsetHeight;
    const newLeft = Math.min(Math.max(newOffsetX, window.pageXOffset), maxWidth);
    const newTop = Math.min(Math.max(newOffsetY, window.pageYOffset), maxHeight);
    draggableWindow.style.left = `${newLeft}px`;
    draggableWindow.style.top = `${newTop}px`;
  });

  playerContainer.addEventListener("mouseup", () => {
    isDragging = false;
  });

  const closeButton = document.createElement("img");
  closeButton.id = "artplayer-close";
  closeButton.src = "/?pic=close";
  closeButton.style = "transition: opacity 0.5s ease"

  document.addEventListener('keydown', function(event) {
    if (!player) return;
    if (event.key === 'Escape' && player) {
        if (player instanceof Artplayer && !player.fullscreen)
          player.destroy();
        else if (player instanceof Plyr && !player.fullscreen.active) {
          player.destroy();
          draggableWindow.style.display = 'none';
          player = null;
        }
    }
  });

  document.querySelectorAll('.play-with-artplayer').forEach(function(anchor) {
    const attr = JSON.parse(anchor.parentElement.dataset.attr);
    let multiQualities, subtitles, subtitle;
    anchor.addEventListener('click', async (event) => {
      event.preventDefault();
      if (player) player.destroy();
      draggableWindow.style.display = 'block';
      const scrollX = window.scrollX;
      const scrollY = window.scrollY;
      const windowWidth = window.innerWidth;
      const windowHeight = window.innerHeight;
      const modalWidth = draggableWindow.offsetWidth;
      const modalHeight = draggableWindow.offsetHeight;
      const left = scrollX + (windowWidth - modalWidth) / 2;
      const top = scrollY + (windowHeight - modalHeight) / 2;
      draggableWindow.style.left = left + 'px';
      draggableWindow.style.top = top + 'px';

      if (!multiQualities) {
        multiQualities = [{
          default: true, 
          html: "源文件", 
          url: anchor.href, 
        }];
        const pickcode = attr.pickcode;
        if (pickcode)
          try {
            const resp = await fetch(`/?method=m3u8&pickcode=${pickcode}`);
            const json = await resp.json();
            if (json instanceof Array && json.length)
              multiQualities.push(...json.map(({title, url})=>({html: title, url, type: "m3u8"})));
          } catch (e) {
            console.error(`can't get multi qualities for ${attr.name}: ${e.message}`);
          }
      }
      if (!subtitles) {
        subtitles = [];
        try {
          const sharecode = attr.share_code;
          const prefix = attr.name.slice(0, attr.name.lastIndexOf("."));
          if (sharecode) {
            const resp = await fetch(`/<share?id=${attr.parent_id}&share_code=${sharecode}&method=list`);
            const filelist = await resp.json();
            for (const {name, url} of filelist) {
              if (/(?i:.ass|.srt|.ssa|.vtt)$/.test(name) && name.startsWith(prefix)) {
                const type = name.slice(name.lastIndexOf(".") + 1);
                subtitles.push({
                  html: name.slice(prefix.length + 1), 
                  {%- if args.load_libass %}
                  url: type === "srt" ? `/a.ass?method=srt2ass&url=${encodeURIComponent(url)}` : url, 
                  type: type === "srt" ? "ass" : type, 
                  {%- else %}
                  url, 
                  type, 
                  {%- endif %}
                  escape: false, 
                });
              }
              if (!subtitle) subtitle = subtitles.at(-1);
            }
          } else {
            const resp = await fetch(`/?method=sub&pickcode=${attr.pickcode}`);
            const json = await resp.json();
            if (json instanceof Object && json.list.length) {
              for (const {title, url, type, sha1} of json.list) {
                if (!sha1)
                  subtitles.push({
                    html: `${title} ${type}`, 
                    {%- if args.load_libass %}
                    url: type === "srt" ? `/a.ass?method=srt2ass&url=${encodeURIComponent(url)}` : url, 
                    type: type === "srt" ? "ass" : type, 
                    {%- else %}
                    url, 
                    type, 
                    {%- endif %}
                    escape: false, 
                  });
                else if (title.startsWith(prefix)) {
                  subtitles.push({
                    html: title.slice(prefix.length + 1), 
                    {%- if args.load_libass %}
                    url: type === "srt" ? `/a.ass?method=srt2ass&url=${encodeURIComponent(url)}` : `/a.${type}?method=redirect&url=${encodeURIComponent(url)}`, 
                    type: type === "srt" ? "ass" : type, 
                    {%- else %}
                    url, 
                    type, 
                    {%- endif %}
                    escape: false, 
                  });
                  if (!subtitle) subtitle = subtitles.at(-1);
                }
              }
            }
          }
          if (!subtitle) subtitle = subtitles[0];
        } catch (e) {
          console.error(`can't get multi subtitles for ${attr.name}: ${e.message}`);
        }
      }
      if (!subtitle) subtitle = {};
      player = new Artplayer({
        container: playerContainer, 
        url: anchor.href, 
        airplay: true, 
        aspectRatio: true, 
        autoMini: true, 
        autoOrientation: true, 
        autoplay: true, 
        fastForward: true, 
        flip: true, 
        fullscreen: true, 
        fullscreenWeb: true, 
        lock: true, 
        miniProgressBar: true, 
        muted: false, 
        pip: true, 
        playbackRate: true, 
        screenshot: true, 
        subtitle, 
        subtitleOffset: true, 
        setting: true, 
        settings: [{
          html: "画质", 
          selector: multiQualities, 
          onSelect: function (item, $dom, event) {
            player.switchQuality(item.url);
            player.type = item.type;
            player.notice.show = `切换画质: ${item.html}`;
            return item.html;
          }, 
        }, {
          html: "字幕", 
          icon: '<img width="22" heigth="22" src="/?pic=subtitle">',
          selector: [
            {
              html: 'Display',
              tooltip: 'Show',
              switch: true,
              onSwitch: function (item) {
                item.tooltip = item.switch ? 'Hide' : 'Show';
                player.subtitle.show = !item.switch;
                return !item.switch;
              },
            }, 
            ...subtitles,
          ],
          onSelect: function (item) {
            {%- if args.load_libass %}
            player.plugins.artplayerPluginLibass.switch(item.url);
            {%- else %}
            player.subtitle.init({
              ...player.subtitle.option, 
              style: {}, 
              ...item, 
            });
            {%- endif %}
            return item.html;
          },
        }],
        customType: {
          m3u8: (video, url, art) => {
            if (Hls.isSupported()) {
              if (art.hls) art.hls.destroy();
              const hls = new Hls();
              hls.loadSource(url);
              hls.attachMedia(video);
              art.hls = hls;
              art.on('destroy', () => hls.destroy());
            } else if (video.canPlayType('application/vnd.apple.mpegurl'))
              video.src = url;
            else
              art.notice.show = 'Unsupported playback format: m3u8';
          }, 
        }, 
        layers: [{
            name: 'potser',
            html: closeButton,
            tooltip: 'close',
            style: {
                position: 'absolute', 
                width: '30px', 
                top: '0px', 
                right: '0px', 
            },
            click: function (...args) {
                player.destroy();
                draggableWindow.style.display = 'none';
            },
          },
        ], 
        moreVideoAttr: {
          [window.location.hostname == "localhost" ? "crossOrigin" : ""]: "anonymous", 
          preload: 'none', 
          playsinline: true, 
        }, 
        plugins: [
          {%- if args.load_libass %}
          artplayerPluginLibass({
            debug: false, 
            wasmUrl: 'https://unpkg.com/libass-wasm@4.1.0/dist/js/subtitles-octopus-worker.wasm', 
            fallbackFont: 'https://artplayer.org/assets/misc/SourceHanSansCN-Bold.woff2', 
          }),
          {%- endif %}
        ],
      });
      window.player = player;
      playerContainer.addEventListener('mouseenter', () => {
        closeButton.style.opacity = 1;
      });
      playerContainer.addEventListener('mouseleave', () => {
        closeButton.style.opacity = 0;
      });
      let hideTimeout;
      playerContainer.addEventListener('mousemove', () => {
        if (!player) return;
        if (player.fullscreen)
          closeButton.style.display = "block";
        clearTimeout(hideTimeout);
        hideTimeout = setTimeout(() => {
          if (player && player.fullscreen)
            closeButton.style.display = "none";
        }, 1000);
      });
      player.on('fullscreen', (isFullScreen) => {
        if (isFullScreen)
          closeButton.style.display = "none";
        else
          closeButton.style.display = "block";
      });
      player.on('destroy', () => {
        clearTimeout(hideTimeout);
        player.pause();
        player.off();
        if (player.hls) 
            player.hls.destroy();
        if (player.flv)
            player.flv.destroy();
        if (player.dash)
            player.dash.destroy();
        if (player.torrent)
            player.torrent.destroy();
        player = null;
      });
    });
  });
  document.querySelectorAll('.play-with-plyr').forEach(function(anchor) {
    anchor.addEventListener('click', function (event) {
      event.preventDefault();
      if (player) player.destroy();
      draggableWindow.style.display = 'block';
      const scrollX = window.scrollX;
      const scrollY = window.scrollY;
      const windowWidth = window.innerWidth;
      const windowHeight = window.innerHeight;
      const modalWidth = draggableWindow.offsetWidth;
      const modalHeight = draggableWindow.offsetHeight;
      const left = scrollX + (windowWidth - modalWidth) / 2;
      const top = scrollY + (windowHeight - modalHeight) / 2;
      draggableWindow.style.left = left + 'px';
      draggableWindow.style.top = top + 'px';
      const video = playerContainer.innerHTML = `
      <video id="player" controls crossorigin playsinline>
        <source src="${anchor.href}" />
      </video>`
      player = new Plyr("#player", {autoplay: true});
    });
  });
});

window.addEventListener("load", function () {
  // startup for particles.js
  // color picker tool: https://www.w3cschool.cn/tools/index?name=cpicker
  const particlesColorDark = ["#1a0000", "#1a1100", "#191a00", "#001a00", "#00001a", "#0f001a", "#160316", "#0d0d0d"];
  const particlesColorLight = ["#ffe5e5", "#fff6e5", "#ffffe5", "#e5ffe5", "#e5e5ff", "#f4e5ff", "#fce9fc", "#f2f2f2"];
  let startThemeColor = document.body.dataset["theme"];
  const particlesConfig = {
    particles: {
      number: {
        value: 80,
        density: {
          enable: true,
          value_area: 800
        }
      },
      color: {
        value: startThemeColor == "dark" ? particlesColorDark : particlesColorLight,
      },
      shape: {
        type: ["circle"],
        stroke: {
          width: 0,
          color: "#fff"
        },
        polygon: {
          nb_sides: 5
        }
      },
      opacity: {
        value: 1,
        random: false,
        anim: {
          enable: false,
          speed: 1,
          opacity_min: 0.1,
          sync: false
        }
      },
      size: {
        value: 8,
        random: true,
        anim: {
          enable: false,
          speed: 10,
          size_min: 10,
          sync: false
        }
      },
      line_linked: {
        enable: true,
        distance: 150,
        color: "#808080",
        opacity: 0.4,
        width: 1
      },
      move: {
        enable: true,
        speed: 5,
        direction: "none",
        random: false,
        straight: false,
        out_mode: "out",
        bounce: false,
        attract: {
          enable: false,
          rotateX: 600,
          rotateY: 1200
        }
      }
    },
    interactivity: {
      detect_on: "canvas",
      events: {
        onhover: {
          enable: true,
          mode: "grab"
        },
        onclick: {
          enable: true,
          mode: "push"
        },
        resize: true
      },
      modes: {
        grab: {
          distance: 140,
          line_linked: {
            opacity: 1
          }
        },
        bubble: {
          distance: 400,
          size: 40,
          duration: 2,
          opacity: 8,
          speed: 3
        },
        repulse: {
          distance: 200,
          duration: 0.4
        },
        push: {
          particles_nb: 4
        },
        remove: {
          particles_nb: 2
        }
      }
    },
    retina_detect: true
  };

  if (startThemeColor != null) {
    // Select the node that will be observed for mutations
    const targetNode = document.body;
    // Options for the observer (which mutations to observe)
    const config = { attributes: true, attributeFilter: ["data-theme"] };
    // Callback function to execute when mutations are observed
    const callback = (mutationList, observer) => {
      for (const mutation of mutationList) {
        if (mutation.type === "attributes") {
          const themeColor = targetNode.dataset["theme"];
          particlesConfig.particles.color.value = themeColor == "dark" ? particlesColorDark : particlesColorLight;
          particlesJS("particles-js", particlesConfig);
        }
      }
    }
    // Create an observer instance linked to the callback function
    const observer = new MutationObserver(callback);
    // Start observing the target node for configured mutations
    observer.observe(targetNode, config);
  }
  var body = document.body;
  var div = document.createElement("div");
  div.id = "particles-js";
  div.setAttribute("style", "position: fixed; height: 100%; width: 100%; z-index: -99;");
  body.insertBefore(div, body.firstElementChild);
  particlesJS("particles-js", particlesConfig);

  function getScrollPercentage() {
    const scrollTop = window.scrollY || document.documentElement.scrollTop;
    const scrollDistance = document.documentElement.scrollHeight - window.innerHeight;
    return (scrollTop / scrollDistance) * 100;
  }

  function rainbowGradient(progress) {
    var colors = [
      [255, 0, 0],    // red
      [255, 165, 0],  // orange
      [255, 255, 0],  // yellow
      [0, 128, 0],    // green
      [0, 0, 255],    // blue
      [75, 0, 130],   // indigo
      [148, 0, 211]   // violet
    ];

    var totalSegments = colors.length - 1;
    var segmentProgress = 1 / totalSegments;
    var segmentIndex = Math.floor(progress / segmentProgress);
    var segmentProgressWithinSegment = (progress - segmentIndex * segmentProgress) / segmentProgress;

    var startColor = colors[segmentIndex];
    var endColor = colors[segmentIndex + 1];

    var r = Math.round(startColor[0] + (endColor[0] - startColor[0]) * segmentProgressWithinSegment);
    var g = Math.round(startColor[1] + (endColor[1] - startColor[1]) * segmentProgressWithinSegment);
    var b = Math.round(startColor[2] + (endColor[2] - startColor[2]) * segmentProgressWithinSegment);

    return 'rgb(' + r + ', ' + g + ', ' + b + ')';
  }

  // progressbar at right-bottom
  var body = document.body;
  var div = document.createElement("div");
  div.id = "progress-container";
  div.setAttribute('style', 'position: fixed; bottom: 10px; right: 10px; width: 4em; height: 4em; z-index: 999; cursor: pointer;');
  body.insertBefore(div, body.firstElementChild);

  var progress = new ProgressBar.Circle("#progress-container", {
    // This has to be the same size as the maximum width to
    // prevent clipping
    strokeWidth: 2,
    trailWidth: 1,
    easing: 'easeInOut',
    duration: 1400,
    text: {
      autoStyleContainer: false,
    },
    from: { color: '#FFFF99', width: 1 },
    to: { color: '#00FF33', width: 4 },
    // Set default step function for all animate calls
    step: function (state, circle) {
      circle.path.setAttribute('stroke', rainbowGradient(circle.value()));
      circle.path.setAttribute('stroke-width', 1 + circle.value() * 3);
      circle.setText(circle.value() * 100);
    }
  });
  progress.text.style.fontFamily = '"Raleway", Helvetica, sans-serif';
  progress.text.style.fontSize = '1rem';

  function getScrollPercentage() {
    const scrollTop = window.scrollY || document.documentElement.scrollTop;
    const scrollDistance = document.documentElement.scrollHeight - window.innerHeight;
    return (scrollTop / scrollDistance) * 100;
  }

  function updateScroll() {
    const scrollPercentage = getScrollPercentage();
    if (isNaN(scrollPercentage) || scrollPercentage < 0.1 || scrollPercentage >= 100) {
      progress.svg.parentNode.style.display = "none";
    } else {
      progress.svg.parentNode.style.display = "block";
      progress.set(scrollPercentage / 100);
      progress.setText(scrollPercentage.toFixed(1) + '%');
    }
  }

  window.addEventListener('scroll', updateScroll);

  document.getElementById('progress-container').addEventListener('click', function () {
    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior: 'smooth'
    });
  });

  updateScroll();

  Fancybox.bind('[data-fancybox="gallery"]', {
    Toolbar: {
      display: {
        left: ["rotateCCW","rotateCW", "flipX", "flipY", "toggle1to1", "reset"], 
        middle: ["infobar"], 
        right: ["fullscreen", "thumbs", "slideshow", "download", "close"], 
      },
    }
  });
});
  </script>
</body>
</html>"""
}))
setattr(flask_app, "jinja_env", env)
env.globals['args'] = args


class DavPathBase:

    def __getattr__(self, attr: str, /):
        try:
            return self.attr[attr]
        except KeyError as e:
            raise AttributeError(attr) from e

    @cached_property
    def creationdate(self, /) -> float:
        return self.ctime

    @cached_property
    def ctime(self, /) -> float:
        return self.attr.get("ctime") or self.attr.get("time", 0)

    @cached_property
    def mtime(self, /) -> float:
        return self.attr.get("mtime") or self.attr.get("time", 0)

    @cached_property
    def name(self, /) -> str:
        return self.attr["name"]

    def get_creation_date(self, /) -> float:
        return self.ctime

    def get_display_name(self, /) -> str:
        return self.name

    def get_etag(self, /) -> str:
        return "%s-%s-%s" % (
            self.attr["id"], 
            self.mtime, 
            self.size, 
        )

    def get_last_modified(self, /) -> float:
        return self.mtime

    def is_link(self, /) -> bool:
        return False

    def support_etag(self, /) -> bool:
        return True

    def support_modified(self, /) -> bool:
        return True


class FileResource(DavPathBase, DAVNonCollection):

    def __init__(
        self, 
        /, 
        path: str, 
        environ: dict, 
        attr: Mapping, 
        is_strm: bool = False, 
    ):
        super().__init__(path, environ)
        self.attr = attr
        self.is_strm = is_strm
        key = (attr["share_code"], attr["id"]) if "share_code" in attr else attr["pickcode"]
        if (url := IMAGE_URL_CACHE.get(key)) and isinstance(url, P115URL):
            self.__dict__["url"] = str(url)
            self.__dict__["size"] = url["size"]
        if is_strm:
            DAV_FILE_CACHE[path] = self

    @cached_property
    def origin(self, /) -> str:
        if origin:
            return origin
        return f"{self.environ['wsgi.url_scheme']}://{self.environ['HTTP_HOST']}"

    @cached_property
    def size(self, /) -> int:
        if self.is_strm:
            return len(self.strm_data)
        return self.attr["size"]

    @cached_property
    def strm_data(self, /) -> bytes:
        attr = self.attr
        origin = self.origin
        name = encode_uri_component_loose(attr["name"])
        if share_code := attr.get("share_code"):
            url = f"{origin}/{name}?method=file&share_code={share_code}&id={attr['id']}"
            if attr.get("thumb"):
                url += "&image=true"
        else:
            url = f"{origin}/{name}?method=file&pickcode={attr['pickcode']}&id={attr['id']}&sha1={attr['sha1']}"
            if attr.get("class") == "PIC" or attr.get("thumb"):
                url += "&image=true"
        return bytes(url, "utf-8")

    @property
    def url(self, /) -> str:
        if url := self.__dict__.get("url", ""):
            return url
        attr = self.attr
        if share_code := attr.get("share_code"):
            if url := attr.get("thumb"):
                url = IMAGE_URL_CACHE[(share_code, attr["id"])] = flatten_image_url(url)
                self.__dict__["url"] = str(url)
                self.__dict__["size"] = url["size"]
            return f"/<share?method=file&share_code={share_code}&id={attr['id']}"
        else:
            pickcode = attr.get("pickcode")
            if attr.get("class") == "PIC" or attr.get("thumb"):
                resp = get_image_url(attr["pickcode"])
                self.__dict__["url"] = str(resp)
                self.__dict__["size"] = resp["size"]
            return f"/?method=file&pickcode={pickcode}"

    def get_content(self, /):
        if self.is_strm:
            return BytesIO(self.strm_data)
        raise DAVError(302, add_headers=[("Location", self.url)])

    def get_content_length(self, /) -> int:
        return self.size

    def support_content_length(self, /) -> bool:
        return True

    def support_ranges(self, /) -> bool:
        return True


class FolderResource(DavPathBase, DAVCollection):

    def __init__(
        self, 
        /, 
        path: str, 
        environ: dict, 
        attr: Mapping, 
    ):
        super().__init__(path, environ)
        self.attr = attr

    @cached_property
    def children(self, /) -> dict[str, FileResource | FolderResource]:
        children: dict[str, FileResource | FolderResource] = {}
        environ = self.environ
        dir_ = self.path
        if dir_ != "/":
            dir_ += "/"
        if dir_ == "/<share/":
            for share in list_shares():
                share_code = share["share_code"]
                children[share["share_code"]] = FolderResource(
                    "/<share/" + share_code, 
                    environ, 
                    {
                        "id": 0, 
                        "parent_id": 0, 
                        "is_directory": True, 
                        "time": int(share["create_time"]), 
                        "size": int(share["file_size"]), 
                        "name": share["share_title"], 
                        "ico": "folder", 
                        "share_code": share_code, 
                    }, 
                )
        else:
            if dir_.startswith("/<share/"):
                share_code = self.attr["share_code"]
                listdir_path: Callable = get_share_fs(share_code).listdir_path
            else:
                listdir_path = fs.listdir_path
                if dir_ == "/":
                    children["<share"] = FolderResource("/<share", environ, {"id": 0, "name": "<share", "size": 0})
            for attr in listdir_path(self.attr):
                name = attr["name"]
                is_strm = False
                is_dir = attr["is_directory"]
                if not is_dir and strm_predicate and strm_predicate(attr):
                    is_strm = True
                    name = splitext(name)[0] + ".strm"
                    path = dir_ + name
                elif predicate and not predicate(attr):
                    continue
                else:
                    path = dir_ + name
                if is_dir:
                    children[name] = FolderResource(path, environ, attr)
                else:
                    children[name] = FileResource(path, environ, attr, is_strm=is_strm)
        return children

    def get_member(self, /, name: str) -> FileResource | FolderResource:
        if not (attr := self.children.get(name)):
            raise DAVError(404, self.path + "/" + name)
        return attr

    def get_member_list(self, /) -> list[FileResource | FolderResource]:
        return list(map(self.get_member, self.get_member_names()))

    def get_member_names(self, /) -> list[str]:
        return list(self.children)

    def get_property_value(self, /, name: str):
        if name == "{DAV:}getcontentlength":
            return 0
        elif name == "{DAV:}iscollection":
            return True
        return super().get_property_value(name)


class P115FileSystemProvider(DAVProvider):

    def get_resource_inst(
        self, 
        /, 
        path: str, 
        environ: dict, 
    ) -> FolderResource | FileResource:
        is_dir = path.endswith("/")
        path = "/" + path.strip("/")
        if strm_predicate:
            if inst := DAV_FILE_CACHE.get(path):
                return inst
            if path.endswith(".strm") and not is_dir:
                dir_, name = splitpath(path)
                inst = self.get_resource_inst(dir_, environ)
                if not isinstance(inst, FolderResource):
                    raise DAVError(404, path)
                return inst.get_member(name)
        if path == "/<share":
            return FolderResource("/<share", environ, {"id": 0, "name": "<share", "size": 0})
        else:
            if path.startswith("/<share/"):
                share_code, _, share_path = path[8:].partition("/")
                share_fs = get_share_fs(share_code)
                get_attr: Callable = partial(share_fs.as_path, share_path)
            else:
                get_attr = partial(fs.as_path, path, refresh=False)
            try:
                attr = get_attr()
            except FileNotFoundError:
                raise DAVError(404, path)
            is_strm = False
            is_dir = attr["is_directory"]
            if not is_dir and strm_predicate and strm_predicate(attr):
                is_strm = True
                path = splitext(path)[0] + ".strm"
            elif predicate and not predicate(attr):
                raise DAVError(404, path)
            if is_dir:
                return FolderResource(path, environ, attr)
            else:
                return FileResource(path, environ, attr, is_strm=is_strm)

    def is_readonly(self, /) -> bool:
        return True


def get_status_code(e: BaseException, /) -> None | int:
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


def reduce_image_url_layers(url: str, /) -> str:
    if not url.startswith(("http://thumb.115.com/", "https://thumb.115.com/")):
        return url
    urlp = urlsplit(url)
    sha1 = urlp.path.rsplit("/")[-1].split("_")[0]
    return f"https://imgjump.115.com/?sha1={sha1}&{urlp.query}&size=0"


def flatten_image_url(url: str, /) -> P115URL:
    if isinstance(url, P115URL):
        return url
    thumb = url
    with urlopen(reduce_image_url_layers(thumb), "HEAD") as resp:
        size = int(resp.headers["Content-Length"])
        url = cast(str, resp.url)
    return P115URL(url, size=size, thumb=thumb)


def get_image_url(pickcode: str, /) -> P115URL:
    url = IMAGE_URL_CACHE.get(pickcode, "")
    if not url:
        resp = check_response(client.fs_image(pickcode, request=urlopen))
        url = cast(str, resp["data"]["origin_url"])
    url = IMAGE_URL_CACHE[pickcode] = flatten_image_url(url)
    return url


def redirect_exception_response(func: Callable, /) -> Callable:
    def wrapper(*args, **kwds):
        try:
            return func(*args, **kwds)
        except BaseException as exc:
            code = get_status_code(exc)
            if code is not None:
                return str(exc), code
            elif isinstance(exc, AuthenticationError):
                return str(exc), 401 # Unauthorized
            elif isinstance(exc, PermissionError):
                return str(exc), 403 # Forbidden
            elif isinstance(exc, FileNotFoundError):
                return str(exc), 404 # Not Found
            elif isinstance(exc, (IsADirectoryError, NotADirectoryError)):
                return str(exc), 406 # Not Acceptable
            elif isinstance(exc, OSError):
                flask_app.logger.exception("500: internal server error")
                return str(exc), 500 # Internal Server Error
            else:
                flask_app.logger.exception("can't make response")
                return str(exc), 503 # Service Unavailable
    return update_wrapper(wrapper, func)


def srt2ass(url, /):
    return SSAFile.from_string(urlopen(url).read().decode("utf-8"), format_="srt").to_string("ass")


def list_shares() -> list[dict]:
    global SHARE_FS_MAP
    share_fs_map_new: dict[str, P115ShareFileSystem] = {}
    shares = client.sharing.list()
    for item in shares:
        share_code = item["share_code"]
        receive_code = item["receive_code"]
        if fs := SHARE_FS_MAP.get(share_code):
            fs.__dict__["receive_code"] = receive_code
            share_fs_map_new[share_code] = fs
        else:
            share_fs_map_new[share_code] = P115ShareFileSystem(client, share_code, receive_code, request=urlopen)
    SHARE_FS_MAP = share_fs_map_new
    return shares


def get_share_fs(share_code: str, /) -> P115ShareFileSystem:
    try:
        return SHARE_FS_MAP[share_code]
    except KeyError:
        list_shares()
        return SHARE_FS_MAP[share_code]


def get_file_url(
    pickcode: str, 
    /, 
    user_agent: str = "", 
    use_web_api: bool = False, 
) -> P115URL:
    return client.download_url(
        pickcode, 
        headers={"User-Agent": user_agent}, 
        use_web_api=use_web_api, 
    )


def get_share_file_url(
    share_code: str, 
    receive_code: str, 
    file_id: int | str, 
    /, 
    use_web_api: bool = False, 
) -> P115URL:
    return client.share_download_url(
        {"share_code": share_code, "receive_code": receive_code, "file_id": file_id}, 
        use_web_api=use_web_api, 
    )


def get_origin() -> str:
    scheme = request.environ.get("HTTP_X_FORWARDED_PROTO") or "http"
    netloc = unquote(urlsplit(request.url).netloc)
    return f"{scheme}://{netloc}"


def normalize_attr(
    info: Mapping, 
    /, 
    origin: str = "", 
) -> dict:
    if not origin:
        origin = get_origin()
    attr = {
        k: info[k] for k in (
            "is_directory", "id", "parent_id", "pickcode", "sha1", "size", "name", "path", 
            "ancestors", "ctime", "mtime", "atime", "time", "thumb", "ico", "share_code",  
        ) if k in info
    }
    attr["id"] = str(attr["id"])
    attr["parent_id"] = str(attr["parent_id"])
    if share_code := attr.get("share_code"):
        url = f"{origin}/<share/{share_code}{encode_uri_component_loose(attr['path'], quote_slash=False)}?share_code={share_code}&id={attr['id']}"
        if attr["is_directory"]:
            attr["url"] = url
        else:
            url += "&method=file"
            if info["violated"] and attr["size"] < 1024 * 1024 * 115:
                url += "&web=true"
            attr["url"] = url
            if thumb := attr.get("thumb"):
                thumb = thumb.replace("_100?", "_0?")
                key = (share_code, attr["id"])
                cached_thumb = IMAGE_URL_CACHE.get(key, "")
                if isinstance(cached_thumb, P115URL):
                    cached_thumb = cached_thumb["thumb"]
                if thumb != cached_thumb:
                    IMAGE_URL_CACHE[key] = thumb
            attr["is_media"] = bool(info.get("play_long")) or type_of_attr(info) in (3, 4)
    else:
        relpath = attr["relpath"] = attr["path"][len(cast(str, root_dir)):]
        path_url = "%s/%s" % (origin, encode_uri_component_loose(relpath, quote_slash=False))
        if attr["is_directory"]:
            attr["url"] = f"{path_url}?id={attr['id']}"
        else:
            pickcode = cast(str, attr["pickcode"])
            SHA1_TO_PICKCODE[attr["sha1"]] = ID_TO_PICKCODE[attr["id"]] = pickcode
            url = f"{path_url}?pickcode={pickcode}"
            if thumb := attr.get("thumb"):
                thumb = thumb.replace("_100?", "_0?")
                cached_thumb = IMAGE_URL_CACHE.get(pickcode, "")
                if isinstance(cached_thumb, P115URL):
                    cached_thumb = cached_thumb["thumb"]
                if thumb != cached_thumb:
                    IMAGE_URL_CACHE[pickcode] = thumb
            if info["violated"] and attr["size"] < 1024 * 1024 * 115:
                url += "&web=true"
            attr["url"] = url + "&method=file"
            attr["is_media"] = bool(info.get("play_long")) or info.get("class") in ("AVI", "JG_AVI", "MUS", "JG_MUS")
    return attr


def get_attr(
    path: str = "", 
    id: None | int = None, 
    /, 
):
    if not root_dir:
        return normalize_attr(fs.attr(root))
    id_or_path: int | str
    ensure_dir = False
    if id is None:
        get_arg = request.args.get
        if pickcode := get_arg("pickcode", "").strip().lower():
            if not pickcode.isalnum():
                return Response(f"bad pickcode: {pickcode!r}", 400)
            id_or_path = fs.get_id_from_pickcode(pickcode)
        elif fid := get_arg("id", "").strip():
            try:
                id_or_path = int(fid)
            except ValueError:
                return Response(f"bad id: {fid!r}", 400)
        elif sha1 := get_arg("sha1", "").strip().upper():
            if not len(sha1) == 40 or sha1.strip(hexdigits):
                return Response(f"bad sha1: {sha1!r}", 400)
            resp = check_response(client.fs_shasearch(sha1))
            id_or_path = int(resp["data"]["file_id"])
        else:
            path = unquote(get_arg("path", "")) or path
            ensure_dir = path_is_dir_form(path)
            id_or_path = path.lstrip("/")
    else:
        id_or_path = id
    attr = fs.attr(id_or_path, ensure_dir=ensure_dir, refresh=False)
    if root and not any(info["id"] == root for info in attr["ancestors"]):
        return Response("out of root range", 403)
    return normalize_attr(attr)


def get_share_attr(path: str = "", /, share_code: str = ""):
    get_arg = request.args.get
    if not share_code:
        share_code = get_arg("share_code", "")
    if not share_code:
        return {"share_code": "", "id": 0, "is_directory": True}
    fs = get_share_fs(share_code)
    id_or_path: int | str
    if fid := get_arg("id", "").strip():
        try:
            id_or_path = int(fid)
        except ValueError:
            return Response(f"bad id: {fid!r}", 400)
    else:
        id_or_path = unquote(get_arg("path", "")) or path
    attr = fs.attr(id_or_path)
    return normalize_attr(attr)


def get_list(path: str = "", /):
    if not root_dir:
        return Response("root is not directory", 403)
    id_or_path: int | str
    get_arg = request.args.get
    if pickcode := get_arg("pickcode", "").strip().lower():
        if not pickcode.isalnum():
            return Response(f"bad pickcode: {pickcode!r}", 400)
        id_or_path = fs.get_id_from_pickcode(pickcode)
    elif fid := get_arg("id", "").strip():
        try:
            id_or_path = int(fid)
        except ValueError:
            return Response(f"bad id: {fid!r}", 400)
    else:
        path = unquote(get_arg("path", "")) or path
        id_or_path = path.lstrip("/")
    children = fs.listdir_attr(id_or_path, page_size=10_000)
    if children and root and not any(int(info["id"]) == root for info in children[0]["ancestors"]):
        return Response("out of root range", 403)
    earliest_thumb_ts = min((int(attr["thumb"].rsplit("=", 1)[1]) for attr in children if not attr["is_directory"] and attr.get("thumb")), default=0)
    if earliest_thumb_ts and earliest_thumb_ts - time() < 600:
        children = fs.listdir_attr(id_or_path, page_size=10_000, refresh=True)
    origin = get_origin()
    return [normalize_attr(attr, origin) for attr in children]


def get_share_list(path: str = "", /, share_code: str = ""):
    get_arg = request.args.get
    if not share_code:
        share_code = get_arg("share_code", "")
    if not share_code:
        shares = list_shares()
        origin = get_origin()
        return [{
            "id": 0, 
            "parent_id": 0, 
            "is_directory": True, 
            "time": int(s["create_time"]), 
            "size": int(s["file_size"]), 
            "name": s["share_title"], 
            "ico": "folder", 
            "share_code": s["share_code"], 
            "url": f"{origin}/<share?share_code={s['share_code']}&id=0", 
        } for s in shares]
    fs = get_share_fs(share_code)
    id_or_path: int | str
    if fid := get_arg("id", "").strip():
        try:
            id_or_path = int(fid)
        except ValueError:
            return Response(f"bad id: {fid!r}", 400)
    else:
        id_or_path = unquote(get_arg("path", "")) or path
    children = fs.listdir_attr(id_or_path, page_size=10_000)
    if children:
        earliest_thumb_ts = min((int(attr["thumb"].rsplit("=", 1)[1]) for attr in children if not attr["is_directory"] and attr.get("thumb")), default=0)
        if earliest_thumb_ts and earliest_thumb_ts - time() < 600:
            children = fs.listdir_attr(id_or_path, page_size=10_000, refresh=True)
    origin = get_origin()
    return [normalize_attr(attr, origin) for attr in children]


def get_file_pickcode(path: str = "", /, pickcode: str = "") -> str | Response:
    if root_dir:
        attr: dict
        get_arg = request.args.get
        if pickcode or (pickcode := get_arg("pickcode", "").strip().lower()):
            if not pickcode.isalnum():
                return Response(f"bad pickcode: {pickcode!r}", 400)
            return pickcode
        elif fid := get_arg("id", "").strip():
            try:
                file_id = int(fid)
            except ValueError:
                return Response(f"bad id: {file_id!r}", 400)
            attr = fs.attr(file_id, refresh=False)
            return normalize_attr(attr)["pickcode"]
        elif sha1 := get_arg("sha1", "").strip().upper():
            if not len(sha1) == 40 or sha1.strip(hexdigits):
                return Response(f"bad sha1: {sha1!r}", 400)
            resp = check_response(client.fs_shasearch(sha1))
            return resp["data"]["pick_code"]
        else:
            path = unquote(get_arg("path", "")) or path
            attr = fs.attr(path.lstrip("/"), ensure_dir=False, refresh=False)
            attr = normalize_attr(attr)
            if root and not any(info["id"] == root for info in attr["ancestors"]):
                return Response("out of root range", 403)
            return attr["pickcode"]
    else:
        return root_pickcode


def get_m3u8(path: str = "", /, pickcode: str = "") -> list[dict] | Response:
    """获取 m3u8 文件链接
    """
    pickcode_resp = get_file_pickcode(path, pickcode)
    if isinstance(pickcode_resp, Response):
        return pickcode_resp
    pickcode = pickcode_resp
    resp = client.fs_video_app(pickcode)
    if not resp["state"]:
        return []
    return resp["data"]["video_url"]


def get_subtitles(path: str = "", /, pickcode: str = "") -> None | dict | Response:
    """获取字幕（随便提供此文件夹内的任何一个文件的提取码即可）
    """
    pickcode_resp = get_file_pickcode(path, pickcode)
    if isinstance(pickcode_resp, Response):
        return pickcode_resp
    pickcode = pickcode_resp
    resp = client.fs_video_subtitle(pickcode)
    return resp.get("data")


def get_url(path: str = "", /, pickcode: str = "") -> dict | Response:
    """获取下载链接
    """
    pickcode_resp = get_file_pickcode(path, pickcode)
    if isinstance(pickcode_resp, Response):
        return pickcode_resp
    pickcode = pickcode_resp
    get_arg = request.args.get
    if is_image := get_arg("image") not in (None, "0", "false"):
        return {"type": "image", "url": get_image_url(pickcode)}
    use_web_api = get_arg("web") not in (None, "0", "false")
    user_agent = request.headers.get("User-Agent", "")
    bytes_range = request.headers.get("Range", "")
    url: None | P115URL
    if bytes_range and not user_agent.lower().startswith(("vlc/", "oplayer/", "lavf/")):
        remote_addr = request.remote_addr or ""
        cooldown_key = (pickcode, remote_addr, user_agent, bytes_range)
        if cooldown_key in URL_COOLDOWN:
            return Response("too many requests", 429)
        URL_COOLDOWN[cooldown_key] = None
        key = (pickcode, remote_addr, user_agent, use_web_api)
        if not (url := URL_CACHE.get(key)):
            URL_CACHE[key] = url = get_file_url(pickcode, user_agent=user_agent, use_web_api=use_web_api)
    else:
        url = get_file_url(pickcode, user_agent=user_agent, use_web_api=use_web_api)
    return {"type": "file", "url": str(url), "headers": url["headers"], "web": use_web_api}


def get_share_url(path: str = "", /, share_code: str = "", file_id: int | str = ""):
    get_arg = request.args.get
    if not share_code:
        share_code = get_arg("share_code", "")
    if not share_code:
        return Response("`share_code` not provided", 400)
    fs = get_share_fs(share_code)
    attr: dict = {}
    if file_id or (file_id := get_arg("id", "").strip()):
        try:
            file_id = int(file_id)
        except ValueError:
            return Response(f"bad id: {file_id!r}", 400)
    else:
        path = unquote(get_arg("path", "")) or path
        attr = fs.attr(path, ensure_dir=False)
        attr = normalize_attr(attr)
        file_id = cast(int, attr["id"])
    if is_image := get_arg("image") not in (None, "0", "false"):
        key = (share_code, file_id)
        if not (thumb := IMAGE_URL_CACHE.get(key, "")):
            if not attr:
                attr = fs.attr(file_id, ensure_dir=False)
                attr = normalize_attr(attr)
            thumb = cast(str, attr["thumb"])
        thumb = IMAGE_URL_CACHE[key] = flatten_image_url(thumb)
        if "thumb" in attr:
            return {"type": "image", "url": thumb}
    use_web_api = get_arg("web") not in (None, "0", "false")
    user_agent = request.headers.get("User-Agent", "")
    bytes_range = request.headers.get("Range", "")
    share_code = fs.share_code
    receive_code = fs.receive_code
    url: None | P115URL
    if bytes_range and not user_agent.lower().startswith(("vlc/", "oplayer/", "lavf/")):
        remote_addr = request.remote_addr or ""
        cooldown_key = (share_code, receive_code, file_id, remote_addr, user_agent, bytes_range)
        if cooldown_key in URL_COOLDOWN:
            return Response("too many requests", 429)
        URL_COOLDOWN[cooldown_key] = None
        cache_key = (share_code, receive_code, file_id, remote_addr, user_agent, use_web_api)
        if not (url := URL_CACHE.get(cache_key)):
            URL_CACHE[cache_key] = url = get_share_file_url(share_code, receive_code, file_id, use_web_api=use_web_api)
    else:
        url = get_share_file_url(share_code, receive_code, file_id, use_web_api=use_web_api)
    return {"type": "file", "url": str(url), "headers": url.get("headers"), "web": use_web_api}


def open_file(url, /, headers: None | Mapping = None):
    if headers is None:
        headers = {}
    else:
        headers = dict(headers)
    headers["Content-Encoding"] = "identity"
    if bytes_range := request.headers.get("Range"):
        headers["Range"] = bytes_range
    resp = urlopen(url, headers=headers)
    return Response(
        resp, 
        headers={
            k: v for k, v in resp.headers.items() 
            if k.lower() not in ("connection", "date")
        }, 
        status=resp.status, 
    )


def get_page(path: str = "", /, as_file: bool = False):
    if not root_dir or as_file or request.args.get("pickcode", "").strip():
        resp = get_url(path)
        if isinstance(resp, Response):
            return resp
        if resp.get("web"):
            return open_file(resp["url"], resp.get("headers"))
        return redirect(resp["url"])
    attr = get_attr(path)
    if isinstance(attr, Response):
        return attr
    if attr["is_directory"]:
        children = get_list(path)
        if isinstance(children, Response):
            return children
    else:
        resp = get_url(path, attr["pickcode"])
        if isinstance(resp, Response):
            return resp
        if resp.get("web"):
            return open_file(resp["url"], resp.get("headers"))
        return redirect(resp["url"])
    ancestors = attr["ancestors"]
    last_info = ancestors[-1]
    is_root = last_info["id"] == root
    parent_id = last_info["parent_id"]
    if is_root:
        header = f'<strong><a href="/?id={root}&method=list" style="border: 1px solid black; text-decoration: none">/</a></strong>'
    else:
        for i, info in enumerate(ancestors):
            if info["id"] == root:
                break
        header = f'<strong><a href="/?id={root}" style="border: 1px solid black; text-decoration: none">/</a></strong>' + "".join(
                f'<strong><a href="/?id={info["id"]}" style="border: 1px solid black; text-decoration: none">{escape(escape_name(info["name"]))}</a></strong>/' 
                for info in ancestors[i+1:-1]
            ) + f'<strong><a href="/?id={last_info["id"]}&method=list" style="border: 1px solid black; text-decoration: none">{escape(escape_name(last_info["name"]))}</a></strong>'
    return render_template_string(
        """\
  {%- extends "base_template" %}
  {%- block content %}
  {{ header | safe }}
  <table>
    <thead>
      <tr>
        <th style="width: 0px"></th>
        <th style="min-width: 100px">Name</th>
        <th>Open</th>
        <th style="width: 100px">Size</th>
        <th style="width: 30px">Attr</th>
        <th style="width: 160px">Last Modified</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        {%- if is_root %}
        <td><i class="file-type tp-folder-receive" folder-type="shared"></i></td>
        <td colspan="5"><a href="/<share" style="display: block; text-align: center; text-decoration: none; font-size: 30px">分享列表</a></td>
        {%- else %}
        <td colspan="6"><a href="/?id={{ parent_id }}" style="display: block; text-align: center; text-decoration: none; font-size: 30px">..</a></td>
        {%- endif %}
      </tr>
      {%- for attr in children %}
      <tr>
        {%- set name = attr["name"] %}
        {%- set url = attr["url"] %}
        <td><i class="file-type tp-{{ attr.get("ico") or "" }}"></i></td>
        <td style="word-wrap: break-word"><a href="{{ url | encode_uri(html_escape=True) | safe }}" style="text-decoration: none">{{ name }}</a></td>
        {%- if attr.get("is_media") %}
        {%- set platform = user_agent.get("platform", {}).get("name", "").lower() %}
        <td style="min-width: 160px; max-width: 210px" data-attr='{{ attr | json_dumps }}'>
          <a class="popup play-with-artplayer" href="{{ url | encode_uri(html_escape=True) | safe }}"><img class="icon" src="/?pic=artplayer"/><span class="popuptext">Artplayer</span></a>
          <a class="popup play-with-plyr" href="{{ url | encode_uri(html_escape=True) | safe }}"><img class="icon" src="/?pic=plyr"/><span class="popuptext">plyr</span></a>
          <a class="popup" href="iina://weblink?url={{ url | urlencode }}"><img class="icon" src="/?pic=iina" /><span class="popuptext">IINA</span></a>
          <a class="popup" href="potplayer://{{ url | encode_uri(html_escape=True) | safe }}"><img class="icon" src="/?pic=potplayer" /><span class="popuptext">PotPlayer</span></a>
          {%- if platform == "ios" %}
          <a class="popup" href="vlc-x-callback://x-callback-url/stream?url={{ url | urlencode }}"><img class="icon" src="/?pic=vlc" /><span class="popuptext">VLC</span></a>
          {%- else %}
          <a class="popup" href="vlc://{{ url | encode_uri(html_escape=True) | safe }}"><img class="icon" src="/?pic=vlc" /><span class="popuptext">VLC</span></a>
          {%- endif %}
          <a class="popup" href="filebox://play?url={{ url | urlencode }}"><img class="icon" src="/?pic=fileball" /><span class="popuptext">Fileball</span></a>
          <a class="popup" href="intent:{{ url | encode_uri(html_escape=True) | safe }}#Intent;package=com.mxtech.videoplayer.ad;S.title={{ name }};end"><img class="icon" src="/?pic=mxplayer" /><span class="popuptext">MX Player</span></a>
          <a class="popup" href="intent:{{ url | encode_uri(html_escape=True) | safe }}#Intent;package=com.mxtech.videoplayer.pro;S.title={{ name }};end"><img class="icon" src="/?pic=mxplayer-pro" /><span class="popuptext">MX Player Pro</span></a>
          <a class="popup" href="infuse://x-callback-url/play?url={{ url | urlencode }}"><img class="icon" src="/?pic=infuse" /><span class="popuptext">infuse</span></a>
          {%- if platform == "mac os" %}
          <a class="popup" href="nplayer-mac://weblink?url={{ url | urlencode }}"><img class="icon" src="/?pic=nplayer" /><span class="popuptext">nPlayer</span></a>
          {%- else %}
          <a class="popup" href="nplayer-{{ url | encode_uri(html_escape=True) | safe }}"><img class="icon" src="/?pic=nplayer" /><span class="popuptext">nPlayer</span></a>
          {%- endif %}
          <a class="popup" href="omniplayer://weblink?url={{ url | urlencode }}"><img class="icon" src="/?pic=omniplayer" /><span class="popuptext">OmniPlayer</span></a>
          <a class="popup" href="figplayer://weblink?url={{ url | urlencode }}"><img class="icon" src="/?pic=figplayer" /><span class="popuptext">Fig Player</span></a>
          <a class="popup" href="mpv://{{ url | encode_uri(html_escape=True) | safe }}"><img class="icon" src="/?pic=mpv" /><span class="popuptext">MPV</span></a>
          <a class="popup" href="stellar://play/{{ url | encode_uri(html_escape=True) | safe }}"><img class="icon" src="/?pic=stellarplayer" /><span class="popuptext">恒星播放器</span></a>
        {%- elif not attr["is_directory"] and attr.get("thumb") %}
        <td>
          <a 
            class="popup is-image" 
            data-fancybox="gallery" 
            data-caption="{{ attr["name"] }}"
            data-download-src="{{ url | encode_uri(html_escape=True) | safe }}" 
            data-src="{{ IMAGE_URL_CACHE[attr["pickcode"]] }}" 
            data-thumb-src="{{ attr["thumb"].replace("_0?", "_200?") }}" 
          >
            <img class="icon" src="/?pic=fancybox" /><span class="popuptext">fancybox</span>
          </a>
        {%- else %}
        <td>
        {%- endif %}
        </td>
        {%- if attr["is_directory"] %}
        <td style="text-align: center">--</td>
        {%- else %}
        <td style="text-align: right"><span class="popup">{{ attr["size"] | format_size }}<span class="popuptext">{{ attr["size"] }}</span></span></td>
        {%- endif %}
        <td style="text-align: center"><a href="/?id={{ attr["id"] }}&method=attr">attr</a></td>
        <td style="text-align: center">{{ (attr.get("mtime") or attr["time"]) | format_timestamp }}</td>
      </tr>
      {%- endfor %}
    </tbody>
  </table>
  {%- endblock %}""", 
        is_root=is_root, 
        parent_id=parent_id, 
        children=children, 
        header=header, 
        user_agent=detect_ua(request.headers.get("User-Agent", "")), 
        IMAGE_URL_CACHE=IMAGE_URL_CACHE, 
    )


def get_share_page(path: str = "", /, share_code: str = "", as_file: bool = False):
    if as_file:
        resp = get_share_url(path, share_code)
        if isinstance(resp, Response):
            return resp
        if resp.get("web"):
            return open_file(resp["url"], resp.get("headers"))
        return redirect(resp["url"])
    attr = get_share_attr(path, share_code)
    if isinstance(attr, Response):
        return attr
    if not attr["is_directory"]:
        resp = get_share_url(path, share_code, attr["id"])
        if isinstance(resp, Response):
            return resp
        if resp.get("web"):
            return open_file(resp["url"], resp.get("headers"))
        return redirect(resp["url"])
    children = get_share_list(path, share_code)
    if isinstance(children, Response):
        return children
    share_code = attr["share_code"]
    parts = [f'<strong><a href="/?id=0" style="border: 1px solid black; text-decoration: none">/</a></strong>']
    add_part = parts.append
    if not share_code:
       add_part(f'<strong><a href="/<share?id=0&share_code=&method=list" style="border: 1px solid black; text-decoration: none">&lt;share</a></strong>')
    else:
        add_part(f'<strong><a href="/<share?id=0&share_code=" style="border: 1px solid black; text-decoration: none">&lt;share</a></strong>/')
        ancestors = attr["ancestors"]
        if len(ancestors) > 1:
            add_part(f'<strong><a href="/<share?id=0&share_code={share_code}" style="border: 1px solid black; text-decoration: none">{share_code}</a></strong>')
            for info in ancestors[1:-1]:
                add_part(f'/<strong><a href="/<share?id={info["id"]}&share_code={share_code}" style="border: 1px solid black; text-decoration: none">{escape(escape_name(info["name"]))}</a></strong>')
            info = ancestors[-1]
            add_part(f'/<strong><a href="/<share?id={info["id"]}&share_code={share_code}&method=list" style="border: 1px solid black; text-decoration: none">{escape(escape_name(info["name"]))}</a></strong>')
        else:
            add_part(f'<strong><a href="/<share?id=0&share_code={share_code}&method=list" style="border: 1px solid black; text-decoration: none">{share_code}</a></strong>')
    return render_template_string(
        """\
  {%- extends "base_template" %}
  {%- block content %}
  {{ header | safe }}
  <table>
    <thead>
      <tr>
        <th style="width: 0px"></th>
        <th style="min-width: 100px">Name</th>
        <th style="width: 210px">Open</th>
        <th style="width: 100px">Size</th>
        <th style="width: 30px">Attr</th>
        <th style="width: 160px">Last Modified</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        {%- if not attr["share_code"] %}
        <td colspan="6"><a href="/" style="display: block; text-align: center; text-decoration: none; font-size: 30px">..</a></td>
        {%- elif attr["id"] == 0 %}
        <td colspan="6"><a href="/<share" style="display: block; text-align: center; text-decoration: none; font-size: 30px">..</a></td>
        {%- else %}
        <td colspan="6"><a href="/<share?share_code={{ attr["share_code"] }}&id={{ attr["parent_id"] }}" style="display: block; text-align: center; text-decoration: none; font-size: 30px">..</a></td>
        {%- endif %}
      </tr>
      {%- for attr in children %}
      <tr>
        {%- set name = attr["name"] %}
        {%- set url = attr["url"] %}
        <td><i class="file-type tp-{{ attr.get("ico") or "" }}"></i></td>
        <td style="word-wrap: break-word"><a href="{{ url | encode_uri(html_escape=True) | safe }}" style="text-decoration: none">{{ name }}</a></td>
        {%- if attr.get("is_media") %}
        {%- set platform = user_agent.get("platform", {}).get("name", "").lower() %}
        <td style="min-width: 160px" data-attr='{{ attr | json_dumps }}'>
          <a class="popup play-with-artplayer" href="{{ url | encode_uri(html_escape=True) | safe }}"><img class="icon" src="/?pic=artplayer" /><span class="popuptext">Artplayer</span></a>
          <a class="popup play-with-plyr" href="{{ url | encode_uri(html_escape=True) | safe }}"><img class="icon" src="/?pic=plyr" /><span class="popuptext">plyr</span></a>
          <a class="popup" href="iina://weblink?url={{ url | urlencode }}"><img class="icon" src="/?pic=iina" /><span class="popuptext">IINA</span></a>
          <a class="popup" href="potplayer://{{ url | encode_uri(html_escape=True) | safe }}"><img class="icon" src="/?pic=potplayer" /><span class="popuptext">PotPlayer</span></a>
          {%- if platform == "ios" %}
          <a class="popup" href="vlc-x-callback://x-callback-url/stream?url={{ url | urlencode }}"><img class="icon" src="/?pic=vlc" /><span class="popuptext">VLC</span></a>
          {%- else %}
          <a class="popup" href="vlc://{{ url | encode_uri(html_escape=True) | safe }}"><img class="icon" src="/?pic=vlc" /><span class="popuptext">VLC</span></a>
          {%- endif %}
          <a class="popup" href="filebox://play?url={{ url | urlencode }}"><img class="icon" src="/?pic=fileball" /><span class="popuptext">Fileball</span></a>
          <a class="popup" href="intent:{{ url | encode_uri(html_escape=True) | safe }}#Intent;package=com.mxtech.videoplayer.ad;S.title={{ name }};end"><img class="icon" src="/?pic=mxplayer" /><span class="popuptext">MX Player</span></a>
          <a class="popup" href="intent:{{ url | encode_uri(html_escape=True) | safe }}#Intent;package=com.mxtech.videoplayer.pro;S.title={{ name }};end"><img class="icon" src="/?pic=mxplayer-pro" /><span class="popuptext">MX Player Pro</span></a>
          <a class="popup" href="infuse://x-callback-url/play?url={{ url | urlencode }}"><img class="icon" src="/?pic=infuse" /><span class="popuptext">infuse</span></a>
          {%- if platform == "mac os" %}
          <a class="popup" href="nplayer-mac://weblink?url={{ url | urlencode }}"><img class="icon" src="/?pic=nplayer" /><span class="popuptext">nPlayer</span></a>
          {%- else %}
          <a class="popup" href="nplayer-{{ url | encode_uri(html_escape=True) | safe }}"><img class="icon" src="/?pic=nplayer" /><span class="popuptext">nPlayer</span></a>
          {%- endif %}
          <a class="popup" href="omniplayer://weblink?url={{ url | urlencode }}"><img class="icon" src="/?pic=omniplayer" /><span class="popuptext">OmniPlayer</span></a>
          <a class="popup" href="figplayer://weblink?url={{ url | urlencode }}"><img class="icon" src="/?pic=figplayer" /><span class="popuptext">Fig Player</span></a>
          <a class="popup" href="mpv://{{ url | encode_uri(html_escape=True) | safe }}"><img class="icon" src="/?pic=mpv" /><span class="popuptext">MPV</span></a>
          <a class="popup" href="stellar://play/{{ url | encode_uri(html_escape=True) | safe }}"><img class="icon" src="/?pic=stellarplayer" /><span class="popuptext">恒星播放器</span></a>
        {%- elif not attr["is_directory"] and attr.get("thumb") %}
        <td>
          <a 
            class="popup is-image" 
            data-fancybox="gallery" 
            data-caption="{{ attr["name"] }}"
            data-download-src="{{ url | encode_uri(html_escape=True) | safe }}" 
            data-src="{{ IMAGE_URL_CACHE[(attr["share_code"], attr["id"])] }}" 
            data-thumb-src="{{ attr["thumb"].replace("_0?", "_200?") }}" 
          >
            <img class="icon" src="/?pic=fancybox" /><span class="popuptext">fancybox</span>
          </a>
        {%- else %}
        <td>
        {%- endif %}
        </td>
        {%- if attr["is_directory"] and not attr["size"] %}
        <td style="text-align: center">--</td>
        {%- else %}
        <td style="text-align: right"><span class="popup">{{ attr["size"] | format_size }}<span class="popuptext">{{ attr["size"] }}</span></span></td>
        {%- endif %}
        <td style="text-align: center"><a href="/<share?share_code={{ attr['share_code'] }}&id={{ attr["id"] }}&method=attr">attr</a></td>
        <td style="text-align: center">{{ (attr.get("mtime") or attr["time"]) | format_timestamp }}</td>
      </tr>
      {%- endfor %}
    </tbody>
  </table>
  {%- endblock %}""", 
        attr=attr, 
        children=children, 
        header="".join(parts), 
        user_agent=detect_ua(request.headers.get("User-Agent", "")), 
        IMAGE_URL_CACHE=IMAGE_URL_CACHE, 
    )


flask_app.template_filter("encode_uri")(encode_uri)


@flask_app.template_filter("json_dumps")
def json_dumps(data, /) -> str:
    return dumps(data).decode("utf-8").replace("'", "&apos;")


@flask_app.template_filter("format_size")
def format_size(
    n: int, 
    /, 
    unit: str = "", 
    precision: int = 2, 
) -> str:
    "scale bytes to its proper byte format"
    if unit == "B" or not unit and n < 1024:
        return f"{n} B"
    b = 1
    b2 = 1024
    for u in ["K", "M", "G", "T", "P", "E", "Z", "Y"]:
        b, b2 = b2, b2 << 10
        if u == unit if unit else n < b2:
            break
    return f"%.{precision}f {u}B" % (n / b)


@flask_app.template_filter("format_timestamp")
def format_timestamp(ts: int | float, /) -> str:
    return str(datetime.fromtimestamp(ts))


@flask_app.get("/")
@redirect_exception_response
def index():
    match request.args.get("pic"):
        case "favicon":
            return send_file(BytesIO(b'<svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><rect width="16" height="16" rx="8" fill="#2777F8"/><path d="M4.5874 6.99646C4.60631 6.96494 4.61891 6.92713 4.63152 6.90192C5.17356 5.81784 5.7219 4.74006 6.25764 3.64969C6.38999 3.37867 6.60429 3.25891 6.88792 3.25891H9.39012C9.71786 3.25891 10.0582 3.25261 10.3859 3.25891C10.7326 3.26521 11.0729 3.19589 11.4007 3.08243C11.4259 3.07613 11.4637 3.05722 11.4826 3.06352C11.5646 3.06983 11.6087 3.15807 11.5772 3.24C11.4196 3.56145 11.2557 3.88289 11.0793 4.20433C10.9532 4.43123 10.7515 4.55098 10.4994 4.55098H7.72618C7.42364 4.55098 7.20305 4.68334 7.077 4.96697C6.95094 5.23168 6.81228 5.49009 6.67992 5.75481C6.66101 5.78002 6.65471 5.80523 6.6358 5.83674C6.81858 5.88087 7.00767 5.91238 7.18414 5.94389C7.73249 6.06365 8.29343 6.1834 8.81026 6.4166C9.5792 6.75695 10.2158 7.25487 10.6444 7.97969C10.9091 8.42088 11.0667 8.88098 11.0982 9.3915C11.1927 10.5638 10.7578 11.5219 9.88176 12.2845C9.28296 12.8013 8.58336 13.1038 7.80812 13.2488C7.35432 13.3308 6.89422 13.3559 6.44042 13.3244C5.92359 13.2803 5.42567 13.1479 4.95927 12.9084C4.95296 12.9022 4.94036 12.9022 4.91515 12.8833C5.00969 12.8895 5.07271 12.9022 5.14205 12.9022C5.85426 12.9652 6.54756 12.8833 7.21566 12.6564C7.79551 12.4546 8.32494 12.1584 8.74723 11.6857C9.09388 11.295 9.28927 10.8475 9.35229 10.3306C9.44684 9.61841 9.18212 9.03855 8.72202 8.52173C8.24931 8.00489 7.66315 7.67716 7.00767 7.45655C6.49715 7.28639 5.98662 7.16663 5.45088 7.091C5.17986 7.04688 4.90254 7.02167 4.63152 6.99646C4.61891 7.00906 4.61261 7.00906 4.5874 6.99646Z" fill="white"/></svg>'), mimetype="image/svg+xml")
        case "fancybox":
            return send_file(BytesIO(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 37 37"><circle cx="18.5" cy="18.5" r="18.5" fill="#fff"/><circle cx="18.5" cy="15.5" r="1.1"/><circle cx="18.5" cy="22" r="1.1"/><circle cx="18.5" cy="28.5" r="1.1"/><path d="M27 11.2a2.9 2.9 0 0 1-1.7.8l-4.5-3h-.5l-2 .6-1.7-.5h-.8a118.3 118.3 0 0 1-5 3l-.8-.9c-.5-.5-.5-1.3-.5-2v-4l.3-1.4L11 3l1.9.8c.2.3 2 1.5 2.8 2l2-.2H19l1.4.3h.5l3-2 1.8-1 1.5.5.3 1.4v4.6c0 1-.4 1.6-.6 1.8Zm-22.2-5A18.5 18.5 0 0 0 0 18.4a18.5 18.5 0 0 0 13.8 17.8l-3.4-11zm27.4 0-5.7 19.1-3.1 11A18.5 18.5 0 0 0 37 18.5a18.5 18.5 0 0 0-4.9-12.4z"/></svg>'), mimetype="image/svg+xml")
        case "figplayer":
            return redirect("https://is1-ssl.mzstatic.com/image/thumb/Purple211/v4/f5/3b/9d/f53b9d10-b126-16ba-9f55-632135bfede3/AppIcon-0-0-85-220-0-0-4-0-2x.png/434x0w.webp")
        case "fileball":
            return send_file(BytesIO(b'<svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M0 6.5C0 2.91015 2.91015 0 6.5 0H25.5C29.0899 0 32 2.91015 32 6.5V25.5C32 29.0899 29.0899 32 25.5 32H6.5C2.91015 32 0 29.0899 0 25.5V6.5Z" fill="#FFCA28"/><path fill-rule="evenodd" clip-rule="evenodd" d="M7.75 7.875C6.50736 7.875 5.5 8.88236 5.5 10.125V21.875C5.5 23.1176 6.50736 24.125 7.75 24.125H24.25C25.4926 24.125 26.5 23.1176 26.5 21.875V12.025C26.5 10.7726 25.4774 9.7613 24.2251 9.77514L15.3125 9.875L13.1891 8.17631C12.9453 7.98126 12.6424 7.875 12.3302 7.875H7.75ZM16 20.7917C17.933 20.7917 19.5 19.2247 19.5 17.2917C19.5 15.3587 17.933 13.7917 16 13.7917C14.067 13.7917 12.5 15.3587 12.5 17.2917C12.5 19.2247 14.067 20.7917 16 20.7917Z" fill="white"/><path d="M15.5623 15.8389C15.476 15.7814 15.365 15.776 15.2735 15.825C15.1821 15.8739 15.125 15.9692 15.125 16.0729V18.3229C15.125 18.4267 15.1821 18.522 15.2735 18.5709C15.365 18.6199 15.476 18.6145 15.5623 18.557L17.2498 17.432C17.328 17.3798 17.375 17.292 17.375 17.1979C17.375 17.1039 17.328 17.0161 17.2498 16.9639L15.5623 15.8389Z" fill="white"/></svg>'), mimetype="image/svg+xml")
        case "iina":
            return send_file(BytesIO(b'<svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg"><rect y="0.000244141" width="32" height="32" rx="7.51807" fill="url(#paint0_linear_10408_1309)"/><rect x="5.5" y="13.3784" width="2.00482" height="5.35904" rx="1.00241" fill="url(#paint1_linear_10408_1309)"/><rect x="9.02173" y="11.7976" width="2.62169" height="7.78795" rx="1.31084" fill="url(#paint2_linear_10408_1309)"/><path d="M13.2881 14.1557C13.2881 10.8731 13.2881 9.23184 14.1967 8.44754C14.4469 8.23163 14.7356 8.06495 15.0476 7.95629C16.1812 7.56155 17.6025 8.38219 20.4453 10.0235L23.8046 11.9629C26.6474 13.6042 28.0687 14.4248 28.2937 15.6039C28.3556 15.9285 28.3556 16.2618 28.2937 16.5864C28.0687 17.7654 26.6474 18.5861 23.8046 20.2274L20.4453 22.1668C17.6025 23.8081 16.1812 24.6287 15.0476 24.234C14.7356 24.1253 14.4469 23.9587 14.1967 23.7427C13.2881 22.9584 13.2881 21.3172 13.2881 18.0346L13.2881 14.1557Z" fill="url(#paint3_linear_10408_1309)"/><defs><linearGradient id="paint0_linear_10408_1309" x1="16" y1="0.000244141" x2="16" y2="32.0002" gradientUnits="userSpaceOnUse"><stop stop-color="#4E4E4E"/><stop offset="1" stop-color="#262525"/></linearGradient><linearGradient id="paint1_linear_10408_1309" x1="5.5" y1="16.0387" x2="7.50482" y2="15.7495" gradientUnits="userSpaceOnUse"><stop stop-color="#8148EF"/><stop offset="1" stop-color="#4A2CC4"/></linearGradient><linearGradient id="paint2_linear_10408_1309" x1="9.02173" y1="15.6636" x2="11.6536" y2="15.322" gradientUnits="userSpaceOnUse"><stop stop-color="#4435E1"/><stop offset="1" stop-color="#3E5EFA"/></linearGradient><linearGradient id="paint3_linear_10408_1309" x1="25.4842" y1="15.653" x2="13.4168" y2="12.8771" gradientUnits="userSpaceOnUse"><stop stop-color="#00DDFE"/><stop offset="1" stop-color="#0092FA"/></linearGradient></defs></svg>'), mimetype="image/svg+xml")
        case "infuse":
            return redirect("https://static.firecore.com/images/infuse/infuse-icon_2x.png")
        case "mpv":
            return send_file(BytesIO(b'<svg xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:cc="http://creativecommons.org/ns#" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:svg="http://www.w3.org/2000/svg" xmlns="http://www.w3.org/2000/svg" version="1.1" viewBox="0 0 55.898387 55.898387" height="59.62495" width="59.62495"><metadata><rdf:RDF><cc:Work rdf:about=""><dc:format>image/svg+xml</dc:format><dc:type rdf:resource="http://purl.org/dc/dcmitype/StillImage" /><dc:title>Logo of mpv</dc:title></cc:Work></rdf:RDF></metadata><g transform="translate(-4.050806,-992.41299)" id="layer1"><circle r="27.949194" cy="1020.3622" cx="32" id="path4380" style="opacity:1;fill:#e5e5e5;fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:0.10161044;stroke-linecap:round;stroke-linejoin:bevel;stroke-miterlimit:1;stroke-dasharray:none;stroke-dashoffset:0;stroke-opacity:0.99215686" /><circle r="25.950588" cy="1019.5079" cx="32.727058" id="path4390" style="opacity:1;fill:#672168;fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:0.0988237;stroke-linecap:round;stroke-linejoin:bevel;stroke-miterlimit:1;stroke-dasharray:none;stroke-dashoffset:0;stroke-opacity:0.99215686" /><circle r="20" cy="1017.7957" cx="34.224396" id="path4400" style="opacity:1;fill:#420143;fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:0.1;stroke-linecap:round;stroke-linejoin:bevel;stroke-miterlimit:1;stroke-dasharray:none;stroke-dashoffset:0;stroke-opacity:0.99215686" /><path id="path4412" d="m 44.481446,1020.4807 a 12.848894,12.848894 0 0 1 -12.84889,12.8489 12.848894,12.848894 0 0 1 -12.8489,-12.8489 12.848894,12.848894 0 0 1 12.8489,-12.8489 12.848894,12.848894 0 0 1 12.84889,12.8489 z" style="fill:#dddbdd;fill-opacity:1;fill-rule:evenodd;stroke:none;stroke-width:0.1;stroke-linecap:butt;stroke-linejoin:miter;stroke-miterlimit:4;stroke-dasharray:none;stroke-opacity:1" /><path id="path4426" d="m 28.374316,1014.709 v 11.4502 l 9.21608,-5.8647 z" style="fill:#691f69;fill-opacity:1;fill-rule:evenodd;stroke:none;stroke-width:0.1;stroke-linecap:butt;stroke-linejoin:miter;stroke-miterlimit:4;stroke-dasharray:none;stroke-opacity:1" /></g></svg>'), mimetype="image/svg+xml")
        case "mxplayer":
            return send_file(BytesIO(b'<svg width="100px" viewBox="0 0 100 100" height="100px" version="1.1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><g id="svgg"><path id="path0" d="M47.333 2.447 C 44.804 2.654,41.449 3.238,37.838 4.099 C 36.827 4.340,34.775 5.042,32.667 5.869 C 31.213 6.440,27.478 8.258,26.784 8.733 C 26.436 8.972,26.090 9.167,26.015 9.167 C 25.624 9.167,20.550 12.838,19.003 14.240 C 16.084 16.885,12.607 20.793,11.216 22.991 C 10.894 23.500,10.494 24.067,10.329 24.250 C 10.163 24.433,9.804 25.016,9.531 25.545 C 9.258 26.075,8.953 26.606,8.853 26.726 C 8.267 27.432,6.137 32.182,5.232 34.800 C 2.837 41.731,1.961 51.320,3.142 57.667 C 3.321 58.629,3.592 60.129,3.743 61.000 C 3.963 62.269,5.332 66.789,5.990 68.417 C 6.440 69.530,8.141 73.073,8.631 73.917 C 8.951 74.467,9.401 75.254,9.632 75.667 C 9.863 76.079,10.364 76.829,10.747 77.333 C 11.129 77.837,11.486 78.362,11.540 78.500 C 12.001 79.669,18.426 86.557,20.168 87.750 C 20.570 88.025,21.086 88.422,21.315 88.632 C 21.842 89.116,25.549 91.634,25.950 91.780 C 26.115 91.840,26.558 92.098,26.935 92.353 C 27.956 93.045,31.932 94.904,33.876 95.600 C 42.948 98.843,51.123 99.447,60.583 97.570 C 62.142 97.261,63.979 96.823,64.667 96.597 C 67.249 95.747,68.898 95.147,69.810 94.724 C 70.327 94.484,71.275 94.046,71.917 93.749 C 72.558 93.453,73.496 92.965,74.000 92.665 C 74.504 92.365,75.254 91.933,75.667 91.706 C 76.079 91.478,76.792 91.015,77.250 90.676 C 77.708 90.338,78.196 90.018,78.333 89.965 C 80.371 89.185,88.473 81.008,90.417 77.771 C 90.600 77.466,91.045 76.774,91.405 76.233 C 92.525 74.553,93.455 72.785,95.077 69.250 C 98.036 62.806,99.454 52.414,98.443 44.583 C 98.289 43.392,98.119 42.079,98.065 41.667 C 97.643 38.416,95.090 31.158,93.200 27.835 C 92.861 27.238,92.533 26.629,92.473 26.482 C 92.412 26.335,91.999 25.666,91.556 24.996 C 91.113 24.327,90.675 23.660,90.583 23.516 C 88.060 19.536,82.404 13.785,78.333 11.062 C 77.921 10.786,77.246 10.330,76.833 10.050 C 75.738 9.306,72.984 7.716,72.417 7.500 C 72.148 7.398,71.250 6.985,70.422 6.582 C 69.594 6.179,68.467 5.701,67.917 5.520 C 67.367 5.339,66.242 4.954,65.417 4.665 C 60.715 3.018,52.563 2.018,47.333 2.447 M38.562 30.863 C 39.399 31.337,40.683 32.076,41.417 32.504 C 42.150 32.931,43.087 33.468,43.500 33.695 C 43.913 33.923,45.337 34.731,46.667 35.492 C 47.996 36.252,50.658 37.774,52.583 38.875 C 54.508 39.976,56.833 41.307,57.750 41.835 C 58.667 42.362,61.104 43.749,63.167 44.916 C 65.229 46.084,67.254 47.243,67.667 47.492 C 68.079 47.741,69.467 48.533,70.750 49.251 C 73.449 50.762,73.833 51.063,73.833 51.664 C 73.833 52.380,73.934 52.317,60.167 60.158 C 52.879 64.309,46.167 68.140,45.250 68.673 C 36.899 73.527,36.862 73.544,36.241 72.922 L 35.830 72.511 35.873 51.574 L 35.917 30.637 36.310 30.319 C 36.844 29.886,36.837 29.884,38.562 30.863 " stroke="none" fill="#3c8cec" fill-rule="evenodd"></path></g></svg>'), mimetype="image/svg+xml")
        case "mxplayer-pro":
            return send_file(BytesIO(b'<svg width="100px" viewBox="0 0 100 100" height="100px" version="1.1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><g id="svgg"><path id="path0" d="M47.333 2.447 C 44.804 2.654,41.449 3.238,37.838 4.099 C 36.827 4.340,34.775 5.042,32.667 5.869 C 31.213 6.440,27.478 8.258,26.784 8.733 C 26.436 8.972,26.090 9.167,26.015 9.167 C 25.624 9.167,20.550 12.838,19.003 14.240 C 16.084 16.885,12.607 20.793,11.216 22.991 C 10.894 23.500,10.494 24.067,10.329 24.250 C 10.163 24.433,9.804 25.016,9.531 25.545 C 9.258 26.075,8.953 26.606,8.853 26.726 C 8.267 27.432,6.137 32.182,5.232 34.800 C 2.837 41.731,1.961 51.320,3.142 57.667 C 3.321 58.629,3.592 60.129,3.743 61.000 C 3.963 62.269,5.332 66.789,5.990 68.417 C 6.440 69.530,8.141 73.073,8.631 73.917 C 8.951 74.467,9.401 75.254,9.632 75.667 C 9.863 76.079,10.364 76.829,10.747 77.333 C 11.129 77.837,11.486 78.362,11.540 78.500 C 12.001 79.669,18.426 86.557,20.168 87.750 C 20.570 88.025,21.086 88.422,21.315 88.632 C 21.842 89.116,25.549 91.634,25.950 91.780 C 26.115 91.840,26.558 92.098,26.935 92.353 C 27.956 93.045,31.932 94.904,33.876 95.600 C 42.948 98.843,51.123 99.447,60.583 97.570 C 62.142 97.261,63.979 96.823,64.667 96.597 C 67.249 95.747,68.898 95.147,69.810 94.724 C 70.327 94.484,71.275 94.046,71.917 93.749 C 72.558 93.453,73.496 92.965,74.000 92.665 C 74.504 92.365,75.254 91.933,75.667 91.706 C 76.079 91.478,76.792 91.015,77.250 90.676 C 77.708 90.338,78.196 90.018,78.333 89.965 C 80.371 89.185,88.473 81.008,90.417 77.771 C 90.600 77.466,91.045 76.774,91.405 76.233 C 92.525 74.553,93.455 72.785,95.077 69.250 C 98.036 62.806,99.454 52.414,98.443 44.583 C 98.289 43.392,98.119 42.079,98.065 41.667 C 97.643 38.416,95.090 31.158,93.200 27.835 C 92.861 27.238,92.533 26.629,92.473 26.482 C 92.412 26.335,91.999 25.666,91.556 24.996 C 91.113 24.327,90.675 23.660,90.583 23.516 C 88.060 19.536,82.404 13.785,78.333 11.062 C 77.921 10.786,77.246 10.330,76.833 10.050 C 75.738 9.306,72.984 7.716,72.417 7.500 C 72.148 7.398,71.250 6.985,70.422 6.582 C 69.594 6.179,68.467 5.701,67.917 5.520 C 67.367 5.339,66.242 4.954,65.417 4.665 C 60.715 3.018,52.563 2.018,47.333 2.447 M38.562 30.863 C 39.399 31.337,40.683 32.076,41.417 32.504 C 42.150 32.931,43.087 33.468,43.500 33.695 C 43.913 33.923,45.337 34.731,46.667 35.492 C 47.996 36.252,50.658 37.774,52.583 38.875 C 54.508 39.976,56.833 41.307,57.750 41.835 C 58.667 42.362,61.104 43.749,63.167 44.916 C 65.229 46.084,67.254 47.243,67.667 47.492 C 68.079 47.741,69.467 48.533,70.750 49.251 C 73.449 50.762,73.833 51.063,73.833 51.664 C 73.833 52.380,73.934 52.317,60.167 60.158 C 52.879 64.309,46.167 68.140,45.250 68.673 C 36.899 73.527,36.862 73.544,36.241 72.922 L 35.830 72.511 35.873 51.574 L 35.917 30.637 36.310 30.319 C 36.844 29.886,36.837 29.884,38.562 30.863 " stroke="none" fill="#3c8cec" fill-rule="evenodd"></path></g><text font-weight="bold" transform="matrix(0.663942 0 0 0.582329 8.8976 40.4465)" stroke="#000" xml:space="preserve" text-anchor="start" font-family="Noto Sans JP" font-size="24" id="svg_1" y="80.42001" x="39.18799" stroke-width="0" fill="#ffffff">PRO</text></svg>'), mimetype="image/svg+xml")
        case "nplayer":
            return send_file(BytesIO(b'<svg width="277" height="309" viewBox="0 0 277 309" fill="none" xmlns="http://www.w3.org/2000/svg"><path opacity="0.672154" d="M260.201 177.907L49.6985 303.216C34.117 312.492 13.9456 307.415 4.64436 291.876C1.60485 286.799 0 280.995 0 275.082L0 33.6449C0 15.5487 14.7106 0.878906 32.8571 0.878906C38.421 0.878906 43.8938 2.28787 48.7623 4.97371L259.265 121.102C275.144 129.862 280.895 149.799 272.111 165.634C269.299 170.703 265.189 174.938 260.201 177.907Z" fill="#D8D8D8"/><mask id="mask0_66_11681" style="mask-type:luminance" maskUnits="userSpaceOnUse" x="0" y="0" width="277" height="308"><path d="M260.201 177.907L49.6985 303.216C34.117 312.492 13.9456 307.415 4.64436 291.876C1.60485 286.799 0 280.995 0 275.082L0 33.6449C0 15.5487 14.7106 0.878906 32.8571 0.878906C38.421 0.878906 43.8938 2.28787 48.7623 4.97371L259.265 121.102C275.144 129.862 280.895 149.799 272.111 165.634C269.299 170.703 265.189 174.938 260.201 177.907Z" fill="white"/></mask><g mask="url(#mask0_66_11681)"><path d="M-19.7148 263.128L269.428 184.489V269.681L-19.7148 354.872V263.128Z" fill="url(#paint0_linear_66_11681)"/><path d="M-19.7148 169.139L295.784 85.1509V177.936L-19.7148 269.681L-19.7148 169.139Z" fill="url(#paint1_linear_66_11681)"/><path d="M-19.7148 75.5481L269.428 -1.88672V91.7038L-19.7148 172.424V75.5481Z" fill="#93F12E"/><path d="M-19.7148 -19.863L269.428 -97.2979V-1.8866L-19.7148 75.4581L-19.7148 -19.863Z" fill="#FDEC16"/></g><defs><linearGradient id="paint0_linear_66_11681" x1="82.5056" y1="342.89" x2="242.723" y2="223.789" gradientUnits="userSpaceOnUse"><stop stop-color="#FF452E"/><stop offset="1" stop-color="#FF2015"/></linearGradient><linearGradient id="paint1_linear_66_11681" x1="-203.313" y1="266.912" x2="-119.436" y2="481.32" gradientUnits="userSpaceOnUse"><stop stop-color="#43DCFF"/><stop offset="0.195856" stop-color="#3ED8FE"/><stop offset="0.558535" stop-color="#17C2ED"/><stop offset="1" stop-color="#0B9BE2"/></linearGradient></defs></svg>'), mimetype="image/svg+xml")
        case "omniplayer":
            return redirect("https://cdn.okaapps.com/resource/icon/app_icons/omniplayer.png")
        case "potplayer":
            return send_file(BytesIO(b'<svg width="256pt" height="256pt" version="1.1" viewBox="0 0 256 256" xmlns="http://www.w3.org/2000/svg"><g id="#f8d714ff" fill="#f8d714"><path d="m14.48 5.74c3.4-1.07 7.01-0.71 10.52-0.77 70.34 0.02 140.68-0.01 211.02 0.01 5.46-0.33 10.91 2.69 13.41 7.57 2.08 3.81 1.52 8.3 1.6 12.47-0.01 68.66-0.01 137.32 0 205.98-0.06 4.38 0.49 9.15-1.94 13.05-2.6 4.58-7.88 7.21-13.09 6.96-71.98 0.04-143.96 0.03-215.93 0-5.25 0.27-10.56-2.37-13.17-6.99-2.42-3.88-1.87-8.63-1.93-12.99 0.02-70.34-0.01-140.67 0.01-211.01-0.43-6.21 3.59-12.31 9.5-14.28m107.84 33.69c-14.96 1.39-29.3 8.36-39.65 19.25-9.91 10.28-16.17 24-17.37 38.23-1.18 12.94 1.74 26.23 8.31 37.46 7.78 13.44 20.66 23.86 35.48 28.54 14.49 4.68 30.65 3.88 44.61-2.22 14.42-6.23 26.32-18.03 32.68-32.4 6.61-14.74 7.24-32.04 1.71-47.22-4.72-13.25-14.04-24.78-25.96-32.24-11.74-7.43-25.99-10.76-39.81-9.4m-58.68 142.57c0 11.33-0.01 22.66 0 34h7.36c0-4.13 0-8.26 0.01-12.38 4.89-0.21 10.28 0.89 14.7-1.78 6.64-4.22 5.84-16.13-1.84-18.76-6.53-2.02-13.51-0.71-20.23-1.08m31.36-0.02v34.03c2.21-0.01 4.43-0.02 6.64-0.03 0.01-11.3-0.09-22.6 0.05-33.89-2.23-0.1-4.46-0.07-6.69-0.11m14.91 9.93c-2.42 1.25-3.4 3.9-4.08 6.36 2.18 0.12 4.38 0.06 6.57 0.15 0.83-4.08 5.95-5.29 9.03-2.88 0.68 1.52 1.23 4.02-0.79 4.76-3.79 1.3-8.04 0.88-11.69 2.64-4.94 2.35-4.8 10.64 0.13 12.94 4.31 1.97 9.56 1.01 13.21-1.89 0.26 3.53 4.7 1.48 7.03 2.02-1.44-6.71-0.21-13.61-0.86-20.38-0.19-2.04-1.85-3.62-3.67-4.32-4.76-1.82-10.32-1.73-14.88 0.6m52.44 1.46c-4.44 4.27-4.97 11.44-2.64 16.91 2.61 6 10.47 8.19 16.25 5.72 3.31-1.17 5.09-4.4 6.6-7.34-1.94-0.02-3.87-0.03-5.8 0-1.88 2.97-5.81 4.17-8.96 2.5-2.29-1.05-2.56-3.78-2.98-5.95 6.09-0.03 12.18 0 18.27-0.01-0.37-3.83-0.81-7.91-3.32-11.01-4.08-5.29-12.77-5.47-17.42-0.82m30.89 1.79c0.06-1.38 0.12-2.77 0.16-4.15-2.13-0.01-4.27-0.01-6.4-0.01v25.01c2.21-0.01 4.43-0.03 6.64-0.04 0.32-5.5-0.92-11.27 1.04-16.55 1.5-3.15 5.26-3.51 8.33-3.15-0.01-2.14-0.01-4.28-0.02-6.42-3.98 0.03-7.62 1.94-9.75 5.31m-61.66-4.17c3.01 8.67 6.35 17.24 9.1 25.99 0.23 3.74-3.99 4.08-6.67 3.4-0.01 1.73-0.01 3.47-0.01 5.2 4.41 0.8 10.45 0.5 12.22-4.49 3.74-9.96 7.1-20.06 10.66-30.08-2.29-0.01-4.58-0.01-6.86-0.01-1.82 6.03-3.63 12.06-5.5 18.06-2.14-5.92-3.89-11.98-5.73-18.01-2.4-0.05-4.81-0.05-7.21-0.06z"/><path d="m111.13 74.07c1.31-0.17 2.41 0.69 3.5 1.25 13.64 8.39 27.33 16.71 41 25.05 1.27 0.84 3.17 1.74 2.53 3.64-1.02 1.06-2.3 1.82-3.55 2.58-13.78 8.18-27.43 16.6-41.23 24.75-1.21 1.08-3.48 0.59-3.29-1.3-0.22-17.35-0.01-34.71-0.1-52.06 0.12-1.36-0.28-3.1 1.14-3.91z"/><path d="m71 187.63c3.41 0.08 7.12-0.52 10.26 1.13 2.82 2.15 2.47 7.87-1.24 8.92-2.98 0.55-6.02 0.3-9.02 0.31v-10.36z"/><path d="m164.77 200.98c0.41-3.09 2.66-6.44 6.2-5.83 3.27-0.26 4.83 3.13 5.25 5.84-3.82 0.02-7.64 0.02-11.45-0.01z"/><path d="m112.05 208c1.75-3.68 6.75-2.65 10.01-3.99-0.17 2.65 0.47 6.23-2.36 7.73-2.87 2.1-8.98 0.72-7.65-3.74z"/></g><g id="#ffffffff"><path d="m122.32 39.43c13.82-1.36 28.07 1.97 39.81 9.4 11.92 7.46 21.24 18.99 25.96 32.24 5.53 15.18 4.9 32.48-1.71 47.22-6.36 14.37-18.26 26.17-32.68 32.4-13.96 6.1-30.12 6.9-44.61 2.22-14.82-4.68-27.7-15.1-35.48-28.54-6.57-11.23-9.49-24.52-8.31-37.46 1.2-14.23 7.46-27.95 17.37-38.23 10.35-10.89 24.69-17.86 39.65-19.25m-11.19 34.64c-1.42 0.81-1.02 2.55-1.14 3.91 0.09 17.35-0.12 34.71 0.1 52.06-0.19 1.89 2.08 2.38 3.29 1.3 13.8-8.15 27.45-16.57 41.23-24.75 1.25-0.76 2.53-1.52 3.55-2.58 0.64-1.9-1.26-2.8-2.53-3.64-13.67-8.34-27.36-16.66-41-25.05-1.09-0.56-2.19-1.42-3.5-1.25z" fill="#fff"/></g><g id="#222222ff" fill="#222"><path d="m63.64 182c6.72 0.37 13.7-0.94 20.23 1.08 7.68 2.63 8.48 14.54 1.84 18.76-4.42 2.67-9.81 1.57-14.7 1.78-0.01 4.12-0.01 8.25-0.01 12.38h-7.36c-0.01-11.34 0-22.67 0-34m7.36 5.63v10.36c3-0.01 6.04 0.24 9.02-0.31 3.71-1.05 4.06-6.77 1.24-8.92-3.14-1.65-6.85-1.05-10.26-1.13z"/><path d="m95 181.98c2.23 0.04 4.46 0.01 6.69 0.11-0.14 11.29-0.04 22.59-0.05 33.89-2.21 0.01-4.43 0.02-6.64 0.03v-34.03z"/><path d="m109.91 191.91c4.56-2.33 10.12-2.42 14.88-0.6 1.82 0.7 3.48 2.28 3.67 4.32 0.65 6.77-0.58 13.67 0.86 20.38-2.33-0.54-6.77 1.51-7.03-2.02-3.65 2.9-8.9 3.86-13.21 1.89-4.93-2.3-5.07-10.59-0.13-12.94 3.65-1.76 7.9-1.34 11.69-2.64 2.02-0.74 1.47-3.24 0.79-4.76-3.08-2.41-8.2-1.2-9.03 2.88-2.19-0.09-4.39-0.03-6.57-0.15 0.68-2.46 1.66-5.11 4.08-6.36m2.14 16.09c-1.33 4.46 4.78 5.84 7.65 3.74 2.83-1.5 2.19-5.08 2.36-7.73-3.26 1.34-8.26 0.31-10.01 3.99z"/><path d="m162.35 193.37c4.65-4.65 13.34-4.47 17.42 0.82 2.51 3.1 2.95 7.18 3.32 11.01-6.09 0.01-12.18-0.02-18.27 0.01 0.42 2.17 0.69 4.9 2.98 5.95 3.15 1.67 7.08 0.47 8.96-2.5 1.93-0.03 3.86-0.02 5.8 0-1.51 2.94-3.29 6.17-6.6 7.34-5.78 2.47-13.64 0.28-16.25-5.72-2.33-5.47-1.8-12.64 2.64-16.91m2.42 7.61c3.81 0.03 7.63 0.03 11.45 0.01-0.42-2.71-1.98-6.1-5.25-5.84-3.54-0.61-5.79 2.74-6.2 5.83z"/><path d="m193.24 195.16c2.13-3.37 5.77-5.28 9.75-5.31 0.01 2.14 0.01 4.28 0.02 6.42-3.07-0.36-6.83 0-8.33 3.15-1.96 5.28-0.72 11.05-1.04 16.55-2.21 0.01-4.43 0.03-6.64 0.04v-25.01c2.13 0 4.27 0 6.4 0.01-0.04 1.38-0.1 2.77-0.16 4.15z"/><path d="m131.58 190.99c2.4 0.01 4.81 0.01 7.21 0.06 1.84 6.03 3.59 12.09 5.73 18.01 1.87-6 3.68-12.03 5.5-18.06 2.28 0 4.57 0 6.86 0.01-3.56 10.02-6.92 20.12-10.66 30.08-1.77 4.99-7.81 5.29-12.22 4.49 0-1.73 0-3.47 0.01-5.2 2.68 0.68 6.9 0.34 6.67-3.4-2.75-8.75-6.09-17.32-9.1-25.99z"/></g></svg>'), mimetype="image/svg+xml")
        case "stellarplayer":
            return send_file(BytesIO(b'<svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg"><g id="logo"><rect width="28" height="28" rx="6.22222" fill="url(#paint0_linear_87_144)"/><g><g id="&#231;&#188;&#150;&#231;&#187;&#132; 21"><path fill-rule="evenodd" clip-rule="evenodd" d="M10.0555 19.9097C9.0377 19.303 8.03054 18.677 7.04678 18.0162C6.05833 17.3521 4.97744 16.6761 4.15079 15.8125C3.44858 15.0788 3.13926 14.1435 3.52322 13.1783C3.74487 12.6215 4.14919 12.289 4.61728 11.9388C6.16872 10.7778 7.90225 9.84974 9.61487 8.94708C10.8692 8.28582 12.1528 7.679 13.4606 7.1278C14.3868 6.73734 11.3384 20.6746 10.0555 19.9097Z" fill="url(#paint1_linear_87_144)"/><path fill-rule="evenodd" clip-rule="evenodd" d="M20.9028 12.135C20.9408 13.2208 20.9431 14.3074 20.9225 15.3929C20.9033 16.4679 20.8302 17.5411 20.7219 18.6099C20.5583 20.2262 20.6614 22.9355 18.825 23.6847C18.053 23.9997 17.2103 23.8022 16.4753 23.4613C15.6146 23.0621 14.7763 22.5885 13.9444 22.1363C12.6322 21.4229 11.339 20.6746 10.0561 19.9097C9.03831 19.303 20.871 11.2294 20.9028 12.135Z" fill="url(#paint2_linear_87_144)"/><path fill-rule="evenodd" clip-rule="evenodd" d="M20.7208 9.42192C20.8133 10.3242 20.8706 11.2294 20.9024 12.135C20.9404 13.2208 20.9427 14.3075 20.9221 15.3929C20.9029 16.468 7.90248 9.84977 9.6151 8.9471C10.8694 8.28584 12.153 7.67901 13.4608 7.12781C14.3871 6.73735 15.3015 6.31235 16.2645 6.01414C17.0337 5.77602 17.9108 5.49825 18.7327 5.70721C19.6449 5.93901 20.2067 6.7775 20.4448 7.63575C20.6045 8.21022 20.6604 8.83292 20.7208 9.42192Z" fill="url(#paint3_linear_87_144)"/><g filter="url(#filter0_d_87_144)"><path fill-rule="evenodd" clip-rule="evenodd" d="M21.6535 17.9191C20.9196 18.4518 20.1654 18.9553 19.3982 19.4367C18.4782 20.014 17.5397 20.5604 16.5907 21.0865C15.6514 21.6085 14.6868 22.0827 13.7083 22.524C12.2286 23.1916 9.93732 24.6391 8.37016 23.4163C7.71128 22.9022 7.46023 22.0699 7.38705 21.2594C7.30144 20.3104 7.29128 19.3434 7.26592 18.3928C7.22588 16.8933 7.22563 15.3929 7.24483 13.8932C7.26002 12.7033 7.29718 11.5131 7.37613 10.3258C7.45559 9.1328 7.49902 7.85339 7.83203 6.7012C8.11496 5.72241 8.76895 4.98452 9.79586 4.83498C10.3883 4.74885 10.8783 4.93412 11.4155 5.16596C13.1962 5.93435 14.8665 6.97796 16.5045 8.01608C17.7043 8.7763 18.8716 9.58934 20.003 10.4513C20.8043 11.0617 21.6296 11.6445 22.3696 12.3332C22.9606 12.8832 23.6399 13.5074 23.8706 14.3274C24.1268 15.2374 23.683 16.1465 23.06 16.7839C22.6431 17.2107 22.1326 17.5714 21.6535 17.9191Z" fill="white"/></g><path fill-rule="evenodd" clip-rule="evenodd" d="M16.7797 15.7278C16.535 15.9105 16.2837 16.0833 16.0279 16.2484C15.7213 16.4465 15.4084 16.6339 15.0921 16.8144C14.779 16.9935 14.4574 17.1562 14.1313 17.3076C13.6381 17.5366 12.8743 18.0332 12.3519 17.6137C12.1323 17.4373 12.0486 17.1518 12.0242 16.8737C11.9957 16.5481 11.9923 16.2164 11.9838 15.8903C11.9705 15.3759 11.9704 14.8611 11.9768 14.3466C11.9819 13.9384 11.9942 13.5301 12.0206 13.1228C12.047 12.7135 12.0615 12.2746 12.1725 11.8793C12.2668 11.5435 12.4848 11.2904 12.8271 11.2391C13.0246 11.2095 13.1879 11.2731 13.367 11.3526C13.9606 11.6162 14.5174 11.9742 15.0633 12.3304C15.4633 12.5912 15.8524 12.8701 16.2295 13.1658C16.4966 13.3752 16.7717 13.5752 17.0184 13.8114C17.2154 14.0001 17.4418 14.2143 17.5187 14.4956C17.6041 14.8078 17.4562 15.1197 17.2485 15.3383C17.1096 15.4847 16.9394 15.6085 16.7797 15.7278Z" fill="url(#paint4_linear_87_144)"/></g></g></g><defs><linearGradient id="paint0_linear_87_144" x1="12.0694" y1="45.9458" x2="43.1922" y2="15.5614" gradientUnits="userSpaceOnUse"><stop stop-color="#8E3BEB"/><stop offset="0.358999" stop-color="#4B55E8"/><stop offset="0.684563" stop-color="#3861E7"/><stop offset="1" stop-color="#3E93FF"/></linearGradient><linearGradient id="paint1_linear_87_144" x1="0.881796" y1="20.3806" x2="10.6665" y2="22.3946" gradientUnits="userSpaceOnUse"><stop stop-color="white"/><stop offset="1" stop-color="white" stop-opacity="0.0315158"/><stop offset="1" stop-color="white" stop-opacity="0.01"/></linearGradient><linearGradient id="paint2_linear_87_144" x1="23.3468" y1="21.5116" x2="18.183" y2="15.0328" gradientUnits="userSpaceOnUse"><stop stop-color="white"/><stop offset="1" stop-color="white" stop-opacity="0.01"/></linearGradient><linearGradient id="paint3_linear_87_144" x1="14.332" y1="1.72647" x2="9.79149" y2="9.03326" gradientUnits="userSpaceOnUse"><stop stop-color="white"/><stop offset="1" stop-color="white" stop-opacity="0.01"/></linearGradient><linearGradient id="paint4_linear_87_144" x1="15.2557" y1="9.29257" x2="9.39501" y2="13.0592" gradientUnits="userSpaceOnUse"><stop stop-color="#386CEB"/><stop offset="1" stop-color="#3A40DB"/></linearGradient></defs></svg>'), mimetype="image/svg+xml")
        case "vlc":
            return send_file(BytesIO(b'<svg height="512px" style="enable-background:new 0 0 512 512;" version="1.1" viewBox="0 0 512 512" width="512px" xml:space="preserve" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><g id="_x31_2-vlc_x2C__media_x2C__player"><g><g><g><path d="M478.104,458.638l-59.65-119.619c-2.535-5.058-7.691-8.255-13.326-8.255H106.872 c-5.635,0-10.791,3.197-13.326,8.255L33.887,458.638c-2.325,4.637-2.053,10.141,0.66,14.538 c2.715,4.396,7.516,7.118,12.676,7.118h417.554c5.16,0,9.959-2.694,12.707-7.087 C480.193,468.778,480.404,463.307,478.104,458.638L478.104,458.638z M478.104,458.638" style="fill:#FF9800;"/></g><path d="M375.297,345.718c0,43.659-107.068,44.858-119.297,44.858c-12.23,0-119.302-1.199-119.302-44.858 c0-1.197,0.301-2.691,0.6-3.887l20.579-75.665c14.61,11.369,53.086,19.739,98.124,19.739s83.512-8.37,98.123-19.739 l20.578,75.665C375.002,343.026,375.297,344.521,375.297,345.718L375.297,345.718z M375.297,345.718" style="fill:#FCFCFC;"/><path d="M332.35,186.62c-18.787,5.975-46.227,9.565-76.35,9.565s-57.563-3.591-76.351-9.565l22.964-84.34 c15.506,2.69,34,4.187,53.387,4.187s37.879-1.496,53.387-4.187L332.35,186.62z M332.35,186.62" style="fill:#FCFCFC;"/><path d="M256,106.467c-19.387,0-37.881-1.496-53.387-4.187l10.439-37.982 c5.666-20.03,22.668-32.592,42.947-32.592s37.279,12.562,42.945,32.297l10.441,38.277 C293.879,104.971,275.387,106.467,256,106.467L256,106.467z M256,106.467" style="fill:#FF9800;"/><path d="M354.123,266.166c-14.611,11.369-53.086,19.739-98.123,19.739s-83.513-8.37-98.124-19.739 l21.772-79.546c18.789,5.975,46.228,9.565,76.351,9.565s57.563-3.591,76.35-9.565L354.123,266.166z M354.123,266.166" style="fill:#FF9800;"/></g></g></g><g id="Layer_1"/></svg>'), mimetype="image/svg+xml")
        case "artplayer":
            return redirect("https://artplayer.org/document/logo.png")
        case "plyr":
            return send_file(BytesIO(b'<svg width="300" height="300" xmlns="http://www.w3.org/2000/svg" clip-rule="evenodd" version="1.1"><g><ellipse filter="url(#svg_1_blur)" stroke="#cccccc" fill="#fcfefe" cx="151" cy="152.33333" id="svg_1" rx="149.5" ry="150"/><ellipse fill="#1db2fd" stroke="#000" cx="151" cy="152.33333" id="svg_4" rx="130" ry="130" stroke-width="0"/><path transform="rotate(90 168 152.333)" fill="#ffffff" d="m90,217.33333l78.00001,-130l78.00001,130l-156.00001,0l-0.00001,0z" id="svg_7" stroke="#000" stroke-width="0"/></g><defs><filter height="200%" width="200%" y="-50%" x="-50%" id="svg_1_blur"><feGaussianBlur stdDeviation="1" in="SourceGraphic"/></filter></defs></svg>'), mimetype="image/svg+xml")
        case "close":
            return send_file(BytesIO(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 50 50" width="100px" height="100px"><path d="M 9.15625 6.3125 L 6.3125 9.15625 L 22.15625 25 L 6.21875 40.96875 L 9.03125 43.78125 L 25 27.84375 L 40.9375 43.78125 L 43.78125 40.9375 L 27.84375 25 L 43.6875 9.15625 L 40.84375 6.3125 L 25 22.15625 Z" fill="#FFFFFF"/></svg>'), mimetype="image/svg+xml")
        case "subtitle":
            return send_file(BytesIO(b'<svg xmlns="http://www.w3.org/2000/svg" height="24" width="24" viewBox="0 0 48 48"><path d="M0 0h48v48H0z" fill="none"/><path fill="#ffffff" d="M40 8H8c-2.21 0-4 1.79-4 4v24c0 2.21 1.79 4 4 4h32c2.21 0 4-1.79 4-4V12c0-2.21-1.79-4-4-4zM8 24h8v4H8v-4zm20 12H8v-4h20v4zm12 0h-8v-4h8v4zm0-8H20v-4h20v4z"/></svg>'), mimetype="image/svg+xml")
        case _:
            return query("/")


@flask_app.get("/<path:path>")
@redirect_exception_response
def query(path: str = ""):
    get_arg = request.args.get
    method = get_arg("method")
    if method in ("srt2ass", "download", "redirect"):
        url = get_arg("url")
        if not url:
            return "bad url", 400
        match method:
            case "srt2ass":
                return send_file(BytesIO(srt2ass(unquote(url)).encode("utf-8")), "application/x-ass")
            case "download":
                return send_file(urlopen(url), "application/octent-stream")
            case "redirect":
                return redirect(url)
    path = path.lstrip("/")
    if path == "<share" or path.startswith("<share/") or get_arg("share_code"):
        share_code = ""
        if path.startswith("<share/"):
            path = path.removeprefix("<share/")
            share_code, _, path = path.partition("/")
            if get_arg("share_code"):
                share_code = ""
        elif path == "<share":
            path = ""
        match method:
            case "attr":
                return get_share_attr(path, share_code)
            case "list":
                return get_share_list(path, share_code)
            case "url":
                return get_share_url(path, share_code)
            case _:
                return get_share_page(path, share_code, as_file=method=="file")
    else:
        match method:
            case "attr":
                return get_attr(path)
            case "list":
                return get_list(path)
            case "url":
                return get_url(path)
            case "m3u8":
                return get_m3u8(path)
            case "sub":
                return get_subtitles(path)
            case _:
                return get_page(path, as_file=method=="file")


# NOTE: https://wsgidav.readthedocs.io/en/latest/user_guide_configure.html
WSGIDAV_CONFIG = {
    "host": "0.0.0.0", 
    "port": 0, 
    "mount_path": "/<dav", 
    "provider_mapping": {"/": P115FileSystemProvider()}, 
    "simple_dc": {"user_mapping": {"*": True}}, 
}
wsgidav_app = WsgiDAVApp(WSGIDAV_CONFIG)
application = DispatcherMiddleware(flask_app, {"/<dav": wsgidav_app})


if __name__ == "__main__":
    from werkzeug.serving import run_simple

    debug = args.debug
    kwargs = dict(
        hostname=args.host, 
        port=args.port, 
        application=application, 
        use_reloader=debug, 
        use_debugger=debug, 
        use_evalex=debug, 
        threaded=True, 
    )
    run_simple(**kwargs)

# TODO: 如果某个目录正在获取中，返回 concurrent.futures.Future，另一个线程如果也需要获取此目录，则直接获取此 future，对 web 和 webdav 都如此
# TODO: 可能是 wsgidav 的问题，propfind 响应太慢了，即使给文件夹做了缓存，需要看看怎么优化，可能需要对 propfind 的结果做缓存
# TODO: 完整的 wsgidav 配置文件支持
# TODO: 更完整信息的支持，类似 xattr
# TODO: 401 报错检查 cookies 是否被更新，如果是，则重跑
# TODO: 改用 blacksheep 框架？
# TODO: 研究一下，压缩包是否有 app 解压方法（这样就可以免 web 接口限制）
# TODO: 虽然115分享的图片也能获去cdn图片，但是并不能单独获取某个文件的属性，因此并不能给图片更新，除非这张图片被转存了，然后缓存转存后的pickcode，以后就可以反复更新了
# TODO: 加上搜索框和分页，加上图库浏览功能
# TODO: 对 head 请求进行优化，更快地响应，尽量避免做实际的事情
# TODO: 音乐播放器
# TODO: 播放器实现，播放列表，字幕或歌词绑定，弹幕、封面、元数据等功能
# TODO: 网页版支持播放 m3u8，自动绑定字幕等，这样可以避免那种没有声音的情况，默认使用最高画质，如果没有m3u8，则会退到原始视频
# TODO: 使用115接口保存播放进度

# TODO: 在线播放：播放列表、字幕列表（自动执行绑定视频）、多码率列表
# TODO: 支持自定义转换规则，把 srt 转换为 ass 时，添加样式和字体，或者添加一个在线的样式选择框，就像 115
# TODO: 直接用 m3u8 实现播放列表和各种附加，这样一切都是流媒体

