#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 4)
__all__ = ["make_application"]
__requirements__ = ["blacksheep", "blacksheep_client_request", "cachetools", "p115client", "posixpatht", "uvicorn"]
__doc__ = """\
        \x1b[5m🚀\x1b[0m \x1b[1m115 直链服务\x1b[0m \x1b[5m🍳\x1b[0m

链接格式（每个参数都是\x1b[1;31m可选的\x1b[0m）：\x1b[4m\x1b[34mhttp://localhost:8000{\x1b[1;36mpath2\x1b[0m\x1b[4m\x1b[34m}?pickcode={\x1b[1;36mpickcode\x1b[0m\x1b[4m\x1b[34m}&id={\x1b[1;36mid\x1b[0m\x1b[4m\x1b[34m}&sha1={\x1b[1;36msha1\x1b[0m\x1b[4m\x1b[34m}&path={\x1b[1;36mpath\x1b[0m\x1b[4m\x1b[34m}&kind={\x1b[1;36mkind\x1b[0m\x1b[4m\x1b[34m}&cache={\x1b[1;36mcache\x1b[0m\x1b[4m\x1b[34m}&sign={\x1b[1;36msign\x1b[0m\x1b[4m\x1b[34m}&t={\x1b[1;36mt\x1b[0m\x1b[4m\x1b[34m}\x1b[0m

- \x1b[1;36mpickcode\x1b[0m: 文件的 \x1b[1;36mpickcode\x1b[0m，优先级高于 \x1b[1;36mid\x1b[0m
- \x1b[1;36mid\x1b[0m: 文件的 \x1b[1;36mid\x1b[0m，优先级高于 \x1b[1;36msha1\x1b[0m
- \x1b[1;36msha1\x1b[0m: 文件的 \x1b[1;36msha1\x1b[0m，优先级高于 \x1b[1;36mpath\x1b[0m
- \x1b[1;36mpath\x1b[0m: 文件的路径，优先级高于 \x1b[1;36mpath2\x1b[0m
- \x1b[1;36mpath2\x1b[0m: 文件的路径，优先级最低
- \x1b[1;36mkind\x1b[0m: 文件类型，默认为 \x1b[1mfile\x1b[0m，用于返回特定的下载链接
    - \x1b[1mfile\x1b[0m: 文件，返回普通的链接（\x1b[1;31m有\x1b[0m\x1b[1m并发数限制\x1b[0m）
    - \x1b[1mimage\x1b[0m: 图片，返回 CDN 链接（\x1b[1;32m无\x1b[0m\x1b[1m并发数限制\x1b[0m）
    - \x1b[1msubtitle\x1b[0m: 字幕，返回链接（\x1b[1;32m无\x1b[0m\x1b[1m并发数限制\x1b[0m）
- \x1b[1;36mcache\x1b[0m: 接受 \x1b[1;33m1\x1b[0m | \x1b[1;33mtrue\x1b[0m 或 \x1b[1;33m0\x1b[0m | \x1b[1;33mfalse\x1b[0m，如果为 \x1b[1;33m1\x1b[0m | \x1b[1;33mtrue\x1b[0m，则使用 \x1b[1;36mpath\x1b[0m 到 \x1b[1;36mpickcode\x1b[0m 的缓存（\x1b[1m如果有的话\x1b[0m），否则不使用（\x1b[1m即使有的话\x1b[0m）
- \x1b[1;36msign\x1b[0m: 计算方式为 \x1b[2mhashlib.sha1(bytes(f"302@115-{token}-{t}-{value}", "utf-8")).hexdigest()\x1b[0m
    - \x1b[1mtoken\x1b[0m: 命令行中所传入的 \x1b[1mtoken\x1b[0m
    - \x1b[1mt\x1b[0m: 过期时间戳（\x1b[1m超过这个时间后，链接不可用\x1b[0m）
    - \x1b[1mvalue\x1b[0m: 按顺序检查 \x1b[1;36mpickcode\x1b[0m、\x1b[1;36mid\x1b[0m、\x1b[1;36msha1\x1b[0m、\x1b[1;36mpath\x1b[0m、\x1b[1;36mpath2\x1b[0m，最先有效的那个值
- \x1b[1;36mt\x1b[0m: 链接过期时间戳，接受一个整数，只在使用签名时有效，如果不提供或者小于等于 0，则永久有效

        \x1b[5m🔨\x1b[0m 如何运行 \x1b[5m🪛\x1b[0m

请在当前工作目录下创建一个 \x1b[4m\x1b[34m115-cookies.txt\x1b[0m，并把 115 的 cookies 保存其中，格式为

    UID=...; CID=...; SEID=...

然后运行脚本（默认端口：\x1b[1;33m8000\x1b[0m，可用命令行参数 \x1b[1m-P\x1b[0m/\x1b[1m--port\x1b[0m 指定其它端口号）

    python web_115_302.py

支持对指定目录进行预热，请发送目录 id (cid) 到后台任务

    \x1b[1mPOST\x1b[0m \x1b[4m\x1b[34mhttp://localhost:8000/run?cid={cid}\x1b[0m

另外还提供了文档

    \x1b[4m\x1b[34mhttp://localhost:8000/docs\x1b[0m

或者

    \x1b[4m\x1b[34mhttp://localhost:8000/redocs\x1b[0m

再推荐一个命令行使用，用于执行 HTTP 请求的工具，类似 \x1b[1;3mwget\x1b[0m

    \x1b[4m\x1b[34mhttps://pypi.org/project/httpie/\x1b[0m
"""
__licence__ = "GPLv3 <https://www.gnu.org/licenses/gpl-3.0.txt>"
__licence_str__ = """\
                    GNU GENERAL PUBLIC LICENSE
                       Version 3, 29 June 2007

 Copyright (C) 2007 Free Software Foundation, Inc. <https://fsf.org/>
 Everyone is permitted to copy and distribute verbatim copies
 of this license document, but changing it is not allowed.

                            Preamble

  The GNU General Public License is a free, copyleft license for
software and other kinds of works.

  The licenses for most software and other practical works are designed
to take away your freedom to share and change the works.  By contrast,
the GNU General Public License is intended to guarantee your freedom to
share and change all versions of a program--to make sure it remains free
software for all its users.  We, the Free Software Foundation, use the
GNU General Public License for most of our software; it applies also to
any other work released this way by its authors.  You can apply it to
your programs, too.

  When we speak of free software, we are referring to freedom, not
price.  Our General Public Licenses are designed to make sure that you
have the freedom to distribute copies of free software (and charge for
them if you wish), that you receive source code or can get it if you
want it, that you can change the software or use pieces of it in new
free programs, and that you know you can do these things.

  To protect your rights, we need to prevent others from denying you
these rights or asking you to surrender the rights.  Therefore, you have
certain responsibilities if you distribute copies of the software, or if
you modify it: responsibilities to respect the freedom of others.

  For example, if you distribute copies of such a program, whether
gratis or for a fee, you must pass on to the recipients the same
freedoms that you received.  You must make sure that they, too, receive
or can get the source code.  And you must show them these terms so they
know their rights.

  Developers that use the GNU GPL protect your rights with two steps:
(1) assert copyright on the software, and (2) offer you this License
giving you legal permission to copy, distribute and/or modify it.

  For the developers' and authors' protection, the GPL clearly explains
that there is no warranty for this free software.  For both users' and
authors' sake, the GPL requires that modified versions be marked as
changed, so that their problems will not be attributed erroneously to
authors of previous versions.

  Some devices are designed to deny users access to install or run
modified versions of the software inside them, although the manufacturer
can do so.  This is fundamentally incompatible with the aim of
protecting users' freedom to change the software.  The systematic
pattern of such abuse occurs in the area of products for individuals to
use, which is precisely where it is most unacceptable.  Therefore, we
have designed this version of the GPL to prohibit the practice for those
products.  If such problems arise substantially in other domains, we
stand ready to extend this provision to those domains in future versions
of the GPL, as needed to protect the freedom of users.

  Finally, every program is threatened constantly by software patents.
States should not allow patents to restrict development and use of
software on general-purpose computers, but in those that do, we wish to
avoid the special danger that patents applied to a free program could
make it effectively proprietary.  To prevent this, the GPL assures that
patents cannot be used to render the program non-free.

  The precise terms and conditions for copying, distribution and
modification follow.

                       TERMS AND CONDITIONS

  0. Definitions.

  "This License" refers to version 3 of the GNU General Public License.

  "Copyright" also means copyright-like laws that apply to other kinds of
works, such as semiconductor masks.

  "The Program" refers to any copyrightable work licensed under this
License.  Each licensee is addressed as "you".  "Licensees" and
"recipients" may be individuals or organizations.

  To "modify" a work means to copy from or adapt all or part of the work
in a fashion requiring copyright permission, other than the making of an
exact copy.  The resulting work is called a "modified version" of the
earlier work or a work "based on" the earlier work.

  A "covered work" means either the unmodified Program or a work based
on the Program.

  To "propagate" a work means to do anything with it that, without
permission, would make you directly or secondarily liable for
infringement under applicable copyright law, except executing it on a
computer or modifying a private copy.  Propagation includes copying,
distribution (with or without modification), making available to the
public, and in some countries other activities as well.

  To "convey" a work means any kind of propagation that enables other
parties to make or receive copies.  Mere interaction with a user through
a computer network, with no transfer of a copy, is not conveying.

  An interactive user interface displays "Appropriate Legal Notices"
to the extent that it includes a convenient and prominently visible
feature that (1) displays an appropriate copyright notice, and (2)
tells the user that there is no warranty for the work (except to the
extent that warranties are provided), that licensees may convey the
work under this License, and how to view a copy of this License.  If
the interface presents a list of user commands or options, such as a
menu, a prominent item in the list meets this criterion.

  1. Source Code.

  The "source code" for a work means the preferred form of the work
for making modifications to it.  "Object code" means any non-source
form of a work.

  A "Standard Interface" means an interface that either is an official
standard defined by a recognized standards body, or, in the case of
interfaces specified for a particular programming language, one that
is widely used among developers working in that language.

  The "System Libraries" of an executable work include anything, other
than the work as a whole, that (a) is included in the normal form of
packaging a Major Component, but which is not part of that Major
Component, and (b) serves only to enable use of the work with that
Major Component, or to implement a Standard Interface for which an
implementation is available to the public in source code form.  A
"Major Component", in this context, means a major essential component
(kernel, window system, and so on) of the specific operating system
(if any) on which the executable work runs, or a compiler used to
produce the work, or an object code interpreter used to run it.

  The "Corresponding Source" for a work in object code form means all
the source code needed to generate, install, and (for an executable
work) run the object code and to modify the work, including scripts to
control those activities.  However, it does not include the work's
System Libraries, or general-purpose tools or generally available free
programs which are used unmodified in performing those activities but
which are not part of the work.  For example, Corresponding Source
includes interface definition files associated with source files for
the work, and the source code for shared libraries and dynamically
linked subprograms that the work is specifically designed to require,
such as by intimate data communication or control flow between those
subprograms and other parts of the work.

  The Corresponding Source need not include anything that users
can regenerate automatically from other parts of the Corresponding
Source.

  The Corresponding Source for a work in source code form is that
same work.

  2. Basic Permissions.

  All rights granted under this License are granted for the term of
copyright on the Program, and are irrevocable provided the stated
conditions are met.  This License explicitly affirms your unlimited
permission to run the unmodified Program.  The output from running a
covered work is covered by this License only if the output, given its
content, constitutes a covered work.  This License acknowledges your
rights of fair use or other equivalent, as provided by copyright law.

  You may make, run and propagate covered works that you do not
convey, without conditions so long as your license otherwise remains
in force.  You may convey covered works to others for the sole purpose
of having them make modifications exclusively for you, or provide you
with facilities for running those works, provided that you comply with
the terms of this License in conveying all material for which you do
not control copyright.  Those thus making or running the covered works
for you must do so exclusively on your behalf, under your direction
and control, on terms that prohibit them from making any copies of
your copyrighted material outside their relationship with you.

  Conveying under any other circumstances is permitted solely under
the conditions stated below.  Sublicensing is not allowed; section 10
makes it unnecessary.

  3. Protecting Users' Legal Rights From Anti-Circumvention Law.

  No covered work shall be deemed part of an effective technological
measure under any applicable law fulfilling obligations under article
11 of the WIPO copyright treaty adopted on 20 December 1996, or
similar laws prohibiting or restricting circumvention of such
measures.

  When you convey a covered work, you waive any legal power to forbid
circumvention of technological measures to the extent such circumvention
is effected by exercising rights under this License with respect to
the covered work, and you disclaim any intention to limit operation or
modification of the work as a means of enforcing, against the work's
users, your or third parties' legal rights to forbid circumvention of
technological measures.

  4. Conveying Verbatim Copies.

  You may convey verbatim copies of the Program's source code as you
receive it, in any medium, provided that you conspicuously and
appropriately publish on each copy an appropriate copyright notice;
keep intact all notices stating that this License and any
non-permissive terms added in accord with section 7 apply to the code;
keep intact all notices of the absence of any warranty; and give all
recipients a copy of this License along with the Program.

  You may charge any price or no price for each copy that you convey,
and you may offer support or warranty protection for a fee.

  5. Conveying Modified Source Versions.

  You may convey a work based on the Program, or the modifications to
produce it from the Program, in the form of source code under the
terms of section 4, provided that you also meet all of these conditions:

    a) The work must carry prominent notices stating that you modified
    it, and giving a relevant date.

    b) The work must carry prominent notices stating that it is
    released under this License and any conditions added under section
    7.  This requirement modifies the requirement in section 4 to
    "keep intact all notices".

    c) You must license the entire work, as a whole, under this
    License to anyone who comes into possession of a copy.  This
    License will therefore apply, along with any applicable section 7
    additional terms, to the whole of the work, and all its parts,
    regardless of how they are packaged.  This License gives no
    permission to license the work in any other way, but it does not
    invalidate such permission if you have separately received it.

    d) If the work has interactive user interfaces, each must display
    Appropriate Legal Notices; however, if the Program has interactive
    interfaces that do not display Appropriate Legal Notices, your
    work need not make them do so.

  A compilation of a covered work with other separate and independent
works, which are not by their nature extensions of the covered work,
and which are not combined with it such as to form a larger program,
in or on a volume of a storage or distribution medium, is called an
"aggregate" if the compilation and its resulting copyright are not
used to limit the access or legal rights of the compilation's users
beyond what the individual works permit.  Inclusion of a covered work
in an aggregate does not cause this License to apply to the other
parts of the aggregate.

  6. Conveying Non-Source Forms.

  You may convey a covered work in object code form under the terms
of sections 4 and 5, provided that you also convey the
machine-readable Corresponding Source under the terms of this License,
in one of these ways:

    a) Convey the object code in, or embodied in, a physical product
    (including a physical distribution medium), accompanied by the
    Corresponding Source fixed on a durable physical medium
    customarily used for software interchange.

    b) Convey the object code in, or embodied in, a physical product
    (including a physical distribution medium), accompanied by a
    written offer, valid for at least three years and valid for as
    long as you offer spare parts or customer support for that product
    model, to give anyone who possesses the object code either (1) a
    copy of the Corresponding Source for all the software in the
    product that is covered by this License, on a durable physical
    medium customarily used for software interchange, for a price no
    more than your reasonable cost of physically performing this
    conveying of source, or (2) access to copy the
    Corresponding Source from a network server at no charge.

    c) Convey individual copies of the object code with a copy of the
    written offer to provide the Corresponding Source.  This
    alternative is allowed only occasionally and noncommercially, and
    only if you received the object code with such an offer, in accord
    with subsection 6b.

    d) Convey the object code by offering access from a designated
    place (gratis or for a charge), and offer equivalent access to the
    Corresponding Source in the same way through the same place at no
    further charge.  You need not require recipients to copy the
    Corresponding Source along with the object code.  If the place to
    copy the object code is a network server, the Corresponding Source
    may be on a different server (operated by you or a third party)
    that supports equivalent copying facilities, provided you maintain
    clear directions next to the object code saying where to find the
    Corresponding Source.  Regardless of what server hosts the
    Corresponding Source, you remain obligated to ensure that it is
    available for as long as needed to satisfy these requirements.

    e) Convey the object code using peer-to-peer transmission, provided
    you inform other peers where the object code and Corresponding
    Source of the work are being offered to the general public at no
    charge under subsection 6d.

  A separable portion of the object code, whose source code is excluded
from the Corresponding Source as a System Library, need not be
included in conveying the object code work.

  A "User Product" is either (1) a "consumer product", which means any
tangible personal property which is normally used for personal, family,
or household purposes, or (2) anything designed or sold for incorporation
into a dwelling.  In determining whether a product is a consumer product,
doubtful cases shall be resolved in favor of coverage.  For a particular
product received by a particular user, "normally used" refers to a
typical or common use of that class of product, regardless of the status
of the particular user or of the way in which the particular user
actually uses, or expects or is expected to use, the product.  A product
is a consumer product regardless of whether the product has substantial
commercial, industrial or non-consumer uses, unless such uses represent
the only significant mode of use of the product.

  "Installation Information" for a User Product means any methods,
procedures, authorization keys, or other information required to install
and execute modified versions of a covered work in that User Product from
a modified version of its Corresponding Source.  The information must
suffice to ensure that the continued functioning of the modified object
code is in no case prevented or interfered with solely because
modification has been made.

  If you convey an object code work under this section in, or with, or
specifically for use in, a User Product, and the conveying occurs as
part of a transaction in which the right of possession and use of the
User Product is transferred to the recipient in perpetuity or for a
fixed term (regardless of how the transaction is characterized), the
Corresponding Source conveyed under this section must be accompanied
by the Installation Information.  But this requirement does not apply
if neither you nor any third party retains the ability to install
modified object code on the User Product (for example, the work has
been installed in ROM).

  The requirement to provide Installation Information does not include a
requirement to continue to provide support service, warranty, or updates
for a work that has been modified or installed by the recipient, or for
the User Product in which it has been modified or installed.  Access to a
network may be denied when the modification itself materially and
adversely affects the operation of the network or violates the rules and
protocols for communication across the network.

  Corresponding Source conveyed, and Installation Information provided,
in accord with this section must be in a format that is publicly
documented (and with an implementation available to the public in
source code form), and must require no special password or key for
unpacking, reading or copying.

  7. Additional Terms.

  "Additional permissions" are terms that supplement the terms of this
License by making exceptions from one or more of its conditions.
Additional permissions that are applicable to the entire Program shall
be treated as though they were included in this License, to the extent
that they are valid under applicable law.  If additional permissions
apply only to part of the Program, that part may be used separately
under those permissions, but the entire Program remains governed by
this License without regard to the additional permissions.

  When you convey a copy of a covered work, you may at your option
remove any additional permissions from that copy, or from any part of
it.  (Additional permissions may be written to require their own
removal in certain cases when you modify the work.)  You may place
additional permissions on material, added by you to a covered work,
for which you have or can give appropriate copyright permission.

  Notwithstanding any other provision of this License, for material you
add to a covered work, you may (if authorized by the copyright holders of
that material) supplement the terms of this License with terms:

    a) Disclaiming warranty or limiting liability differently from the
    terms of sections 15 and 16 of this License; or

    b) Requiring preservation of specified reasonable legal notices or
    author attributions in that material or in the Appropriate Legal
    Notices displayed by works containing it; or

    c) Prohibiting misrepresentation of the origin of that material, or
    requiring that modified versions of such material be marked in
    reasonable ways as different from the original version; or

    d) Limiting the use for publicity purposes of names of licensors or
    authors of the material; or

    e) Declining to grant rights under trademark law for use of some
    trade names, trademarks, or service marks; or

    f) Requiring indemnification of licensors and authors of that
    material by anyone who conveys the material (or modified versions of
    it) with contractual assumptions of liability to the recipient, for
    any liability that these contractual assumptions directly impose on
    those licensors and authors.

  All other non-permissive additional terms are considered "further
restrictions" within the meaning of section 10.  If the Program as you
received it, or any part of it, contains a notice stating that it is
governed by this License along with a term that is a further
restriction, you may remove that term.  If a license document contains
a further restriction but permits relicensing or conveying under this
License, you may add to a covered work material governed by the terms
of that license document, provided that the further restriction does
not survive such relicensing or conveying.

  If you add terms to a covered work in accord with this section, you
must place, in the relevant source files, a statement of the
additional terms that apply to those files, or a notice indicating
where to find the applicable terms.

  Additional terms, permissive or non-permissive, may be stated in the
form of a separately written license, or stated as exceptions;
the above requirements apply either way.

  8. Termination.

  You may not propagate or modify a covered work except as expressly
provided under this License.  Any attempt otherwise to propagate or
modify it is void, and will automatically terminate your rights under
this License (including any patent licenses granted under the third
paragraph of section 11).

  However, if you cease all violation of this License, then your
license from a particular copyright holder is reinstated (a)
provisionally, unless and until the copyright holder explicitly and
finally terminates your license, and (b) permanently, if the copyright
holder fails to notify you of the violation by some reasonable means
prior to 60 days after the cessation.

  Moreover, your license from a particular copyright holder is
reinstated permanently if the copyright holder notifies you of the
violation by some reasonable means, this is the first time you have
received notice of violation of this License (for any work) from that
copyright holder, and you cure the violation prior to 30 days after
your receipt of the notice.

  Termination of your rights under this section does not terminate the
licenses of parties who have received copies or rights from you under
this License.  If your rights have been terminated and not permanently
reinstated, you do not qualify to receive new licenses for the same
material under section 10.

  9. Acceptance Not Required for Having Copies.

  You are not required to accept this License in order to receive or
run a copy of the Program.  Ancillary propagation of a covered work
occurring solely as a consequence of using peer-to-peer transmission
to receive a copy likewise does not require acceptance.  However,
nothing other than this License grants you permission to propagate or
modify any covered work.  These actions infringe copyright if you do
not accept this License.  Therefore, by modifying or propagating a
covered work, you indicate your acceptance of this License to do so.

  10. Automatic Licensing of Downstream Recipients.

  Each time you convey a covered work, the recipient automatically
receives a license from the original licensors, to run, modify and
propagate that work, subject to this License.  You are not responsible
for enforcing compliance by third parties with this License.

  An "entity transaction" is a transaction transferring control of an
organization, or substantially all assets of one, or subdividing an
organization, or merging organizations.  If propagation of a covered
work results from an entity transaction, each party to that
transaction who receives a copy of the work also receives whatever
licenses to the work the party's predecessor in interest had or could
give under the previous paragraph, plus a right to possession of the
Corresponding Source of the work from the predecessor in interest, if
the predecessor has it or can get it with reasonable efforts.

  You may not impose any further restrictions on the exercise of the
rights granted or affirmed under this License.  For example, you may
not impose a license fee, royalty, or other charge for exercise of
rights granted under this License, and you may not initiate litigation
(including a cross-claim or counterclaim in a lawsuit) alleging that
any patent claim is infringed by making, using, selling, offering for
sale, or importing the Program or any portion of it.

  11. Patents.

  A "contributor" is a copyright holder who authorizes use under this
License of the Program or a work on which the Program is based.  The
work thus licensed is called the contributor's "contributor version".

  A contributor's "essential patent claims" are all patent claims
owned or controlled by the contributor, whether already acquired or
hereafter acquired, that would be infringed by some manner, permitted
by this License, of making, using, or selling its contributor version,
but do not include claims that would be infringed only as a
consequence of further modification of the contributor version.  For
purposes of this definition, "control" includes the right to grant
patent sublicenses in a manner consistent with the requirements of
this License.

  Each contributor grants you a non-exclusive, worldwide, royalty-free
patent license under the contributor's essential patent claims, to
make, use, sell, offer for sale, import and otherwise run, modify and
propagate the contents of its contributor version.

  In the following three paragraphs, a "patent license" is any express
agreement or commitment, however denominated, not to enforce a patent
(such as an express permission to practice a patent or covenant not to
sue for patent infringement).  To "grant" such a patent license to a
party means to make such an agreement or commitment not to enforce a
patent against the party.

  If you convey a covered work, knowingly relying on a patent license,
and the Corresponding Source of the work is not available for anyone
to copy, free of charge and under the terms of this License, through a
publicly available network server or other readily accessible means,
then you must either (1) cause the Corresponding Source to be so
available, or (2) arrange to deprive yourself of the benefit of the
patent license for this particular work, or (3) arrange, in a manner
consistent with the requirements of this License, to extend the patent
license to downstream recipients.  "Knowingly relying" means you have
actual knowledge that, but for the patent license, your conveying the
covered work in a country, or your recipient's use of the covered work
in a country, would infringe one or more identifiable patents in that
country that you have reason to believe are valid.

  If, pursuant to or in connection with a single transaction or
arrangement, you convey, or propagate by procuring conveyance of, a
covered work, and grant a patent license to some of the parties
receiving the covered work authorizing them to use, propagate, modify
or convey a specific copy of the covered work, then the patent license
you grant is automatically extended to all recipients of the covered
work and works based on it.

  A patent license is "discriminatory" if it does not include within
the scope of its coverage, prohibits the exercise of, or is
conditioned on the non-exercise of one or more of the rights that are
specifically granted under this License.  You may not convey a covered
work if you are a party to an arrangement with a third party that is
in the business of distributing software, under which you make payment
to the third party based on the extent of your activity of conveying
the work, and under which the third party grants, to any of the
parties who would receive the covered work from you, a discriminatory
patent license (a) in connection with copies of the covered work
conveyed by you (or copies made from those copies), or (b) primarily
for and in connection with specific products or compilations that
contain the covered work, unless you entered into that arrangement,
or that patent license was granted, prior to 28 March 2007.

  Nothing in this License shall be construed as excluding or limiting
any implied license or other defenses to infringement that may
otherwise be available to you under applicable patent law.

  12. No Surrender of Others' Freedom.

  If conditions are imposed on you (whether by court order, agreement or
otherwise) that contradict the conditions of this License, they do not
excuse you from the conditions of this License.  If you cannot convey a
covered work so as to satisfy simultaneously your obligations under this
License and any other pertinent obligations, then as a consequence you may
not convey it at all.  For example, if you agree to terms that obligate you
to collect a royalty for further conveying from those to whom you convey
the Program, the only way you could satisfy both those terms and this
License would be to refrain entirely from conveying the Program.

  13. Use with the GNU Affero General Public License.

  Notwithstanding any other provision of this License, you have
permission to link or combine any covered work with a work licensed
under version 3 of the GNU Affero General Public License into a single
combined work, and to convey the resulting work.  The terms of this
License will continue to apply to the part which is the covered work,
but the special requirements of the GNU Affero General Public License,
section 13, concerning interaction through a network will apply to the
combination as such.

  14. Revised Versions of this License.

  The Free Software Foundation may publish revised and/or new versions of
the GNU General Public License from time to time.  Such new versions will
be similar in spirit to the present version, but may differ in detail to
address new problems or concerns.

  Each version is given a distinguishing version number.  If the
Program specifies that a certain numbered version of the GNU General
Public License "or any later version" applies to it, you have the
option of following the terms and conditions either of that numbered
version or of any later version published by the Free Software
Foundation.  If the Program does not specify a version number of the
GNU General Public License, you may choose any version ever published
by the Free Software Foundation.

  If the Program specifies that a proxy can decide which future
versions of the GNU General Public License can be used, that proxy's
public statement of acceptance of a version permanently authorizes you
to choose that version for the Program.

  Later license versions may give you additional or different
permissions.  However, no additional obligations are imposed on any
author or copyright holder as a result of your choosing to follow a
later version.

  15. Disclaimer of Warranty.

  THERE IS NO WARRANTY FOR THE PROGRAM, TO THE EXTENT PERMITTED BY
APPLICABLE LAW.  EXCEPT WHEN OTHERWISE STATED IN WRITING THE COPYRIGHT
HOLDERS AND/OR OTHER PARTIES PROVIDE THE PROGRAM "AS IS" WITHOUT WARRANTY
OF ANY KIND, EITHER EXPRESSED OR IMPLIED, INCLUDING, BUT NOT LIMITED TO,
THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE.  THE ENTIRE RISK AS TO THE QUALITY AND PERFORMANCE OF THE PROGRAM
IS WITH YOU.  SHOULD THE PROGRAM PROVE DEFECTIVE, YOU ASSUME THE COST OF
ALL NECESSARY SERVICING, REPAIR OR CORRECTION.

  16. Limitation of Liability.

  IN NO EVENT UNLESS REQUIRED BY APPLICABLE LAW OR AGREED TO IN WRITING
WILL ANY COPYRIGHT HOLDER, OR ANY OTHER PARTY WHO MODIFIES AND/OR CONVEYS
THE PROGRAM AS PERMITTED ABOVE, BE LIABLE TO YOU FOR DAMAGES, INCLUDING ANY
GENERAL, SPECIAL, INCIDENTAL OR CONSEQUENTIAL DAMAGES ARISING OUT OF THE
USE OR INABILITY TO USE THE PROGRAM (INCLUDING BUT NOT LIMITED TO LOSS OF
DATA OR DATA BEING RENDERED INACCURATE OR LOSSES SUSTAINED BY YOU OR THIRD
PARTIES OR A FAILURE OF THE PROGRAM TO OPERATE WITH ANY OTHER PROGRAMS),
EVEN IF SUCH HOLDER OR OTHER PARTY HAS BEEN ADVISED OF THE POSSIBILITY OF
SUCH DAMAGES.

  17. Interpretation of Sections 15 and 16.

  If the disclaimer of warranty and limitation of liability provided
above cannot be given local legal effect according to their terms,
reviewing courts shall apply local law that most closely approximates
an absolute waiver of all civil liability in connection with the
Program, unless a warranty or assumption of liability accompanies a
copy of the Program in return for a fee.

                     END OF TERMS AND CONDITIONS

            How to Apply These Terms to Your New Programs

  If you develop a new program, and you want it to be of the greatest
possible use to the public, the best way to achieve this is to make it
free software which everyone can redistribute and change under these terms.

  To do so, attach the following notices to the program.  It is safest
to attach them to the start of each source file to most effectively
state the exclusion of warranty; and each file should have at least
the "copyright" line and a pointer to where the full notice is found.

    <one line to give the program's name and a brief idea of what it does.>
    Copyright (C) <year>  <name of author>

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.

Also add information on how to contact you by electronic and paper mail.

  If the program does terminal interaction, make it output a short
notice like this when it starts in an interactive mode:

    <program>  Copyright (C) <year>  <name of author>
    This program comes with ABSOLUTELY NO WARRANTY; for details type `show w'.
    This is free software, and you are welcome to redistribute it
    under certain conditions; type `show c' for details.

The hypothetical commands `show w' and `show c' should show the appropriate
parts of the General Public License.  Of course, your program's commands
might be different; for a GUI interface, you would use an "about box".

  You should also get your employer (if you work as a programmer) or school,
if any, to sign a "copyright disclaimer" for the program, if necessary.
For more information on this, and how to apply and follow the GNU GPL, see
<https://www.gnu.org/licenses/>.

  The GNU General Public License does not permit incorporating your program
into proprietary programs.  If your program is a subroutine library, you
may consider it more useful to permit linking proprietary applications with
the library.  If this is what you want to do, use the GNU Lesser General
Public License instead of this License.  But first, please read
<https://www.gnu.org/licenses/why-not-lgpl.html>.
"""
__license_str_zh__ = """\
                    GNU 通用公共许可证
                        第 3 版，2007 年 6 月 29 日

版权所有 (C) 2007 自由软件基金会 <https://fsf.org/>
任何人都可以复制和分发本许可证的完整副本，但不允许修改它。

                            引言

    GNU 通用公共许可证是一份适用于软件和其他类型的作品的，自由的 copyleft 许可证。

    大多数软件和其他实用性作品的许可证，都设法剥夺你的自由，让你无法修改和分享作品。相反，GNU 通用公共许可证力图保障你能自由地分享和修改一个程序的全部版本——确保该程序对每一位用户来说都是自由软件。我们自由软件基金会为我们的大多数软件采用了 GNU 通用公共许可证；本许可证也适用于其他任何类型的作品，只要其作者也以这种方式发布作品。你也可以将本许可证应用于你的程序。

    所谓自由软件，强调的是自由，而与价格无关。我们设计通用公共许可证，是为了确保你能够自由地分发自由软件的副本（你可以为此收费）、确保你能够接收到或在需要时索取到源代码、确保你能够修改软件或把它的一部分复用在新的自由的程序中，并确保你知道你可以做这些事。

    为了保障你的权利，我们不能让他人拒绝你的这些权利，也不能让他人要求你放弃这些权利。因此，在分发软件的副本时或修改它时，你有责任尊重其他人的自由。

    例如，如果分发了这样一个程序，无论是否收费，你必须把你获得的自由同样地给予至接收者。你必须确保他们也能接收到或索取到源代码。并且你必须给他们展示这些条款，让他们知道自己有这些权利。

    开发者使用 GNU GPL，通过以下两步来保障你的权利：（1）主张软件的版权，并（2）通过本许可证授予你复制、分发及修改本软件的合法权利。

    为保护开发者和作者，GPL 明确声明本自由软件没有品质担保。为用户和作者着想，GPL 需要修改版有修改过的标记，以防修改版出现的问题归结至先前版本的作者。

    有些设备设计出来，使用户无法安装或运行其内部软件的修改版，但厂商却能这么做。这根本上违背了保障用户能自由修改软件这一目标。这种滥用模式出现在了个人用品领域，而这恰是最不可接受的。因此，我们设计了此版本的 GPL 来禁止这些产品的这种行为。如果类似问题在其他领域也大量出现，我们会准备在未来的 GPL 版本中，将这样的阻止条款也扩展到这些领域，以保障用户的自由。

    最后，每个程序都常常受到软件专利的威胁。国家不应该允许专利去限制开发和使用通用计算机上的软件。但是，在那些实际允许了此类限制的国家，我们希望避免自由的程序因受到专利覆盖而专有化的危险。为阻止这种特殊的危险，GPL 确保专利不会被用于使该程序非自由化。

    以下是关于复制、分发和修改的条款和条件细则。

                            条款与条件

    0. 定义

    “本许可证”指 GNU 通用公共许可证第 3 版。

    “版权”也指适用于其他类型作品的类版权法律，例如适用于半导体掩模的相关法律。

    “本程序”指任何在本许可证下发布的有版权的作品。每位许可获得者都称作“你”。“许可获得者”和“接收者”可以是个人或组织。

    “修改”一份作品指需要版权许可才能进行的复制这份作品或改编这份作品的全部或一部分的行为，这些行为不同于制作完全相同的副本。所产生的作品称为前作的“修改版”，也称“基于”前作的作品。

    “涵盖作品”指未修改的本程序或基于本程序的作品。

    “传播”作品指那些在适用版权法律下，未经许可就会构成直接或间接侵权的行为，不包括在计算机上运行或进行私下修改。传播包括复制、分发（无论修改与否）、向公众公开，以及在某些国家的其他行为。

    “输送”一份作品指任何让他方能够制作或者接收副本的传播行为。仅仅通过计算机网络来与用户交互，但是没有传输副本，则不算输送。

    一个显示“适当的法律声明”的交互式用户界面，应包括一个便捷且显著的视觉特性，它满足以下要求：（1）显示适当的版权声明；且（2）告诉用户本作品没有品质担保（除非提供了品质担保）、许可获得者可以在本许可证约束下输送该作品、及查看本许可证副本的方法。如果该界面提供一个用户命令列表或选项列表，例如菜单，则此列表应有一个显著的选项符合上述规范。

    1. 源代码

    作品的“源代码”指作品首选的便于修改的形式，“目标代码”指作品的任何非源代码形式。

    “标准接口”指标准化组织定义的官方标准中的接口，或针对某种编程语言设定的接口中，此语言的开发者广泛使用的接口。

    可执行作品的“系统库”不涉及程序整体，而是一切符合以下要求的内容：（a）以通常形式和主要部件打包在一起，却并非主要部件的一部分，且（b）仅用于配合主要部件来使作品可以使用，或仅用于实现以源代码形式公开了实现的标准接口。“主要部件”在这里指可执行作品运行依赖的操作系统（如果存在）的必要部件（内核、窗口系统等），或生成该作品所使用的编译器，或运行该作品所使用的目标代码解释器。

    目标代码形式的作品，其“对应源代码”指生成、安装、运行（对于可执行作品而言）目标代码和修改该作品所需的所有源代码，包括控制上述行为的脚本。但是，其中不包括作品的系统库、通用工具、未修改便直接用于进行上述行为却不是该作品一部分的通常可得的自由程序。例如，对应源代码包括配合作品源文件的接口定义文件，以及该作品专门依赖的共享库和动态链接子程序的源代码。这种依赖行为，可能表现为那些子程序与该作品其他部分发生的密切数据通信或控制流。

    对应源代码不必包括那些用户可以通过对应源代码其他部分自动生成的内容。

    源代码形式的作品的对应源代码即其本身。

    2. 基本许可

    通过本许可证授予的一切权利都是对本程序的版权而言的，并且在所述条件都满足时，这些权利不可收回。本许可证明确授权你不受限制地运行本程序的未修改版。涵盖作品的输出，仅当其内容构成一个涵盖作品时，才会为本许可证所约束。本许可证承认版权法赋予你的正当使用或与之等价的权利。

    只要你获得的许可仍有效，你可以无条件地制作、运行和传播涵盖作品，但输送行为有另行约束。如果你向他人输送涵盖作品的唯一目的，是让他们专门为你进行修改或为你提供运行那些作品的工具，并且你遵守了本许可证中关于输送你不占有版权的材料的条款，那么你可以以这种方式输送。那些以此方式替你制作或运行这些涵盖作品的人，必须专门代表你在你的指引和管理下做这些事情，即禁止他们在双方关系之外制作任何你的有版权材料的副本。

    仅当满足下文所述条件时，才允许在其他任何情况下输送。分许可是不允许的，且第 10 条已使分许可没有必要了。

    3. 保护用户的合法权利免受反规避法限制

    在任何响应了 1996 年 12 月 20 日通过的世界知识产权组织版权条约第 11 条所要求的法律，或类似的禁止或限制技术措施规避的法律下，涵盖作品不应该视为有效技术措施的一部分。

    当你输送一份涵盖作品时，你即放弃行使任何法律权利来禁止对技术措施的规避行为，乃至于通过行使本许可证所予权利实现的规避。你即已表明不会企图通过限制用户操作或修改涵盖作品来确保你或第三方的禁止技术措施规避的法定权利。

    4. 输送完整副本

    你可以通过任何媒介输送你接收到的本程序的源代码的完整副本，但要做到：为每一个副本醒目而恰当地发布版权声明；完整保留所有关于本许可证及按第 7 节加入的任何非许可性条款将应用于本代码的声明；完整地保留所有关于不提供品质担保的声明；并随同本程序给所有接收者一份本许可证的副本。

    你可以免费或收费输送每一份副本，也可以提供支持或担保以换取收入。

    5. 输送修改过的源代码版本

    你可以以源代码形式输送基于本程序的作品或用以从本程序生成修改版的改动，除满足第 4 节的条款外，还需要同时满足以下所有条件：

        a）该作品必须带有醒目的声明，说明你修改了它，并给出相应的修改日期。

        b）该作品必须带有醒目的声明，说明其在本许可证及任何通过第 7 节加入的条件下发布。这项要求修正了第 4 节关于“完整保留”的要求。

        c）你必须按照本许可证将该作品整体向获得副本的人授权，本许可证及第 7 节的任何适用的附加条款就此适用于整个作品，及其每一部分，不管打包方式如何。本许可证不允许以其他任何形式授权该作品，但如果你单独受到了这样的许可，则本许可证不否认该许可。

        d）如果该作品有交互式用户界面，则每个交互式用户界面必须显示适当的法律声明。但是，如果本程序有交互式用户界面却不显示适当的法律声明，你的作品也不必如此。
    一个位于存储媒介或分发媒介之中的，由涵盖作品与其他分离或独立的作品组成的联合体，在既不是涵盖作品的自然扩展、也不是为构筑更大的程序而组合的、同时其本身及其产生的版权不会用于限制该联合体的用户被单体作品授予的法律权利时，称为“聚合版”。在聚合版中包含涵盖作品并不会使本许可证影响聚合版的其他部分。

    6. 输送非源代码的形式

    你可以在第 4 节和第 5 节的条款下输送涵盖作品的目标代码形式，前提是你要在本许可证下以如下方式之一输送机器可读的对应源代码：

        a）输送位于或包含于一个物理产品（包括物理分发媒介）中的目标代码时，随之附带一个写入了对应源代码的常用于交换软件的耐用物理媒介。

        b）输送位于或包含于一个物理产品（包括物理分发媒介）中的目标代码时，随之附带一份书面承诺——承诺的有效期至少为三年，且如果你后续仍提供该产品模型的配件或客户服务，则有效期相应延长；承诺的内容为向每一位目标代码的持有者提供以下二者之一：（1）一个常用于交换软件的耐用物理媒介，其中存入了该产品中本许可证涵盖的所有软件的对应源代码，且此项的收费不得超过你通过物理方式进行该输送所需的合理成本，或（2）通过网络服务器免费获得对应源代码的途径。

        c）输送单独的目标代码副本时，随之附带一份提供对应源代码的书面承诺的副本。这种情况只允许偶尔出现且不能盈利，并且仅限在你以第 6 节 b 项的方式收到了目标代码及这样的承诺之时。

        d）以在指定地点提供目标代码获取服务（无论是否收费）的形式输送目标代码时，在同一地点以同样的方式提供同等的对应源代码获取权，并不得额外收费。你不必要求接收者在复制目标代码的同时复制源代码。如果提供复制目标代码的地点为网络服务器，对应源代码可以提供在另一个支持相同复制功能的（由你或者第三方运营的）服务器上，不过你要在目标代码处指出对应源代码的确切路径。不管托管源代码使用了什么服务器，你有义务要确保服务器在需要时持续可用以满足这些要求。

        e）通过点对点传输来输送目标代码时，告知其他对等体目标代码和源代码在何处以第 6 节 d 项的形式向大众免费提供。

    “用户产品”指（1）“消费品”，即用于个人、家庭或日常用途的有形的个人财产，或（2）以家用为目的而设计或销售的物品。在判断一款产品是否为消费品时，应尽量从覆盖范围这一方面来决定，以解决引起争议的情况。就特定用户接收到的特定产品而言，“正常使用”指对此类产品的典型或一般使用，不管该用户的身份，也不管该用户对该产品的实际使用方法，或该用户预期使用该产品的方法，或该产品预期的被用户使用的方法。无论产品是否实质上具有商业上的、工业上的或非面向消费者的用途，它都视为消费品，除非以上用法代表了它唯一的主要使用模式。

    用户产品的“安装信息”，指使用涵盖作品的对应源代码的修改版来将涵盖作品的修改版安装和运行于该用户产品这一过程所需的所有方法、流程、认证密钥或其他信息。这些信息必须足以保证修改过的目标代码不会仅仅因为被修改过而不能或难以继续工作。

    如果你输送一份位于、或伴随着、或尤其用于一个用户产品的目标代码作品，且该输送体现为该用户产品的所有权和使用权永久或在一定时期内转移到了接收者（无论转移形式如何），则根据本节输送的对应源代码必须伴有安装信息。不过，如果你和第三方都没有保留在该用户产品上安装修改后的目标代码的能力（如作品安装在 ROM 上），则这项要求不成立。

    要求提供安装信息并不要求为用户修改或安装的作品，以及其载体产品继续提供支持服务、品质担保或升级。当修改本身对网络运行有实质上的负面影响，或违背了网络通信规则和协议时，可以拒绝其联网。

    根据本节输送的源代码及安装信息，必须使用公共的文件格式（并且存在可用的公开源代码的处理工具），同时不得对解包、读取和复制要求任何密码。

    7. 附加条款

    “附加许可”用于补充本许可证，可在本许可证的一种或多种条件下基于例外情况。只要符合适用法律，应用于本程序整体的附加许可应被视为本许可证的内容。如果附加许可只应用于程序的某部分，则该部分可以在那些许可下单独适用，但本程序整体仍受本许可证管理，且没有附加许可。

    当你输送涵盖作品的副本时，你可以选择性删除来自该副本的或来自该副本任何部分的任何附加许可。（附加许可可以写明在某些情况下要求你修改时删除该许可。）在你为一份涵盖作品添加的材料中，你可以为你拥有或可授予版权的材料增加附加许可。

    尽管本许可证存在其他规定，对于你添加到涵盖作品的材料，你可以（如果你获得该材料版权持有人的授权）以如下条款补充本许可证的条款：

        a）以异于第 15 和第 16 条的方式来拒供品质担保或限制责任；或

        b）要求在该材料中或在包含了该材料的作品所显示的适当的法律声明中，保留特定的合理法律声明或作者贡献信息；或

        c）禁止歪曲材料的来源，或要求合理标记修改版，说明其不是原版；或

        d）限制将该材料的作者或授权人的名字用于宣传目的；或

        e）拒绝在商标法下授予某些商品名、商标或服务标识的使用权；或

        f）要求任何输送该材料（或其修改版）并对接收者提供契约性责任承诺的人，保证这种许诺不会给作者或授权者带来连带责任。

    此外的所有非许可性附加条款都被视作第 10 节所说的“进一步的限制”。如果你接收到的程序或其部分，声称受本许可证约束，却补充了这种进一步的限制条款，你可以去掉它们。如果某许可证文档包含进一步的限制条款，但允许通过本许可证再许可或输送，那你可以为一份涵盖作品添加受那份许可证文档的条款所管理的材料，前提是进一步的限制在再许可或输送时不会生效。

    如果你根据本节向涵盖作品添加了条款，你必须在相关的源文件中声明应用于那些文件的附加条款，或者指出哪里可以找到适用的条款。

    附加条款，不管是许可性的还是非许可性的，可以以独立的书面许可证出现，也可以声明为例外情况，两种做法都可以实现上述要求。

    8. 终止许可

    除非本许可证明确授权，你不得传播或修改涵盖作品。其他任何传播或修改涵盖作品的企图都是无效的，并将自动终止你通过本许可证获得的权利（包括第 11 节第 3 段中授予的一切专利许可）。

    然而，当你不再违反本许可证时，你的许可将从特定版权持有人处以如下方式恢复：(1)暂时恢复，直到版权持有人明确终止你的许可；及(2)永久恢复，如果版权持有人没能在许可终止后 60 天内以合理的方式通知你的违反行为。

    再者，如果你第一次收到了特定版权持有人关于你违反本许可证（对任意作品）的通告，且在收到通知后 30 天内改正了该违反行为，那你可以继续享有此许可。

    当你享有的权利在本节下被中止时，他方已经从你那通过本许可证获得的副本或权利的许可不会因此终止。如果你的权利已被终止且未被永久恢复，你没有资格凭第 10 节重新获得同一材料的授权。

    9. 持有副本无需接受本许可证

    你不必为接收或运行本程序而接受本许可证。类似地，仅仅因为点对点传输来接收副本而引发的对涵盖作品的辅助性传播，并不要求接受本许可证。但是，除本许可证外没有什么可以授权你传播或修改任何涵盖作品。如果你不接受本许可证，这些行为就侵犯了版权。因此，一旦你修改或传播一份涵盖作品，你即表明接受了本许可证。

    10. 对下游接收者的自动授权

    每当你输送一份涵盖作品，其接收者自动获得来自初始授权人的许可，批准你依照本许可证运行、修改和传播该作品。你没有要求第三方遵守本许可证的义务。

    “实体交易”指转移一个组织的控制权或基本全部资产、或拆分一个组织或将组织合并的交易行为。如果实体交易导致一份涵盖作品的传播，则交易中收到作品副本的各方，都将如上一自然段所述，获得前人享有或可以提供的对该作品的任何许可，以及从前人处获得并拥有对应源代码的权利，如果前人享有或可以通过合理的努力获得此源代码。

    你不可以对本许可证所申明或授予的权利的行使施以进一步的限制。例如，你不可以索要授权费或版税，或就行使本许可证所授权利征收其他费用；你也不能发起诉讼（包括交互诉讼和反诉），宣称制作、使用、零售、批发、引进本程序或其部分的行为侵犯了任何专利。

    11. 专利

    “贡献者”指在本许可证下授予本程序或本程序基于的作品的使用权的版权持有人。授权作品称为贡献者的“贡献者版”。

    贡献者的“实质专利权”指该贡献者拥有或掌控的，无论是已获得的还是将获得的全部专利权中，在通过本许可证允许的某种方式来制作、使用或销售其贡献者版作品时可能会侵犯的专利权，但不包括仅在修改该贡献者版时才会侵犯的权利。此项定义中，“掌控”所指包括符合本许可证要求的对专利进行分许可的权利。

    每位贡献者皆就其实质专利权，授予你一份非独占的、全球有效的免版税专利许可，允许你制作、使用、零售、批发、引进，及运行、修改、传播其贡献者版的内容。

    在以下三自然段中，“专利许可”指通过任何方式明确说明的不行使专利权（例如对使用专利的明确许可或不起诉专利侵权的契约）的协议或承诺。对某方“授予”专利许可，指达成这种协议或承诺，不对该方强制执行专利权。

    如果你输送的涵盖作品已知依赖于某专利许可，且该作品的对应源代码并不是任何人都能根据本许可证从公开的网络服务器上或其他地方免费获得，那你必须做到以下之一：（1）以上述方式提供对应源代码；或（2）放弃从该程序的该专利许可中获得利益；或（3）以某种和本许可证相一致的方式将专利许可扩展到下游接收者。“已知依赖于”指你实际上知道若没有专利许可，你在某国家输送涵盖作品的行为，或者接收者在某国家使用涵盖作品的行为，会侵犯一项或多项该国认定的专利，而你有理由相信这些专利是有效的。

    在依照或涉及某一次交易或协定时，如果你输送一份涵盖作品或得到了输送的涵盖作品而构成了传播，并且为该作品的一些接收方授予了专利许可，以使他们可以使用、传播、修改或输送该作品的特定副本，则你授予的专利许可将自动延伸至每一个收到本作品或其修改版的接收者。

    如果某专利许可在其涵盖范围内不包含本许可证专门授予的一项或多项权利，或禁止行使上述权利，或以不行使上述权利为前提，则该专利许可是“歧视性”的。如果你和经营软件分发的第三方商业机构有合作，合作要求你更具涵盖作品的输送范围向其付费，并授予从你这里接收涵盖作品的第三方一份歧视性专利许可，且该专利许可（a）与你输送的涵盖作品副本（或在此基础上制作的副本）有关，或（b）针对且涉及包含了该涵盖作品的产品或联合体，那么你不得输送涵盖作品，除非你参加此项合作的时间或该专利许可的授予时间早于 2007 年 3 月 28 日。

    本许可证的任何部分不应被解释成在排斥或限制任何暗含的授权，或者其他在适用法律下对抗侵权的措施。

    12. 不得抛弃他人的自由

    即便你面临与本许可证条款相冲突的条款（无论来自于法庭要求、协议还是其他地方），你也不能以此为由违背本许可证的条款。如果你不能在输送该涵盖作品的同时满足来自本许可证的要求和其他相关的要求，那么你就不能输送该涵盖作品。例如，当你同意了某些需要你在再输送时向你的输送对象收取版税的条款时，唯一能同时满足这些条款和本许可证要求的做法便是不输送本程序。

    13. 和 GNU Affero 通用公共许可证一起使用

    尽管本许可证存在其他规定，你有权将任何涵盖作品与通过 GNU Affero 通用公共许可证授权的作品关联或组合成一份联合作品，及输送该联合作品。本许可证对其中的涵盖作品部分仍然有效，但 GNU Affero 通用公共许可证第 13 节的关于网络交互的特别要求适用于整个联合作品。

    14. 本许可证的修订版

    自由软件基金会可能会不定时发布 GNU 通用公共许可证的修订版和/或新版。新版将秉承当前版本的精神，但在细节上会有差异，以应对新的问题或事项。

    每一版都会有不同的版本号。如果本程序指定其使用 GNU 通用公共许可证的特定版本“或任何后续的版本”，你可以选择遵守该版本或者自由软件基金会发布的任何后续版本的条款与条件。如果本程序没有指定 GNU 通用公共许可证的版本，你可以选用自由软件基金会发布的任意版本。

    如果本程序指定一位代理人来决定使用哪个将来的 GNU 通用公共许可证版本，则该代理人通过公开声明采用的版本，永久许可你为本程序使用该版本。

    新的许可证版本可能会给予你额外或不同的许可。但是，任何作者或版权持有人的义务，不会因为你选择新的版本而增加。

    15. 不提供品质担保

    本程序在适用法律范围内不提供品质担保。除非另作书面声明，版权持有人和/或第三方“一概”不提供任何显示或隐式的品质担保，品质担保所指包括而不仅限于有经济价值和适合特定用途的保证。全部风险，如程序的质量和性能问题，皆由你承担。若程序出现缺陷，你将承担所有必要的服务费、修复费和更正费。

    16. 责任范围

    除非受适用法律或书面协议要求，任何版权持有人或任何在本许可证下修改和/或输送本程序的第三方，都不对你的损失负有责任，包括由于使用或者不能使用本程序造成的任何一般的、特殊的、偶发的或必然的损失（包括但不限于数据丢失、数据失真、你或第三方的后续损失、其他程序无法与本程序协同运作的问题），即使版权持有人或第三方受到过要求要对这样的损失负责。

    17. 第 15 节和第 16 节的解释

    如果上述不提供品质担保的声明和责任范围声明不为地方法律所支持，复审法庭应采用最接近于完全放弃本程序相关民事责任的地方法律，除非本程序附带收费的品质担保或责任许诺。

                            条款和条件至此结束

            如何将上述条款应用到你的新程序

    如果你开发了一个新程序，并希望它能最大限度地为公众所使用，最好的办法是使其成为自由软件，使每个人都能通过上述条款对其再分发及修改。

    为此，请为程序附上以下声明。最安全的做法是将其附在每份源文件的开头，以便于最有效地传递免责信息；且每个文件至少应包含一行“版权”声明并告知许可证全文的位置。

        <用一行来标明程序名及其作用。>
        版权所有 (C) <年份> <作者名称>

        本程序为自由软件：在自由软件基金会发布的 GNU 通用公共许可证的约束下，
        你可以对其进行再分发及修改。许可证版本为第三版或（你可选的）后续版本。

        我们希望发布的这款程序有用，但其不带任何担保；甚至不默认保证它有经济
        价值和适合特定用途。详情参见 GNU 通用公共许可证。

        你理当已收到一份 GNU 通用公共许可证的副本。如果你没有收到它，请查阅
        <https://www.gnu.org/licenses/>。

同时提供你的电子及书面邮件联系方式。

    如果该程序是在终端交互式操作的，则让它在交互模式开始时输出类似下面的一段声明：

        <程序名> 版权所有 (C) <年份> <作者名称>
        本程序不提供任何品质担保，输入 'show w' 可查看详情。
        本程序是自由软件，欢迎你在满足一定条件后对其再发布；
        输入 'show c' 可查看详情。

例子中的命令 'show w' 和 'show c' 应该用于显示 GNU 通用公共许可证相应的部分。当然，你也可以为程序选用其他命令，对图形界面，你可以使用“关于”提示框。

    如果你之上存在雇主（你是程序员）或校方，你还应当让他们在必要时为此程序签署“放弃版权声明”。欲知这方面的详情，以及如何应用和遵守 GNU GPL，请参见 <https://www.gnu.org/licenses/>。

    本 GNU 通用公共许可证不允许把你的程序并入专有程序。如果你的程序是一个子程序库，你可能会认为允许它被专有应用程序链接会使之更有用。如果你想允许这种行为的话，请使用 GNU 宽通用公共许可证。但在此之前，请先阅读 <https://www.gnu.org/philosophy/why-not-lgpl.html>。
"""

