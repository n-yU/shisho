from logging import getLogger, StreamHandler, DEBUG, Formatter
from typing import Dict, Any
from math import ceil
from pathlib import Path
from flask import Flask, render_template, request
from elasticsearch import Elasticsearch
from backend.openbd import OpenBD
from backend.doc2vecwrapper import Doc2VecWrapper
import MeCab
import yaml

# ロガー設定
logger = getLogger(__name__)
handler = StreamHandler()
handler.setLevel(DEBUG)
logger.setLevel(DEBUG)
logger.addHandler(handler)
logger.propagate = False
handler.setFormatter(Formatter('[shisho] %(message)s'))


def get_config() -> Dict[str, Any]:
    """司書設定ファイル（yml形式）読み込み
    Returns:
        Dict[str, Any]: 司書設定
    """
    config_path = Path('./config/config.yml')

    try:
        with open(config_path) as f:
            conf = yaml.safe_load(f)
    except Exception as e:
        logger.error('コンフィグの読み込みに失敗しました')
        logger.error('フォーマットに問題がある可能性があります')
        logger.error(e)
        exit()

    return conf


config = get_config()   # 司書設定
# MeCab設定: NEologd（MeCab用システム辞書）を使った分かち書き
mecab = MeCab.Tagger('-Ochasen -d /usr/lib/aarch64-linux-gnu/mecab/dic/mecab-ipadic-neologd')
# Doc2Vecモデル読み込み（パスが存在しない -> 未訓練状態）
d2v = Doc2VecWrapper(model_path=Path('/projects/model/d2v.model'))
app = Flask(__name__)   # Flaskインスタンスをappという名前で生成


def get_title(page_name: str) -> str:
    """ページタイトル取得

    Args:
        page_name (str): ページタイトル

    Returns:
        str: ページ名
    """
    title = "{0} - {1}".format(page_name, config['shishosan'])
    return title


@app.route('/')
def index():
    # "GET /" -> "index.html"のレンダリング
    title = get_title('トップ')

    # bookインデックスのdocument（書籍）からランダムピックアップ
    es = Elasticsearch('elasticsearch')
    es_params = {'size': 6}
    body = {'query': {'function_score': {"query": {"match_all": {}}, "random_score": {}}}}
    response = es.search(index='book', body=body, params=es_params)['hits']['hits']
    es.close()

    picked_books = [sr['_source'] for sr in response]   # ピックアップ書籍
    return render_template('index.html', title=title, picked_books=picked_books)


@app.route('/register')
def register_check():
    # "GET /register" -> "register.html"のレンダリング
    title = get_title('登録確認')
    return render_template('register.html', title=title)


@app.route('/register', methods=['POST'])
def register_inquire():
    # "POST /register" -> "register.html"のレンダリング（リクエスト結果付与）
    title = get_title('書籍問い合わせ結果')
    isbn10 = request.form['isbn10']             # 問い合わせ対象書籍ISBN-10コード
    book = OpenBD(isbn10=isbn10, mecab=mecab)   # openBDリクエスト
    result = book.result                      # リクエスト結果

    if result == 'OK':
        # 書籍情報取得成功 -> 書籍基本情報送信
        book_info = book.get_std_info()  # 書籍基本情報
        return render_template('register.html', title=title, isbn10=isbn10, result=result, book_info=book_info)
    else:
        # 書籍情報取得失敗 -> リクエスト結果のみ送信
        return render_template('register.html', title=title, isbn10=isbn10, result=result)


@app.route('/register/post', methods=['GET', 'POST'])
def register_post():
    # "POST /register/post" -> "registered.html"のレンダリング
    title = get_title('登録完了')
    isbn10 = request.form['isbn10']  # 登録対象書籍のISBN-10コード
    book_info = OpenBD(isbn10=isbn10, mecab=mecab).get_std_info()   # 登録書籍基本情報

    es = Elasticsearch('elasticsearch')
    es.index(index='book', doc_type='_doc', body=book_info, id=isbn10)  # bookインデックスに登録
    logger.debug('書籍の登録に成功しました (ISBN-10: {})'.format(isbn10))

    es.indices.refresh(index='book')    # bookインデックス更新 <- 反映には1秒のラグがあるため
    n_book = es.count(index='book')['count']    # 登録書籍総数
    es.close()

    # 書籍総数が10の倍数 -> Doc2Vecモデル再構築
    # configで弄れるようにする予定
    if n_book % 10 == 0:
        global d2v
        d2v = Doc2VecWrapper(model_path=Path('/projects/model/d2v.model'), initialize=True)
        d2v.train()

    return render_template('registered.html', title=title, isbn10=isbn10, book_info=book_info)


@app.route('/delete')
def delete_inquire():
    # "GET /delete" -> "delete.html"のレンダリング
    if request.args.get('isbn10'):
        # 本ページの削除ボタンからのアクセス
        title = get_title('削除確認')
        isbn10 = request.args['isbn10']  # 削除対象書籍ISBN-10コード

        # 削除問い合わせ対象書籍情報取得
        es = Elasticsearch('elasticsearch')
        book = es.get_source(index='book', id=isbn10)
        es.close()

        return render_template('delete.html', title=title, isbn10=isbn10, book=book)
    else:
        # 本ページの削除ボタンを経由しないアクセス
        title = get_title('削除不可')
        return render_template('delete.html', title=title)


