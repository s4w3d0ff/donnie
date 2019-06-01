#!/usr/bin/python
# -*- coding: utf-8 -*-
#
#    BTC: 13MXa7EdMYaXaQK6cDHqd4dwr2stBK3ESE
#    LTC: LfxwJHNCjDh2qyJdfu22rBFi2Eu8BjQdxj
#
#    https://github.com/s4w3d0ff/donnie
#
#    Copyright (C) 2018  https://github.com/s4w3d0ff
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
from . import tools
from . import poloapi

logger = tools.getLogger(__name__)


class Donnie(object):

    def __init__(self, key=None, secret=None, interval=2, *args, **kwargs):
        if not 'jsonNums' in kwargs:
            kwargs['jsonNums'] = float
        self.api = poloapi.Poloniex(key, secret, *args, **kwargs)
        self._running = False
        self.interval = interval
        self.mThread = None

    def setKeys(self, key, secret):
        self.api.key = key
        self.api.secret = secret

    def run(self):
        while self._running:
            tools.sleep(self.interval)

    def start(self):
        self.mThread = tools.Thread(target=self.run)
        self.mThread.daemon = True
        self._running = True
        self.mThread.start()
        logger.info('Main thread started')

    def stop(self):
        self._running = False
        self.mThread.join()
        logger.info('Main thread stopped/joined')


if __name__ == '__main__':
    bot = Donnie()
    bot.start()
    tools.sleep(5)
    bot.stop()