if __name__ == "__main__":
    from argparse import ArgumentParser, RawTextHelpFormatter

    parser = ArgumentParser(formatter_class=RawTextHelpFormatter, description=__doc__)
    parser.add_argument("-cp", "--cookies-path", default="", help="cookies 文件保存路径，默认为当前工作目录下的 115-cookies.txt")
    parser.add_argument("-p", "--password", help="执行 POST 请求所需密码")
    parser.add_argument("-t", "--token", default="", help="用于给链接进行签名的 token，如果不提供则无签名")
    parser.add_argument("-pcs", "--path-cache-size", type=int, default=1048576, help="路径缓存的容量大小，默认值 1048576，等于 0 时关闭，小于等于 0 时不限")
    parser.add_argument("-pct", "--path-cache-ttl", type=float, default=0, help="路径缓存的存活时间，小于等于 0 或等于 inf 或 nan 时不限，默认为不限")
    parser.add_argument("-H", "--host", default="0.0.0.0", help="ip 或 hostname，默认值：'0.0.0.0'")
    parser.add_argument("-P", "--port", default=8000, type=int, help="端口号，默认值：8000")
    parser.add_argument("-v", "--version", action="store_true", help="输出版本号")
    parser.add_argument("-l", "--license", action="store_true", help="输出授权信息")

    args = parser.parse_args()
    if args.version:
        print(".".join(map(str, __version__)))
        raise SystemExit(0)
    elif args.license:
        print(__license_str_zh__)
        raise SystemExit(0)

