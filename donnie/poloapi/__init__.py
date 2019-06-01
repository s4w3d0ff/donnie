import poloniex

class StopLimit(object):
    def __init__(self, market, amount, stop, limit, test=False):
        self.market = str(market)
        self.amount = float(amount)
        self.stop = float(stop)
        self.limit = float(limit)
        self.order = False
        self.logger = poloniex.logging.getLogger('StopLimit')
        self.logger.setLevel(poloniex.logging.DEBUG)
        self.test = test

    def check(self, lowAsk, highBid):
        # sell
        if self.amount < 0 and self.stop >= float(highBid):
            # dont place order if we are testing
            if self.test:
                self.order = True
            else:
                # sell amount at limit
                self.order = self.sell(self.market,
                                       self.limit,
                                       abs(self.amount))

            self.logger.info('%s sell stop order triggered! (%s)',
                             self.market, str(self.stop))
        # buy
        if self.amount > 0 and self.stop <= float(lowAsk):
            # dont place order if we are testing
            if self.test:
                self.order = True
            else:
                # buy amount at limit
                self.order = self.buy(self.market, self.limit, self.amount)

            self.logger.info('%s buy stop order triggered! (%s)',
                             self.market, str(self.stop))

    def __call__(self):
        return self.order


class Poloniex(poloniex.Poloniex):
    def __init__(self, *args, **kwargs):
        super(Poloniex, self).__init__(*args, **kwargs)
        self.stopOrders = {}
        # tick holds ticker data
        self.tick = {}
        # get inital ticker data
        iniTick = self.returnTicker()
        # save a dict of the market ids to referace
        self._ids = {market: int(iniTick[market]['id']) for market in iniTick}
        # save ticker data as float instead of str
        for market in iniTick:
            self.tick[self._ids[market]] = {
                item: float(iniTick[market][item]) for item in iniTick[market]
                }

    def ticker(self, market=None):
        '''returns ticker data saved from websocket '''
        if not self._t or not self._running or self.channels['1002']['sub']:
            self.logger.error("Websocket isn't running or not subscribed to ticker!")
            return self.returnTicker()
        if market:
            return self.tick[self._ids[market]]
        return self.tick

    def _checkStops(self, msg):
        mktid = str(msg[0])
        mkt = self.channels[mktid]['name']
        la = msg[2]
        hb = msg[3]
        for order in self.stopOrders:
            if str(self.stopOrders[order].market) == str(mkt) and not self.stopOrders[order]():
                self.logger.debug('%s lowAsk=%s highBid=%s',
                                  mkt, str(la), str(hb))
                self.stopOrders[order].check(la, hb)

    def addStopLimit(self, market, amount, stop, limit, test=False):
        self.logger.debug('%s stop limit set: [Amount]%.8f [Stop]%.8f [Limit]%.8f',
                          market, amount, stop, limit)
        self.stopOrders[market+str(stop)] = StopLimit(market, amount, stop, limit, test)

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
        self._checkStops(msg)
