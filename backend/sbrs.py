from logging import getLogger, StreamHandler, DEBUG, Formatter
import sys
from pathlib import Path
from typing import Union
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from backend.doc2vecwrapper import Doc2VecWrapper
from backend.db import get_history_df, History

parent_dir = str(Path(__file__).parent.parent.resolve())
sys.path.append(parent_dir)
from config import get_config

# ロガー設定
logger = getLogger(__name__)
handler = StreamHandler()
handler.setLevel(DEBUG)
logger.setLevel(DEBUG)
logger.addHandler(handler)
logger.propagate = False
handler.setFormatter(Formatter('[shisho:SBRS] %(asctime)s - %(message)s'))


def calc_similarity(rep_1: np.ndarray, rep_2: np.ndarray) -> float:
    """ベクトル間のコサイン類似度の計算
    Args:
        rep_1 (np.ndarray): ベクトル1
        rep_2 (np.ndarray): ベクトル2（ベクトル1とベクトル2が逆でも計算結果は同じ）
    Returns:
        float: ベクトル1とベクトル2のコサイン類似度
    """
    cos_sim = float(np.dot(rep_1, rep_2) / (np.linalg.norm(rep_1) * np.linalg.norm(rep_2)))
    return cos_sim


class ProposalSystem():
    """提案SBRS
    """

    def __init__(self, train_df: pd.core.frame.DataFrame, d2v: Doc2VecWrapper):
        """インスタンス生成時の初期化処理

        Args:
            train_df (pd.core.frame.DataFrame): 訓練セット（過去の閲覧履歴）
            d2v (Doc2VecWrapper): Doc2Vec（書籍表現管理）
        """
        # 訓練済みDodc2Vecモデルのみ受付
        if not d2v.is_trained:
            logger.exception('Doc2Vecモデルが未訓練状態です')
        self.d2v = d2v

        self.params = get_config()['sbrs']          # 提案SBRSハイパーパラメータ設定
        self.train_df = train_df                    # 訓練セット
        self.uIds = set(train_df['uId'].unique())   # ユーザID集合

        self.users = dict()  # ProposalUserインスタンス集合
        # 訓練セットに含まれる全ユーザ分のProposalUserクラス（提案システム用のユーザクラス）のインスタンス生成
        for uId in self.uIds:
            self.users[uId] = ProposalUser(uId=uId, prop_sys=self)

    @property
    def n_constructed_book(self) -> int:
        """書籍表現数算出

        Returns:
            int: 書籍表現数
        """
        return len(self.d2v.bv.index_to_key)

    @property
    def n_constructed_user(self) -> int:
        """ユーザ表現数算出

        Returns:
            int: ユーザ表現数算出
        """
        return len(self.user_reps)

    def get_book_rep(self, bId: str) -> Union[np.ndarray, None]:
        """書籍表現取得

        Args:
            bId (str): 書籍ID（ISBN-10）

        Returns:
            Union[np.ndarray, None]: 書籍表現（取得失敗時はNone）
        """
        try:
            # 指定したISBN-10に対応する書籍の分散表現を取得
            book_rep = self.d2v.bv[bId]
        except KeyError:
            # 書籍表現取得失敗（新規登録書籍など）
            book_rep = None
        return book_rep

    def construct_book_knn_model(self) -> None:
        """書籍KNNモデル構築
        """
        book_knn_model = NearestNeighbors(n_neighbors=min(self.params['search']['k_book'] + 1, self.n_constructed_book))
        self.book_knn_model = book_knn_model.fit(np.array(self.d2v.bv[self.d2v.bv.index_to_key]))
        self.bId_by_bIdx = np.array(self.d2v.bv.index_to_key)   # 書籍IX対応IDリスト

    def construct_user_knn_model(self) -> None:
        """ユーザKNNモデル構築
        """
        user_knn_model = NearestNeighbors(n_neighbors=min(self.params['search']['k_user'] + 1, self.n_constructed_user))
        self.user_knn_model = user_knn_model.fit(np.array(list(self.user_reps.values())))
        self.uId_by_uIdx = np.array(list(self.users.keys()))    # ユーザIX対応IDリスト

    def learn(self) -> None:
        """提案システム学習（各表現の構築/更新）
        """
        self.user_reps = dict()  # ユーザ表現集合

        for log in self.train_df.itertuples():
            book_rep = self.get_book_rep(bId=log.bId)   # 書籍表現

            if book_rep is None:    # 書籍表現取得失敗 -> 各表現の更新・構築行わない
                continue

            self.users[log.uId].update_reps(log=log)    # ログをもつユーザのセッション・ユーザ表現の更新・構築

        self.construct_book_knn_model()  # 書籍KNNモデル構築

        if self.n_constructed_user > 1:  # ユーザ表現数2以上（最低でも自身含む最近傍） -> ユーザKNNモデル構築
            self.construct_user_knn_model()

    def update(self, log: History, return_rec=True) -> Union[np.ndarray, None]:
        """提案SBRS更新（ログから各表現更新 -> 必要に応じて推薦書籍集合生成）

        Args:
            log (History): ログ（uId, sId, bIdなど内包）
            return_rec (bool, optional): 推薦アイテム集合の生成を試みるならTrue．Defaults to True.

        Returns:
            Union[np.ndarray, None]: 生成成功 -> 推薦書籍集合
        """
        if self.users.get(log.uId) is None:  # 新規ユーザ -> 提案SBRS用ユーザインスタンス生成
            self.uIds.add(log.uId)
            self.users[log.uId] = ProposalUser(uId=log.uId, prop_sys=self)
        self.users[log.uId].update_reps(log=log)    # 各表現更新（or 構築）

        # ユーザKNNモデル構築済＆出現書籍表現構築済 -> 推薦書籍集合生成
        if return_rec and (self.user_knn_model is not None) and (self.get_book_rep(bId=log.bId) is not None):
            rec_books = self.users[log.uId].search_recommended_books(log=log)
        else:
            rec_books = None
        return rec_books


