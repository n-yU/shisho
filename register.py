from logging import getLogger, StreamHandler, DEBUG, Formatter
from pathlib import Path
from tqdm import tqdm
from elasticsearch import Elasticsearch
import MeCab
from backend.openbd import OpenBD
from backend.doc2vecwrapper import Doc2VecWrapper

# ロガー設定
logger = getLogger(__name__)
handler = StreamHandler()
handler.setLevel(DEBUG)
logger.setLevel(DEBUG)
logger.addHandler(handler)
logger.propagate = False
handler.setFormatter(Formatter('[tosho42] %(message)s'))

if __name__ == '__main__':
    mecab = MeCab.Tagger('-Ochasen -r /etc/mecabrc -d /usr/lib/x86_64-linux-gnu/mecab/dic/mecab-ipadic-neologd')   # MeCab設定
    books_path = Path('./config/books.txt')  # 書籍データファイルパス

    # 書籍データ読み込み
    with open(books_path, mode='r') as f:
        books = f.readlines()

    es = Elasticsearch('elasticsearch')
    for book in tqdm(books):
        # 書籍登録
        # ISBN-10 -> openBDへ書籍情報リクエスト -> 基本情報取得 -> bookインデックスに登録
        isbn10 = book.strip()
        book = OpenBD(isbn10=isbn10, mecab=mecab).get_std_info()
        es.index(index='book', doc_type='_doc', body=book, id=isbn10)
    es.indices.refresh(index='book')
    es.close()
    logger.debug('書籍データの一括登録が完了しました')

    # Doc2Vecモデルの初期化と訓練
    Path('/projects/model').mkdir(exist_ok=True)
    d2v = Doc2VecWrapper(model_path=Path('/projects/model/d2v.model'), initialize=True)
    d2v.train()
    logger.debug('Doc2Vecモデルの訓練が完了しました')
