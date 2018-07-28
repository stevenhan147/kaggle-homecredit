import pandas as pd
import numpy as np
import pandas as pd
import numpy as np
import lightgbm as lgb
import time
import gc
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import KFold, StratifiedKFold
from contextlib import contextmanager
from lightgbm import LGBMClassifier

np.random.seed(42)


@contextmanager
def timer(title):
    t0 = time.time()
    yield
    print("{} - done in {:.0f}s".format(title, time.time() - t0))


def lgbm_cv(param, X, y, X_test, nfolds=5, submission='../output/sub.csv'):
    folds = KFold(n_splits=nfolds, shuffle=True, random_state=47)
    feature_importance_df = pd.DataFrame()
    feats = [f for f in X.columns if f not in ['TARGET', 'SK_ID_CURR', 'SK_ID_BUREAU', 'SK_ID_PREV', 'index']]
    oof_preds = np.zeros(X.shape[0])

    if X_test is not None:
        preds_test = np.empty((nfolds, X_test.shape[0]))

    roc = []

    for n_fold, (train_idx, valid_idx) in enumerate(folds.split(X[feats], y)):
        train_x, train_y = X[feats].iloc[train_idx], y.iloc[train_idx]
        valid_x, valid_y = X[feats].iloc[valid_idx], y.iloc[valid_idx]

        # LightGBM parameters found by Bayesian optimization
        clf = LGBMClassifier(**param)
        clf.fit(train_x, train_y, eval_set=[(valid_x, valid_y)],
                eval_metric='auc', verbose=-1, early_stopping_rounds=200)

        oof_preds[valid_idx] = clf.predict_proba(valid_x, num_iteration=clf.best_iteration_)[:, 1]

        if submission is not None:
            preds_test[n_fold, :] = clf.predict_proba(X_test, num_iteration=clf.best_iteration_)[:, 1]

        fold_importance_df = pd.DataFrame()
        fold_importance_df["feature"] = feats
        fold_importance_df["importance"] = clf.feature_importances_
        fold_importance_df["fold"] = n_fold + 1
        feature_importance_df = pd.concat([feature_importance_df, fold_importance_df], axis=0)
        # print('Fold {} AUC : {:.6f}'.format(n_fold + 1, roc_auc_score(valid_y, oof_preds[valid_idx])))
        roc.append(roc_auc_score(valid_y, oof_preds[valid_idx]))

        del clf, train_x, train_y, valid_x, valid_y
        gc.collect()

    # print('Full AUC score %.6f' % roc_auc_score(y, oof_preds))
    # display_importances(feature_importance_df)

    if submission is not None:
        preds = preds_test.mean(axis=0)
        sub = pd.read_csv('../input/sample_submission.csv')
        sub['TARGET'] = preds
        sub.to_csv(submission, index=False)

    roc.append(roc_auc_score(y, oof_preds))
    return roc


def feature_selection_eval(param, X: pd.DataFrame, X_add, y, X_test, nfolds, set=2, file='log_fw.txt'):
    n_columns = X_add.shape[1]

    n_loop = n_columns // set

    with open(file, 'a') as f:
        # baseline
        auc = lgbm_cv(param, X, y, None, 5, None)
        f.write('{},{},{},{},{},{},baseline,baseline\n'.format(auc[0], auc[1], auc[2], auc[3], auc[4], auc[5]))

        for i in range(n_loop):
            X_c = X.copy()
            for n in range(set):
                idx = i * set + n
                col = X_add.columns.tolist()[idx]
                X_c[col] = X_add[col]

            add_columns = X_add.columns.tolist()[i * set:(i + 1) * set]
            print('add:{}'.format(add_columns))
            auc = lgbm_cv(param, X_c, y, None, 5, None)
            f.write(
                '{},{},{},{},{},{},{}\n'.format(auc[0], auc[1], auc[2], auc[3], auc[4], auc[5], add_columns[0]))
            f.flush()


X = pd.read_feather('x_base2.f')
X_add = pd.read_feather('x_add4.f')
y = pd.read_feather('y.f')

print(X.shape)
print(X_add.shape)
print(y.shape)

tgt = ~X.TARGET.isnull()
X = X[tgt].reset_index(drop=True)

X_add = X_add[tgt].reset_index(drop=True)

# lr=0.02 : 0.7888116, round1000, 976s
# lr=0.04 : 0.7888695+ 0.0022, round621, 621s
lgb_param = {
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
    'n_estimators': 10000,
    'verbose': -1
}

feature_selection_eval(lgb_param, X, X_add.drop('SK_ID_CURR', axis=1), y['y'], None, 5, set=1, file='log_fw4.txt')