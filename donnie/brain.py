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
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
from sklearn import preprocessing
from sklearn.metrics import accuracy_score
import joblib

from .tools import (getLogger, pd, np, time, shuffleDataFrame,
                     json, isString, prepDataframe, splitTrainTestData)

logger = getLogger(__name__)


class Brain(object):
    """
    The Brain object
    Holds sklrean classifiers and makes it simpler to train using a dataframe
    """

    def __init__(self, lobes=False):
        """
        lobes = a dict of classifiers to use in the VotingClassifier
            defaults to RandomForestClassifier and DecisionTreeClassifier
        """
        if isString(lobes):
            try:
                self.load(lobes.split('.pickle')[0])
            except Exception as e:
                logger.exception(e)
                lobes = False
        if not lobes:
            lobes = {'rf': RandomForestClassifier(n_estimators=7,
                                                  random_state=666),
                     'dt': DecisionTreeClassifier()
                     }
        self.lobe = VotingClassifier(
            estimators=[(lobe, lobes[lobe]) for lobe in lobes],
            voting='hard',
            n_jobs=-1)
        self._trained = False

    def train(self, df, shuffle=True, preprocess=False, *args, **kwargs):
        """
        Takes a dataframe of features + a 'label' column and trains the lobe
        """
        if self._trained:
            logger.warning('Overwriting an already trained brain!')
            self._trained = False

        # shuffle data for good luck
        if shuffle:
            df = shuffleDataFrame(df)
        # scale train data and fit lobe
        x = df.drop('label', axis=1).values
        y = df['label'].values
        del df
        if preprocess:
            x = preprocessing.scale(x)
        logger.info('Training with %d samples', len(x))
        self.lobe.fit(x, y)
        self._trained = True

    def predict(self, df):
        """ Get a prediction from the votingLobe """
        return self.lobe.predict(prepDataframe(df).values)

    def score(self, df, test='predict'):
        """ Get a prediction score from the votingLobe """
        df = prepDataframe(df)
        return accuracy_score(df[test].values, df['label'].values)

    def save(self, location="brain"):
        """ Pickle the brain """
        if self._trained:
            joblib.dump(self.lobe, location + ".pickle")
            logger.info('Brain %s saved', location + '.pickle')
        else:
            return logger.error('Brain is not trained yet! Nothing to save...')

    def load(self, location="brain"):
        """ Loads a brain pickle """
        logger.info('Loading saved brain %s', location + '.pickle')
        self.lobe = joblib.load(location + ".pickle")
        self._trained = True