try:
    from blacksheep import json, redirect, text, Application, FromJSON, Router
    from blacksheep.client.session import ClientSession
    from blacksheep.exceptions import HTTPException
    from blacksheep.server.compression import use_gzip_compression
    from blacksheep.server.openapi.common import ParameterInfo
    from blacksheep.server.openapi.ui import ReDocUIProvider
    from blacksheep.server.openapi.v3 import OpenAPIHandler
    from blacksheep.server.remotes.forwarding import ForwardedHeadersMiddleware
    from blacksheep.messages import Request
    from blacksheep_client_request import request as blacksheep_request
    from cachetools import LRUCache, TTLCache
    from openapidocs.v3 import Info # type: ignore
    from p115client import P115Client, AuthenticationError, SUFFIX_TO_TYPE
    from p115client.tool.iterdir import iter_files, _iter_fs_files
    from posixpatht import dirname, escape, joins, splits
except ImportError:
    from sys import executable
    from subprocess import run
    run([executable, "-m", "pip", "install", "-U", *__requirements__], check=True)
    from blacksheep import json, redirect, text, Application, FromJSON, Router
    from blacksheep.client.session import ClientSession
    from blacksheep.exceptions import HTTPException
    from blacksheep.server.compression import use_gzip_compression
    from blacksheep.server.openapi.common import ParameterInfo
    from blacksheep.server.openapi.ui import ReDocUIProvider
    from blacksheep.server.openapi.v3 import OpenAPIHandler
    from blacksheep.server.remotes.forwarding import ForwardedHeadersMiddleware
    from blacksheep.messages import Request
    from blacksheep_client_request import request as blacksheep_request
    from cachetools import LRUCache, TTLCache
    from openapidocs.v3 import Info # type: ignore
    from p115client import P115Client, AuthenticationError, SUFFIX_TO_TYPE
    from p115client.tool.iterdir import iter_files, _iter_fs_files
    from posixpatht import dirname, escape, joins, splits

