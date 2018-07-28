import pandas as pd
import credit
import bureau
import application
import pos_cash
import install
import prev


class Feature(object):
    def __init__(self):
        tables = {
            'credit': credit.Credit(),
            'bureau': bureau.Bureau(),
            'prev': prev.Prev(),
            'install': install.Install(),
            'cash': pos_cash.PosCash(),
            'app': application.Application()
        }

        print('transform...')
        for _, v in tables.items():
            v.fill()
            v.transform()

        df = tables['app'].df

        for k, v in tables.items():
            if k == 'app':
                continue

            df = v.aggregate(df)
            print('{} merged. shape: {}'.format(k, df.shape))

        df = tables['app'].transform_with_others(df, tables['prev'].prev)
        print('transform finished. {}'.format(df.shape))

        self.tables = tables
        self.df = df
        self._load_exotic()
        self._delete_columns()

    def _delete_columns(self):
        self.df.drop(['ORGANIZATION_TYPE', 'AMT_REQ_CREDIT_BUREAU_HOUR', 'AMT_REQ_CREDIT_BUREAU_DAY',
                      'AMT_REQ_CREDIT_BUREAU_WEEK', 'AMT_REQ_CREDIT_BUREAU_MON', 'AMT_REQ_CREDIT_BUREAU_QRT',
                      'FLAG_CONT_MOBILE', 'FLAG_DOCUMENT_10', 'FLAG_DOCUMENT_11', 'FLAG_DOCUMENT_12',
                      'FLAG_DOCUMENT_13', 'FLAG_DOCUMENT_14', 'FLAG_DOCUMENT_15', 'FLAG_DOCUMENT_17',
                      'FLAG_DOCUMENT_19', 'FLAG_DOCUMENT_2', 'FLAG_DOCUMENT_20', 'FLAG_DOCUMENT_21', 'FLAG_DOCUMENT_4',
                      'FLAG_DOCUMENT_7', 'FLAG_DOCUMENT_9', 'FLAG_MOBIL'
                      ], axis=1, inplace=True)

    def _load_exotic(self):
        d = pd.read_feather('../model/predicted_dpd.f')
        self.df = pd.merge(self.df, d[['SK_ID_CURR', 'PREDICTED_X14Y-1']], on='SK_ID_CURR', how='left')

        d = pd.read_feather('../model/x_add2.f')
        self.df = pd.merge(self.df, d[['SK_ID_CURR', 'POS_PREDICTED']], on='SK_ID_CURR', how='left')


if __name__ == "__main__":
    f = Feature()

    print(f.shape)

    f.df.to_feather('features_all.f')
    f.df.head(100).to_csv('all_sample.csv', index=False)
