# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Translates stuff into English
"""
import aiohttp
import asyncio
import re
import time

from telethon import events


class Translator:
    _TKK_RE = re.compile(r"tkk:'(\d+)\.(\d+)'", re.DOTALL)
    _BASE_URL = 'https://translate.google.com'
    _TRANSLATE_URL = 'https://translate.google.com/translate_a/single'
    _HEADERS = {
        'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:75.0) Gecko/20100101 Firefox/75.0'
    }

    def __init__(self, target='en', source='auto'):
        self._target = target
        self._source = source
        self._session = aiohttp.ClientSession(headers=self._HEADERS)
        self._tkk = None
        self._tkk_lock = asyncio.Lock()

    async def _fetch_tkk(self):
        async with self._session.get(self._BASE_URL) as resp:
            html = await resp.text()
            return tuple(map(int, self._TKK_RE.search(html).groups()))

    def _need_refresh_tkk(self):
        return (self._tkk is None) or (self._tkk[0] != int(time.time() / 3600))

    def _calc_token(self, text):
        """
        Original code by ultrafunkamsterdam/googletranslate:
        https://github.com/ultrafunkamsterdam/googletranslate/blob/bd3f4d0a1386ffa634c8ebbebb3603279f3ece99/googletranslate/__init__.py#L263
        """
        def xor_rot(a, b):
            size_b = len(b)
            c = 0
            while c < size_b - 2:
                d = b[c + 2]
                d = ord(d[0]) - 87 if 'a' <= d else int(d)
                d = (a % 0x100000000) >> d if '+' == b[c + 1] else a << d
                a = a + d & 4294967295 if '+' == b[c] else a ^ d
                c += 3
            return a

        a = []
        for i in text:
            val = ord(i)
            if val < 0x10000:
                a += [val]
            else:
                a += [
                    math.floor((val - 0x10000) / 0x400 + 0xD800),
                    math.floor((val - 0x10000) % 0x400 + 0xDC00),
                ]

        d = self._tkk
        b = d[0]
        e = []
        g = 0
        size = len(text)
        while g < size:
            l = a[g]
            if l < 128:
                e.append(l)
            else:
                if l < 2048:
                    e.append(l >> 6 | 192)
                else:
                    if (
                            (l & 64512) == 55296
                            and g + 1 < size
                            and a[g + 1] & 64512 == 56320
                    ):
                        g += 1
                        l = 65536 + ((l & 1023) << 10) + (a[g] & 1023)
                        e.append(l >> 18 | 240)
                        e.append(l >> 12 & 63 | 128)
                    else:
                        e.append(l >> 12 | 224)
                    e.append(l >> 6 & 63 | 128)
                e.append(l & 63 | 128)
            g += 1
        a = b
        for i, value in enumerate(e):
            a += value
            a = xor_rot(a, '+-a^+6')
        a = xor_rot(a, '+-3^+b+-f')
        a ^= d[1]
        if a < 0:
            a = (a & 2147483647) + 2147483648
        a %= 1000000
        return '{}.{}'.format(a, a ^ b)

    async def translate(self, text, target=None, source=None):
        if self._need_refresh_tkk():
            async with self._tkk_lock:
                self._tkk = await self._fetch_tkk()

        params = [
            ('client', 'webapp'),
            ('sl', source or self._source),
            ('tl', target or self._target),
            ('hl', 'en'),
            *[('dt', x) for x in ['at', 'bd', 'ex', 'ld', 'md', 'qca', 'rw', 'rm', 'sos', 'ss', 't']],
            ('ie', 'UTF-8'),
            ('oe', 'UTF-8'),
            ('otf', 1),
            ('ssel', 0),
            ('tsel', 0),
            ('tk', self._calc_token(text)),
            ('q', text),
        ]

        async with self._session.get(self._TRANSLATE_URL, params=params) as resp:
            data = await resp.json()
            return ''.join(part[0] for part in data[0] if part[0] is not None)

    async def close(self):
        await self._session.close()


translator = Translator()


@borg.on(events.NewMessage(pattern=r"\.tl", outgoing=True))
async def _(event):
    if event.is_reply:
        text = (await event.get_reply_message()).raw_text
    else:
        text = ''
        started = False
        async for m in borg.iter_messages(event.chat_id):
            if started and m.sender_id == borg.uid:
                break
            if m.sender_id != borg.uid:
                started = True
            if not started or not m.raw_text:
                continue
            if ' ' in m.raw_text:
                text = m.raw_text + '\n' + text
            else:
                text = m.raw_text + ' ' + text

    translated = await translator.translate(text.strip())
    await event.edit('translation: ' + translated, parse_mode=None)


async def unload():
    await translator.close()