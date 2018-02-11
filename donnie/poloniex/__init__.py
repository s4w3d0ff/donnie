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
#
# python 2
try:
    from urllib import urlencode as _urlencode
    str = unicode
# python 3
except:
    from urllib.parse import urlencode as _urlencode
# core
from json import loads as _loads
from json import dumps as _dumps
from hmac import new as _new
from hashlib import sha512 as _sha512
from itertools import chain as _chain
from functools import wraps as _wraps
from threading import Semaphore, Timer

# 3rd party
from requests.exceptions import RequestException
from requests import Session
from websocket import WebSocketApp

# local
from ..tools import (pd, pymongo, getLogger, time, sleep, UTCstr2epoch,
                     MINUTE, HOUR, DAY, WEEK, MONTH, YEAR, SATOSHI,
                     getDatabase, roundDown, geoProgress, Thread)

# logger
logger = getLogger(__name__)

retryDelays = (0, 2, 5, 30)

# Possible Commands
PUBLIC_COMMANDS = [
    'returnTicker',
    'return24hVolume',
    'returnOrderBook',
    'marketTradeHist',
    'returnChartData',
    'returnCurrencies',
    'returnLoanOrders']

PRIVATE_COMMANDS = [
    'returnBalances',
    'returnCompleteBalances',
    'returnDepositAddresses',
    'generateNewAddress',
    'returnDepositsWithdrawals',
    'returnOpenOrders',
    'returnTradeHistory',
    'returnAvailableAccountBalances',
    'returnTradableBalances',
    'returnOpenLoanOffers',
    'returnOrderTrades',
    'returnActiveLoans',
    'returnLendingHistory',
    'createLoanOffer',
    'cancelLoanOffer',
    'toggleAutoRenew',
    'buy',
    'sell',
    'cancelOrder',
    'moveOrder',
    'withdraw',
    'returnFeeInfo',
    'transferBalance',
    'returnMarginAccountSummary',
    'marginBuy',
    'marginSell',
    'getMarginPosition',
    'closeMarginPosition']

# parent trade minimums
TRADE_MINS = {
    "BTC": 0.0001,
    "USDT": 0.0001,
    "ETH": 0.0001,
    "XMR": 0.0001
}

# smallest loan fraction
LOANTOSHI = 0.000001


class PoloniexError(Exception):
    """ Exception for handling poloniex api errors """
    pass


class RetryException(PoloniexError):
    """ Exception for retry decorator """
    pass


