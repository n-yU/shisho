from logging import getLogger, StreamHandler, DEBUG, Formatter
from math import ceil
from pathlib import Path
import os
from elasticsearch import Elasticsearch
import MeCab

from flask import Flask, render_template, request, redirect, url_for
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager, login_required, login_user, logout_user, current_user
from flask_bcrypt import Bcrypt

from backend.schedule import run_schedule
from backend.openbd import OpenBD
from backend.doc2vecwrapper import Doc2VecWrapper
from backend.db import LoginUser, record_history, get_user_history, change_session, get_guest_uIds
from backend.sbrs import get_prop_sbrs
from config import get_config


# ロガー設定
logger = getLogger(__name__)
handler = StreamHandler()
handler.setLevel(DEBUG)
logger.setLevel(DEBUG)
logger.addHandler(handler)
logger.propagate = False
handler.setFormatter(Formatter('[shisho] %(message)s'))


config = get_config()   # 司書設定
# MeCab設定: NEologd（MeCab用システム辞書）を使った分かち書き
mecab = MeCab.Tagger('-Ochasen -r /etc/mecabrc -d /usr/lib/x86_64-linux-gnu/mecab/dic/mecab-ipadic-neologd')
# Doc2Vecモデル読み込み（パスが存在しない -> 未訓練状態）
d2v = Doc2VecWrapper(model_path=Path('/projects/model/d2v.model'))
guest_uIds_set = set(get_guest_uIds())  # ゲストアカウント ユーザID集合

login_manager = LoginManager()
app = Flask(__name__)   # Flaskインスタンスをappという名前で生成
login_manager.init_app(app)
login_manager.login_view = 'login'          # ログインページ
app.config['SECRET_KEY'] = os.urandom(24)   # セッション情報暗号化
csrf = CSRFProtect(app)                     # flask-wtfによるCSRF対策
bcrypt = Bcrypt(app)                        # flask-bcryptパスワードハッシュ化

prop_sbrs = get_prop_sbrs(d2v=d2v)  # 提案SBRS
run_schedule()                      # 定期実行ジョブのスケジューリング


@login_manager.user_loader
def load_user(uId: str) -> LoginUser:
    """認証ユーザの呼び出し方定義

    Args:
        uId (str): ユーザID

    Returns:
        LoginUser: ログインユーザ
    """
    return LoginUser.query.filter(LoginUser.uId == uId).one_or_none()


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
@login_required
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
    return render_template('index.html', shishosan=config['shishosan'], title=title, picked_books=picked_books)


@app.route('/login', methods=['GET'])
def login_form():
    # "GET /login" -> レンダリング: "login.html"
    title = get_title('ログイン')
    next_url = request.args.get('next', '/')
    return render_template('login.html', shishosan=config['shishosan'], title=title, next_url=next_url)


@app.route('/login', methods=['POST'])
def login():
    # "POST /login" -> ログイン試行
    input_uId = request.form.get('uId', '')  # 入力ユーザID
    user = load_user(uId=input_uId)         # 入力ユーザIDに対応するユーザ（存在しない -> None）

    if input_uId == '':
        # ユーザID未入力
        title = get_title('ログイン')
        return render_template('login.html', shishosan=config['shishosan'], title=title, error='ユーザIDが未入力です')
    elif not user:
        # 存在しないユーザID
        title = get_title('ログイン')
        return render_template('login.html', shishosan=config['shishosan'], title=title, error='指定したユーザIDは未登録です')
    else:
        pass

    input_password = request.form.get('password', '')   # 入力パスワード
    valid_pass = bcrypt.check_password_hash(user.password, input_password)  # パスワード確認（一致でTrue）
    if valid_pass:
        # パスワード一致 -> ログイン
        login_user(user, remember=(True if request.form.get('rmm') else False))
        return redirect(request.form.get('next_url'))
    elif input_password == '':
        # パスワード未入力
        title = get_title('ログイン')
        return render_template('login.html', shishosan=config['shishosan'], title=title, error='パスワードが未入力です')
    elif not valid_pass:
        # パスワード不一致
        title = get_title('ログイン')
        return render_template('login.html', shishosan=config['shishosan'], title=title, error='パスワードが異なります')
    else:
        title = get_title('ログイン')
        return render_template('login.html', shishosan=config['shishosan'], title=title, error='不明なエラーです')


@app.route("/history")
@login_required
def history():
    # "GET /history" -> "history.html"のレンダリング
    title = get_title('閲覧履歴')
    user_history = get_user_history(user=current_user)
    # 表示する閲覧履歴の最大冊数は30冊
    hisotry_max_size, unique_user_history, bIds_set = 30, [], set()

    # 最新順（タイムスタンプ降順）取得 -> 重複履歴除外
    es = Elasticsearch('elasticsearch')
    for lId, log in sorted(user_history.items(), reverse=True):
        if len(unique_user_history) == hisotry_max_size:
            break
        if log['bId'] in bIds_set:
            # 時系列順で後に閲覧した書籍 -> 除外
            continue

        bIds_set.add(log['bId'])
        unique_user_history.append(log)
        unique_user_history[-1]['book'] = es.get_source(index='book', id=log['bId'])    # 書籍情報取得
    es.close()

    # 閲覧書籍0冊 -> None
    if len(user_history) == 0:
        unique_user_history = None

    return render_template('history.html', shishosan=config['shishosan'], title=title, user_history=unique_user_history)


@app.route("/logout")
@login_required
def logout():
    # "GET /logout" -> ログアウト処理
    change_session(user=current_user)   # セッション変更
    logout_user()                       # ログアウト
    return redirect(url_for('login'))


