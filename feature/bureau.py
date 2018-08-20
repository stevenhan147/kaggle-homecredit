import pandas as pd
import numpy as np
import features_common


class Bureau(object):
    def __init__(self, bureau=None, bb=None, prep_mode = 0):
        if bureau is None:
            assert bb is None
            self.df = features_common.read_csv('../input/bureau.csv')
            self.balance = features_common.read_csv('../input/bureau_balance.csv')
            self.transformed = False
        else:
            self.df = pd.read_feather(bureau)
            self.balance = pd.read_feather(bb)
            self.transformed = True

        self.prep_mode = prep_mode

    @classmethod
    def from_cache(cls):
        print('bureau loading from cache...')
        return cls('cache/bureau.f', 'cache/bb.f')

    def fill(self):
        if self.transformed:
            return
        self.df['AMT_CREDIT_SUM'].replace(0, np.nan, inplace=True)
        self.df['AMT_CREDIT_SUM_DEBT'].replace(0, np.nan, inplace=True)

    def transform(self):
        if self.transformed:
            return

        bureau = self.df
        bureau_balance = self.balance
        
        # 終了予定日と、実際の終了日の差
        bureau['ENDDATE_DIFF'] = bureau['DAYS_ENDDATE_FACT'] - bureau['DAYS_CREDIT_ENDDATE']

        # 返済期間の長さ
        bureau['DAYS_CREDIT_PLAN'] = bureau['DAYS_CREDIT_ENDDATE'] - bureau['DAYS_CREDIT']

        # 返済遅延
        bureau_balance['DPD'] = bureau_balance[['STATUS']].replace(['C', 'X', '0', '1', '2', '3', '4', '5'],
                                                                             [0, 0, 0, 15, 45, 75, 105, 135])
        bureau_balance['DPD'].value_counts()

        # 同一のCREDIT_TYPEの中での、相対クレジット額
        mean_amt_credit = bureau.groupby('CREDIT_TYPE')['AMT_CREDIT_SUM'].quantile().reset_index()
        mean_amt_credit.columns = ['CREDIT_TYPE', 'MEAN_AMT_CREDIT_BY_CREDIT_TYPE']
        bureau = pd.merge(bureau, mean_amt_credit, on='CREDIT_TYPE', how='left')
        bureau['AMT_CREDIT_SUM_RATIO'] = bureau['AMT_CREDIT_SUM'] / bureau['MEAN_AMT_CREDIT_BY_CREDIT_TYPE']
    
        # 限度額に対する借入額の比率
        bureau['AMT_CREDIT_DEBT_PERC'] = bureau['AMT_CREDIT_SUM_DEBT'] / bureau['AMT_CREDIT_SUM']
        bureau['AMT_CREDIT_DEBT_DIFF'] = bureau['AMT_CREDIT_SUM_DEBT'] - bureau['AMT_CREDIT_SUM']
    
        # 総額と1回あたり支払額の比率
        bureau['AMT_CREDIT_ANNUITY_PERC'] = bureau['AMT_ANNUITY'] / bureau['AMT_CREDIT_SUM']

        def apply_m40000(x):
            return x if x > -40000 else np.nan

        def apply_plan(x):
            if x <= 0:
                return np.nan
            if x >= 30000:
                return np.nan
            return x

        if self.prep_mode == 1:
            self.df['DAYS_CREDIT_UPDATE'] = self.df['DAYS_CREDIT_UPDATE'].apply(apply_m40000)
        if self.prep_mode == 2:
            self.df['DAYS_CREDIT_ENDDATE'] = self.df['DAYS_CREDIT_ENDDATE'].apply(apply_m40000)
        if self.prep_mode == 3:
            self.df['AMT_CREDIT_MAX_OVERDUE'].replace(np.nan, 0, inplace=True)
        if self.prep_mode == 4:
            self.df = self.df.query('CREDIT_CURRENCY == "currency 1"').reset_index(drop=True)
        if self.prep_mode == 5:
            self.df['AMT_CREDIT_SUM_DEBT'].replace(0, np.nan, inplace=True)
        if self.prep_mode == 6:
            self.df['DAYS_CREDIT_PLAN'] = self.df['DAYS_CREDIT_PLAN'].apply(apply_plan)
        if self.prep_mode == 7:
            self.df = self.df.query('CREDIT_ACTIVE == "Active" or CREDIT_ACTIVE == "Closed"').reset_index(drop=True)

        print('prep mode: {}, shape: {}'.format(self.prep_mode, self.df.shape))

        self.df = bureau
        self.balance = bureau_balance
        self.df.to_feather('cache/bureau.f')
        self.balance.to_feather('cache/bb.f')

    def aggregate(self, df_base):
        print('aggregate: bureau')
        agg = {
            'DAYS_CREDIT': ['count', 'mean'],
            'CREDIT_DAY_OVERDUE': ['mean', 'sum'],
            'DAYS_CREDIT_ENDDATE': ['mean'],
            'DAYS_ENDDATE_FACT': ['mean'],
            'AMT_CREDIT_MAX_OVERDUE': ['mean', 'sum'],
            'CNT_CREDIT_PROLONG': ['mean', 'sum'],
            'AMT_CREDIT_SUM': ['mean', 'sum'],
            'AMT_CREDIT_SUM_DEBT': ['mean', 'sum'],
            'AMT_CREDIT_SUM_LIMIT': ['mean', 'sum'],
            'AMT_CREDIT_SUM_OVERDUE': ['mean', 'sum'],
            'CREDIT_TYPE': ['nunique'],
            'DAYS_CREDIT_UPDATE': ['mean'],
            'AMT_ANNUITY': ['mean', 'sum'],

            'BB_DPD_MEAN': ['mean', 'max'],
            'BB_MONTHS_BALANCE_MIN': ['min'],
            'BB_MONTHS_BALANCE_MAX': ['max'],
            'BB_MONTHS_BALANCE_SIZE': ['mean', 'sum'],

            'ENDDATE_DIFF': ['mean'],
            'AMT_CREDIT_SUM_RATIO': ['mean', 'max'],
            'DAYS_CREDIT_PLAN': ['mean', 'sum'],

            'AMT_CREDIT_DEBT_PERC': ['mean','min','max'],
            'AMT_CREDIT_DEBT_DIFF': ['mean','sum']
        }

        bb_aggregations = {
            'MONTHS_BALANCE': ['min', 'max', 'size'],
            'DPD': ['min', 'max', 'mean', 'std']
        }

        # BBをmerge
        bb_agg = self.balance.groupby('SK_ID_BUREAU').agg(bb_aggregations)
        bb_agg.columns = pd.Index(['BB_' + e[0] + "_" + e[1].upper() for e in bb_agg.columns.tolist()])
        bb_agg.reset_index(inplace=True)

        b = self.df
        b = pd.merge(b, bb_agg, how='left', on='SK_ID_BUREAU')

        # カテゴリ別とステータス別に分けておく。

        df_base = features_common.aggregate(df_base, agg, b, 'b_')
        df_base = features_common.aggregate(df_base, agg, b.query('CREDIT_ACTIVE == "Active"'), 'b_active_')
        df_base = features_common.aggregate(df_base, agg, b.query('CREDIT_ACTIVE == "Closed"'), 'b_closed_')
        df_base = features_common.aggregate(df_base, agg, b.query('CREDIT_TYPE == "Consumer credit"'), 'b_consumer_')
        df_base = features_common.aggregate(df_base, agg, b.query('CREDIT_TYPE == "Credit card"'), 'b_credit_')
        df_base = features_common.aggregate(df_base, agg, b.query('CREDIT_TYPE == "Car loan"'), 'b_car_')
        df_base = features_common.aggregate(df_base, agg, b.query('CREDIT_TYPE == "Mortgage"'), 'b_mortage_')
        df_base = features_common.aggregate(df_base, agg, b.query('CREDIT_TYPE == "Microloan"'), 'b_micro_')

        df_base = features_common.aggregate(df_base, agg, b.query('DAYS_CREDIT >= -720'), 'b_720_')
        df_base = features_common.aggregate(df_base, agg, b.query('DAYS_CREDIT >= -365'), 'b_365_')
        df_base = features_common.aggregate(df_base, agg, b.query('DAYS_CREDIT >= -180'), 'b_180_')

        self.df = b
        return df_base