class PoloniexBase(object):
    """The Poloniex Object!"""

    def __init__(
            self, key=None, secret=None, timeout=None,
            rateLimit=(1.0, 6), jsonNums=None, proxies=None):
        """
        key = str api key supplied by Poloniex
        secret = str secret hash supplied by Poloniex
        timeout = int time in sec to wait for an api response
            (otherwise 'requests.exceptions.Timeout' is raised)
        rateLimit = tuple or None, first value is timeframe, second value is
            call limit per timeframe (default is 1.0 sec, 6 calls)
        jsonNums = datatype to use when parsing json ints and floats

        # Time Placeholders: (MONTH == 30*DAYS)
        self.MINUTE, self.HOUR, self.DAY, self.WEEK, self.MONTH, self.YEAR
        """
        # create requests session
        self.session = Session()
        # set rateLimit
        self.rateLimit = rateLimit
        # create rate limiter
        if self.rateLimit:
            self.limiter = Semaphore(rateLimit[1])
        else:
            self.limiter = None
        # set proxies and json number datatypes
        self.proxies, self.jsonNums = proxies, jsonNums
        # grab keys, set timeout
        self.key, self.secret, self.timeout = key, secret, timeout
        # create nonce
        self._nonce = int("{:.6f}".format(time()).replace('.', ''))
        # set time labels
        self.MINUTE, self.HOUR, self.DAY = MINUTE, HOUR, DAY
        self.WEEK, self.MONTH = WEEK, MONTH
        self.YEAR = YEAR

    # -----------------Meat and Potatos---------------------------------------
    def _retry(func):
        """ retry decorator """
        @_wraps(func)
        def retrying(*args, **kwargs):
            problems = []
            for delay in _chain(retryDelays, [None]):
                try:
                    # attempt call
                    return func(*args, **kwargs)

                # we need to try again
                except RequestException as problem:
                    problems.append(problem)
                    if delay is None:
                        logger.debug(problems)
                        raise RetryException(
                            'retryDelays exhausted ' + str(problem))
                    else:
                        # log exception and wait
                        logger.debug(problem)
                        logger.info("-- delaying for %ds", delay)
                        sleep(delay)
        return retrying

    @property
    def nonce(self):
        """ Increments the nonce """
        self._nonce += 42
        return self._nonce

    def _wait(self):
        """ Makes sure our api calls don't go past the api call limit """
        self.limiter.acquire()  # blocking call
        # delayed release
        timer = Timer(self.rateLimit[0], self.limiter.release)
        # allows the timer to be canceled on exit
        timer.setDaemon(True)
        timer.start()

    def _checkCmd(self, command):
        """ Returns if the command is private of public, raises PoloniexError
        if command is not found """
        global PUBLIC_COMMANDS, PRIVATE_COMMANDS
        if command in PRIVATE_COMMANDS:
            # check for keys
            if not self.key or not self.secret:
                raise PoloniexError("An Api Key and Secret needed!")
            return 'Private'
        if command in PUBLIC_COMMANDS:
            return 'Public'

        raise PoloniexError("Invalid Command!: %s" % command)

    def _handleReturned(self, data):
        """ Handles returned data from poloniex"""
        try:
            if not self.jsonNums:
                out = _loads(data, parse_float=str)
            else:
                out = _loads(data,
                             parse_float=self.jsonNums,
                             parse_int=self.jsonNums)
        except:
            logger.error(data)
            raise PoloniexError('Invalid json response returned')

        # check if poloniex returned an error
        if 'error' in out:

            # update nonce if we fell behind
            if "Nonce must be greater" in out['error']:
                self._nonce = int(
                    out['error'].split('.')[0].split()[-1])
                # raise RequestException so we try again
                raise RequestException('PoloniexError: ' + out['error'])

            # conncetion timeout from poloniex
            if "please try again" in out['error'].lower():
                # raise RequestException so we try again
                raise RequestException('PoloniexError: ' + out['error'])

            # raise other poloniex errors, ending retry loop
            else:
                raise PoloniexError(out['error'])
        return out

    @_retry
    def __call__(self, command, args={}):
        """ Main Api Function
        - encodes and sends <command> with optional [args] to Poloniex api
        - raises 'poloniex.PoloniexError' if an api key or secret is missing
            (and the command is 'private'), if the <command> is not valid, or
            if an error is returned from poloniex.com
        - returns decoded json api message """
        # get command type
        cmdType = self._checkCmd(command)

        # pass the command
        args['command'] = command
        payload = {}
        # add timeout
        payload['timeout'] = self.timeout

        # private?
        if cmdType == 'Private':
            payload['url'] = 'https://poloniex.com/tradingApi'

            # wait if needed
            if self.limiter:
                self._wait()

            # set nonce
            args['nonce'] = self.nonce

            # add args to payload
            payload['data'] = args

            # sign data with our Secret
            sign = _new(
                self.secret.encode('utf-8'),
                _urlencode(args).encode('utf-8'),
                _sha512)

            # add headers to payload
            payload['headers'] = {'Sign': sign.hexdigest(),
                                  'Key': self.key}
            # add proxies if needed
            if self.proxies:
                payload['proxies'] = self.proxies

            # send the call
            ret = self.session.post(**payload)

            # return data
            return self._handleReturned(ret.text)

        # public?
        if cmdType == 'Public':
            # encode url
            payload['url'] = 'https://poloniex.com/public?' + _urlencode(args)

            # wait if needed
            if self.limiter:
                self._wait()

            # add proxies if needed
            if self.proxies:
                payload['proxies'] = self.proxies
            # send the call
            ret = self.session.get(**payload)

            # return data
            return self._handleReturned(ret.text)

    # --PUBLIC COMMANDS-------------------------------------------------------
    def returnTicker(self):
        """ Returns the ticker for all markets. """
        return self.__call__('returnTicker')

    def return24hVolume(self):
        """ Returns the 24-hour volume for all markets,
        plus totals for primary currencies. """
        return self.__call__('return24hVolume')

    def returnOrderBook(self, currencyPair='all', depth=20):
        """ Returns the order book for a given market as well as a sequence
        number for use with the Push API and an indicator specifying whether the
        market is frozen. (defaults to 'all' markets, at a 'depth' of 20 orders)
        """
        return self.__call__('returnOrderBook', {
            'currencyPair': str(currencyPair).upper(),
            'depth': str(depth)
        })

    @_retry
    def marketTradeHist(self, currencyPair, start=False, end=False):
        """ Returns the past 200 trades for a given market, or up to 50,000
        trades between a range specified in UNIX timestamps by the "start" and
        "end" parameters. """
        # wait if needed
        if self.limiter:
            self._wait()
        args = {'command': 'returnTradeHistory',
                'currencyPair': str(currencyPair).upper()}
        if start:
            args['start'] = start
        if end:
            args['end'] = end
        ret = self.session.get(
            'https://poloniex.com/public?' + _urlencode(args),
            proxies=self.proxies,
            timeout=self.timeout)
        # decode json
        return self._handleReturned(ret.text)

    def returnChartData(self, currencyPair, period=False,
                        start=False, end=False):
        """ Returns candlestick chart data. Parameters are "currencyPair",
        "period" (candlestick period in seconds; valid values are 300, 900,
        1800, 7200, 14400, and 86400), "start", and "end". "Start" and "end"
        are given in UNIX timestamp format and used to specify the date range
        for the data returned (default date range is start='1 day ago' to
        end='now') """
        if period not in [300, 900, 1800, 7200, 14400, 86400]:
            raise PoloniexError("%s invalid candle period" % str(period))
        if not start:
            start = time() - self.DAY
        if not end:
            end = time()
        return self.__call__('returnChartData', {
            'currencyPair': str(currencyPair).upper(),
            'period': str(period),
            'start': str(start),
            'end': str(end)
        })

    def returnCurrencies(self):
        """ Returns information about all currencies. """
        return self.__call__('returnCurrencies')

    def returnLoanOrders(self, currency):
        """ Returns the list of loan offers and demands for a given currency,
        specified by the "currency" parameter """
        return self.__call__('returnLoanOrders', {
                             'currency': str(currency).upper()})

    # --PRIVATE COMMANDS------------------------------------------------------
    def returnBalances(self):
        """ Returns all of your available balances."""
        return self.__call__('returnBalances')

    def returnCompleteBalances(self, account='all'):
        """ Returns all of your balances, including available balance, balance
        on orders, and the estimated BTC value of your balance. By default,
        this call is limited to your exchange account; set the "account"
        parameter to "all" to include your margin and lending accounts. """
        return self.__call__('returnCompleteBalances',
                             {'account': str(account)})

    def returnDepositAddresses(self):
        """ Returns all of your deposit addresses. """
        return self.__call__('returnDepositAddresses')

    def generateNewAddress(self, currency):
        """ Generates a new deposit address for the currency specified by the
        "currency" parameter. """
        return self.__call__('generateNewAddress', {
                             'currency': currency})

    def returnDepositsWithdrawals(self, start=False, end=False):
        """ Returns your deposit and withdrawal history within a range,
        specified by the "start" and "end" parameters, both of which should be
        given as UNIX timestamps. (defaults to 1 month)"""
        if not start:
            start = time() - self.MONTH
        if not end:
            end = time()
        args = {'start': str(start), 'end': str(end)}
        return self.__call__('returnDepositsWithdrawals', args)

    def returnOpenOrders(self, currencyPair='all'):
        """ Returns your open orders for a given market, specified by the
        "currencyPair" parameter, e.g. "BTC_XCP". Set "currencyPair" to
        "all" to return open orders for all markets. """
        return self.__call__('returnOpenOrders', {
                             'currencyPair': str(currencyPair).upper()})

    def returnTradeHistory(
        self, currencyPair='all', start=False, end=False, limit=None
    ):
        """ Returns your trade history for a given market, specified by the
        "currencyPair" POST parameter. You may specify "all" as the
        currencyPair to receive your trade history for all markets. You may
        optionally specify a range via "start" and/or "end" POST parameters,
        given in UNIX timestamp format; if you do not specify a range, it will
        be limited to one day. You may optionally limit the number of entries
        returned using the "limit" parameter, up to a maximum of 10,000. If the
        "limit" parameter is not specified, no more than 500 entries will be
        returned.  """
        args = {'currencyPair': str(currencyPair).upper()}
        if start:
            args['start'] = start
        if end:
            args['end'] = end
        if limit:
            args['limit'] = limit
        return self.__call__('returnTradeHistory', args)

    def returnOrderTrades(self, orderNumber):
        """ Returns all trades involving a given order, specified by the
        "orderNumber" parameter. If no trades for the order have occurred
        or you specify an order that does not belong to you, you will receive
        an error. """
        return self.__call__('returnOrderTrades', {
                             'orderNumber': str(orderNumber)})

    def buy(self, currencyPair, rate, amount, orderType=False):
        """ Places a limit buy order in a given market. Required parameters are
        "currencyPair", "rate", and "amount". You may optionally set "orderType"
        to "fillOrKill", "immediateOrCancel" or "postOnly". A fill-or-kill order
        will either fill in its entirety or be completely aborted. An
        immediate-or-cancel order can be partially or completely filled, but
        any portion of the order that cannot be filled immediately will be
        canceled rather than left on the order book. A post-only order will
        only be placed if no portion of it fills immediately; this guarantees
        you will never pay the taker fee on any part of the order that fills.
        If successful, the method will return the order number. """
        args = {
            'currencyPair': str(currencyPair).upper(),
            'rate': str(rate),
            'amount': str(amount),
        }
        # order type specified?
        if orderType:
            possTypes = ['fillOrKill', 'immediateOrCancel', 'postOnly']
            # check type
            if not orderType in possTypes:
                raise PoloniexError('Invalid orderType')
            args[orderType] = 1

        return self.__call__('buy', args)

    def sell(self, currencyPair, rate, amount, orderType=False):
        """ Places a sell order in a given market. Parameters and output are
        the same as for the buy method. """
        args = {
            'currencyPair': str(currencyPair).upper(),
            'rate': str(rate),
            'amount': str(amount),
        }
        # order type specified?
        if orderType:
            possTypes = ['fillOrKill', 'immediateOrCancel', 'postOnly']
            # check type
            if not orderType in possTypes:
                raise PoloniexError('Invalid orderType')
            args[orderType] = 1

        return self.__call__('sell', args)

    def cancelOrder(self, orderNumber):
        """ Cancels an order you have placed in a given market. Required
        parameter is "orderNumber". """
        return self.__call__('cancelOrder', {'orderNumber': str(orderNumber)})

    def moveOrder(self, orderNumber, rate, amount=False, orderType=False):
        """ Cancels an order and places a new one of the same type in a single
        atomic transaction, meaning either both operations will succeed or both
        will fail. Required parameters are "orderNumber" and "rate"; you may
        optionally specify "amount" if you wish to change the amount of the new
        order. "postOnly" or "immediateOrCancel" may be specified as the
        "orderType" param for exchange orders, but will have no effect on
        margin orders. """

        args = {
            'orderNumber': str(orderNumber),
            'rate': str(rate)
        }
        if amount:
            args['amount'] = str(amount)
        # order type specified?
        if orderType:
            possTypes = ['immediateOrCancel', 'postOnly']
            # check type
            if not orderType in possTypes:
                raise PoloniexError('Invalid orderType: %s' % str(orderType))
            args[orderType] = 1

        return self.__call__('moveOrder', args)

    def withdraw(self, currency, amount, address, paymentId=False):
        """ Immediately places a withdrawal for a given currency, with no email
        confirmation. In order to use this method, the withdrawal privilege
        must be enabled for your API key. Required parameters are
        "currency", "amount", and "address". For XMR withdrawals, you may
        optionally specify "paymentId". """
        args = {
            'currency': str(currency).upper(),
            'amount': str(amount),
            'address': str(address)
        }
        if paymentId:
            args['paymentId'] = str(paymentId)
        return self.__call__('withdraw', args)

    def returnFeeInfo(self):
        """ If you are enrolled in the maker-taker fee schedule, returns your
        current trading fees and trailing 30-day volume in BTC. This
        information is updated once every 24 hours. """
        return self.__call__('returnFeeInfo')

    def returnAvailableAccountBalances(self, account=False):
        """ Returns your balances sorted by account. You may optionally specify
        the "account" parameter if you wish to fetch only the balances of
        one account. Please note that balances in your margin account may not
        be accessible if you have any open margin positions or orders. """
        if account:
            return self.__call__('returnAvailableAccountBalances',
                                 {'account': account})
        return self.__call__('returnAvailableAccountBalances')

    def returnTradableBalances(self):
        """ Returns your current tradable balances for each currency in each
        market for which margin trading is enabled. Please note that these
        balances may vary continually with market conditions. """
        return self.__call__('returnTradableBalances')

    def transferBalance(self, currency, amount,
                        fromAccount, toAccount, confirmed=False):
        """ Transfers funds from one account to another (e.g. from your
        exchange account to your margin account). Required parameters are
        "currency", "amount", "fromAccount", and "toAccount" """
        args = {
            'currency': str(currency).upper(),
            'amount': str(amount),
            'fromAccount': str(fromAccount),
            'toAccount': str(toAccount)
        }
        if confirmed:
            args['confirmed'] = 1
        return self.__call__('transferBalance', args)

    def returnMarginAccountSummary(self):
        """ Returns a summary of your entire margin account. This is the same
        information you will find in the Margin Account section of the Margin
        Trading page, under the Markets list """
        return self.__call__('returnMarginAccountSummary')

    def marginBuy(self, currencyPair, rate, amount, lendingRate=2):
        """ Places a margin buy order in a given market. Required parameters are
        "currencyPair", "rate", and "amount". You may optionally specify a
        maximum lending rate using the "lendingRate" parameter (defaults to 2).
        If successful, the method will return the order number and any trades
        immediately resulting from your order. """
        return self.__call__('marginBuy', {
            'currencyPair': str(currencyPair).upper(),
            'rate': str(rate),
            'amount': str(amount),
            'lendingRate': str(lendingRate)
        })

    def marginSell(self, currencyPair, rate, amount, lendingRate=2):
        """ Places a margin sell order in a given market. Parameters and output
        are the same as for the marginBuy method. """
        return self.__call__('marginSell', {
            'currencyPair': str(currencyPair).upper(),
            'rate': str(rate),
            'amount': str(amount),
            'lendingRate': str(lendingRate)
        })

    def getMarginPosition(self, currencyPair='all'):
        """ Returns information about your margin position in a given market,
        specified by the "currencyPair" parameter. You may set
        "currencyPair" to "all" if you wish to fetch all of your margin
        positions at once. If you have no margin position in the specified
        market, "type" will be set to "none". "liquidationPrice" is an
        estimate, and does not necessarily represent the price at which an
        actual forced liquidation will occur. If you have no liquidation price,
        the value will be -1. (defaults to 'all')"""
        return self.__call__('getMarginPosition', {
                             'currencyPair': str(currencyPair).upper()})

    def closeMarginPosition(self, currencyPair):
        """ Closes your margin position in a given market (specified by the
        "currencyPair" parameter) using a market order. This call will also
        return success if you do not have an open position in the specified
        market. """
        return self.__call__(
            'closeMarginPosition', {'currencyPair': str(currencyPair).upper()})

    def createLoanOffer(self, currency, amount,
                        lendingRate, autoRenew=0, duration=2):
        """ Creates a loan offer for a given currency. Required parameters are
        "currency", "amount", "lendingRate", "duration" (num of days, defaults
        to 2), "autoRenew" (0 or 1, defaults to 0 'off'). """
        return self.__call__('createLoanOffer', {
            'currency': str(currency).upper(),
            'amount': str(amount),
            'duration': str(duration),
            'autoRenew': str(autoRenew),
            'lendingRate': str(lendingRate)
        })

    def cancelLoanOffer(self, orderNumber):
        """ Cancels a loan offer specified by the "orderNumber" parameter. """
        return self.__call__(
            'cancelLoanOffer', {'orderNumber': str(orderNumber)})

    def returnOpenLoanOffers(self):
        """ Returns your open loan offers for each currency. """
        return self.__call__('returnOpenLoanOffers')

    def returnActiveLoans(self):
        """ Returns your active loans for each currency."""
        return self.__call__('returnActiveLoans')

    def returnLendingHistory(self, start=False, end=False, limit=False):
        """ Returns your lending history within a time range specified by the
        "start" and "end" parameters as UNIX timestamps. "limit" may also
        be specified to limit the number of rows returned. (defaults to the last
        months history)"""
        if not start:
            start = time() - self.MONTH
        if not end:
            end = time()
        args = {'start': str(start), 'end': str(end)}
        if limit:
            args['limit'] = str(limit)
        return self.__call__('returnLendingHistory', args)

    def toggleAutoRenew(self, orderNumber):
        """ Toggles the autoRenew setting on an active loan, specified by the
        "orderNumber" parameter. If successful, "message" will indicate
        the new autoRenew setting. """
        return self.__call__(
            'toggleAutoRenew', {'orderNumber': str(orderNumber)})


