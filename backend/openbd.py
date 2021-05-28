from logging import getLogger, StreamHandler, DEBUG, Formatter
from typing import Dict, Union
import re
import json
import requests
import MeCab
from neologdn import normalize

# ロガー設定
logger = getLogger(__name__)
handler = StreamHandler()
handler.setLevel(DEBUG)
logger.setLevel(DEBUG)
logger.addHandler(handler)
logger.propagate = False
handler.setFormatter(Formatter('[openBD] %(asctime)s - %(message)s'))


class OpenBD:
    # openBD: https://openbd.jp/
    def __init__(self, isbn10: int, mecab: MeCab.Tagger):
        """"インスタンス生成時の初期化処理

        Args:
            isbn10 (int): OpenBDへリクエストする書籍のISBN-10
            mecab (MeCab.Tagger): MeCab設定（辞書等）
        """
        self.isbn10 = isbn10    # 書籍のISBN-10
        self.result = self.get_json_from_openbd()  # openBDへのリクエスト結果
        self.mecab = mecab      # MeCab設定

    def get_json_from_openbd(self) -> str:
        """openBDから書籍情報取得

        Returns:
            str: openBDリクエスト結果
        """
        # 指定ISBN-10の書籍情報を取得する, openBDエンドポイント
        openbd_endpoint = 'https://api.openbd.jp/v1/get?isbn={0}'.format(self.isbn10)

        try:
            response = requests.get(openbd_endpoint)
            response.raise_for_status()
        except requests.RequestException as e:
            # ステータスコード200番台以外 -> エラーログ出力
            logger.debug(e)
            return 'FAILED'

        openbd = json.loads(response.text)[0]   # 書籍情報 from openBD
        # openBDで書籍情報が見つからないケース
        if openbd is None:
            return 'NOT FOUND'

        self.openbd = openbd
        return 'OK'

    def get_std_info(self) -> Union[Dict[str, str], bool]:
        if self.result != 'OK':
            logger.debug('openBDからの書籍情報取得に失敗しているため基本情報を取得できません')
            return False

        # 基本情報取得
        title = self.openbd['summary']['title']         # タイトル
        publisher = self.openbd['summary']['publisher']  # 出版社
        authors = self.openbd['summary']['author']      # 著者
        cover = self.openbd['summary']['cover']         # 表紙画像URL

        # ISBN-10ベース情報
        isbn10 = self.isbn10
        amazon = 'https://www.amazon.co.jp/dp/{0}'.format(isbn10)

        # 出版日: 形式が異なるため一時変数に代入後処理
        tmp_pubdate = self.openbd['summary']['pubdate']
        if len(tmp_pubdate) == 8:
            # pubdate: yyyyMMdd
            pubdate = '{0}-{1}-{2}'.format(tmp_pubdate[:4], tmp_pubdate[4:6], tmp_pubdate[6:])
        else:
            # pubdare: yyyy-MM
            pubdate = '{0}-01'.format(tmp_pubdate)

        # 書籍詳細（目次や概要など）の取得
        if self.openbd['onix']['CollateralDetail'].get('TextContent'):
            # 複数ある場合は連結
            detail = ' '.join([text_content['Text'].replace('\n', ' ') for text_content in self.openbd['onix']['CollateralDetail']['TextContent']])
        else:
            # 詳細が存在しない場合 -> 未登録とする
            detail = '未登録'

        # 書籍説明（タイトル，出版社，著者，詳細を連結した文章）テキスト（処理前）
        # neologdnによる正規化 -> 数字削除（目次対策）
        tmp_description = re.sub(r'[0-9]+', ' ', normalize('{0} {1} {2} {3}'.format(title, publisher, authors, detail)))

        # 書籍説明テキストの分かち書きと品詞フィルタリング
        description_word_list = []  # 書籍説明テキスト対象単語
        for line in self.mecab.parse(tmp_description).splitlines():
            chunks = line.split('\t')
            if len(chunks) > 3 and (chunks[3].startswith('動詞') or chunks[3].startswith('形容詞') or chunks[3].startswith('名詞')):
                # 動詞or形容詞or名詞 -> 訓練対象
                description_word_list.append(chunks[0])

        # 書籍説明テキスト（処理後）: Doc2Vec訓練時に書籍を表す文章として使用
        description = ' '.join(description_word_list)

        info = dict(amazon=amazon, isbn10=isbn10, cover=cover, title=title, publisher=publisher, authors=authors, pubdate=pubdate, description=description)
        return info