class ProposalUser():
    """提案SBRS用ユーザ
    """

    def __init__(self, uId: str, prop_sys: ProposalSystem):
        """インスタンス生成時の初期化処理

        Args:
            uId (str): ユーザID
            prop_sys (ProposalSystem): このユーザを管理する提案SBRS
        """
        self.sIds = ['*']           # セッションID集合
        self.session_reps = dict()  # セッション表現集合
        self.uId = uId              # ユーザID
        self.user_rep = None        # ユーザ表現

        self.prop_sys = prop_sys            # このユーザを管理する提案SBRS
        self.params = self.prop_sys.params  # 提案SBRSハイパーパラメータ設定
        self.prv_bId = None                 # 直前閲覧書籍ID（ISBN-10）（同書籍連続時の例外処理のため）

    @ property
    def latest_sId(self) -> str:
        """最新セッションID取得

        Returns:
            str: 最新セッションID
        """
        return self.sIds[-1]

    @ property
    def latest_session_rep(self) -> np.ndarray:
        """最新セッション表現取得

        Returns:
            np.ndarray: 最新セッション表現
        """
        rep = self.session_reps[self.latest_sId].copy()
        return rep

    def update_reps(self, log: History) -> None:
        """各表現の構築/更新

        Args:
            log (History): ログ
        """
        # 直前に閲覧した書籍と同じ -> 各表現の構築/更新スキップ
        if (self.prv_bId is not None) and (log.bId == self.prv_bId):
            return
        self.prv_bId = log.bId  # 直前閲覧書籍ID更新

        self.__construct_session_rep(sId=log.sId, bId=log.bId)  # セッション表現の構築/更新

        # 現在のセッションのセッション表現構築済＆セッション末尾ログ -> ユーザ表現の構築/更新
        if (self.session_reps[log.sId] is not None) and log.isLast:
            success_construct_user_rep = self.construct_user_rep(sId=log.sId)   # ユーザ表現の構築/更新試行
            if success_construct_user_rep:
                # 構築/更新成功 -> 提案システム管理ユーザ表現集合へ追加/更新
                self.prop_sys.user_reps[self.uId] = self.user_rep.copy()

    def __construct_session_rep(self, sId: str, bId: str) -> bool:
        """セッション表現の構築/更新

        Args:
            sId (str): セッションID
            bId (str): 出現書籍ID

        Returns:
            bool: セッション表現構築/更新に成功 -> True
        """
        book_rep = self.prop_sys.get_book_rep(bId=bId)  # 出現書籍表現

        if book_rep is None:    # 出現書籍の書籍表現未構築 -> セッション表現構築/更新失敗
            return False

        if sId != self.latest_sId:
            # 現在のセッションIDと最新セッション表現と対応するIDが異なる -> 新規セッション -> セッション表現構築
            self.sIds.append(sId)
            self.session_reps[sId] = book_rep.copy()    # 出現書籍表現により構築
            logger.debug('uId:{0}/sId:{1}/bId:{2} -> Construct session rep.'.format(self.uId, sId, bId))
        else:
            # セッション表現更新
            srep_cm = self.params['session_rep']['update_method']    # セッション表現更新法

            if srep_cm == 'cos':
                # セッション表現更新法: コサイン類似度 (COSine similarity)

                # 最新セッション表現と出現書籍表現のコサイン類似度
                sim = calc_similarity(rep_1=self.latest_session_rep, rep_2=book_rep)
                weight = abs(sim)   # セッション表現更新用重み

                # セッション表現更新（TODO: 4種類の計算方法追加）
                updated_session_rep = weight * self.latest_session_rep + book_rep
            elif srep_cm == 'odd':
                # セッション表現構築法: 順序差減衰 (Order Decay Difference)
                # TODO: 実装
                pass
            else:
                logger.exception('指定したセッション表現構築法"{}"は未定義です'.format(srep_cm))

            self.session_reps[self.latest_sId] = updated_session_rep    # セッション表現更新
            logger.debug('uId:{0}/sId:{1}/bId:{2} -> Update session rep.'.format(self.uId, sId, bId))

        return True

    def construct_user_rep(self, sId: str) -> bool:
        """ユーザ表現の構築/更新

        Args:
            sId (str): セッションID

        Returns:
            bool: ユーザ表現構築/更新に成功 -> True
        """

        # 現在のセッションIDと最新セッション表現と対応するIDが異なる -> セッション表現未構築 -> ユーザ表現構築/更新失敗
        if sId != self.latest_sId:
            return False

        if self.user_rep is None:   # ユーザ表現未構築 ->ユーザ表現構築
            self.user_rep = self.latest_session_rep.copy()  # 最新セッション表現により構築
            # 構築済ユーザ表現数増加（ただし2以上） -> ユーザKNNモデル再構築
            if self.prop_sys.n_constructed_user > 1:
                self.prop_sys.construct_user_knn_model()
            logger.debug('uId:{0}/sId:{0} -> Construct user rep.'.format(self.uId, sId))
        else:
            # ユーザ表現更新
            context_size = self.params['user_rep']['context_size']  # コンテキストセッション数
            if context_size < 1:
                logger.exception('コンテキストサイズ（指定値: {}）は1以上の整数を指定してください'.format(context_size))
            # 最新context_size個のセッションID取得（ただし，min{過去セッションID数, context_size})
            context_sIds = self.sIds[1:][-context_size:]

            weighted_rep_sum, weight_sum = np.zeros(100), 0.0    # セッション表現加重和，ユーザ表現更新用重み和

            for sId in context_sIds:
                srep = self.session_reps[sId]   # コンテキストに含まれるセッション表現の取得
                sim = calc_similarity(rep_1=self.latest_session_rep, rep_2=srep)    # 最新セッション表現とのコサイン類似度計算
                weight = abs(sim)   # ユーザ表現更新用重み

                weighted_rep_sum += weight * srep
                weight_sum += weight

            updated_user_rep = weighted_rep_sum / weight_sum    # コンテキストセッション表現の加重平均によるユーザ表現計算
            self.user_rep = updated_user_rep.copy()             # ユーザ表現更新
            logger.debug('uId:{0}/sId:{1} -> Update user rep.'.format(self.uId, sId))

        return True

    def construct_rtuser_rep(self) -> np.ndarray:
        """リアルタイムユーザ表現の構築/更新

        Returns:
            np.ndarray: リアルタイムユーザ表現
        """
        # ユーザ表現未構築 -> 最新セッション表現をそのままリアルタイムユーザ表現とする
        if self.user_rep is None:
            return self.latest_session_rep

        # 最新セッション表現とユーザ表現のコサイン類似度計算
        sim = calc_similarity(rep_1=self.latest_session_rep, rep_2=self.user_rep)
        weight = abs(sim)   # リアルタイムユーザ表現構築用重み

        rturep_cm = self.params['rtuser_rep']['construct_method']   # リアルタイムユーザ表現構築法
        if rturep_cm == 'avg-session':      # 加重平均（セッション軸）
            rtuser_rep = weight * self.latest_session_rep + (1 - weight) * self.user_rep
        elif rturep_cm == 'avg-user':       # 加重平均（ユーザ軸）
            rtuser_rep = (1 - weight) * self.latest_session_rep + weight * self.user_rep
        elif rturep_cm == 'sum-session':    # 加重和（セッション軸）
            rtuser_rep = weight * self.latest_session_rep + self.user_rep
        elif rturep_cm == 'sum-user':       # 加重和（ユーザ軸）
            rtuser_rep = self.latest_session_rep + weight * self.user_rep
        else:
            logger.exception('指定したリアルタイムユーザ表現構築法"{0}"は未定義です'.format(rturep_cm))

        logger.debug('uId:{0} -> Construct rtuser rep.'.format(self.uId))
        return rtuser_rep

    def search_recommended_books(self, log: History) -> np.ndarray:
        """推薦書籍探索

        Args:
            log (ログ): History

        Returns:
            np.ndarray: 推薦書籍集合
        """
        k_book, k_user = self.params['search']['k_book'], self.params['search']['k_user']   # 近傍書籍数，近傍ユーザ数
        rtuser_rep = self.construct_rtuser_rep()    # リアルタイムユーザ表現取得

        # リアルタイムユーザ表現近傍（k_book+1）書籍インデックス -> ID変換
        nn_books_idx = self.prop_sys.book_knn_model.kneighbors([rtuser_rep], return_distance=False)
        nn_books = self.prop_sys.bId_by_bIdx[nn_books_idx[0]]

        rsm = self.params['search']['method']   # 推薦書籍探索法
        if rsm == 'nn':     # NN型探索
            # 出現書籍除外 -> 先頭k_book個取得
            recommended_books = nn_books[log.bId != nn_books][:k_book]
        elif rsm == 'cf':   # CF型探索
            # リアルタイムユーザ表現近傍（k_user+1）ユーザインデックス -> ID変換
            nn_users_idx = self.prop_sys.user_knn_model.kneighbors([rtuser_rep], return_distance=False)
            tmp_nn_users = self.prop_sys.uId_by_uIdx[nn_users_idx[0]]

            # 自身除外 -> 先頭k_user人取得 -> 各IDに対応するユーザ表現取得
            nn_users = tmp_nn_users[log.uId != tmp_nn_users][:k_user]
            nn_users_rep = np.array([self.prop_sys.user_reps[uId] for uId in nn_users])

            # TODO: エラー吐かなければ消す
            # if nn_users_rep.shape[0] == 0:
            #     return None

            # 近傍ユーザ表現の近傍（k_book+1）書籍インデックス
            tmp_nn_books_idx_by_nn_users = self.prop_sys.book_knn_model.kneighbors(nn_users_rep, return_distance=False)
            # 先頭k_book個取得 -> 1次元行列化
            nn_books_idx_by_nn_users = np.array([nb[:k_book] for nb in tmp_nn_books_idx_by_nn_users]).ravel()
            # 書籍IDへ変換 -> 直負書籍削除
            nn_books_by_nn_users = np.unique(self.prop_sys.bId_by_bIdx[nn_books_idx_by_nn_users])

            common_nn_books = set(nn_books) & set(nn_books_by_nn_users)  # 共通近傍書籍
            recommended_books = []  # 推薦書籍集合

            for bId in nn_books:    # 共通近傍書籍を優先的に推薦書籍集合に追加
                if len(recommended_books) >= k_book:    # 推薦書籍集合サイズ上限
                    break
                if (bId in common_nn_books) and (bId != log.bId):       # 共通近傍書籍かつ出現書籍でない書籍を追加
                    recommended_books.append(bId)

            for bId in nn_books:
                if len(recommended_books) >= k_book:    # 推薦書籍集合サイズ上限
                    break
                if (bId not in common_nn_books) and (bId != log.bId):   # 共通近傍書籍でなく出現書籍でもない書籍を追加
                    recommended_books.append(bId)
        else:
            logger.exception('指定した推薦アイテム探索法"{0}"は未定義です'.format(rsm))

        assert(log.bId not in recommended_books)    # 出現書籍が推薦書籍集合に含まれていないか確認
        return recommended_books


def get_prop_sbrs(d2v: Doc2VecWrapper) -> ProposalSystem:
    """過去閲覧履歴から提案SBRSの取得/学習

    Args:
        d2v (Doc2VecWrapper): 学習済Doc2Vecモデル

    Returns:
        ProposalSystem: [description]
    """
    train_df = get_history_df()  # 過去閲覧履歴を訓練セットとする
    prop_sbrs = ProposalSystem(train_df=train_df, d2v=d2v)  # 提案SBRS取得
    prop_sbrs.learn()   # 提案SBRS学習

    return prop_sbrs