class wsPoloniex(PoloniexBase):
    """
    Poloniex Object with websocket thread
    """

    def _handle_tick(self, message):
        """ Handles ticker messages from the websocket """
        if message[1] == 1:
            return logger.info('Subscribed to ticker')
        if message[1] == 0:
            return logger.info('Unsubscribed to ticker')

        data = message[2]
        data = [float(dat) for dat in data]
        self._tick[data[0]] = {'id': data[0],
                               'last': data[1],
                               'lowestAsk': data[2],
                               'highestBid': data[3],
                               'percentChange': data[4],
                               'baseVolume': data[5],
                               'quoteVolume': data[6],
                               'isFrozen': data[7],
                               'high24hr': data[8],
                               'low24hr': data[9]
                               }
        self.heartbeat = time()

    def _handle_stats(self, message):
        """ Handles the 'stats' messages from the websocket """
        if message[1] == 1:
            return logger.info('Subscribed to stat updates')
        if message[1] == 0:
            return logger.info('Unsubscribed to stat updates')

        self.stats = message[2]
        self.heartbeat = time()

    def _handle_orderbook(self, message):
        """ Handles the orderbook messages from the websocket """
        if message[1] == 1:
            return logger.info('Subscribed to %s orderbook' % message[0])
        if message[1] == 0:
            return logger.info('Unsubscribed to %s orderbook' % message[0])

        self.heartbeat = time()

    def _handle_heartbeat(self, message):
        """ Handles the heartbeat messages from the websocket """
        self.heartbeat = time()

    def _on_message(self, ws, message):
        """ Handles all messages from the websocket """
        message = _loads(message)
        if 'error' in message:
            return logger.error(message['error'])

        elif message[0] == 1002:
            self._handle_tick(message)

        elif message[0] == 1003:
            self._handle_stats(message)

        elif message[0] == 1010:
            self._handle_heartbeat(message)

        else:
            try:
                if '_' in message[0]:
                    self._handle_orderbook(message)
            except:
                logging.debug(message)

    def _on_error(self, ws, error):
        """ Handles error messages from the websocket """
        logger.error(error)

    def _on_close(self, ws):
        """ Fires when the websocket is closed """
        if self._wst._running:
            try:
                self.stopWebsocket()
            except Exception as e:
                logger.exception(e)
        else:
            logger.info("Websocket closed!")

    def _on_open(self, ws):
        """ Fires when the websocket is connected (used for subscribing) """
        for channel in self._wsSubs:
            self._ws.send(_dumps({'command': 'subscribe', 'channel': channel}))

    @property
    def tickerStatus(self):
        """
        Returns True if the websocket thread is running, False if not.
        """
        try:
            return self._wst._running
        except:
            return False

    def startWebsocket(self, subscriptions=[1002]):
        """ Run the websocket in a thread """
        self._tick = {}
        self._wsSubs = subscriptions
        iniTick = self.returnTicker()
        self._ids = {market: iniTick[market]['id'] for market in iniTick}
        for market in iniTick:
            self._tick[self._ids[market]] = iniTick[market]

        self._ws = WebSocketApp("wss://api2.poloniex.com/",
                                on_open=self._on_open,
                                on_message=self._on_message,
                                on_error=self._on_error,
                                on_close=self._on_close)
        self._wst = Thread(target=self._ws.run_forever)
        self._wst.daemon = True
        self._wst._running = True
        self._wst.start()
        logger.info('Websocket thread started')

    def stopWebsocket(self):
        """ Stop/join the websocket thread """
        self._wst._running = False
        self._ws.close()
        self._wst.join()
        logger.info('Websocket thread stopped/joined')

    def tick(self, market=None):
        """ returns ticker from websocket if running/connected, else
        'self.returnTicker is used'"""
        if self.tickerStatus:
            if market:
                return self._tick[self._ids[market]]
            return self._tick
        logger.warning('Push ticker is not running!')
        if market:
            return self.returnTicker()[market]
        return self.returnTicker()


