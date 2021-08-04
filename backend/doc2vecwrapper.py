from logging import getLogger, StreamHandler, DEBUG, Formatter
from typing import List, Tuple
from pathlib import Path
from elasticsearch import Elasticsearch
import MeCab
from gensim.models.doc2vec import Doc2Vec, TaggedDocument

# ロガー設定
logger = getLogger(__name__)
handler = StreamHandler()
handler.setLevel(DEBUG)
logger.setLevel(DEBUG)
logger.addHandler(handler)
logger.propagate = False
handler.setFormatter(Formatter('[shisho] %(asctime)s - %(message)s'))


class Doc2VecWrapper():
    def __init__(self, model_path: Path, initialize=False):
        """インスタンス生成時の初期化処理

        Args:
            model_path (Path): モデルファイルパス
            initialize (bool, optional): モデル初期化時->True．Defaults to False.
        """
        self.model_path = model_path    # モデルファイルパス

        # 非初期化指定＆モデルパス先存在 -> 訓練済みとする
        if (not initialize) and self.model_path.exists():
            self.is_trained = True
        else:
            self.is_trained = False

        # 訓練済み -> モデル読み込み
        if self.is_trained:
            self.__load_model()

        # MeCab設定: NEologd（MeCab用システム辞書）を使った分かち書き
        self.mecab = MeCab.Tagger('-Ochasen -r /etc/mecabrc -d /usr/lib/x86_64-linux-gnu/mecab/dic/mecab-ipadic-neologd')

    def __load_model(self) -> None:
        """モデル読み込み
        """
        self.model = Doc2Vec.load(str(self.model_path))  # モデル
        self.wv = self.model.wv
        self.bv = self.model.dv  # 書籍ベクトル: Doc2Vecで学習された文書ベクトル

    def get_title_from_isbn10(self, isbn10: str) -> str:
        """ISBN-10から書籍タイトル取得（Elasticsearch経由）

        Args:
            isbn10 (str): ISBN-10コード

        Returns:
            str: 書籍タイトル
        """
        es = Elasticsearch('elasticsearch')
        title = es.get_source(index="book", id=isbn10)['title']
        es.close()

        return title

    def train(self, retrain=False) -> bool:
        """モデル訓練

        Args:
            retrain (bool, optional): 再訓練->True．Defaults to False.

        Returns:
            bool: 訓練成功->True
        """
        # 非再訓練指定＆訓練済み -> エラーとする
        if (not retrain) and self.is_trained:
            return False

        # 全書籍情報取得
        es = Elasticsearch('elasticsearch')
        n_book = es.count(index='book')['count']    # 登録書籍総数
        books = es.search(index='book', size=n_book)['hits']['hits']
        es.close()

        # Doc2Vec学習データ準備
        data = [(book['_id'], book['_source']['description']) for book in books]  # ISBN-10と書籍説明取得
        documents = [TaggedDocument(dscrp, [isbn10]) for isbn10, dscrp in data]  # ISBN-10を文書（書籍説明）のタグとする

        # Doc2Vecモデルの訓練・保存
        # パラメータは暫定値 <- 詳細検証予定
        self.model = Doc2Vec(documents=documents, dm=0, vector_size=100, min_count=1, epochs=30)
        self.model.save(str(self.model_path))

        self.wv = self.model.wv  # 学習済み単語ベクトル (Word Vectors)
        self.bv = self.model.dv  # 学習済み書籍ベクトル（Document (paragraph) Vectors）

        return True

    def calc_word_cossim(self, word_1: str, word_2: str) -> float:
        """単語同士のコサイン類似度計算

        Args:
            word_1 (str): 単語1
            word_2 (str): 単語2

        Returns:
            float: 単語1と単語2のコサイン類似度
        """
        cossim = self.wv.similarity(w1=word_1, w2=word_2)
        return cossim

    def calc_book_cossim(self, isbn10_1: str, isbn10_2: str) -> float:
        """書籍同士のコサイン類似度計算

        Args:
            isbn10_1 (str): 書籍1のISBN-10
            isbn10_2 (str): 書籍2のISBN-10

        Returns:
            float: 書籍1と書籍2のコサイン類似度
        """
        cossim = self.bv.similarity(w1=isbn10_1, w2=isbn10_2)
        return cossim

    def get_similar_books(self, isbn10: str, topn: int, verbose=False) -> List[Tuple[str, float]]:
        """ターゲット書籍に類似する書籍集合取得

        Args:
            isbn10 (str): ターゲット書籍のISBN-10
            topn (int): 取得する書籍数（類似ベスト数）
            verbose (bool, optional): 詳細表示->True．Defaults to False.

        Returns:
            List[Tuple[str, float]]: 類似書籍集合
        """
        # ISBN-10に対応する書籍と類似するトップtopn個の書籍取得
        similar_books = self.bv.most_similar(positive=[isbn10], topn=topn)

        # 類似書籍詳細表示
        if verbose:
            logger.debug('ターゲット: {0}'.format(self.get_title_from_isbn10(isbn10=isbn10)))
            for idx, sb in enumerate(similar_books):
                logger.debug('{0}位 {1}: {2}'.format(idx + 1, self.get_title_from_isbn10(isbn10=sb[0]), sb[1]))

        return similar_books
