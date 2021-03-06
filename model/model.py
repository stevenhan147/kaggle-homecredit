import gc
import pandas as pd
import numpy as np
import time
from datetime import datetime
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import KFold, StratifiedKFold
from lightgbm import LGBMClassifier


BASE_X_PATH = 'x_base.f'
ADD_X_PATH = ['x_add2.f','x_add_dpd_predicted_reg_all.f','predicted_dpd.f','x_add4.f']#, 'x_add3.f']


def prep_and_split(df):
    for c in df:
        if df[c].dtype.name == 'object':
            df[c] = df[c].astype('category')

    if 'SK_ID_CURR' in df.columns:
        df.drop('SK_ID_CURR', axis=1, inplace=True)

    X_train = df[~df.TARGET.isnull()].drop('TARGET', axis=1)
    y_train = df[~df.TARGET.isnull()]['TARGET']
    X_test = df[df.TARGET.isnull()].drop('TARGET', axis=1)

    return X_train, y_train, X_test


class Model(object):
    def __init__(self, name, remove_columns = None,
                 add_columns = None, drop_xna = False,
                 param = None, kfold_seed = 47, lgb_seed = None, n_estimators = 10000, log = None):
        self.name = name

        if log is None:
            self.logfile = open('../output/{}.txt'.format(name), 'w')
        else:
            self.logfile = open('../output/{}.txt'.format(log), 'w')


        if param is None:
            self.param = {
                'objective': 'binary',
                'num_leaves': 32,
                'learning_rate': 0.04,
                'colsample_bytree': 0.95,
                'subsample': 0.872,
                'max_depth': 8,
                'reg_alpha': 0.04,
                'reg_lambda': 0.073,
                'min_split_gain': 0.0222415,
                'min_child_weight': 40,
                'metric': 'auc',
                'n_estimators': 10000
            }
        else:
            self.param = param

        if lgb_seed is not None:
            self.param['seed'] = lgb_seed
        self.param['n_estimators'] = n_estimators
        self.kfold_seed = kfold_seed
        self.feature_importance_df = None
        self.classifiers = []

        self.x = pd.read_feather(BASE_X_PATH).reset_index(drop=True)

        def _load_f(f):
            df = pd.read_feather(f)
            if len(df) != 356255:
                raise RuntimeError('length error {} != 356255'.format(len(df)))
            if 'SK_ID_CURR' in df:
                df.drop('SK_ID_CURR', axis=1, inplace=True)

            return df

        if add_columns is not None:
            x_add = pd.concat([_load_f(f) for f in ADD_X_PATH], axis=1)

            print('add: {}'.format(add_columns))

            for a in add_columns:
                print(a)
                self.x[a] = x_add[a]

            print(self.x.shape)

        if remove_columns is not None:
            self.x.drop(remove_columns, axis=1, inplace=True)

        for c in ['SK_ID_CURR', 'SK_ID_BUREAU', 'SK_ID_PREV', 'index']:
            if c in self.x:
                print('drop {}'.format(c))
                self.x.drop(c, axis=1, inplace=True)

        if drop_xna:
            self.x = self.x[self.x['CODE_GENDER'] != 'XNA'].reset_index(drop=True)

        self.x.to_feather('x_model12.f')

        print('shape: {}'.format(self.x.shape))
        self.x_train, self.y_train, self.x_test = prep_and_split(self.x)

        self.x_train.reset_index(drop=True,inplace=True)
        self.x_test.reset_index(drop=True, inplace=True)

    # Display/plot feature importance
    def display_importances(self, feature_importance_df_, filename, n=60):
        cols = feature_importance_df_[["feature", "importance"]].groupby("feature").mean().sort_values(by="importance",
                                                                                                       ascending=False)[
               :n].index

        import matplotlib.pyplot as plt
        import seaborn as sns

        best_features = feature_importance_df_.loc[feature_importance_df_.feature.isin(cols)]
        plt.figure(figsize=(10, 12))
        sns.barplot(x="importance", y="feature", data=best_features.sort_values(by="importance", ascending=False))
        plt.title('LightGBM Features (avg over folds)')
        plt.tight_layout()
        plt.savefig('{}.png'.format(filename))

    def cv(self, nfolds=5, submission=True):
        self.classifiers.clear()

        folds = KFold(n_splits=nfolds, shuffle=True, random_state=47)
        self.feature_importance_df = pd.DataFrame()

        oof_preds = np.zeros(self.x_train.shape[0])
        preds_test = np.empty((nfolds, self.x_test.shape[0]))

        self.logfile.write('param: {}\n'.format(self.param))
        self.logfile.write('fold: {}\n'.format(nfolds))
        self.logfile.write('data shape: {}\n'.format(self.x_train.shape))
        self.logfile.write('features: {}\n'.format(self.x_train.columns.tolist()))
        self.logfile.write('output: ../output/{}.csv\n'.format(self.name))
        self.logfile.flush()

        for n_fold, (train_idx, valid_idx) in enumerate(folds.split(self.x_train, self.y_train)):
            fstart = time.time()
            train_x, train_y = self.x_train.iloc[train_idx], self.y_train.iloc[train_idx]
            valid_x, valid_y = self.x_train.iloc[valid_idx], self.y_train.iloc[valid_idx]

            # LightGBM parameters found by Bayesian optimization
            clf = LGBMClassifier(**self.param)
            clf.fit(train_x, train_y, eval_set=[(valid_x, valid_y)],
                    eval_metric='auc', verbose=25, early_stopping_rounds=200)

            oof_preds[valid_idx] = clf.predict_proba(valid_x, num_iteration=clf.best_iteration_)[:, 1]
            preds_test[n_fold, :] = clf.predict_proba(self.x_test, num_iteration=clf.best_iteration_)[:, 1]

            fold_importance_df = pd.DataFrame()
            fold_importance_df["feature"] = self.x_train.columns.tolist()
            fold_importance_df["importance"] = clf.feature_importances_
            fold_importance_df["fold"] = n_fold + 1
            self.feature_importance_df = pd.concat([self.feature_importance_df, fold_importance_df], axis=0)

            strlog = '[{}][{:.1f} sec] Fold {} AUC : {:.6f}'.format(str(datetime.now()), time.time() - fstart, n_fold + 1, roc_auc_score(valid_y, oof_preds[valid_idx]))
            print(strlog)
            self.logfile.write(strlog+'\n')

            self.classifiers.append(clf)
            del clf, train_x, train_y, valid_x, valid_y
            gc.collect()

        full_auc = roc_auc_score(self.y_train, oof_preds)
        strlog = 'Full AUC score {:.6f}'.format(full_auc)
        print(strlog)
        self.logfile.write(strlog+'\n')
        #display_importances(self.feature_importance_df)

        if submission:
            preds = preds_test.mean(axis=0)
            sub = pd.read_csv('../input/sample_submission.csv')
            sub['TARGET'] = preds
            sub.to_csv('../output/{}.csv'.format(self.name), index=False)

        cols = self.feature_importance_df[["feature", "importance"]].groupby("feature").mean().sort_values(by="importance", ascending=False)[:50].index
        self.logfile.write('top features: {}'.format(cols))
        self.logfile.flush()

        self.display_importances(self.feature_importance_df, self.name)

        return self.feature_importance_df, full_auc

