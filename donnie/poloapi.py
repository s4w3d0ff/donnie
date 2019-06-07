import poloniex
from .tools import getDatabase, getLogger, TA

logger = getLogger(__name__)


class Poloniex(poloniex.PoloniexSocketed):
    def __init__(self, *args, **kwargs):
        super(Poloniex, self).__init__(*args, **kwargs)
        self.db = getDatabase('poloniex')
        # holds stop orders
        self.stopOrders = {}
        # holds ticker data
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
        mkt = self.channels[str(int(data[0]))]['name']
        la = data[2]
        hb = data[3]
        for id in self.stopOrders:
            # market matches and the order hasnt triggered yet
            if str(self.stopOrders[id]['market']) == str(mkt) and not self.stopOrders[id]['order']:
                self.logger.info('%s lowAsk=%s highBid=%s', mkt, str(la), str(hb))
                self._check_stop(id, la, hb)


    def _check_stop(self, id, lowAsk, highBid):
        amount = self.stopOrders[id]['amount']
        stop = self.stopOrders[id]['stop']
        test = self.stopOrders[id]['test']
        # sell
        if amount < 0 and stop >= float(highBid):
            # dont place order if we are testing
            if test:
                self.stopOrders[id]['order'] = True
            else:
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
            if test:
                self.stopOrders[id]['order'] = True
            else:
                # buy amount at limit
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
        if not self.channels['1002']['sub']:
            if not self._t or not self._running:
                self.logger.error("Websocket isn't running!")
                return self.returnTicker()
            else:
                self.logger.error("Not subscribed to ticker! Subscribing...")
                self.subscribe('1002')
                return self.returnTicker()
        if market:
            return self.tick[self._ids[market]]
        return self.tick


    def cbck(self, id):
        """
        Example callback for stop orders
        """
        print(self.stopOrders[id])