@app.route('/delete/post', methods=['GET', 'POST'])
def delete_post():
    # "POST /delete/post" -> "deleted.html"のレンダリング
    title = get_title('削除完了')
    isbn10 = request.form['isbn10']  # 削除対象書籍ISBN-10コード

    es = Elasticsearch('elasticsearch')
    book_title = es.get_source(index='book', id=isbn10)['title']    # 削除対象書籍タイトル
    es.delete(index='book', id=isbn10)  # bookインデックスから対象書籍削除
    logger.debug('書籍の削除に成功しました (ISBN-10: {})'.format(isbn10))

    es.indices.refresh(index='book')    # bookインデックス更新 <- 後のD2Vモデル再訓練時に削除した書籍が混入しないようにするため
    es.close()

    # 削除した書籍を推薦対象外とするため，削除ごとにDoc2Vecモデルを再構築
    global d2v
    d2v = Doc2VecWrapper(model_path=Path('/projects/model/d2v.model'), initialize=True)
    d2v.train()

    return render_template('deleted.html', title=title, isbn10=isbn10, book_title=book_title)


@app.route('/shelf/<page>', methods=['GET', 'POST'])
def shelf(page=None):
    # "GET /shelf/<page>" -> "shelf.html"のレンダリング
    page = int(page)    # ページ番号

    # 1ページあたりの書籍表示数
    if request.form and request.form['display']:
        # 表示数変更ボタンから変更された値
        display = int(request.form['display'])
    elif request.args and request.args.get('display'):
        # GETパラメータから参照された値（変更後ページ遷移）
        display = int(request.args.get('display'))
    else:
        # デフォルト
        display = 12

    # pページ目 -> 全登録書籍のうち，((p - 1) * 表示数)番目から(表示数)個取得
    es_params = {'from': (page - 1) * display, 'size': display}
    es = Elasticsearch('elasticsearch')
    books = es.search(index='book', params=es_params)['hits']['hits']
    n_book = es.count(index='book')['count']    # 書籍総数
    es.close()

    n_shelf = ceil(n_book / display)     # 本棚（ページ）数 -> ceil(書籍総数 / 表示数) (ceil: 天井関数)
    title = get_title('本棚 ({0}/{1})'.format(page, n_shelf))
    return render_template('shelf.html', title=title, books=books, page=page, display=display, n_shelf=n_shelf)


@app.route('/search')
def search():
    # "GET /search" -> "search.html"のレンダリング
    page = int(request.args.get('p', default=1))        # ページ番号
    display = int(request.args.get('d', default=12))    # 1ページあたり表示数

    # TODO: 詳細検索実装
    if request.args.get('q'):
        # 検索KW入力あり（簡易検索）
        q = request.args['q']   # 検索KW（クエリ）
        title = get_title('検索結果: {0}'.format(q))
        props = ['title', 'publisher', 'authors', 'description']    # タイトル・出版社・著者・詳細を対象とした全文検索
        query = dict(zip(props, [q for _ in range(len(props))]))    # Elasticsearch用クエリ

        # タイトル・出版社・著者・詳細それぞれに対して検索 -> 各ヒット書籍集合の和集合をとる
        body = {'query': {'bool': {"should": [{'match': {prop: val}} for prop, val in query.items()]}}}
    else:
        # 検索KW未入力
        title = get_title('検索ワード未入力')
        search_title = '検索ワードを入力してください'
        return render_template('search.html', title=title, search_title=search_title, q='', page=page, display=display)

    es = Elasticsearch('elasticsearch')
    # pページ目 -> 全登録書籍のうち，((p - 1) * 表示数)番目から(表示数)個取得
    es_params = {'from': (page - 1) * display, 'size': display}

    response = es.search(index='book', body=body, params=es_params)['hits']  # ヒット書籍情報取得
    n_hit = response['total']['value']  # 検索ヒット数
    n_page = ceil(n_hit / display)  # 本棚（ページ）数 -> ceil(書籍総数 / 表示数) (ceil: 天井関数)
    es.close()
    result = [sr['_source'] for sr in response['hits']]

    if len(result):
        # ヒット書籍あり
        search_title = '検索結果: {0} ({1}冊中{2}~{3}冊)'.format(q, n_hit, display * (page - 1) + 1, min(display * page, n_hit))
    else:
        # ヒット書籍なし
        search_title = '検索結果: {0} (0冊)'.format(q)
        q = ''  # 再検索させるため検索KWは削除しておく
    return render_template('search.html', title=title, search_title=search_title, q=q, result=result,
                           page=page, display=display, n_page=n_page)


@app.route('/book/<isbn10>')
def book(isbn10=None):
    # "GET /search/<isbn10>" -> "book.html"のレンダリング
    # TODO: 未登録書籍へのアクセス対応
    # TODO: D2Vモデル訓練データ外書籍へのアクセス対応

    title = get_title('本:{0}'.format(isbn10))

    es = Elasticsearch('elasticsearch')
    book = es.get_source(index='book', id=isbn10)   # bookインデックスから取得
    n_book = es.count(index='book')['count']    # 書籍総数

    if n_book >= 10:
        # 10冊以上 -> D2Vモデル構築済み -> 非パーソナライズ推薦（類似書籍取得）
        sim_books_isbn10 = d2v.get_similar_books(isbn10=isbn10, topn=6, verbose=False)  # 類似書籍ISBN-10コード
        sim_books = [es.get_source(index='book', id=sb[0]) for sb in sim_books_isbn10]  # 類似書籍情報取得
    else:
        sim_books = None

    es.close()
    return render_template('book.html', title=title, isbn10=isbn10, book=book, sim_books=sim_books)


@app.route('/explore')
def explore():
    # "GET /explore" -> "explore.html"のレンダリング
    # TODO: 詳細検索機能

    title = get_title('詳細検索')
    return render_template('explore.html', title=title)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