@app.route('/register')
@login_required
def register_check():
    # "GET /register" -> "register.html"のレンダリング
    title = get_title('登録確認')
    return render_template('register.html', shishosan=config['shishosan'], title=title)


@app.route('/register', methods=['POST'])
@login_required
def register_inquire():
    # "POST /register" -> "register.html"のレンダリング（リクエスト結果付与）
    title = get_title('書籍問い合わせ結果')
    isbn10 = request.form['isbn10']             # 問い合わせ対象書籍ISBN-10コード
    book = OpenBD(isbn10=isbn10, mecab=mecab)   # openBDリクエスト
    result = book.result                      # リクエスト結果

    if current_user.uId in guest_uIds_set:
        result = 'GUEST USER'

    if result == 'OK':
        # 書籍情報取得成功 -> 書籍基本情報送信
        book_info = book.get_std_info()  # 書籍基本情報
        return render_template('register.html', shishosan=config['shishosan'], title=title, isbn10=isbn10, result=result, book_info=book_info)
    else:
        # 書籍情報取得失敗 -> リクエスト結果のみ送信
        return render_template('register.html', shishosan=config['shishosan'], title=title, isbn10=isbn10, result=result)


@app.route('/register/post', methods=['GET', 'POST'])
@login_required
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

    # 書籍総数が10の倍数（TODO: 値はconfigで弄れるようにする）
    if n_book % 10 == 0:
        global d2v, prop_sbrs
        d2v = Doc2VecWrapper(model_path=Path('/projects/model/d2v.model'), initialize=True)
        d2v.train()                         # Doc2Vecモデル再構築
        prop_sbrs = get_prop_sbrs(d2v=d2v)  # 提案システム再構築

    return render_template('registered.html', shishosan=config['shishosan'], title=title, isbn10=isbn10, book_info=book_info)


@app.route('/delete')
@login_required
def delete_inquire():
    # "GET /delete" -> "delete.html"のレンダリング
    if request.args.get('isbn10') and current_user.uId not in guest_uIds_set:
        # 本ページの削除ボタンからのアクセス
        title = get_title('削除確認')
        isbn10 = request.args['isbn10']  # 削除対象書籍ISBN-10コード

        # 削除問い合わせ対象書籍情報取得
        es = Elasticsearch('elasticsearch')
        book = es.get_source(index='book', id=isbn10)
        es.close()

        return render_template('delete.html', shishosan=config['shishosan'], title=title, isbn10=isbn10, book=book)
    else:
        # 本ページの削除ボタンを経由しないアクセス
        title = get_title('削除不可')
        return render_template('delete.html', shishosan=config['shishosan'], title=title)


@app.route('/delete/post', methods=['GET', 'POST'])
@login_required
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

    return render_template('deleted.html', shishosan=config['shishosan'], title=title, isbn10=isbn10, book_title=book_title)


@app.route('/shelf/<page>', methods=['GET', 'POST'])
@login_required
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
    return render_template('shelf.html', shishosan=config['shishosan'], title=title, books=books, page=page, display=display, n_shelf=n_shelf)


@app.route('/search')
@login_required
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
        return render_template('search.html', shishosan=config['shishosan'], title=title, search_title=search_title, q='',
                               page=page, display=display)

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
    return render_template('search.html', shishosan=config['shishosan'], title=title, search_title=search_title, q=q,
                           result=result, page=page, display=display, n_page=n_page)


@app.route('/book/<isbn10>')
@login_required
def book(isbn10=None):
    # "GET /search/<isbn10>" -> "book.html"のレンダリング
    # 類似書籍: 非パーソナライズ推薦（Doc2Vec）による書籍
    # 推薦書籍: パーソナライズ推薦（提案SBRS）による書籍

    title = get_title('本:{0}'.format(isbn10))

    es = Elasticsearch('elasticsearch')
    book = es.get_source(index='book', id=isbn10)   # bookインデックスから取得
    n_book = es.count(index='book')['count']    # 書籍総数

    if n_book >= 10:
        # 10冊以上 -> D2Vモデル構築済み -> 非パーソナライズ推薦（類似書籍取得）
        try:
            sim_books_isbn10 = d2v.get_similar_books(isbn10=isbn10, topn=6, verbose=False)  # 類似書籍ISBN-10
            sim_books = [es.get_source(index='book', id=sb[0]) for sb in sim_books_isbn10]  # 類似書籍情報取得
        except KeyError:
            # 分散表現未構築（モデル再構築前） -> 非パーソナライズ推薦キャンセル
            sim_books = None
    else:
        sim_books = None

    log = record_history(user=current_user, bId=isbn10)     # 書籍閲覧履歴記録
    rec_books_isbn10 = prop_sbrs.update(log=log)            # 推薦書籍ISBN-10

    # 推薦書籍なし（各情報不足により提案SBRSが推薦生成できず） -> 類似書籍のみ表示
    if rec_books_isbn10 is None:
        rec_books = None
    else:
        # ISBN-10に対応する書籍情報習得
        rec_books = [es.get_source(index='book', id=isbn10) for isbn10 in rec_books_isbn10]
    es.close()

    return render_template('book.html', shishosan=config['shishosan'], title=title, isbn10=isbn10, book=book,
                           sim_books=sim_books, rec_books=rec_books)


@app.route('/explore')
@login_required
def explore():
    # "GET /explore" -> "explore.html"のレンダリング
    # TODO: 詳細検索機能

    title = get_title('詳細検索')
    return render_template('explore.html', shishosan=config['shishosan'], title=title)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=True)
