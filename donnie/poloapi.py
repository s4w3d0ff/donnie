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

import poloniex
from .tools import (getDatabase, getLogger, zoomOHLC, addIndicators,
                    getChartDataFrame, updateChartData, getLastEntry,
                    UTCstr2epoch, epoch2UTCstr, time)

logger = getLogger(__name__)


class Poloniex(poloniex.PoloniexSocketed):
    def __init__(self, *args, **kwargs):
        kwargs['subscribe'] = kwargs.get('subscribe', d={'ticker': self.on_ticker})
        kwargs['start'] = kwargs.get('start', d=true)
        kwargs['jsonNums'] = kwargs.get('jsonNums', d=float)
        super(Poloniex, self).__init__(*args, **kwargs)
        self.db = getDatabase('poloniex')
        # holds stop orders
        self.stopOrders = {}
        # holds ticker data
        self.tick = {}
        # holds market ids
        self._ids = {}
        # get inital ticker data
        iniTick = self.returnTicker()
        for market in iniTick:
            self._ids[market] = int(iniTick[market]['id'])
            self.tick[self._ids[market]] = {
                item: float(iniTick[market][item]) for item in iniTick[market]
                }


    def on_ticker(self, msg):
        # save ticker updates to self.tick
        data = [float(dat) for dat in msg]
        self.tick[int(data[0])] = {'id': int(data[0]),
                                  'last': data[1],
                                  'lowestAsk': data[2],
                                  'highestBid': data[3],
                                  'percentChange': data[4],
                                  'baseVolume': data[5],
                                  'quoteVolume': data[6],
                                  'isFrozen': int(data[7]),
                                  'high24hr': data[8],
                                  'low24hr': data[9]
                                  }
        # check stop orders
        self.checkMarketStops(int(data[0]), data[2], data[3])

    def checkMarketStops(self, mkt, la, hb):
        if isinstance(mkt, int):
            mkt = self._getChannelName(mkt)
        for id in self.stopOrders:
            # market matches and the order hasnt triggered yet
            if str(self.stopOrders[id]['market']) == str(mkt) and not self.stopOrders[id]['order']:
                self.logger.info('%s lowAsk=%s highBid=%s', mkt, str(la), str(hb))
                self._check_stop(id, la, hb)


    def _check_stop(self, id, lowAsk, highBid):
        amount = self.stopOrders[id]['amount']
        stop = self.stopOrders[id]['stop']
        # sell
        if amount < 0 and stop >= float(highBid):
            # dont place order if we are testing
            self.stopOrders[id]['order'] = True
            if not self.stopOrders[id]['test']:
                # sell amount at limit
                self.stopOrders[id]['order'] = self.sell(
                    self.stopOrders[id]['market'],
                    self.stopOrders[id]['limit'],
                    abs(amount))

            self.logger.info('%s sell stop order triggered! (%s)',
                             self.stopOrders[id]['market'],
                             str(stop))
            if self.stopOrders[id]['callback']:
                self.stopOrders[id]['callback'](id)

        # buy
        if amount > 0 and stop <= float(lowAsk):
            # dont place order if we are testing
            self.stopOrders[id]['order'] = True
            if not self.stopOrders[id]['test']:
                self.stopOrders[id]['order'] = self.buy(
                    self.stopOrders[id]['market'],
                    self.stopOrders[id]['limit'],
                    amount)

            self.logger.info('%s buy stop order triggered! (%s)',
                             self.stopOrders[id]['market'],
                             str(stop))
            if self.stopOrders[id]['callback']:
                self.stopOrders[id]['callback'](id)


    def addStopLimit(self, market, amount, stop, limit, callback=None, test=False):
        self.stopOrders[market+str(stop)] = {'market': market,
                                             'amount': amount,
                                             'stop': stop,
                                             'limit': limit,
                                             'callback': callback,
                                             'test': test,
                                             'order': False
                                            }
        self.logger.info('%s stop limit set: [Amount]%.8f [Stop]%.8f [Limit]%.8f',
                          market, amount, stop, limit)


    def ticker(self, market=None):
        """
        Returns ticker data saved from websocket. Returns a logger error
        and REST ticker data if the socket isnt running. Auto-subscribes to
        ticker if the socket is running and not subscribed.
        """
        if not self.channels['ticker']['sub']:
            if not self._t or not self._running:
                self.logger.error("Websocket isn't running!")
                return self.returnTicker()
            else:
                self.logger.error("Not subscribed to ticker! Subscribing...")
                self.subscribe('ticker', self.on_ticker)
                return self.returnTicker()
        if market:
            return self.tick[self._ids[market]]
        return self.tick


    def cbck(self, id):
        """
        Example callback for stop orders
        """
        print(self.stopOrders[id])


    def chartDataFrame(self, pair, frame=172800, zoom=False, indica=False):
        """ returns chart data in a dataframe from mongodb, updates/fills the
        data, the date column is the '_id' of each candle entry, and
        the date column has been removed. Use 'frame' to restrict the amount
        of data returned.
        Example: 'frame=self.YEAR' will return last years data
        """
        dbcolName = pair.upper() + '-chart'

        # get db collection
        db = self.db[dbcolName]

        # get last candle data
        last = getLastEntry(db)

        # no entrys found, get all 5min data from poloniex
        if not last:
            self.logger.warning('%s collection is empty!', dbcolName)
            last = {
                '_id': UTCstr2epoch("2015-01-01", fmat="%Y-%m-%d")
                }

        stop = int(last['_id'])
        start = time()
        end = time()
        flag = True
        while not int(stop) == int(start) and flag:
            # get 3 months of data at a time
            start -= self.MONTH * 3

            # dont go past 'stop'
            if start < stop:
                start = stop

            # get needed data
            self.logger.debug('Getting %s - %s %s candles from Poloniex...',
                              epoch2UTCstr(start), epoch2UTCstr(end), pair)
            new = self.returnChartData(pair,
                                       period=60 * 5,
                                       start=start,
                                       end=end)

            # stop if data has stopped comming in
            if len(new) == 1:
                flag = False

            # add new candles
            self.logger.debug(
                'Updating %s database with %s entrys...', pair, str(len(new))
                )

            updateChartData(db, new)

            # make new end the old start
            end = start

        # make dataframe
        self.logger.debug('Getting %s chart data from db', pair)
        df = getChartDataFrame(db, time() - frame)

        # adjust candle period 'zoom'
        if zoom:
            df = zoomOHLC(df, zoom)

        # add TA indicators
        if indica:
            df = addIndicators(df, **indica)

        return df


    def myTradeHistory(self, query=None):
        """
        Retrives and saves trade history in "poloniex.'self.pair'-tradeHistory"
        """
        dbcolName = self.pair + '-tradeHistory'
        db = getMongoColl('poloniex', dbcolName)
        # get last trade
        old = {'date': time() - self.api.YEAR * 10}
        try:
            old = list(db.find().sort('date', pymongo.ASCENDING))[-1]
        except:
            logger.warning('No %s trades found in database', self.pair)
        # get new data from poloniex
        hist = self.api.returnTradeHistory(self.pair, start=old['date'] - 1)

        if len(hist) > 0:
            logger.info('%d new %s trade database entries',
                        len(hist), self.pair)

            for trade in hist:
                _id = trade['globalTradeID']
                del trade['globalTradeID']
                trade['date'] = UTCstr2epoch(trade['date'])
                trade['amount'] = float(trade['amount'])
                trade['total'] = float(trade['total'])
                trade['tradeID'] = int(trade['tradeID'])
                trade['orderNumber'] = int(trade['orderNumber'])
                trade['rate'] = float(trade['rate'])
                trade['fee'] = float(trade['fee'])
                db.update_one({"_id": _id}, {"$set": trade}, upsert=True)

        df = pd.DataFrame(list(db.find(query).sort('date',
                                                   pymongo.ASCENDING)))
        if 'date' in df:
            df['date'] = pd.to_datetime(df["date"], unit='s')
            df.set_index('date', inplace=True)
        return df

    def myLendingHistory(self, coin=False, query=False):
        """
        Retrives and saves lendingHistory in 'poloniex.lendingHistory' database
        coin = coin to get history for (defaults to self.child)
        query = pymongo query for .find() (defaults to last 24 hours)
        """
        if not query:
            query = {'currency': coin, '_id': {'$gt': time() - self.api.DAY}}
        if not coin:
            coin = self.child
        db = getMongoColl('poloniex', 'lendingHistory')
        # get last entry timestamp
        old = {'open': time() - self.api.YEAR * 10}
        try:
            old = list(db.find({"currency": coin}).sort('open',
                                                        pymongo.ASCENDING))[-1]
        except:
            logger.warning(RD('No %s loan history found in database!'), coin)
        # get new entries
        new = self.api.returnLendingHistory(start=old['open'] - 1)
        nLoans = [loan for loan in new if loan['currency'] == coin]
        if len(nLoans) > 0:
            logger.info(GR('%d new lending database entries'), len(new))
            for loan in nLoans:
                _id = loan['id']
                del loan['id']
                loan['close'] = UTCstr2epoch(loan['close'])
                loan['open'] = UTCstr2epoch(loan['open'])
                loan['rate'] = float(loan['rate'])
                loan['duration'] = float(loan['duration'])
                loan['interest'] = float(loan['interest'])
                loan['fee'] = float(loan['fee'])
                loan['earned'] = float(loan['earned'])
                db.update_one({'_id': _id}, {'$set': loan}, upsert=True)
        return pd.DataFrame(list(db.find(query).sort('open',
                                                     pymongo.ASCENDING)))