class Poloniex(wsPoloniex):
    """
    Everything that is PoloniexBase and wsPoloniex but with mongodb support for
    chart data, trade history, and lending history. It also has a few other
    helper methods.
    """

    def chartDataframe(self, pair, start=None, zoom=None, indicators=None):
        """ returns chart data in a dataframe from mongodb, updates/fills the
        data, the date column is the '_id' of each candle entry, and
        the date column has been removed. Use 'start' to restrict the amount
        of data returned.
        Example: 'start=time() - YEAR' will return last years data
        """
        if not start:
            start = time() - self.YEAR
        # get db connection
        db = getDatabase('poloniex')[pair.upper() + '-chart']
        # get last candle
        try:
            last = list(db.find({"_id": {
                "$gt": time() - self.WEEK * 2
            }}).sort('timestamp', pymongo.ASCENDING))[-1]
        except:
            last = False
        # no entrys found, get all 5min data from poloniex
        if not last:
            logger.warning('%s collection is empty!', pair + '-chart')
            logger.info('Getting new %s candles from Poloniex...', pair)
            new = self.returnChartData(pair,
                                       period=60 * 5,
                                       start=time() - self.YEAR * 13)
        else:
            logger.info('Getting new %s candles from Poloniex...', pair)
            new = self.returnChartData(pair,
                                       period=60 * 5,
                                       start=int(last['_id']))
        # add new candles
        updateSize = len(new)
        logger.info('Updating %s with %s new entrys!...',
                    pair + '-chart', str(updateSize))
        if updateSize > 10000:
            logger.warning("This can take awhile...")
        for i in range(updateSize):
            db.update_one({'_id': new[i]['date']},
                          {"$set": new[i]},
                          upsert=True)
        logger.info('Getting %s chart data from db', pair)
        # make dataframe
        df = pd.DataFrame(list(db.find({"_id": {"$gt": start}}
                                       ).sort('timestamp', pymongo.ASCENDING)))
        # set date column to datetime
        df['date'] = pd.to_datetime(df["_id"], unit='s')
        # adjust candle period 'zoom'
        if zoom:
            logger.debug('Zooming %s dataframe...', pair)
            df.set_index('date', inplace=True)
            df = df.resample(rule=zoom,
                             closed='left',
                             label='left').apply({'open': 'first',
                                                  'high': 'max',
                                                  'low': 'min',
                                                  'close': 'last',
                                                  'quoteVolume': 'sum',
                                                  'volume': 'sum',
                                                  'weightedAverage': 'mean'})
            df.reset_index(inplace=True)
        return df

    def myTradeHistory(self, pair, query=None):
        """
        Retrives and saves trade history in "poloniex.'pair'-tradeHistory" db
        """
        db = getDatabase('poloniex')[pair.upper() + '-tradeHistory']
        # get last trade
        old = {'date': time() - self.YEAR * 10}
        try:
            old = list(db.find().sort('date', pymongo.ASCENDING))[-1]
        except:
            logger.warning('No %s trades found in database', pair)
        # get new data from poloniex
        hist = self.returnTradeHistory(pair, start=old['date'] - 1)

        if len(hist) > 0:
            logger.info('%d new %s trade database entries',
                        len(hist), pair)

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

    def myLendingHistory(self, coin, query=None):
        """
        Retrives and saves lendingHistory in 'poloniex.lendingHistory' database
        coin = coin to get history for
        query = pymongo query for .find() (defaults to last 24 hours)
        """
        if not query:
            query = {'currency': coin, '_id': {'$gt': time() - self.DAY}}
        db = getDatabase('poloniex')['lendingHistory']
        # get last entry timestamp
        old = {'open': time() - self.YEAR * 10}
        try:
            old = list(db.find({"currency": coin}).sort('open',
                                                        pymongo.ASCENDING))[-1]
        except:
            logger.warning('No %s loan history found in database!', coin)
        # get new entries
        new = self.returnLendingHistory(start=old['open'] - 1)
        nLoans = [loan for loan in new if loan['currency'] == coin]
        if len(nLoans) > 0:
            logger.info('%d new lending database entries', len(new))
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

    def cancelAllOrders(self, market='all', arg=False):
        """ Cancels all orders for a market or all markets. Can be limited to
        just buy or sell orders using the 'arg' param """
        # get open orders for 'market'
        orders = self.returnOpenOrders(market)
        # if market is set to 'all' we will cancel all open orders
        if market == 'all':
            # iterate through each market
            for market in orders:
                # iterate through each market order
                for order in orders[market]:
                    # if arg = 'sell' or 'buy' skip the others
                    if arg in ('sell', 'buy') and order['type'] != arg:
                        continue
                    # show results as we cancel each order
                    logger.debug(self.cancelOrder(order["orderNumber"]))
        else:
            # just an individial market
            for order in orders:
                # if arg = 'sell' or 'buy' skip the others
                if arg in ('sell', 'buy') and order['type'] != arg:
                    continue
                # show output
                logger.debug(self.cancelOrder(order["orderNumber"]))

    def getOrder(self, orderNum):
        """ Helper method for getting an order by 'orderNumber' that reduces
        api errors """
        orders = self.returnOpenOrders("all")
        for market in orders:
            for order in market:
                if int(order['orderNumber']) == int(orderNum):
                    return order
        # else see if it made trades
        return self.myTradeHistory(query={'orderNumber': int(orderNum)})

    def cancelAllLoanOffers(self, coin=False):
        """ Cancels all open loan offers, for all coins or a single <coin> """
        loanOrders = self.returnOpenLoanOffers()
        if not coin:
            for c in loanOrders:
                for order in loanOrders[c]:
                    logger.info(self.cancelLoanOffer(order['id']))
        else:
            for order in loanOrders[coin]:
                logger.info(self.cancelLoanOffer(order['id']))

    def closeAllMargins(self):
        """ Closes all margin positions """
        for m in self.returnTradableBalances():
            logger.info(self.closeMarginPosition(m))

    def autoRenewAll(self, toggle=True):
        """ Turns auto-renew on or off for all active loans """
        for loan in self.returnActiveLoans()['provided']:
            if int(loan['autoRenew']) != int(toggle):
                logger.info('Toggling autorenew for offer %s', loan['id'])
                self.toggleAutoRenew(loan['id'])