import errno
import logging

from asyncio import create_task, CancelledError, Queue
from collections.abc import AsyncIterator, Callable, MutableMapping
from functools import partial, update_wrapper
from hashlib import sha1 as calc_sha1
from math import inf, isinf, isnan
from pathlib import Path
from string import hexdigits
from sys import maxsize
from time import time
from typing import cast, Literal
from urllib.parse import unquote, urlsplit


def reduce_image_url_layers(url: str, /) -> str:
    if not url.startswith(("http://thumb.115.com/", "https://thumb.115.com/")):
        return url
    urlp = urlsplit(url)
    sha1 = urlp.path.rsplit("/")[-1].split("_")[0]
    return f"https://imgjump.115.com/?sha1={sha1}&{urlp.query}&size=0"


def make_application(
    cookies_path: str | Path = "", 
    password: str = "", 
    token: str = "", 
    path_cache_size: int = 1048576, 
    path_cache_ttl: int | float = 0, 
) -> Application:
    # NOTE: cookies 保存路径
    if cookies_path:
        cookies_path = Path(cookies_path)
    else:
        cookies_path = Path("115-cookies.txt")
    # NOTE: id   到 pickcode 的映射
    ID_TO_PICKCODE: MutableMapping[str, str] = LRUCache(65536)
    # NOTE: sha1 到 pickcode 的映射
    SHA1_TO_PICKCODE: MutableMapping[str, str] = LRUCache(65536)
    # NOTE: path 到 pickcode 的映射
    PATH_TO_PICKCODE: None | MutableMapping[str, str] = None
    if path_cache_size:
        if path_cache_ttl > 0 and not isinf(path_cache_ttl) and not isnan(path_cache_ttl):
            if path_cache_size > 0:
                PATH_TO_PICKCODE = TTLCache(path_cache_size, path_cache_ttl)
            else:
                PATH_TO_PICKCODE = TTLCache(maxsize, path_cache_ttl)
        elif path_cache_size > 0:
            PATH_TO_PICKCODE = LRUCache(path_cache_size)
        else:
            PATH_TO_PICKCODE = {}
    # NOTE: 缓存图片的 CDN 直链 1 小时
    IMAGE_URL_CACHE: MutableMapping[str, bytes] = TTLCache(inf, ttl=3600)
    # NOTE: 限制请求频率，以一组请求信息为 key，0.5 秒内相同的 key 只放行一个
    URL_COOLDOWN: MutableMapping[tuple, None] = TTLCache(1024, ttl=0.5)
    # NOTE: 下载链接缓存，以减少接口调用频率，只需缓存很短时间
    URL_CACHE: MutableMapping[tuple, str] = TTLCache(64, ttl=1)
    # NOTE: 缓存字幕的 CDN 直链 1 小时
    SUBTITLE_URL_CACHE: MutableMapping[str, bytes] = TTLCache(inf, ttl=3600)
    # 排队任务（一次性运行，不在周期性运行的 cids 列表中）
    QUEUE: Queue[tuple[str, Literal[1,2,3,4,5,6,7,99]]] = Queue()
    # 执行 POST 请求时所需要携带的密码
    PASSWORD = password
    # blacksheep 应用
    app = Application(router=Router())
    use_gzip_compression(app)
    # 启用文档
    docs = OpenAPIHandler(info=Info(
        title="web-115-302.py web api docs", 
        version=".".join(map(str, __version__)), 
    ))
    docs.ui_providers.append(ReDocUIProvider())
    docs.bind_app(app)
    # 日志对象
    logger = getattr(app, "logger")
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[\x1b[1m%(asctime)s\x1b[0m] (\x1b[1;36m%(levelname)s\x1b[0m) \x1b[5;31m➜\x1b[0m %(message)s"))
    logger.addHandler(handler)
    # 后台任务中，正在运行的任务
    qrunning_task = None
    # 后台任务中运行的 cid
    qcid = ""

    def redirect_exception_response(func, /):
        async def wrapper(*args, **kwds):
            try:
                return await func(*args, **kwds)
            except BaseException as e:
                if isinstance(e, HTTPException):
                    return text(f"{type(e).__module__}.{type(e).__qualname__}: {e}", e.status)
                elif isinstance(e, AuthenticationError):
                    return json(e.args[1], 401)
                elif isinstance(e, PermissionError):
                    return json(e.args[1], 403)
                elif isinstance(e, FileNotFoundError):
                    return json(e.args[1], 404)
                elif isinstance(e, (IsADirectoryError, NotADirectoryError)):
                    return json(e.args[1], 406)
                elif isinstance(e, OSError):
                    if (args := e.args) and len(args) >= 2:
                        message = args[1]
                        if isinstance(message, dict):
                            return json(message, 500)
                    return json({"state": False, "message": str(e)}, 500)
                elif isinstance(e, Exception):
                    return json({"state": False, "message": str(e)}, 503)
                raise
        return update_wrapper(wrapper, func)

    def normalize_attr(
        info: dict, 
        /, 
        dirname: str = "", 
    ) -> dict:
        """对文件信息进行规范化
        """
        is_image = False
        if "file_id" in info or "file_name" in info:
            file_id = info.get("file_id", "")
            if file_id:
                file_id = str(file_id)
            file_name = cast(str, info["file_name"])
            pick_code = cast(str, info["pick_code"])
            if "file_sha1" in info:
                file_sha1 = info["file_sha1"]
            elif "sha1" in info:
                file_sha1 = info["sha1"]
            else:
                file_sha1 = ""
            if "origin_url" in info:
                thumb = info["origin_url"]
            elif "img_url" in info:
                thumb = info["img_url"]
                is_image = True
            else:
                thumb = ""
        else:
            if "fn" in info:
                file_id = str(info["fid"])
                file_name = cast(str, info["fn"])
                pick_code = cast(str, info["pc"])
                file_sha1 = cast(str, info["sha1"])
                thumb = info.get("thumb", "")
                if thumb.startswith("?"):
                    is_image = True
                    thumb = f"https://imgjump.115.com{thumb}&size=0&sha1={file_sha1}"
            else:
                file_id = str(info["fid"])
                file_name = cast(str, info["n"])
                pick_code = cast(str, info["pc"])
                file_sha1 = cast(str, info["sha"])
                thumb = info.get("u", "")
                if info.get("class") in ("PIC", "JG_PIC"):
                    is_image = True
                    thumb = reduce_image_url_layers(thumb)
        if file_sha1:
            SHA1_TO_PICKCODE[file_sha1] = pick_code
        if file_id:
            ID_TO_PICKCODE[file_id] = pick_code
        if PATH_TO_PICKCODE is not None and dirname:
            PATH_TO_PICKCODE[dirname + "/" + escape(file_name)] = pick_code
        attr = {"id": file_id, "name": file_name, "pickcode": pick_code, "sha1": file_sha1}
        if thumb:
            attr["thumb"] = bytes(thumb, "utf-8")
        if is_image:
            IMAGE_URL_CACHE[pick_code] = attr["thumb"]
        return attr

    async def load_files(
        cid: int | str = "0", 
        /, 
        type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    ) -> int:
        """批量拉取文件信息，以构建缓存
        """
        client = app.services.resolve(ClientSession)
        p115client = app.services.resolve(P115Client)
        with_path = PATH_TO_PICKCODE is not None
        count = 0
        async for attr in iter_files(
            p115client, 
            int(cid), 
            type=type, 
            async_=True, 
            with_path=with_path, 
            request=blacksheep_request, 
            session=client, 
            app="android", 
        ):
            pickcode = attr["pickcode"]
            ID_TO_PICKCODE[str(attr["id"])] = pickcode
            SHA1_TO_PICKCODE[attr["sha1"]] = pickcode
            if with_path:
                PATH_TO_PICKCODE[attr["path"]] = pickcode # type: ignore
            if (thumb := attr.get("thumb")) and thumb.startswith("https://imgjump.115.com"):
                IMAGE_URL_CACHE[pickcode] = thumb
            count += 1
        return count

    async def queue_load_files():
        nonlocal qrunning_task, qcid
        while True:
            qcid, type = await QUEUE.get()
            this_start = time()
            qrunning_task = create_task(load_files(qcid, type=type))
            try:
                logger.info(f"background task start: cid={qcid}")
                count = await qrunning_task
            except CancelledError as e:
                logger.warning(f"task cancelled cid={qcid}")
                if not e.args or e.args[0] == "shutdown":
                    return
                cmd = e.args[0]
                if cmd == "sleep":
                    break
            except Exception:
                logger.exception(f"error occurred while loading cid={qcid}")
            else:
                logger.info(f"successfully loaded cid={qcid}, {count} files, {time() - this_start:.6f} seconds")
            finally:
                qcid = ""
                qrunning_task = None
                QUEUE.task_done()

    def iterdir(
        client: P115Client, 
        cid: str, 
        /, 
        only_dirs_or_files: None | bool = None, 
        request: None | Callable = None, 
    ) -> AsyncIterator[dict]:
        """获取目录中的文件信息迭代器
        """
        payload = {"cid": cid, "cur": 1, "fc_mix": 1, "show_dir": 1, "limit": 10_000}
        only_dirs = only_dirs_or_files
        if only_dirs is None:
            only_dirs = False
        elif only_dirs:
            payload["fc_mix"] = 0
        else:
            payload["show_dir"] = 0
        return _iter_fs_files(client, payload, only_dirs=only_dirs, app="android", async_=True, request=request)

    async def get_attr_by_id(
        client: P115Client, 
        id: str, 
        /, 
        request: None | Callable = None, 
    ) -> dict:
        """获取 id 对应的文件的 信息
        """
        resp = await client.fs_file(id, base_url=True, async_=True, request=request)
        if not resp["state"]:
            resp["file_id"] = id
            raise FileNotFoundError(errno.ENOENT, resp)
        info = resp["data"][0]
        if "fid" not in info:
            raise FileNotFoundError(
                errno.EISDIR, 
                {"state": False, "message": "not a file", "file_id": id}, 
            )
        return normalize_attr(info)

    async def get_pickcode_by_id(
        client: P115Client, 
        id: str, 
        /, 
        request: None | Callable = None, 
    ) -> str:
        """获取 id 对应的文件的 pickcode
        """
        if pickcode := ID_TO_PICKCODE.get(id):
            return pickcode
        attr = await get_attr_by_id(client, id, request=request)
        return attr["pickcode"]

    async def get_pickcode_by_sha1(
        client: P115Client, 
        sha1: str, 
        /, 
        request: None | Callable = None, 
    ) -> str:
        """获取 sha1 对应的文件的 pickcode
        """
        if pickcode := SHA1_TO_PICKCODE.get(sha1):
            return pickcode
        resp = await client.fs_shasearch(sha1, async_=True, request=request)
        if not resp["state"]:
            raise FileNotFoundError(
                errno.ENOENT, 
                {"state": False, "message": "no such sha1", "sha1": sha1}, 
            )
        info = resp["data"]
        info["file_sha1"] = sha1
        return normalize_attr(info)["pickcode"]

    async def get_pickcode_by_path(
        client: P115Client, 
        path: str, 
        /, 
        request: None | Callable = None, 
        cache: bool = True, 
    ) -> str:
        """获取路径对应的文件的 pickcode
        """
        error = FileNotFoundError(
            errno.ENOENT, 
            {"state": False, "message": "no such path to file", "path": path}, 
        )
        patht, _ = splits("/" + path)
        if len(patht) == 1:
            raise error
        path = joins(patht)
        if (
            cache and 
            PATH_TO_PICKCODE is not None and
            (pickcode := PATH_TO_PICKCODE.get(path))
        ):
            return pickcode
        i = 1
        if len(patht) > 2:
            for i in range(1, len(patht) - 1):
                name = patht[i]
                if "/" in name:
                    break
            else:
                i += 1
        if i == 1:
            cid = "0"
            dirname = "/"
        else:
            dirname = "/".join(patht[:i])
            resp = await client.fs_dir_getid(dirname, async_=True, request=request)
            if not (resp["state"] and (cid := resp["id"])):
                raise error
        for name in patht[i:-1]:
            async for info in iterdir(client, cid, only_dirs_or_files=True, request=request):
                if info["fn"] == name:
                    cid = info["pid"]
                    dirname += "/" + escape(name)
                    break
            else:
                raise error
        name = patht[-1]
        async for info in iterdir(client, cid, only_dirs_or_files=False, request=request):
            attr = normalize_attr(info, dirname)
            if attr["name"] == name:
                return attr["pickcode"]
        else:
            raise error

    async def get_url(
        client: P115Client, 
        pickcode: str, 
        /, 
        user_agent: str = "", 
        request: None | Callable = None, 
    ) -> str:
        """获取文件的下载链接
        """
        resp = await client.download_url_app(
            pickcode, 
            headers={"User-Agent": user_agent}, 
            async_=True, 
            request=request, 
        )
        if not resp["state"]:
            resp["pickcode"] = pickcode
            raise FileNotFoundError(errno.ENOENT, resp)
        fid, info = next(iter(resp["data"].items()))
        pickcode = info["pick_code"]
        ID_TO_PICKCODE[fid] = SHA1_TO_PICKCODE[info["sha1"]] = pickcode
        if SUFFIX_TO_TYPE.get(info["file_name"].lower()) == 2:
            IMAGE_URL_CACHE.setdefault(pickcode, b"")
        return info["url"]["url"]

    async def get_image_url(
        client: P115Client, 
        pickcode: str, 
        /, 
        request: None | Callable = None, 
    ) -> bytes:
        """获取图片的 cdn 链接
        """
        if url := IMAGE_URL_CACHE.get(pickcode):
            return url
        resp = await client.fs_image(pickcode, async_=True, request=request)
        if not resp["state"]:
            raise FileNotFoundError(
                errno.ENOENT, 
                {"state": False, "message": "no such pickcode to image", "pickcode": pickcode}, 
            )
        return normalize_attr(resp["data"])["thumb"]

    async def get_subtitle_url(
        client: P115Client, 
        pickcode: str, 
        /, 
        request: None | Callable = None, 
    ) -> bytes:
        """获取字幕的下载链接
        """
        if url := SUBTITLE_URL_CACHE.get(pickcode):
            return url
        resp = await client.fs_video_subtitle(pickcode, async_=True, request=request)
        if not resp["state"]:
            raise FileNotFoundError(
                errno.ENOENT, 
                {"state": False, "message": "no such pickcode to subtitle", "pickcode": pickcode}, 
            )
        dir_ = ""
        if PATH_TO_PICKCODE is not None:
            try:
                for k, v in PATH_TO_PICKCODE.items():
                    if v == pickcode:
                        dir_ = dirname(k)
                        break
            except RuntimeError:
                pass
        url = b""
        for info in resp["data"]["list"]:
            if pickcode2 := info.get("pick_code"):
                attr = normalize_attr(info, dir_)
                url2 = SUBTITLE_URL_CACHE[pickcode2] = bytes(info["url"], "utf-8")
                if pickcode == pickcode2:
                    url = url2
        if not url:
            raise FileNotFoundError(
                errno.ENOENT, 
                {"state": False, "message": "no such pickcode to subtitle", "pickcode": pickcode}, 
            )
        return url

    @app.on_middlewares_configuration
    def configure_forwarded_headers(app: Application):
        app.middlewares.insert(0, ForwardedHeadersMiddleware(accept_only_proxied_requests=False))

    @app.lifespan
    async def register_client(app: Application):
        async with ClientSession(follow_redirects=False) as client:
            app.services.register(ClientSession, instance=client)
            yield

    @app.lifespan
    async def register_p115client(app: Application):
        client = P115Client(
            cookies_path, 
            app="alipaymini", 
            check_for_relogin=True, 
        )
        async with client.async_session:
            app.services.register(P115Client, instance=client)
            yield

    @app.lifespan
    async def start_tasks(app: Application):
        queue_task = create_task(queue_load_files())
        try:
            yield
        finally:
            queue_task.cancel("shutdown")

    @app.router.route("/", methods=["GET", "HEAD"])
    @app.router.route("/{path:path2}", methods=["GET", "HEAD"])
    @redirect_exception_response
    async def get_download_url(
        request: Request, 
        client: ClientSession, 
        p115client: P115Client, 
        pickcode: str = "", 
        id: str = "", 
        sha1: str = "", 
        path: str = "", 
        path2: str = "", 
        kind: str = "file", 
        cache: bool = True, 
        sign: str = "", 
        t: int = 0, 
    ):
        """获取文件的下载链接

        :param pickcode: 文件或目录的 pickcode，优先级高于 id
        :param id: 文件的 id，优先级高于 sha1
        :param sha1: 文件的 sha1，优先级高于 path
        :param path: 文件的路径，优先级高于 path2
        :param path2: 文件的路径，这个直接在接口路径之后，不在查询字符串中
        :param kind: 文件类型，默认为 **file**，用于返回特定的下载链接
            <br />- **file**&colon; 文件，返回普通的链接（有并发数限制）
            <br />- **image**&colon; 图片，返回 CDN 链接（无并发数限制）
            <br />- **subtitle**&colon; 字幕，返回链接（无并发数限制）
        :param cache: 是否使用 路径 到 pickcode 的缓存
        :param sign: 签名，计算方式为 `hashlib.sha1(bytes(f"302@115-{token}-{t}-{value}", "utf-8")).hexdigest()`
            <br />- **token**&colon; 命令行中所传入的 token
            <br />- **t**&colon; 过期时间戳（超过这个时间后，链接不可用）
            <br />- **value**&colon; 按顺序检查 `pickcode`、`id`、`sha1`、`path`、`path2`，最先有效的那个值
        :param t: 过期时间戳
        """
        def check_sign(value, /):
            if not token:
                return None
            if sign != calc_sha1(bytes(f"302@115-{token}-{t}-{value}", "utf-8")).hexdigest():
                return json({"state": False, "message": "invalid sign"}, 403)
            elif t > 0 and t <= time():
                return json({"state": False, "message": "url was expired"}, 401)
        do_request = partial(blacksheep_request, session=client)
        if pickcode := pickcode.strip().lower():
            if resp := check_sign(pickcode):
                return resp
            if not pickcode.isalnum():
                return json({"state": False, "message": f"bad pickcode: {pickcode!r}"}, 400)
        elif id := id.strip():
            if resp := check_sign(id):
                return resp
            if id.startswith("0") or not id.isdecimal():
                return json({"state": False, "message": f"bad id: {id!r}"}, 400)
            pickcode = await get_pickcode_by_id(p115client, id, do_request)
        elif sha1 := sha1.strip().upper():
            if resp := check_sign(sha1):
                return resp
            if len(sha1) != 40 or sha1.strip(hexdigits):
                return json({"state": False, "message": f"bad sha1: {sha1!r}"}, 400)
            pickcode = await get_pickcode_by_sha1(p115client, sha1, do_request)
        else:
            value = unquote(path) or path2
            if not value:
                return json({"state": False, "message": "no query value"}, 400)
            if resp := check_sign(value):
                return resp
            pickcode = await get_pickcode_by_path(p115client, value, do_request, cache)
        match kind:
            case "image":
                return redirect(await get_image_url(p115client, pickcode, do_request))
            case "subtitle":
                return redirect(await get_subtitle_url(p115client, pickcode, do_request))
            case _:
                user_agent = (request.get_first_header(b"User-agent") or b"").decode("latin-1")
                bytes_range = (request.get_first_header(b"Range") or b"").decode("latin-1")
                if bytes_range and not user_agent.lower().startswith(("vlc/", "oplayer/", "lavf/")):
                    remote_addr = request.original_client_ip
                    cooldown_key = (pickcode, remote_addr, user_agent, bytes_range)
                    if cooldown_key in URL_COOLDOWN:
                        return text("too many requests", 429)
                    URL_COOLDOWN[cooldown_key] = None
                    key = (pickcode, remote_addr, user_agent)
                    if not (url := URL_CACHE.get(key)):
                        URL_CACHE[key] = url = await get_url(p115client, pickcode, user_agent, do_request)
                else:
                    url = await get_url(p115client, pickcode, user_agent, do_request)
                return redirect(url)

    @app.router.route("/run", methods=["POST"])
    async def do_run(request: Request, cid: str = "0", type: int = 2, password: str = ""):
        """运行后台（预热）任务

        :param cid: 把此 cid 加入后台（预热）任务（默认值 0）
        :param type: 文件类型（默认值 2）
              <br />- **1**&colon; 文档
              <br />- **2**&colon; 图片
              <br />- **3**&colon; 音频
              <br />- **4**&colon; 视频
              <br />- **5**&colon; 压缩包
              <br />- **6**&colon; 应用
              <br />- **7**&colon; 书籍
              <br />- **99**&colon; 任意文件
        :param password: 口令
        """
        if PASSWORD and PASSWORD != password:
            return json({"state": False, "message": "password does not match"}, 401)
        if type not in range(1, 8):
            type = 99
        QUEUE.put_nowait((cid, type)) # type: ignore
        return json({"state": True, "message": "ok"})

    @app.router.route("/skip", methods=["POST"])
    async def do_qskip(request: Request, cid: str = "0", password: str = ""):
        """跳过当前后台（预热）任务中正在运行的任务

        :param cid: 如果提供，则仅当正在运行的 cid 等于此 cid 时，才会取消任务
        :param password: 口令
        """
        if PASSWORD and PASSWORD != password:
            return json({"state": False, "message": "password does not match"}, 401)
        try:
            if not cid or cid == qcid:
                qrunning_task.cancel("skip") # type: ignore
        except AttributeError:
            pass
        return json({"state": True, "message": "ok"})

    @app.router.route("/running", methods=["POST"])
    async def get_batch_task_running(request: Request, password: str = ""):
        """批量任务中，是否有任务在运行中

        :param password: 口令
        """
        if PASSWORD and PASSWORD != password:
            return json({"state": False, "message": "password does not match"}, 401)
        if qrunning_task is None:
            return json({"state": True, "message": "ok", "value": False})
        else:
            return json({"state": True, "message": "ok", "value": True, "cid": qcid})

    @app.router.route("/cookies", methods=["POST"])
    async def set_cookies(request: Request, p115client: P115Client, password: str = "", body: None | FromJSON[dict] = None):
        """更新 cookies

        :param password: 口令
        :param body: 请求体为 json 格式 <code>{"value"&colon; "新的 cookies"}</code>
        """
        if PASSWORD and PASSWORD != password:
            return json({"state": False, "message": "password does not match"}, 401)
        if body:
            payload = body.value
            cookies = payload.get("value")
            if isinstance(cookies, str):
                try:
                    p115client.cookies = cookies
                    return json({"state": True, "message": "ok"})
                except Exception as e:
                    return json({"state": False, "message": str(e)})
        return json({"state": True, "message": "skip"})

    return app


if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError:
        from sys import executable
        from subprocess import run
        run([executable, "-m", "pip", "install", "-U", "uvicorn"], check=True)
        import uvicorn

    app = make_application(
        cookies_path=args.cookies_path, 
        password=args.password, 
        token=args.token, 
        path_cache_size=args.path_cache_size, 
        path_cache_ttl=args.path_cache_ttl, 
    )
    print(__doc__)
    uvicorn.run(
        app=app, 
        host=args.host, 
        port=args.port, 
        proxy_headers=True, 
        forwarded_allow_ips="*", 
    )

# TODO: 提供接口，可用于增删改查 PATH_TO_PICKCODE 的字典，支持使用正则表达式、通配符等，如果为 None，则报错（未开启路径缓存）
# TODO: 提供接口，可以修改 path_cache_size 和 path_cache_ttl（修改后可能导致部分数据丢失）
# TODO: 增加接口，用于一次性获取多个 id 对应的 pickcode
# TODO: 增加接口，支持一次性查询多个直链（需要使用 pickcode 或 id 才行）
# TODO: 缓存到本地的临时 sqlite 数据库中