class PoloniexAdv(Poloniex):
    """
    Everything that is 'Poloniex' but with threaded stop limit feature
    """

    def __init__(self, *args, **kwargs):
        super(Poloniex, self).__init__(*args, **kwargs)
        self.stops = {}

    def addStop(self, pair, amount, stop, limit, interval=2):
        """
        Adds a new stop limit to 'self.stops[<pair>][<stop>]' and starts
        the thread
        """
        if not pair in self.stops:
            self.stops[pair] = {}

        self.stops[pair][str(stop)] = self.StopLimit(self, pair, amount,
                                                     stop, limit, interval)
        self.stops[pair][str(stop)].start()

    def cancelStops(self, market='all'):
        """ Cancels all stops for a market or all markets """
        if market == 'all':
            for pair in self.stops:
                for stop in self.stops[pair]:
                    self.stops[pair][stop]._running = False
                    self.stops[pair][stop].join()
                logger.info('%s stops canceled', pair)
        else:
            for stop in self.stops[pair]:
                self.stops[pair][stop]._running = False
                self.stops[pair][stop].join()
            logger.info('%s stops canceled', pair)

    class StopLimit(Thread):
        """ Stop limit thread """

        def __init__(self, api, pair, amount, stop, limit,
                     interval=2, *args, **kwargs):
            super(PoloniexAdv.StopLimit, self).__init__(*args, **kwargs)
            self.api = api
            self.pair = pair
            self.amount = amount
            self.stop = stop
            self.limit = limit
            self.interval = interval
            self._running = False
            self.daemon = True
            self.order = None

        def run(self):
            self._running = True
            logger.debug('%s stop limit set: [Amount]%.8f [Stop]%.8f [Limit]%.8f',
                         self.pair, self.amount, self.stop, self.limit)
            while self._running:
                try:
                    tick = self.api.tick(self.pair)

                    if self.amount < 0 and self.stop <= tick['highestbid']:
                        logger.debug('%s stop limit triggered!', self.pair)
                        # sell amount at limit
                        self.order = self.api.sell(self.pair,
                                                   self.limit,
                                                   abs(self.amount))
                        self._running = False
                        continue

                    elif self.amount > 0 and self.stop >= tick['lowestAsk']:
                        # buy amount at limit
                        logger.debug('%s stop limit triggered!', self.pair)
                        self.order = self.api.buy(self.pair,
                                                  self.limit,
                                                  self.amount)
                        self._running = False
                        continue

                except Exception as e:
                    self.order = str(e)
                    self._running = False
                    continue

                sleep(self.interval)


class GeoOrder(object):
    def __init__(self, api, pair, amount, size=10, offset=2):
        self.api, self.pair, self.amount = api, pair, amount
        self.size, self.offset = size, offset
        self.orders = []
        self.__call__()

    def __call__(self):
        if len(self.orders) > 0:
            return self.orders

        # get amounts for orders
        amounts = [roundDown(i)
                   for i in geoProgress(self.amount, size=self.size)]

        tick = self.api.tick(self.pair)

        parentMin = TRADE_MINS[self.pair.split('_')[0]]

        # sell orders
        if self.amount < 0:
            amounts.sort(reverse=True)
            # make all amounts above the trade minimum
            for i in range(len(amounts)):
                if abs(amounts[i]) < parentMin:
                    need = parentMin - abs(amounts[i])
                    amounts[i] = float(-parentMin)
                    # take the amount needed from the largest amount
                    amounts[-1] = roundDown(-(abs(amounts[-1]) - need))

            prices = [roundDown(
                float(tick['lowestAsk']) +
                (float(i * self.offset) / 100000000)
            ) for i in range(len(amounts))]

        # buy orders
        elif self.amount > 0:
            amounts.sort(reverse=False)
            # make all amounts above the trade minimum
            for i in range(len(amounts)):
                if amounts[i] < parentMin:
                    need = parentMin - amounts[i]
                    amounts[i] = float(parentMin)
                    # take the amount needed from the largest amount
                    amounts[-1] = roundDown(amounts[-1] - need)

            prices = [roundDown(
                float(tick['highestBid']) -
                (float(i * self.offset) / 100000000)
            ) for i in range(len(amounts))]

        # somehow our total amount is larger than what we wanted
        if abs(sum(amounts)) > abs(self.amount):
            # remove the extra from the largest amount
            amounts[-1] = roundDown(
                amounts[-1] - (sum(amounts) - self.amount)
            )

        print(sum(amounts))

        for amt, price in zip(amounts, prices):
            if amt > 0:
                # positive amounts are buys
                self.orders.append(self.api.buy(self.pair, price, amt))
            else:
                # negative amounts are sells
                self.orders.append(self.api.sell(self.pair, price, abs(amt)))

    def cancel(self):
        if len(self.orders) < 1:
            return logger.info("No orders found in this GeoOrder!")
        for i in range(len(self.orders)):
            try:
                self.orders[i] = self.api.cancelOrder(
                    self.orders[i]['orderNumber'])
            except PoloniexError:
                self.orders[i] = self.api.returnOrderTrades(
                    self.orders[i]['orderNumber'])
